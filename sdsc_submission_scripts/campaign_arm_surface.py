#!/usr/bin/env python
"""Arm SURFACE capture — the three routes argv symmetry cannot see (F-SCANG-4).

``campaign_arm_symmetry.py`` compares two hypothetical command lines. The
frozen row records why that is not enough:

    the launch gate compares two HYPOTHETICAL COMMAND LINES on ONE MACHINE,
    and every route that actually differs between two pods — home-directory
    stores, environment variables, rendered prompt BYTES — is outside what
    it can see.

This module captures those three routes for ONE arm, on the host that will
run that arm, into a JSON artifact. ``campaign_arm_symmetry.py`` compares
two such artifacts. Publishing the artifact into the shared campaign
workspace root is what makes the comparison CROSS-POD: the second pod's
preflight reads the first pod's published surface instead of re-deriving a
sibling from its own state, which would agree with itself by construction.

Three sections, one per clause of the requirement:

1. ``prompt_bytes`` — what the model actually receives, not what argv
   promises. Every surface is produced by CALLING the production renderer
   (``render_available_models`` / ``render_available_losses`` /
   ``load_stage_prompt`` / ``get_task_description`` /
   ``render_forward_contract`` / ``resolve_run_proposal_blocks``), never by
   re-implementing it here — a second renderer would be free to drift from
   the one the run obeys, and then the gate would certify bytes nobody
   sends.

   Each surface is captured TWICE: once at the ARM's own
   ``baseline_isolation`` and once at a NEUTRAL ``baseline_isolation=False``
   shared by both arms. The neutral render is the contamination detector —
   it holds every machine-local input (the capability store, the task
   config, the templates) with the treatment held constant, so a difference
   between arms can only come from the machine. The arm render is where the
   treatment must SHOW: two arms whose arm renders are byte-identical are
   mis-wired, not symmetric.

   What this does NOT capture, stated so the launch packet cannot overclaim:
   the run-time evidence blocks (accumulated records, expert context,
   previous failures, hardware context) do not exist before iteration 1 and
   are left as literal ``{placeholder}`` tokens. This is the cold-start
   prompt surface, which is exactly the surface a preflight can speak for.

2. ``environment`` — every variable under a DECLARED prefix, plus a
   DECLARED explicit list. Secret-shaped names record presence only, never
   a value.

3. ``machine_local_stores`` — content digests of the home-directory and
   checkout-local stores that reach a run. Digests are computed over paths
   RELATIVE to each store root, so the same store mounted at two absolute
   paths on two pods digests identically; an absolute path never enters the
   hash.

4. ``provenance`` (N-6) — WHO captured this surface, WHEN, and from WHICH
   CODE. Without it the artifact is unattributable, and a reader that
   cannot attribute it cannot honestly call it cross-pod evidence: the
   preflight used to label a sibling surface ``published`` on FILE
   EXISTENCE alone, so one same-host rehearsal — or a day-1 publication
   surviving every later cold start, since the cold-start row globs band
   workspaces and never the campaign root — earned the strongest label the
   report can print. The label must not claim more than the comparison
   established, so the strength is DERIVED from these fields by
   ``campaign_arm_symmetry.py`` and is not a caller's assertion.

Writes JSON to ``--out``. Nothing is printed to stdout on success:
importing the framework emits plugin-loader chatter, and a caller parsing
stdout would parse that too.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

#: Artifact schema. The comparator refuses a surface it does not know how
#: to read rather than silently comparing two shapes.
#:
#: v1 -> v2 (N-6) adds the REQUIRED ``provenance`` section. The bump is the
#: point: a v1 artifact carries no captured-at, no host and no revision, so
#: nothing about it can be verified, and a stale v1 file already sitting in
#: a campaign root must be REFUSED rather than silently read as another
#: pod's evidence.
SURFACE_SCHEMA = "campaign_arm_surface/v2"

#: Provenance keys every v2 surface carries. The comparator requires all of
#: them; a surface missing one is unattributable and is refused.
PROVENANCE_KEYS = ("captured_at", "captured_at_epoch", "host", "project_dir", "revision")

#: The #255 arm vocabulary this capture speaks. Gold<->Blind treatment
#: symmetry is a separate blind-launch prerequisite and is deliberately NOT
#: served here (campaign_preflight.sh, "NOT in this script's remit").
ARMS = ("with-prior-art", "without-prior-art")

# --- environment: the DECLARED capture rule --------------------------------

#: Every variable whose NAME starts with one of these is captured. A PREFIX
#: rule, not a name list, so a knob added to the framework tomorrow is
#: covered without editing this file — a name list is how an environment
#: check goes quietly stale.
ENVIRONMENT_PREFIXES = ("SIDERIUS_", "TIDMAD_", "H100_", "VALIDATION_")

#: Names outside those prefixes that reach a run. Each is here for a reason:
#: PYTHONPATH selects WHICH CHECKOUT's framework executes (the E1 trap that
#: preflight R2b exists for); CUDA_VISIBLE_DEVICES selects the card;
#: OMP_NUM_THREADS and PYTORCH_CUDA_ALLOC_CONF change execution behaviour;
#: CHAIN_STOP_FILE redirects the chain's stop check (F-SCANI-2's declared
#: environment input, captured here precisely BECAUSE it is a legal one).
ENVIRONMENT_EXPLICIT_NAMES = (
    "PYTHONPATH",
    "CUDA_VISIBLE_DEVICES",
    "OMP_NUM_THREADS",
    "PYTORCH_CUDA_ALLOC_CONF",
    "CHAIN_STOP_FILE",
)

#: Names whose VALUE must never enter an artifact that gets copied into a
#: launch packet. Presence is still compared: an API key set on one arm and
#: absent on the other is an asymmetry worth naming.
_SECRET_SHAPED = re.compile(r"(API_KEY|_TOKEN|_SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)

#: The placeholder recorded instead of a secret's value.
SECRET_PLACEHOLDER = "<set:value-withheld>"

#: What an occurrence of this surface's own checkout root is rewritten to in
#: every captured environment VALUE (N-9).
#:
#: WHY THIS IS NOT A HOLE. ``PYTHONPATH`` is captured precisely because it
#: selects WHICH CHECKOUT executes (preflight R2b's E1 trap) and it is NOT
#: on the comparator's arm-local allowlist, so a difference FAILS. But the
#: preflight INJECTS it as an ABSOLUTE path to its own checkout, and two
#: pods legitimately hold that checkout at two different absolute paths —
#: the cross-pod comparison would then be red for a reason that is not an
#: asymmetry, and a gate that cannot pass on two real pods gets switched
#: off. This is the SAME portability argument ``digest_paths`` already
#: makes for the stores, applied to the environment: the identity of the
#: checkout is compared as the surface's recorded ``revision``, and its
#: mount point is normalised away. Anything else on the path — a second
#: clone injected on one pod only — still differs and still fails.
PROJECT_DIR_TOKEN = "<project_dir>"

# --- machine-local stores: what is CONTENT and what is DERIVED -------------

#: Directory names skipped when digesting a store, and file suffixes skipped
#: within it (N-9). A ``.pyc`` is DERIVED from a ``.py`` that is already in
#: the digest, and under Python's default timestamp invalidation its header
#: embeds the SOURCE MTIME — which is host-local. Two pods holding an
#: identical store therefore digest differently as soon as either has
#: imported from it, so hashing bytecode makes the store layer red for a
#: reason that is not a content difference. Excluding it removes no
#: detection: a plugin whose SOURCE differs still moves the digest.
DERIVED_STORE_DIRS = ("__pycache__",)
DERIVED_STORE_SUFFIXES = (".pyc", ".pyo")

# --- machine-local stores: the DECLARED roster -----------------------------

#: Store id -> human description. The ROOTS are resolved by the CLI through
#: production authorities and passed in; this table only names what exists.
STORE_IDS = (
    "generated_library",
    "checkout_capability_state",
    "root_papers_cache",
    "calibration_store",
)

#: Refuse to hash an unbounded tree rather than hang a launch gate. A store
#: over this many files is reported as an ERROR entry, never as a digest
#: that silently covered part of it.
MAX_STORE_ENTRIES = 10000

# --- prompt surfaces -------------------------------------------------------

#: The three proposal pipeline stages and the two exploration modes they are
#: assembled under. Both modes are captured: the mode is chosen at run time,
#: so a gate that looked at only one would be blind to half the templates.
PROPOSAL_STAGES = ("comparison_stage", "causal_reasoning_stage", "proposing_stage")
EXPLORATION_MODES = ("explore", "exploit")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_text(text: str) -> dict:
    """The comparable identity of one rendered surface."""
    return {"sha256": _sha256_text(text), "bytes": len(text.encode("utf-8"))}


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # In place: os.walk reads this list back to decide where to descend,
        # so pruning here is what keeps a bytecode cache out of the digest.
        dirnames[:] = sorted(d for d in dirnames if d not in DERIVED_STORE_DIRS)
        for name in sorted(filenames):
            if name.endswith(DERIVED_STORE_SUFFIXES):
                continue
            yield Path(dirpath) / name


def digest_paths(labelled_paths: Sequence[tuple[str, str]]) -> dict:
    """Content digest of a store made of labelled files and directories.

    ``labelled_paths`` is ``[(label, absolute_path), ...]``. Every entry is
    hashed as ``"<label>/<path relative to that entry's root>"`` plus the
    file's own sha256, so the digest is a function of CONTENT and STRUCTURE
    only — never of where the store is mounted. Two pods holding the same
    store at different absolute paths therefore agree, which is the whole
    point of comparing them across hosts. For the same reason DERIVED
    bytecode (:data:`DERIVED_STORE_DIRS` / :data:`DERIVED_STORE_SUFFIXES`)
    is excluded: its header carries the host-local source mtime.

    Returns ``{"present", "entry_count", "content_sha256", "sample"}``, or
    an ``{"error": ...}`` entry when the store is too large to hash.
    """
    rows: list[tuple[str, str]] = []
    present = False
    for label, raw in labelled_paths:
        path = Path(raw)
        if not path.exists():
            continue
        present = True
        if path.is_dir():
            for file_path in _iter_files(path):
                rel = file_path.relative_to(path).as_posix()
                rows.append((f"{label}/{rel}", _sha256_file(file_path)))
        else:
            rows.append((label, _sha256_file(path)))
        if len(rows) > MAX_STORE_ENTRIES:
            return {
                "present": True,
                "error": (
                    f"store holds more than {MAX_STORE_ENTRIES} files; refusing to "
                    "hash an unbounded tree in a launch gate"
                ),
            }
    rows.sort()
    joined = "\n".join(f"{name}\0{digest}" for name, digest in rows)
    return {
        "present": present,
        "entry_count": len(rows),
        "content_sha256": _sha256_text(joined),
        "sample": [name for name, _ in rows[:10]],
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_environment(
    environ: Mapping[str, str], *, project_dir: str | None = None
) -> dict[str, str]:
    """The declared environment slice, with secret VALUES withheld.

    When ``project_dir`` is given, every occurrence of that checkout root in
    a captured VALUE is rewritten to :data:`PROJECT_DIR_TOKEN` — see that
    constant for why this is a portability normalisation and not a hole.
    Omitting it (the default) captures values verbatim.
    """
    root = project_dir.rstrip("/") if project_dir else ""
    captured: dict[str, str] = {}
    for name, value in environ.items():
        if not (name.startswith(ENVIRONMENT_PREFIXES) or name in ENVIRONMENT_EXPLICIT_NAMES):
            continue
        if _SECRET_SHAPED.search(name):
            captured[name] = SECRET_PLACEHOLDER
            continue
        captured[name] = value.replace(root, PROJECT_DIR_TOKEN) if root else value
    return dict(sorted(captured.items()))


def resolve_revision(project_dir: str) -> tuple[str | None, bool | None]:
    """``(HEAD sha, dirty)`` for the checkout that rendered this surface.

    ``(None, None)`` when the directory is not a readable git checkout. The
    comparator treats an unknown revision as UNVERIFIABLE rather than as
    agreement: two surfaces rendered by different code are comparing two
    renderers, not two machines, and that must be visible.
    """
    try:
        sha = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", project_dir, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None, None
    return (sha or None), bool(status)


def capture_provenance(
    *,
    project_dir: str,
    host: str,
    captured_at_epoch: float,
    revision: str | None,
    revision_dirty: bool | None,
) -> dict:
    """WHO captured this surface, WHEN, and from WHICH CODE (N-6).

    Pure: every value is supplied. The strength of the claim a reader may
    make about this artifact is DERIVED from these fields by the
    comparator — the reader never accepts a strength label as an assertion,
    because the defect this section closes is exactly a label asserted on
    file existence.
    """
    epoch = int(captured_at_epoch)
    return {
        "captured_at": datetime.fromtimestamp(epoch, tz=UTC).isoformat(),
        "captured_at_epoch": epoch,
        "host": host,
        "project_dir": project_dir,
        "revision": revision,
        "revision_dirty": revision_dirty,
    }


def render_prompt_surfaces(*, baseline_isolation: bool) -> dict[str, str]:
    """Every cold-start prompt surface, rendered by the PRODUCTION renderers.

    Imports are local: this module is also imported by the comparator's
    tests, which must not pay the framework import cost to read a roster.
    """
    from agent.prompt_templates.proposal import (
        load_stage_prompt,
        render_available_losses,
        render_available_models,
    )
    from agent.schemas.task_config import ForwardContract
    from agent_generated._registry import CapabilityRegistry
    from workflows.model_exploration import resolve_run_proposal_blocks
    from workflows.task_config import (
        get_task_description,
        load_task_config,
        render_forward_contract,
    )

    registry = CapabilityRegistry()
    models_block = render_available_models(registry, baseline_isolation=baseline_isolation)
    losses_block = render_available_losses(registry)

    task_config = load_task_config()
    blocks = resolve_run_proposal_blocks(None)

    surfaces: dict[str, str] = {
        "proposal.available_models_block": models_block,
        "proposal.available_losses_block": losses_block,
        "task.task_description": get_task_description(task_config),
        "task.forward_contract": render_forward_contract(
            ForwardContract(**task_config["forward_contract"])
        ),
        "proposal.task_blocks": json.dumps(
            blocks.model_dump() if hasattr(blocks, "model_dump") else blocks,
            indent=2,
            sort_keys=True,
            default=str,
        ),
    }
    # The stage system prompts, assembled the way the proposer assembles
    # them. Only the machine-local blocks are substituted; the run-time
    # evidence placeholders stay literal (see the module docstring).
    template_vars = {
        "available_models_block": models_block,
        "available_losses_block": losses_block,
    }
    for stage in PROPOSAL_STAGES:
        for mode in EXPLORATION_MODES:
            surfaces[f"proposal.stage.{stage}.{mode}"] = load_stage_prompt(
                stage,
                mode,
                template_vars,
                baseline_isolation=baseline_isolation,
            )
    return surfaces


def build_surface(
    *,
    arm: str,
    baseline_isolation: bool,
    environ: Mapping[str, str],
    stores: Mapping[str, Sequence[tuple[str, str]]],
    provenance: Mapping[str, object],
) -> dict:
    """The complete arm surface artifact.

    ``stores`` maps a :data:`STORE_IDS` member to its labelled paths; the
    CLI resolves those through the production authorities. Passing them in
    keeps this function pure and lets a test drive it against ``tmp_path``
    instead of the developer's home directory.

    ``provenance`` comes from :func:`capture_provenance` and is REQUIRED: a
    surface nobody can attribute is a surface nobody can call cross-pod
    evidence, and the artifact is written once and read later by a
    different pod.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r} (expected one of {ARMS})")
    unknown = sorted(set(stores) - set(STORE_IDS))
    if unknown:
        raise ValueError(f"undeclared store id(s): {unknown} (declared: {list(STORE_IDS)})")
    missing = sorted(set(STORE_IDS) - set(stores))
    if missing:
        raise ValueError(f"store id(s) not resolved: {missing}")
    missing_provenance = sorted(set(PROVENANCE_KEYS) - set(provenance))
    if missing_provenance:
        raise ValueError(f"provenance key(s) not captured: {missing_provenance}")

    arm_render = render_prompt_surfaces(baseline_isolation=baseline_isolation)
    neutral_render = render_prompt_surfaces(baseline_isolation=False)
    prompt_bytes = {
        surface_id: {
            "arm": digest_text(text),
            "neutral": digest_text(neutral_render[surface_id]),
        }
        for surface_id, text in sorted(arm_render.items())
    }
    return {
        "schema": SURFACE_SCHEMA,
        "arm": arm,
        "baseline_isolation": baseline_isolation,
        "provenance": dict(provenance),
        "prompt_bytes": prompt_bytes,
        "environment": capture_environment(environ, project_dir=str(provenance["project_dir"])),
        "machine_local_stores": {
            store_id: digest_paths(stores[store_id]) for store_id in STORE_IDS
        },
    }


def resolve_stores(
    project_dir: str, environ: Mapping[str, str]
) -> dict[str, list[tuple[str, str]]]:
    """The four machine-local stores, resolved through production authorities.

    ``resolve_generated_library`` owns the generated-library root (the two
    layers, the "~" expansion, the relative-path refusal) exactly as
    preflight R1c consults it — re-deriving it in a second place is how a
    check drifts from what the run obeys.
    """
    from core.generated_library import resolve_generated_library

    generated_root = resolve_generated_library().root
    calibration_dir = environ.get("SIDERIUS_CALIBRATION_DIR") or os.path.join(
        os.path.expanduser("~"), ".siderius"
    )
    return {
        "generated_library": [("generated_library", generated_root)],
        "checkout_capability_state": [
            ("models", os.path.join(project_dir, "agent_generated", "models")),
            (
                "capability_index",
                os.path.join(project_dir, "agent_generated", "_capability_index.json"),
            ),
        ],
        "root_papers_cache": [
            ("root_papers_cache", os.path.join(project_dir, "reference_data", "root_papers_cache"))
        ],
        "calibration_store": [("calibration_store", calibration_dir)],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arm", required=True, choices=list(ARMS))
    parser.add_argument(
        "--baseline-isolation",
        choices=("true", "false"),
        required=True,
        help=(
            "the arm's declared isolation flag, as the launcher derives it "
            "(with-prior-art: false, without-prior-art: true)"
        ),
    )
    parser.add_argument("--project-dir", required=True, help="the checkout the run will execute")
    parser.add_argument("--out", required=True, help="path to write the surface JSON")
    args = parser.parse_args(argv)

    project_dir = os.path.abspath(args.project_dir)
    try:
        revision, revision_dirty = resolve_revision(project_dir)
        surface = build_surface(
            arm=args.arm,
            baseline_isolation=args.baseline_isolation == "true",
            environ=os.environ,
            stores=resolve_stores(project_dir, os.environ),
            provenance=capture_provenance(
                project_dir=project_dir,
                host=socket.gethostname(),
                captured_at_epoch=time.time(),
                revision=revision,
                revision_dirty=revision_dirty,
            ),
        )
    # A launch gate reports its failure; it never hands an operator a
    # traceback in the middle of a preflight summary.
    except Exception as exc:
        print(f"[arm-surface] capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(surface, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, out_path)
    print(f"[arm-surface] {args.arm}: wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
