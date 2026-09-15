#!/usr/bin/env python3
"""
Per-iteration runner for the SIDERIUS exploration workflow.

Runs ONE iteration of `run_workflow()` (max_iterations=1) using explicit
source paths. Designed for per-iteration Slurm jobs where each job is
1-4 hours and the workflow is chained across many jobs.

Each iteration:
  1. Loads source data from explicit paths (seeds + previous iterations)
  2. Runs the 5-agent loop (interpret → propose → implement → validate → tune)
  3. Writes a manifest.json summarizing the iteration's output for the next job

Usage:
    python src/workflows/run_one_iteration.py \\
        --workspace /scratch/exploration_v1 \\
        --start_iteration 3 \\
        --source_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json \\
        --max_rounds 20 \\
        --llm_model gemini-3.1-pro-preview \\
        --gpu_memory_limit_gb 10

When ``--start_iteration > 1`` the runner auto-restores plugin classes
from iters [1, N-1] in ``{workspace}/plugins/iter_NNN/`` and prepends
their ``run_output_*.json`` paths onto the seed list — operators no
longer pass prior iters' run_outputs explicitly. The deprecated
``--iteration`` alias is still accepted for one release; use
``--start_iteration`` for new chains.

Iteration manifests are WRITE-ONCE (arXiv-readiness S2 / U5, #258): a
launch into an ``iter_NNN/`` that already holds a ``manifest.json`` is
refused (exit 2) before any work. Rerun an iteration deliberately with
``--replace_iteration_manifest --replacement_reason '<why>'`` — the
previous manifest is set aside as ``manifest.replaced.<stamp>.json`` and
its digests are recorded in the new manifest's ``manifest_replacement``.
#258 refinement (operator ruling): ``--auto_resume`` — forwarded by
``run_chain.sh`` only when the inspector computed the start iteration —
authorizes that SAME replacement path for a manifest whose terminal
status is ``failed`` or ``no_records``; a ``completed`` manifest is never
replaced by auto-resume.
"""

# ruff: noqa: E402 -- bytecode policy must precede third-party and framework imports.

import argparse
import glob
import hashlib
import json
import os
import sys
import traceback
import warnings
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

# A direct one-iteration launch does not pass through run_chain.sh.  Establish
# the same read-only-checkout policy before importing any SIDERIUS module, and
# transport it to every training, inference, scoring, and probe subprocess.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

import yaml
from dotenv import load_dotenv

from agent.schemas.health_feedback import HealthFeedbackRetentionPolicy
from agent.schemas.ordering import ResolvedOrdering, parse_file_order_cli
from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.proposal import OutputTypeName
from agent.schemas.telemetry import LLMBridgeContextError
from agent.skills.evaluate_vram_skill.preflight_adapter import PREFLIGHT_EXECUTION_MODE
from core.iteration_manifest import (
    ManifestAlreadyPublishedError,
    ManifestReplacementError,
    ManifestReplacementRequest,
    classify_manifest_slot,
    manifest_path,
    publish_iteration_manifest,
)
from core.layout import checkout_root
from core.record_role import formal_evidence_of
from core.run_invariants import (
    LockLaunchIdentity,
    RunHealthMaterialization,
    RunInvariants,
    RunInvariantsViolation,
    build_run_invariants,
)
from core.runtime_control.watchdog_profile import (
    ExecutionRegime,
    RequiredProfileBinding,
    RequiredProfileBindingError,
    ResolvedWatchdogSettings,
    resolve_watchdog_launch_settings,
)
from execute_tools.data_paths import DatasetDirectoryUnavailable, resolve_dataset_dir
from execute_tools.dataset_config import DataScope, resolve_dataset_profile
from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.launch_policy import (
    FormalLaunchPolicyError,
    validate_formal_launch,
)
from workflows.llm_config import WorkflowLLMConfig
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import (
    RunTaskComposition,
    bind_run_task_composition,
    compose_run_task_bindings,
    resolve_composed_measurement_capability,
)

_CHECKOUT_ROOT = checkout_root()
SIDERIUS_ROOT = (
    str(_CHECKOUT_ROOT) if _CHECKOUT_ROOT is not None else str(Path(__file__).resolve().parents[2])
)
if _CHECKOUT_ROOT is not None:
    load_dotenv(dotenv_path=Path(SIDERIUS_ROOT) / ".env")


def _positive_int(s: str) -> int:
    """argparse type validator: parse a positive integer (>= 1).

    Used by --max_epochs (Phase 6.8 Commit 11): None / 0 / negative are
    strictly forbidden — every chain run must train for at least one epoch.
    """
    try:
        v = int(s)
    except (TypeError, ValueError) as e:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {s!r}") from e
    if v < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer (>= 1), got {v}")
    return v


def _portion_floor(s: str) -> float:
    """argparse type validator: a portion in [0.01, 1.0].

    The 0.01 floor enforces a segment-integrity rule: with
    ``SEGMENTS_PER_FILE=200``, anything below 0.01 collapses to one
    segment per file (via the ``max(1, ...)`` floor in
    ``execute_tools.sample_set_builder``), which is statistically too
    noisy for trial-mode signal. Failing here at argparse-time keeps
    the iteration from spending tokens on Interpretation only to crash
    inside the Proposer's Pydantic validator.
    """
    try:
        v = float(s)
    except (TypeError, ValueError) as e:
        raise argparse.ArgumentTypeError(f"expected a float in [0.01, 1.0], got {s!r}") from e
    if not (0.01 <= v <= 1.0):
        raise argparse.ArgumentTypeError(
            f"expected a float in [0.01, 1.0], got {v}. The 0.01 floor "
            f"matches the Pydantic schema (ProposalInput.trial_portion / "
            f"HyperparamTuningInput.{{trial,eval}}_portion ge=0.01); below "
            f"that, sample_set_builder collapses to one segment per file, "
            f"which is too noisy for trial-mode signal."
        )
    return v


def load_validation_fixed_candidate_plan(path: str | None) -> dict | None:
    """Load a fixed candidate PLAN for a validation run (V20 FU-D-11).

    Returns ``{"plan": ..., "provenance": ...}``, or ``None`` when no path was
    given (the ordinary campaign case — the proposer decides).

    The provenance half is not decoration: an acceptance run that bypassed the
    proposer must be able to prove WHICH plan it used. It records
    ``candidate_source``, the absolute path, a sha256 over the canonicalised
    payload, and the resolved model identity — computed from the bytes
    actually read, so the hash cannot drift from the plan that was used.

    **Fails closed, loudly.** A malformed file, an unreadable path or a
    payload that is not a valid ``ProposalOutput`` refuses the launch. It does
    NOT fall back to the proposer: a run that asked for a fixed candidate and
    silently got an invented one would report a deterministic acceptance it
    never performed.

    **Unknown keys are REFUSED, not dropped.** ``ProposalOutput`` has no field
    for a score, record, gate verdict, authority verdict or incumbent, so
    Pydantic's default ``extra="ignore"`` would silently discard one that
    appeared. Silent discarding is precisely the defect class this PR family
    hit three times, so a stray ``denoising_score`` fails the launch instead.

    Raises:
        SystemExit: on any unreadable, malformed or results-bearing payload.
    """
    if path is None:
        return None

    from pydantic import ValidationError

    from agent.schemas.proposal import ProposalOutput

    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except OSError as exc:
        raise SystemExit(f"--validation_fixed_candidate_plan: cannot read {path!r}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} must hold a JSON object "
            f"describing one candidate plan, got {type(payload).__name__}"
        )

    # V21 PR E: candidate_id became a ProposalOutput field, which silently
    # removed it from the unknown-key refusal below. It must stay refused
    # HERE: the id is SYSTEM-minted at proposal time (O-E-4), and a fixed
    # plan is by definition not a proposer-emitted candidate — an id entering
    # through this seam would be an identity nobody minted.
    if "candidate_id" in payload:
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} carries "
            f"'candidate_id'. Candidate identity is system-generated at "
            f"proposal time and may not be supplied through a plan; remove "
            f"the key. (A fixed-plan candidate deliberately runs with "
            f"candidate_id=None — it is not a proposer-emitted candidate.)"
        )

    known = set(ProposalOutput.model_fields)
    unknown = sorted(set(payload) - known)
    if unknown:
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} carries keys that are "
            f"not part of a candidate plan: {unknown}. This seam injects a PLAN "
            f"only — a prior score, record, gate verdict, authority verdict or "
            f"incumbent must never enter through it, and dropping them silently "
            f"would hide that it happened."
        )

    try:
        plan = ProposalOutput.model_validate(payload)
    except ValidationError as exc:
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} is not a valid candidate plan: {exc}"
        ) from exc

    # Provenance is computed HERE, from the bytes actually read, so the
    # recorded hash cannot drift from the plan that was used.
    provenance = {
        "candidate_source": "fixed_validation_plan",
        "plan_path": os.path.abspath(path),
        "plan_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "resolved_model_name": plan.model_name,
        "resolved_baseline_config_keys": sorted(plan.baseline_config),
    }
    return {"plan": plan.model_dump(mode="json"), "provenance": provenance}


def _resolve_chain_run_id(workspace: str, run_name: str) -> str:
    """Resolve the immutable per-chain run_id (§1.4.1) for this iteration.

    The chain runner invokes one fresh subprocess per iter — naive
    ``_generate_run_id`` would yield a different value per process and
    violate the bridge's run_id-immutability contract on iter ≥ 2. A
    sidecar file at ``{workspace}/.token_run_id`` carries the value
    forward: iter 1 generates and writes it; later iters read it back.

    Format: ``{run_name}-{utc_ts}-{pid}``.
    """
    sidecar = os.path.join(workspace, ".token_run_id")
    if os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8") as f:
            existing = f.read().strip()
        if existing:
            return existing

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    new = f"{run_name}-{ts}-{os.getpid()}"
    os.makedirs(workspace, exist_ok=True)
    with open(sidecar, "w", encoding="utf-8") as f:
        f.write(new)
    return new


def _infrastructure_abort_reason(results: list) -> str | None:
    """C9c: the tuner's typed infrastructure-abort signal, if it fired.

    ``termination_reason == "infrastructure_abort"`` means the runtime
    EVIDENCE CHANNEL failed — registry, persistence, schema/protocol,
    probe executor, telemetry, communication, or a policy invariant. It is
    deliberately distinct from a candidate rejection (attempt-local), gate
    exhaustion (``no_records``, chain continues), an operator stop, and an
    ordinary subprocess crash.
    """
    for output in results or []:
        if getattr(output, "termination_reason", None) == "infrastructure_abort":
            return getattr(output, "status", None) or "infrastructure_abort"
    return None


def _write_halt_marker(workspace: str, payload: dict) -> str:
    """Write the chain-halt sentinel. Shared by the consecutive-failure
    brake and the C9c infrastructure abort; ``reason`` distinguishes them
    so an operator (and the next process) can tell WHY the chain stopped.
    """
    halt_path = os.path.join(workspace, ".chain_halted")
    with open(halt_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return halt_path


def _check_halt_marker(workspace: str) -> bool:
    """Return True iff a chain halt marker exists in this workspace.

    Cheap fail-fast for SDSC ``afterany`` chains: Slurm queues the next
    iter regardless of the previous's exit code, so we need an on-disk
    sentinel for the next process to bail out before doing any work.
    Called first thing in ``main()`` (after argparse), before any dirs
    are created.
    """
    return os.path.exists(os.path.join(workspace, ".chain_halted"))


def _check_consecutive_failure_brake(
    workspace: str,
    max_failed: int,
) -> list[int] | None:
    """Scan the workspace for a ``max_failed``-long streak of consecutive
    ``status="failed"`` manifests (Stage 4 / Commit 4.6).

    Walks ``{workspace}/iter_NNN/manifest.json`` files in descending iter
    order. Returns the list of failing iter numbers (newest first) when
    the most recent ``max_failed`` committed iters all carry
    ``status="failed"``; returns None otherwise.

    The brake is **fail-open**: a missing or malformed manifest counts
    as "not failed" and breaks the streak. A safety brake must never
    halt a chain on its own flaky reads.

    Only ``status="failed"`` trips the brake. ``"completed"`` and
    ``"no_records"`` both break the streak — ``no_records`` is a
    graceful "no model passed gates" signal, not a failure.

    Args:
        workspace: chain workspace root. Need not exist yet (a fresh
            chain with no iter dirs returns None).
        max_failed: streak length to trip the brake. Caller enforces ≥1
            via the ``_positive_int`` argparse validator.
    """
    if not os.path.isdir(workspace):
        return None

    iter_numbers: list[int] = []
    for name in os.listdir(workspace):
        # Match exactly ``iter_<3 digits>`` to avoid sweeping in
        # artefacts like ``iter_001.bak`` or unrelated dirs.
        if len(name) == 8 and name.startswith("iter_") and name[5:].isdigit():
            iter_numbers.append(int(name[5:]))
    iter_numbers.sort(reverse=True)

    if len(iter_numbers) < max_failed:
        return None

    candidate = iter_numbers[:max_failed]
    for n in candidate:
        manifest_path = os.path.join(workspace, f"iter_{n:03d}", "manifest.json")
        if not os.path.exists(manifest_path):
            return None
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        if manifest.get("status") != "failed":
            return None

    return candidate


def _emit_token_iter_rollup(workspace: str, iteration: int) -> int:
    """Emit one ``[TOKEN_ITER]`` line for the just-finished iteration.

    Because each chain iter is a fresh subprocess with no in-memory
    carry, the cumulative seed is recomputed from ``token_usage.jsonl``
    itself by summing rows where ``iter < iteration`` (skipping
    ``_iter_flush`` markers).
    """
    path = os.path.join(workspace, "token_usage.jsonl")
    if not os.path.exists(path):
        return 0

    calls = 0
    iter_total = 0
    cumulative_prior = 0
    by_node: dict[str, int] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("label") == "_iter_flush":
                    continue
                row_iter = row.get("iter")
                tok_total = (row.get("tokens") or {}).get("total", 0) or 0
                if row_iter == iteration:
                    calls += 1
                    iter_total += tok_total
                    label = row.get("label") or "unlabeled"
                    node_key = label.split(".", 1)[0]
                    by_node[node_key] = by_node.get(node_key, 0) + tok_total
                elif isinstance(row_iter, int) and row_iter < iteration:
                    cumulative_prior += tok_total
    except OSError:
        return 0

    cumulative_total = cumulative_prior + iter_total
    breakdown = "  ".join(f"{k}={v}" for k, v in sorted(by_node.items()))
    print(
        f"[TOKEN_ITER] iter={iteration:02d}  calls={calls}  "
        f"total_tok={iter_total}  ({breakdown})  "
        f"cumulative_total={cumulative_total}"
    )
    return cumulative_total


def resolve_source_paths(source_paths: list[str]) -> list[str]:
    """
    Resolve source path entries to actual JSON file paths.

    Two formats are supported:
      - Direct path: /scratch/.../run_output_*.json (used as-is)
      - Manifest indirection: @manifest:/path/to/manifest.json (read manifest,
        return manifest['output_path'])

    The manifest indirection is used by the orchestrator script when chaining
    iterations: the manifest path is known at submission time, but the actual
    output file path inside it is only known after the iteration completes.
    """
    resolved = []
    for entry in source_paths:
        if entry.startswith("@manifest:"):
            manifest_path = entry[len("@manifest:") :]
            if not os.path.exists(manifest_path):
                raise FileNotFoundError(
                    f"Manifest not found (previous iteration may have failed): {manifest_path}"
                )
            with open(manifest_path) as f:
                manifest = json.load(f)
            status = manifest.get("status")
            if status != "completed":
                raise ValueError(
                    f"Refusing to chain off manifest with status={status!r}: "
                    f"{manifest_path}. Previous iteration did not produce a "
                    f"valid score (best_score={manifest.get('best_score')!r})."
                )
            output_path = manifest.get("output_path")
            if not output_path:
                raise ValueError(f"Manifest has no output_path: {manifest_path}")
            print(f"  Resolved @manifest:{manifest_path} → {output_path}")
            resolved.append(output_path)
        else:
            resolved.append(entry)
    return resolved


def _ordering_by_experiment(tune_output) -> list[dict]:
    """Per-experiment ordering provenance for the iteration manifest.

    One entry per record, each self-identifying by ``exp_id``, because
    ordering may resolve differently across rounds of a single iteration.
    Collapsing them into one iteration-level value would silently misreport
    every round but one (§3.7 granularity rule).

    Only ``resolved_*`` describes selected execution settings, not completed
    traversal; ``proposed_*`` and
    ``override_*`` explain why, and a rejected proposal is carried AS
    rejected so it is never read as agent silence.

    Best-effort by design: the manifest is a handoff aid, and a malformed
    record must not take down an iteration that otherwise succeeded.
    """
    entries: list[dict] = []
    for record in getattr(tune_output, "all_records", None) or []:
        try:
            ordering = ResolvedOrdering.from_record(record)
            entries.append(
                {
                    "exp_id": getattr(record, "exp_id", None),
                    "round_index": getattr(getattr(record, "memory", None), "round_index", None),
                    "proposed_order_strategy": ordering.proposed_strategy,
                    "proposed_file_order": ordering.proposed_file_order,
                    "ordering_proposal_rejected": ordering.proposal_rejected,
                    "ordering_proposal_rejection_reason": ordering.proposal_rejection_reason,
                    "override_order_strategy": ordering.override_strategy,
                    "override_file_order": ordering.override_file_order,
                    "resolved_order_strategy": ordering.resolved_strategy,
                    "resolved_file_order": ordering.resolved_file_order,
                    "ordering_resolution_source": ordering.resolution_source,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[WARN] could not read ordering provenance for a record: {exc}")
    return entries


class AdviceArtifactError(ValueError):
    """A run's advice artifact is unreadable, unparseable, not the one the
    launcher certified, or unable to inject anything.

    Fail-CLOSED, on the ``RequiredProfileBindingError`` precedent: the advice
    artifact is the Gold campaign's INDEPENDENT VARIABLE, so "the file moved
    or changed since the launcher hashed it" must stop the launch rather than
    quietly run a different treatment under the same arm label.

    F-SCHED-5 extends that from IDENTITY to CONSUMABILITY. Certifying WHICH
    bytes were read says nothing about whether those bytes reach a prompt,
    and the binding mechanism is what hides the difference: a misspelled key
    parses, hashes, is distributed to all four bands, is certified by each
    against the parent-pinned digest and is pinned into the run-invariants
    lock as ``_CANONICAL``, while injecting NOTHING. The result is a run
    whose provenance records that advice artifact X was used and whose
    agents received nothing derived from X. ``gold_arm_args`` refuses to
    launch the formal path WITHOUT an advice file, which is the proof that
    the treatment is required; an artifact that cannot inject is therefore
    refused here, by name, rather than satisfying that requirement in form
    only.
    """


#: Top-level keys ``normalize_args`` explodes onto ``args.human_advice_*``.
#: The union of both schemas the loader tolerates during transition:
#: 4-key (propose, implement, tune, mindset) and 5-key (interpret, propose,
#: implement, validate, tune). Any other key reaches NO consumer.
ADVICE_PER_AGENT_KEYS = (
    "interpret",
    "analysis",
    "propose",
    "implement",
    "validate",
    "tune",
)
ADVICE_RECOGNISED_KEYS = (*ADVICE_PER_AGENT_KEYS, "mindset")

#: The ONE way to say "this key is deliberately not advice". A leading
#: underscore marks an inert annotation block. It is spelled as an explicit
#: opt-out precisely so
#: that an unrecognised key WITHOUT it can be treated as the typo it almost
#: always is, instead of being dropped in silence.
ADVICE_INERT_KEY_PREFIX = "_"


def render_advice_value(value: object) -> str | None:
    """Render one advice value the way the agents receive it, or ``None``.

    The ONE rendering authority, called by ``load_advice_artifact`` to decide
    whether a key carries content and by ``normalize_args`` to produce the
    content itself. Split authorities are how a loader comes to accept an
    artifact the consumer then drops: the emptiness test must be the exact
    expression whose result is injected, not a second opinion about it.

    Args:
        value: A parsed JSON value from the advice mapping.

    Returns:
        The rendered text, or ``None`` when the value carries nothing an
        agent could read. A list is joined with newlines (the file format's
        line-list form); every other value is returned unchanged when truthy.
    """
    if isinstance(value, list):
        value = "\n".join(item for item in value if isinstance(item, str))
    return value or None  # type: ignore[return-value]


def _validate_advice_consumability(content: dict, *, resolved: str, observed: str) -> None:
    """Refuse an advice artifact that cannot inject what it declares.

    Three refusals, one property: every declaration in the file reaches a
    consumer, and at least one does.

    1. An unrecognised top-level key that is not ``_``-prefixed. This is the
       misspelling: ``implemnt`` parses as valid JSON and is read by nothing.
    2. A recognised key whose value is not a string or list of strings. The
       list case additionally protects ``normalize_args``, which joins
       unguarded and would raise a bare ``TypeError`` naming no file.
    3. A recognised key present but rendering nothing an agent can read —
       empty, or whitespace only. ``["", ""]`` joins to ``"\\n"``, which is
       TRUTHY, so the consumer's ``or None`` would inject a bare newline;
       emptiness is therefore judged on the STRIPPED rendered text.
    4. No recognised key at all — the vacuous-treatment case.

    Args:
        content: The parsed advice mapping.
        resolved: Absolute path, for the message.
        observed: The artifact's observed digest, for the message — the
            operator needs to know WHICH bytes were refused.

    Raises:
        AdviceArtifactError: naming every offending key and what was wrong
            with it, so one launch surfaces every defect rather than one
            per relaunch.
    """
    where = f"advice artifact at {resolved} (sha256={observed})"

    unrecognised = sorted(
        key
        for key in content
        if key not in ADVICE_RECOGNISED_KEYS and not key.startswith(ADVICE_INERT_KEY_PREFIX)
    )
    if unrecognised:
        raise AdviceArtifactError(
            f"{where} declares top-level keys no agent reads: "
            f"{', '.join(repr(k) for k in unrecognised)}. A key outside "
            f"{ADVICE_RECOGNISED_KEYS} injects nothing, so one transposed letter "
            f"records this artifact as the run's treatment while the agents receive "
            f"nothing derived from it. Correct the spelling, or prefix the key with "
            f"{ADVICE_INERT_KEY_PREFIX!r} to declare it deliberately inert."
        )

    ill_typed: list[str] = []
    empty: list[str] = []
    for key in ADVICE_RECOGNISED_KEYS:
        if key not in content:
            continue
        value = content[key]
        if not isinstance(value, str) and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            ill_typed.append(key)
        else:
            # Emptiness is judged on the RENDERED text, after the same join
            # the consumer applies — `["", ""]` renders to "\n", which is
            # TRUTHY, so the consumer's own `or None` would inject a bare
            # newline and call it advice. `render_advice_value` is left
            # mirroring the consumer exactly; the whitespace test lives here,
            # in the validator, which asks the different question of whether
            # an agent could read anything.
            rendered = render_advice_value(value)
            if rendered is None or not str(rendered).strip():
                empty.append(key)

    if ill_typed:
        raise AdviceArtifactError(
            f"{where} declares {', '.join(repr(k) for k in ill_typed)} with a value "
            f"that is neither a string nor a list of strings. Advice is text an "
            f"agent reads; anything else either reaches a prompt as a repr or "
            f"crashes the line-list join with a bare TypeError naming no file."
        )
    if empty:
        raise AdviceArtifactError(
            f"{where} declares {', '.join(repr(k) for k in empty)} with empty "
            f"content. An empty declaration is dropped by the consumer, so the "
            f"key is present in the artifact and absent from every prompt. Give "
            f"it content or remove the key."
        )

    if not any(key in content for key in ADVICE_RECOGNISED_KEYS):
        raise AdviceArtifactError(
            f"{where} carries no recognised advice key, so it would bind a real "
            f"sha256 into the run-invariants lock and inject NOTHING into any "
            f"round — provenance recording that this artifact was used by a run "
            f"that received nothing derived from it. "
            f"Recognised keys: {', '.join(ADVICE_RECOGNISED_KEYS)}."
        )


@dataclass(frozen=True)
class AdviceArtifact:
    """The advice artifact this process actually read.

    Attributes:
        path: The resolved ABSOLUTE path the bytes came from.
        sha256: The OBSERVED sha256 of those exact bytes. This — never a
            declared value — is what reaches the workspace lock.
        content: The parsed advice mapping, from the SAME bytes.
    """

    path: str
    sha256: str
    content: dict


def load_advice_artifact(path: str, *, declared_sha256: str | None = None) -> AdviceArtifact:
    """Read, certify and parse the advice artifact from ONE read of the file.

    TOCTOU-safe by construction, the ``_load_bound_overlay`` precedent
    (``core/runtime_control/watchdog_profile.py``): the file is read exactly
    once with ``Path.read_bytes``, the sha256 is computed over that bytes
    object, and ``json.loads`` parses the SAME object — never a re-open, so
    no window exists in which a swapped file is hashed as one content and
    parsed as another.

    ``declared_sha256`` is the campaign launcher's OBSERVATION, forwarded on
    argv as a cross-process integrity check. It is CERTIFIED against the
    digest computed here and then discarded: the returned ``sha256`` is
    always this process's own observation. That asymmetry is the point —
    stamping the declared value would make the lock an ECHO, which is
    behaviourally invisible right up until the day the two differ, and that
    is exactly the day the record has to be true.

    Args:
        path: The advice artifact path, absolute or relative to this
            process's working directory.
        declared_sha256: The digest the launcher observed, or ``None`` when
            nothing was declared (a hand-run chain).

    Returns:
        The artifact, carrying the resolved path, the observed digest and
        the parsed content.

    Certification is about WHICH bytes; it is not about whether those bytes
    can do anything. ``_validate_advice_consumability`` closes that gap
    (F-SCHED-5) before the artifact is returned, so an artifact that would
    inject nothing never reaches the digest's distribution at all.

    Raises:
        AdviceArtifactError: the file is missing or unreadable, its bytes do
            not parse as a JSON object, its digest is not
            ``declared_sha256``, or its content cannot inject (an
            unrecognised key, an ill-typed value, an empty declaration, or
            no recognised key at all).
    """
    resolved = os.path.abspath(path)
    try:
        data = Path(resolved).read_bytes()
    except FileNotFoundError:
        raise AdviceArtifactError(
            f"advice artifact not found: {resolved}. A declared advice file is "
            f"the run's treatment — a missing one refuses the launch rather "
            f"than running an untreated arm under a treated label."
        ) from None
    except OSError as exc:
        raise AdviceArtifactError(f"advice artifact at {resolved} is unreadable: {exc}") from exc
    observed = hashlib.sha256(data).hexdigest()
    if declared_sha256 is not None and declared_sha256 != observed:
        raise AdviceArtifactError(
            f"advice artifact identity cannot be certified: the file at "
            f"{resolved} hashes to sha256={observed}, but this launch declares "
            f"sha256={declared_sha256}. The bytes are not the ones the "
            f"launcher recorded — refuse, never consume them. Every band of a "
            f"campaign must read one artifact; an edit between two band "
            f"launches is exactly what this comparison exists to catch."
        )
    try:
        content = json.loads(data)
    except json.JSONDecodeError as exc:
        raise AdviceArtifactError(
            f"advice artifact at {resolved} (sha256={observed}) is not valid JSON: {exc}"
        ) from exc
    if not isinstance(content, dict):
        raise AdviceArtifactError(
            f"advice artifact at {resolved} (sha256={observed}) must be a JSON "
            f"object of advice keys; got {type(content).__name__}."
        )
    _validate_advice_consumability(content, resolved=resolved, observed=observed)
    return AdviceArtifact(path=resolved, sha256=observed, content=content)


def resolve_advice_artifact(args: argparse.Namespace) -> AdviceArtifact | None:
    """The ONE authority for "which advice artifact does this launch read".

    Idempotent and cached on ``args``: ``normalize_args`` resolves it to get
    the advice CONTENT, and ``resolve_launch_identity`` resolves it to get
    the lock IDENTITY. Both must see the same bytes, so exactly one read
    happens per process and both callers go through here — a second reader
    with its own ``open()`` is how the content and the pinned identity would
    come to describe different files.

    Returns:
        The artifact, or ``None`` when this launch declares no advice.
    """
    cached = getattr(args, "advice_artifact", None)
    if cached is not None:
        return cached
    # --advice (4-key) takes precedence over --human_advice_file (5-key).
    path = args.advice or args.human_advice_file
    if not path:
        return None
    artifact = load_advice_artifact(path, declared_sha256=args.advice_sha256)
    args.advice_artifact = artifact
    return artifact


@dataclass(frozen=True)
class LaunchIdentity:
    """The run-identity values this launch resolved ONCE (arXiv U1).

    Built by :func:`resolve_launch_identity` before any manifest can be
    written, and handed — as ONE object — to the invariants pre-flight, the
    workflow launch config and every ``write_manifest`` call, so the three
    cannot resolve the lit-review flag or the arm label differently (the W7
    lesson, applied to identity instead of composition).

    Attributes:
        experiment_arm: The opaque arm label, or ``None`` (unlabelled).
        lit_review_enabled: Resolved topology flag (CLI > YAML > ``False``).
        lit_review_config_path: The operator's config path, as given.
        lit_review_config_sha256: sha256 of the resolved config bytes when
            enabled, else ``None``.
        baseline_isolation: arXiv U3 — the WITHOUT arm's explicit isolation
            flag, straight from ``--baseline_isolation``.
        advice_path: Resolved absolute path of the advice artifact this
            launch read, or ``None``. Recorded, never compared.
        advice_sha256: The OBSERVED digest of that artifact's bytes, or
            ``None``. This is the campaign's treatment identity and it is
            CANONICAL in the workspace lock.
    """

    experiment_arm: str | None
    lit_review_enabled: bool
    lit_review_config_path: str | None
    lit_review_config_sha256: str | None
    baseline_isolation: bool = False
    advice_path: str | None = None
    advice_sha256: str | None = None


def write_manifest(
    iter_dir: str,
    run_name: str,
    results: list,
    *,
    crashed: bool = False,
    healthgate_mode: str | None = None,
    result_authority: str | None = None,
    chain_incumbent_used: float | None = None,
    chain_incumbent_source: dict | None = None,
    health_feedback_policy: dict | None = None,
    fixed_candidate_provenance: dict | None = None,
    launch_identity: LaunchIdentity | None = None,
    replacement: ManifestReplacementRequest | None = None,
) -> dict:
    """
    Write a manifest.json summarizing this iteration's output.

    The manifest is the discoverable handoff between iterations: the next
    iteration's job reads it to find this iteration's tuning output path.

    arXiv U1 — ``launch_identity`` stamps ``experiment_arm``,
    ``lit_review_enabled`` and ``lit_review_config_sha256`` on EVERY branch
    under the lock's own omission rule: a key is written only when it
    departs from the legacy default (arm ``None``, lit-review ``False``, sha
    ``None``), so an unlabelled lit-review-OFF iteration's manifest is
    byte-identical to its pre-U1 form and a reader applies ONE rule to the
    lock and the manifest alike (absent = the default). ``None`` (a caller
    that predates the parameter) stamps nothing.

    S2 / U5 (#258): the manifest is published WRITE-ONCE through
    ``core.iteration_manifest.publish_iteration_manifest`` — it gains a
    ``manifest_sha256`` self-digest, and a second write for the same
    iteration is a named ``ManifestAlreadyPublishedError`` unless
    ``replacement`` carries the explicit operator request, in which case
    the previous manifest is set aside and its digests are recorded under
    ``manifest_replacement``. ``run_output_sha256`` is always computed for
    THIS publication's artifact; it is never copied from a previous
    manifest.

    Status taxonomy (consumed by ``core/resume.py:_read_manifest``):
      * ``"completed"`` — workflow produced a real best_denoising_score.
        Resume: consume the run_output and restore the plugin.
      * ``"no_records"`` — workflow ran cleanly but every tuner round
        failed/was skipped (gate exhaustion, all-rounds returned None
        score). The chain MUST keep going so the next iter's LLM can see
        the bounded negative feedback and adapt. Resume: transport only that
        feedback; skip the invalid artifact and restore no plugin or incumbent.
      * ``"failed"`` — workflow itself crashed (Python exception, seed-
        resolution error, restore_prior_state error). The chain halts.
        Set via ``crashed=True``.
    """
    # `tune_output` is only bound on the completed branch. The stamps at the
    # bottom of this function run on EVERY branch, so it is initialised here
    # rather than guarded there — a crashed or record-less iteration has no
    # tuner output, and `None` is the honest answer for its declared posture.
    tune_output = None

    if crashed:
        manifest = {
            "status": "failed",
            "iteration_dir": iter_dir,
            "output_path": None,
            "model_name": None,
            "best_score": None,
        }
    elif not results:
        manifest = {
            "status": "no_records",
            "iteration_dir": iter_dir,
            "output_path": None,
            "model_name": None,
            "best_score": None,
        }
    else:
        tune_output = results[0]
        # The tuning output is at {iter_dir}/iteration_001/{model_name}/run_output_{run_name}.json
        # (run_workflow always wraps each iteration in iteration_NNN, even with max_iterations=1)
        model_name = tune_output.model_type
        output_path = os.path.join(
            iter_dir, "iteration_001", model_name, f"run_output_{run_name}.json"
        )
        if not os.path.exists(output_path):
            # Defensive: scan iter_dir for the actual file
            candidates = glob.glob(
                os.path.join(iter_dir, "**", f"run_output_{run_name}.json"),
                recursive=True,
            )
            if candidates:
                output_path = candidates[0]
        # A None best_denoising_score means every tuner round was skipped
        # or returned no score (gate exhaustion or LLM-level dead-end).
        # Mark as no_records so the chain continues; resume will see the
        # null output_path and skip this iter cleanly.
        #
        # `score` is CHAINABILITY, not science: it is `top_record` over ALL
        # records, trial and formal mixed (records.py), so it answers "is
        # there an artifact for the next iteration to consume?" and nothing
        # else. `status` keeps deriving from it because the manifest status
        # vocabulary is completed|failed|no_records and is shared by
        # core/resume.py, result consumers, and the inspector. A
        # trial-only iteration DID produce a consumable run_output and a
        # restorable plugin.
        score = tune_output.best_denoising_score
        manifest = {
            "status": "completed" if score is not None else "no_records",
            "iteration_dir": iter_dir,
            "output_path": output_path if score is not None else None,
            "model_name": model_name,
            # The headline number is the FORMAL best — `None` when no formal
            # round produced one. The mixed top score keeps its own key
            # below, under the name that says what it is.
            "best_score": getattr(tune_output, "best_formal_denoising_score", None),
            "raw_best_score": score,
            "best_valid_score": getattr(tune_output, "best_valid_denoising_score", None),
            "raw_best_formal_score": getattr(tune_output, "best_formal_denoising_score", None),
            "best_valid_formal_score": getattr(
                tune_output, "best_valid_formal_denoising_score", None
            ),
            # V19 PR 1 (P1-C4) — read-only trial-best bookkeeping mirror.
            "best_valid_trial_score": getattr(
                tune_output, "best_valid_trial_denoising_score", None
            ),
            "completed_rounds": tune_output.completed_rounds,
            "health_checks_config": getattr(tune_output, "health_checks_config", None),
            # DS6c — invariant stamps (scalar comparability boundary).
            "resolved_data_scope": getattr(tune_output, "resolved_data_scope", None),
            "health_gate_enabled": getattr(tune_output, "health_gate_enabled", None),
            "health_config_sha256": getattr(tune_output, "health_config_sha256", None),
            "formal_reference_score": getattr(tune_output, "formal_reference_score", None),
            # V20 PR D §16.C — the provenance travels WITH the reference.
            # `formal_reference_score: null` alone is ambiguous: it means
            # "no incumbent", "gates off" or "the bound was infinite", and
            # those call for different readings of the iteration.
            "formal_comparison_reference_source": getattr(
                tune_output, "formal_comparison_reference_source", None
            ),
            "resolved_skip_formal_threshold": getattr(
                tune_output, "resolved_skip_formal_threshold", None
            ),
            "resolved_bypass_formal_threshold": getattr(
                tune_output, "resolved_bypass_formal_threshold", None
            ),
            # V19 PR 1 (P1-C3, design §3.4/Invariant II) — the CHAIN
            # incumbent this iteration consumed, under keys DISTINCT from
            # every iteration-local best_* field. ``used`` is what the
            # gates received (null when the coupling flag is OFF or no
            # incumbent existed); ``source`` is the reconstruction
            # provenance (recorded even when unconsumed, so
            # "provided-but-not-consumed" is auditable).
            "chain_incumbent_used": chain_incumbent_used,
            "chain_incumbent_source": chain_incumbent_source,
            # V19 PR 2 (§3.7) — ordering provenance, KEYED PER EXPERIMENT.
            # Ordering can resolve differently for different rounds of one
            # iteration (the agent may propose differently each round when no
            # operator override is in force), so a single iteration-level
            # value would misreport every round but one. Never collapse this.
            "ordering_by_experiment": _ordering_by_experiment(tune_output),
        }
        # V19 PR 1 (§3.6) — immutable artifact identity: hash the exact
        # run_output this manifest describes, so resume can fail closed
        # on any later mutation (ReplayIntegrityError).
        if manifest["output_path"] is not None and os.path.isfile(manifest["output_path"]):
            digest = hashlib.sha256()
            with open(manifest["output_path"], "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            manifest["run_output_sha256"] = digest.hexdigest()

    # F-SCANB-3 — what this iteration produced SCIENTIFICALLY, beside the
    # chainability status rather than inside it, computed by the shared role
    # authority (`core.record_role`) over the persisted record shape. All ten
    # v20 attempt-3 manifests read `status: completed` with a best_score
    # between 0.479 and 10.708 while carrying ZERO formal records, so an
    # operator — and every trajectory built from these manifests — read trial
    # scores as the campaign's results while the status concealed that no
    # formal round had ever run.
    #
    # Stamped on EVERY branch, like the three stamps below: a crashed or
    # record-less iteration produced no formal evidence either, and an
    # all-zero posture is the honest way to say so.
    manifest["formal_evidence"] = formal_evidence_of(tune_output).model_dump()

    # V19 PR 3 (§3.9) — the chain's structured-health-feedback CONTROL
    # POLICY (flag + retention), stamped on EVERY manifest branch
    # (completed / no_records / failed) so failed iterations stay
    # auditable. Policy only: per-round gate evidence lives in the
    # records and the interpretation digest — never duplicated here.
    manifest["health_feedback_policy"] = health_feedback_policy

    # Issue #396 — a scientifically invalid iteration still has evidence.
    #
    # ``no_records`` deliberately names no consumable model artifact: resume
    # must not restore its plugin, score, or incumbent.  A validated tuner
    # output can nevertheless carry the bounded summaries that explain why
    # no candidate was usable.  Persist those summaries on the write-once,
    # self-digested manifest so the next process can learn from the failure
    # without treating the invalid run output as a successful handoff.
    if manifest["status"] == "no_records" and tune_output is not None:
        negative_feedback = {
            field: value.model_dump(mode="json")
            for field in ("gate_exhaustion", "trial_validity_feedback")
            if (value := getattr(tune_output, field, None)) is not None
        }
        if negative_feedback:
            manifest["negative_feedback"] = negative_feedback

    # V20 FU-D-11 — WHICH candidate plan this iteration ran, when the
    # proposer was bypassed. Stamped on EVERY branch, like the policy above:
    # an acceptance run that skipped the proposer must be able to prove what
    # it used, and a failed iteration is exactly when that matters. `None`
    # means the proposer chose normally.
    manifest["fixed_candidate_provenance"] = fixed_candidate_provenance

    # V20 PR A (§11) — pre-flight execution provenance, stamped on EVERY
    # branch for the same reason as the policy above: a crashed iteration
    # is exactly when you want to know how the pre-flight ran.
    #
    # Imported from the adapter rather than written as a literal, so the
    # manifest and the mechanism cannot drift apart. This records which
    # mechanism the build ships; that production reaches it is a separate
    # claim, proven by the reachability guardrails.
    manifest["preflight_execution_mode"] = PREFLIGHT_EXECUTION_MODE

    # V20 PR D (D-C1a) — the declared enforcement/authority axes, stamped on
    # EVERY branch for the same reason as the two above: a crashed iteration
    # is exactly when "was this run even allowed to be authoritative?" has
    # to be answerable.
    #
    # V20 PR D — the DECLARATION is a validated LAUNCH fact, not a
    # tuner-result field. D-C1b refuses the launch outright unless both axes
    # are declared and consistent, so by the time any artifact is written
    # they exist — whether the iteration completed, produced no records,
    # degraded, or crashed.
    #
    # CORRECTED after Gate 2 attempt 1: this previously read the posture off
    # `tune_output` and wrote `null` whenever the tuner produced none. A real
    # chain launched with `--healthgate_mode blocking` therefore recorded
    # `healthgate_mode: null` because it failed, which makes its records
    # `unreconstructable_legacy` under D-C4 even though the run DID declare
    # its posture. The caller's validated declaration is authoritative; the
    # tuner output is only a fallback for callers that predate this
    # parameter.
    manifest["healthgate_mode"] = (
        healthgate_mode
        if healthgate_mode is not None
        else getattr(tune_output, "healthgate_mode", None)
    )
    manifest["result_authority"] = (
        result_authority
        if result_authority is not None
        else getattr(tune_output, "result_authority", None)
    )

    # arXiv U1 (#253 / #254) — run identity, on EVERY branch, under the
    # lock's omission rule (see the docstring). A crashed labelled iteration
    # is exactly when "which arm was this?" has to be answerable.
    if launch_identity is not None:
        if launch_identity.experiment_arm is not None:
            manifest["experiment_arm"] = launch_identity.experiment_arm
        if launch_identity.lit_review_enabled:
            manifest["lit_review_enabled"] = True
        if launch_identity.lit_review_config_sha256 is not None:
            manifest["lit_review_config_sha256"] = launch_identity.lit_review_config_sha256
        # arXiv U3 — the isolation flag, under the same omission rule.
        if launch_identity.baseline_isolation:
            manifest["baseline_isolation"] = True

    # S2 / U5 — self-digest + write-once publish (+ explicit replacement
    # provenance). Stamped LAST so every key above, including any a later
    # producer change adds, is covered by the digest.
    manifest_path = publish_iteration_manifest(iter_dir, manifest, replacement=replacement)
    print(f"Manifest written: {manifest_path}")
    return manifest


@dataclass(frozen=True)
class IterationDirPlan:
    """The iteration's directory, run name and manifest-slot decision."""

    run_name: str
    iter_dir: str
    #: ``None`` for a normal (first) publication; the explicit request when
    #: the operator asked to replace an existing manifest.
    manifest_replacement: ManifestReplacementRequest | None


#: #258 refinement (operator ruling, 2026-08-24): the two TERMINAL states an
#: auto-resume relaunch may replace. A ``completed`` manifest is immutable to
#: auto-resume; anything unrecognisable is refused, never guessed.
_AUTO_RESUME_REPLACEABLE_STATUSES = frozenset({"failed", "no_records"})

#: Recognisable prefix of the provenance reason an auto-resume recovery
#: records — the evidence that the replacement happened BECAUSE of
#: auto-resume, not an operator's explicit destructive operation.
AUTO_RESUME_REPLACEMENT_REASON_PREFIX = "auto_resume recovery"


def _auto_resume_replacement(iter_dir: str) -> ManifestReplacementRequest | None:
    """Classify the manifest slot for an auto-resume relaunch (#258 refinement).

    Auto-resume counts as explicit recovery intent ONLY for a slot whose
    existing manifest is terminally ``failed`` or ``no_records``; the
    replacement then goes through the SAME explicit replacement path (set
    aside + provenance) as ``--replace_iteration_manifest``. Everything else
    returns ``None`` so ``classify_manifest_slot`` refuses exactly as it
    would without the flag: a fresh slot needs no replacement, and a
    ``completed`` — or unreadable / unrecognisable — manifest is never
    replaced by auto-resume. The classification lives HERE, at the
    orchestration boundary; the publish layer never inspects a status.
    """
    path = manifest_path(iter_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            existing = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None  # unclassifiable — fail closed into the write-once refusal
    status = existing.get("status") if isinstance(existing, dict) else None
    if status not in _AUTO_RESUME_REPLACEABLE_STATUSES:
        return None
    return ManifestReplacementRequest(
        reason=(
            f"{AUTO_RESUME_REPLACEMENT_REASON_PREFIX}: prior iteration manifest was "
            f"terminal {status!r} (#258)"
        )
    )


def prepare_iteration_dir(
    workspace: str,
    start_iteration: int,
    *,
    replace_iteration_manifest: bool,
    replacement_reason: str | None,
    auto_resume_recovery: bool = False,
) -> IterationDirPlan:
    """Create ``{workspace}/iter_{N:03d}`` and decide its manifest slot (#258).

    Refuses BEFORE any expensive work, so an hours-long iteration can never
    end in a refused manifest publish. ``auto_resume_recovery`` (the
    ``--auto_resume`` flag, forwarded by ``run_chain.sh`` only when the
    inspector computed the start iteration) authorizes the SAME replacement
    path for a manifest whose terminal status is ``failed`` or
    ``no_records`` — and nothing else.

    Raises:
        ManifestAlreadyPublishedError: a manifest already exists for this
            iteration and no replacement applies (write-once) — including a
            ``completed`` or unclassifiable manifest under auto-resume.
        ManifestReplacementError: ``--replace_iteration_manifest`` without a
            non-empty ``--replacement_reason``, a reason without the flag, or
            an explicit replacement requested where no manifest exists.
    """
    run_name = f"iter_{start_iteration:03d}"
    iter_dir = os.path.join(workspace, run_name)
    os.makedirs(iter_dir, exist_ok=True)
    replacement: ManifestReplacementRequest | None = None
    if replace_iteration_manifest:
        try:
            replacement = ManifestReplacementRequest(reason=replacement_reason or "")
        except ValueError as exc:
            raise ManifestReplacementError(
                f"--replace_iteration_manifest requires --replacement_reason '<why>': {exc}"
            ) from exc
    elif replacement_reason:
        raise ManifestReplacementError(
            "--replacement_reason was given without --replace_iteration_manifest; a "
            "replacement must be requested explicitly, not implied by a reason."
        )
    elif auto_resume_recovery:
        # #258 refinement: recovery intent applies to a failed/no_records
        # slot ONLY; None falls through to the write-once refusal.
        replacement = _auto_resume_replacement(iter_dir)
    classify_manifest_slot(iter_dir, replacement)
    return IterationDirPlan(run_name=run_name, iter_dir=iter_dir, manifest_replacement=replacement)


def build_parser() -> argparse.ArgumentParser:
    """Build the per-iteration runner's argument parser.

    Extracted from ``main`` so unit tests can exercise the CLI surface
    without invoking the workflow. The parser intentionally accepts both
    ``--start_iteration`` (canonical) and ``--iteration`` (deprecated alias);
    :func:`normalize_args` collapses them after parsing.
    """
    parser = argparse.ArgumentParser(
        description="Run one iteration of the SIDERIUS exploration workflow."
    )
    parser.add_argument(
        "--workspace",
        type=str,
        required=True,
        help="Root output directory for this exploration (shared across all iterations).",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        required=True,
        help="Chain-level run name (e.g. 'explore_v12_0504'). Used as the "
        "audit-log identity (chain_run_name) and seeded into the "
        "immutable run_id sidecar at {workspace}/.token_run_id. "
        "Must remain identical across every iteration of the chain — "
        "the bridge refuses run_id mutation per §1.4.1.",
    )
    # Phase 6.8 Task 2 Commit 8 — rename --iteration → --start_iteration so the
    # name matches the unified resume/chain philosophy ("which iter is this
    # invocation about to run; iters [1, N-1] are absorbed from disk").
    # The positional meaning is unchanged; only the name moves. --iteration is
    # kept as a deprecated alias for one release. See
    # docs/phase68_orchestrator_memory_and_resume.md §3.5 Commit 8.
    parser.add_argument(
        "--start_iteration",
        type=int,
        default=None,
        help="Iteration number (1-based) to run *now*. When > 1, the runner "
        "auto-restores plugin classes from iters [1, N-1] via "
        "core.resume.restore_prior_state. Mutually exclusive with the "
        "deprecated --iteration alias.",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=None,
        dest="iteration_legacy",
        help="DEPRECATED — alias for --start_iteration. Will be removed after "
        "the next stable run. Use --start_iteration instead.",
    )
    # Phase 6.8 Commit 11 — rename --source_paths → --seed_paths so the
    # canonical name reflects what the list actually means: *seed* source
    # data, not the full source set (prior iters are auto-discovered from
    # {workspace}/iter_NNN/manifest.json). --source_paths is kept as a
    # deprecated alias for one release. See §3.5 Commit 11.
    parser.add_argument(
        "--seed_paths",
        type=str,
        nargs="+",
        default=None,
        help="Explicit list of HyperparamTuningOutput JSON paths to use as "
        "*seed* source data. Prior iters' run_outputs are auto-discovered "
        "from {workspace}/iter_NNN/manifest.json by restore_prior_state — "
        "they no longer need to be listed here for chain runs (back-compat "
        "still accepts @manifest: indirection in this list). "
        "Mutually exclusive with the deprecated --source_paths alias. "
        "OPTIONAL: omit the flag entirely to start a cold chain with no prior "
        "experimental evidence (a bare --seed_paths with no values is still an "
        "error).",
    )
    parser.add_argument(
        "--source_paths",
        type=str,
        nargs="+",
        default=None,
        dest="source_paths_legacy",
        help="DEPRECATED — alias for --seed_paths. Will be removed after "
        "the next stable run. Use --seed_paths instead.",
    )
    parser.add_argument("--max_rounds", type=int, default=3, help="Tuning rounds per iteration.")
    parser.add_argument(
        "--max_proposal_attempts",
        type=int,
        default=3,
        help="Retry budget for propose→implement→validate.",
    )
    parser.add_argument(
        "--llm_model",
        type=str,
        default="gemini-3.1-pro-preview",
        help="Gemini model ID for all 5 agents (the planner sub-call of the "
        "tuner uses this; the reflector sub-call uses --reflect_model_id "
        "if set, else falls back to a provider-aware default).",
    )
    parser.add_argument(
        "--reflect_provider",
        type=str,
        default=None,
        choices=["gemini", "openai"],
        help="Optional separate provider for the tuner's reflector sub-call. "
        "When unset, the reflector uses the same provider as the planner.",
    )
    parser.add_argument(
        "--reflect_model_id",
        type=str,
        default=None,
        help="Optional separate model for the tuner's reflector sub-call. "
        "When unset for the gemini provider, defaults to 'gemini-2.5-flash' "
        "(GA model with unlimited daily quota). When unset for other "
        "providers, falls back to --llm_model (legacy behavior).",
    )
    parser.add_argument(
        "--gpu_memory_limit_gb",
        type=int,
        default=None,
        help="Hard cap on GPU memory per process (Phase 2, not yet implemented end-to-end).",
    )
    parser.add_argument(
        "--max_epochs",
        type=_positive_int,
        default=1,
        help="Hard cap on epochs per round. Must be >= 1; None forbidden. "
        "Per-mode overrides: --trial_max_epochs / --formal_max_epochs take "
        "precedence for their round role (D-BUD-6).",
    )
    parser.add_argument(
        "--trial_max_epochs",
        type=_positive_int,
        default=None,
        help="TRIAL-role epoch ceiling (campaign decision D-BUD-6; frozen "
        "campaign posture: trial 2 / formal 1). Precedence for a trial "
        "round: this value -> --max_epochs -> no clamp; formal rounds never "
        "read it. Must be >= 1; omit to keep the mode-agnostic --max_epochs.",
    )
    parser.add_argument(
        "--formal_max_epochs",
        type=_positive_int,
        default=None,
        help="FORMAL-role epoch ceiling (campaign decision D-BUD-6). "
        "Precedence for a formal round: this value -> --max_epochs -> no "
        "clamp; trial rounds never read it. Must be >= 1; omit to keep the "
        "mode-agnostic --max_epochs.",
    )
    parser.add_argument(
        "--skip_formal_min_delta",
        type=float,
        default=-1.0,
        help="Skip all formal rounds when best_trial_score < "
        "(current_run_best_formal_score + skip_formal_min_delta). "
        "Matches HyperparamTuningInput schema default -1.0. "
        "Set to 0.0 to skip whenever trial does not beat current best.",
    )
    parser.add_argument(
        "--bypass_formal_time_budget_min_delta",
        type=float,
        default=0.0,
        help="Bypass the formal time-budget gate when best_trial_score >= "
        "(current_run_best_formal_score + bypass_formal_time_budget_min_delta). "
        "Matches HyperparamTuningInput schema default 0.0. "
        "Set to 0.5 to only bypass when trial beats current best by >= 0.5 dB.",
    )
    parser.add_argument(
        "--bypass_formal_time_budget_minutes",
        type=float,
        default=None,
        help="Lane F3: ELEVATED wall-time ceiling (minutes) for a score-qualified "
        "bypass formal attempt — one value drives BOTH re-evaluated admission and "
        "the watchdog ceiling. Omitted (None) = a qualified bypass grants NO "
        "extension. Campaign frozen value: 200.",
    )
    parser.add_argument(
        "--order_strategy_override",
        type=str,
        default=None,
        choices=["shuffle", "sequential"],
        help="V19 PR 2: force the training sample visitation order for every "
        "round of this chain, overriding any agent proposal. Unset (default) "
        "= the agent's proposal decides, falling back to 'shuffle' (pre-V19 "
        "behavior). Pinned in the run-invariants lock — changing it mid-chain "
        "is a violation.",
    )
    parser.add_argument(
        "--file_order_override",
        type=str,
        default=None,
        help="V19 PR 2: comma-separated file visitation ORDER for "
        "--order_strategy_override sequential, e.g. '4,6,5,9,7,8'. Order is "
        "preserved as written and must be a full permutation of the resolved "
        "DataScope. Omit for ascending file index.",
    )
    parser.add_argument(
        "--enable_chain_incumbent_formal_gates",
        action="store_true",
        help="V19 PR 1: let the formal delta gates CONSUME the reconstructed "
        "chain incumbent as their reference. Default OFF (gates see no "
        "reference; reconstruction, provenance, and manifest stamps still "
        "run unconditionally). Rollback = omit this flag; the pre-V19 "
        "fixed-0.0 reference is not restorable.",
    )
    parser.add_argument(
        "--enable_structured_health_feedback",
        action="store_true",
        help="V19 PR 3: render structured HealthGate evidence (per-round "
        "gate fields + collapse fingerprints) in the interpreter and "
        "proposer prompts. Default OFF: prompts are byte-identical to "
        "pre-PR3; the deterministic evidence is still recorded in "
        "artifacts. Pinned in the run-invariants lock — changing it "
        "mid-chain is a violation (use a new workspace).",
    )
    parser.add_argument(
        "--health_feedback_history_window_iterations",
        type=int,
        default=3,
        help="V19 PR 3: fingerprint-history retention window — TOTAL "
        "iterations retained including the current one. Must be >= 1. "
        "Pinned in the run-invariants lock.",
    )
    parser.add_argument(
        "--health_feedback_history_max_entries_per_model",
        type=int,
        default=8,
        help="V19 PR 3: retained fingerprint-history entries per model "
        "(deterministic trim bound). Must be >= 1. Pinned in the "
        "run-invariants lock.",
    )
    parser.add_argument(
        # BooleanOptionalAction, not store_true: the consumer below used to
        # read `args.is_trial or True`, so an explicit False was erased and
        # the flag could never express anything. Default stays True, so
        # omitting it behaves exactly as before; `--no-is_trial` is now the
        # way to ask for a formal-from-the-start run.
        "--is_trial",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable trial mode (default: True). Use --no-is_trial for formal.",
    )
    parser.add_argument(
        "--trial_strategy",
        type=str,
        default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="DEPRECATED no-op (DS7) — warns and is ignored. Use --data_scope.",
    )
    # Lane F2 — the three trial-side portions are TRI-STATE: a TYPED value
    # is EXPERIMENT_FIXED (merged into the plan_overrides lock at the
    # workflow layer, so trial planning cannot silently override it);
    # omitted (None) is AGENT_CONTROLLED — the planner's values execute.
    parser.add_argument(
        "--trial_portion",
        type=_portion_floor,
        default=None,
        help="Floor 0.01 (segment-integrity; mirrors Pydantic ge=0.01). "
        "Typed = EXPERIMENT_FIXED; omitted = agent-controlled (Lane F2).",
    )
    # F-RC-1: the shared parser floor (see `_portion_floor`); its target
    # `HyperparamTuningInput.train_portion` declares ge=0.01.
    parser.add_argument("--train_portion", type=_portion_floor, default=None)
    parser.add_argument(
        "--eval_portion",
        type=_portion_floor,
        default=None,
        help="Floor 0.01 (segment-integrity; mirrors Pydantic ge=0.01). "
        "Typed = EXPERIMENT_FIXED; omitted = agent-controlled (Lane F2).",
    )
    # --- Formal-mode training levers (Phase M, docs §12) + eval scope (Phase R, §13) ---
    # Formal eval strategy is locked to ``snapshot``; the portion defaults to
    # 1.0 (production full-clone for cross-arch comparability, §12.2) and
    # is operator-configurable via ``--formal_eval_portion`` for smoke / CI
    # runs that need to fit a tight ``--formal_time_budget_minutes`` — §13.
    parser.add_argument(
        "--formal_strategy",
        type=str,
        default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="Training-side strategy on formal rounds (default snapshot).",
    )
    parser.add_argument(
        "--formal_portion",
        # F-RC-1: the shared parser floor (see `_portion_floor`).
        type=_portion_floor,
        default=0.1,
        help="Fraction of segments per file for formal training scope (default 0.1).",
    )
    parser.add_argument(
        "--formal_train_portion",
        # F-RC-1: the shared parser floor (see `_portion_floor`).
        type=_portion_floor,
        default=1.0,
        help="Per-epoch iteration fraction for formal training (default 1.0).",
    )
    parser.add_argument(
        "--formal_eval_portion",
        # F-RC-1: the shared parser floor (see `_portion_floor`).
        type=_portion_floor,
        default=1.0,
        help=(
            "Fraction of segments per file for the formal-mode eval scope "
            "(snapshot strategy). Default 1.0 = production full-clone for "
            "cross-architecture score comparability. Lower (e.g. 0.05) for "
            "smoke / CI runs that must fit --formal_time_budget_minutes "
            "(Phase R, §13)."
        ),
    )
    parser.add_argument(
        "--force_formal_round",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "When True (default), the last round of every iteration forces "
            "formal mode (planner is told 'formal mode is MANDATORY' and the "
            "post-LLM override flips is_trial=False). This is the production "
            "contract — produces a cross-architecture comparable formal "
            "score. Pass --no-force_formal_round to let the planner choose "
            "trial mode on the last round (planner is told 'formal mode is "
            "OPTIONAL' and no override fires). Use only for testing / "
            "debugging where the trial-mode portions need to take effect on "
            "the final round."
        ),
    )
    parser.add_argument(
        "--formal_round_strategy",
        type=str,
        choices=[
            "full_clone",
            "hybrid_params",
            "independent",  # canonical
            "inherit_best_trial",
            "llm_propose",  # legacy aliases
        ],
        default="full_clone",
        help=(
            "Orchestration policy for the forced formal round. "
            "'full_clone' (default): inherit model_config, loss_config, lr, "
            "epochs, and batch_size from the highest-scoring trial-mode "
            "success in the iteration. "
            "'hybrid_params': inherit only loss_config + lr (planner keeps "
            "model_config, epochs, batch_size). "
            "'independent': planner's choices honored verbatim. "
            "Legacy aliases accepted: 'inherit_best_trial' -> full_clone, "
            "'llm_propose' -> independent (resolved by schema). "
            "Has no effect when --no-force_formal_round is set."
        ),
    )
    parser.add_argument(
        "--degenerate_penalty_score",
        type=float,
        default=None,
        help=(
            "Operator policy for the agent's reaction when score_vector's "
            "task-specific health check flags a degenerate formal-round output. "
            "Default None nulls the denoising_score (the round can never be "
            "picked as 'best'). A float (typically large-negative, e.g. -5.0) "
            "is used as the round's score, letting the planner rank the "
            "failure below any healthy success. In both cases status is set "
            "to 'failed_mode_collapse' and failure_reason is preserved."
        ),
    )
    parser.add_argument(
        "--cleanup_denoised",
        action="store_true",
        help="Delete denoised H5 files after scoring (recommended for production).",
    )
    parser.add_argument(
        "--human_advice_file",
        type=str,
        default=None,
        help="Path to a JSON file with human advice for each agent. "
        'Schema: {"interpret":"...", "analysis":"...", "propose":"...", '
        '"implement":"...", "validate":"...", "tune":"...", "mindset":"..."} '
        "— a string or a list of lines per key. The key set is CLOSED: an "
        "unrecognised key is refused as a probable misspelling (prefix it "
        "with '_' to declare it deliberately inert), as is a recognised key "
        "with empty content, and a file with no recognised key at all. "
        "Individual --human_advice_* flags override file values.",
    )
    parser.add_argument(
        "--human_advice_interpret",
        type=str,
        default=None,
        help="Human guidance for the interpretation agent.",
    )
    parser.add_argument(
        "--human_advice_analysis",
        type=str,
        default=None,
        help="Human guidance for the optional Data Analysis Agent.",
    )
    parser.add_argument(
        "--human_advice_propose",
        type=str,
        default=None,
        help="Human guidance for the proposal agent.",
    )
    parser.add_argument(
        "--human_advice_implement",
        type=str,
        default=None,
        help="Human guidance for the implementor agent.",
    )
    parser.add_argument(
        "--human_advice_validate",
        type=str,
        default=None,
        help="Human guidance for the validator agent.",
    )
    parser.add_argument(
        "--human_advice_tune", type=str, default=None, help="Human guidance for the tuning agent."
    )
    parser.add_argument(
        "--plan_overrides",
        type=str,
        default=None,
        help="JSON string of hard overrides for the LLM's ExperimentPlan. "
        'E.g. \'{"trial_portion": 0.2, "train_portion": 1.0}\'. '
        "Keys must be valid ExperimentPlan fields.",
    )
    parser.add_argument(
        "--workflow_parameter_rules",
        type=str,
        default=None,
        help=(
            "JSON object using the same ParameterRules schema as a task manifest. "
            "Omitted leaves the workflow unconstrained; exact rules lock values, "
            "while range, allowed, and registered predicate rules validate the "
            "agent's proposal."
        ),
    )
    # --- Workflow-level CLI flags (Phase 6.8 Commit 11) ---
    parser.add_argument(
        "--llm_config",
        type=str,
        default=None,
        help="Path to a WorkflowLLMConfig JSON file for per-node model routing. "
        "Overrides --llm_model when provided.",
    )
    parser.add_argument(
        "--healthgate_mode",
        choices=["blocking", "observe_only"],
        default=None,
        help="V20 PR D: whether HealthGate verdicts ENFORCE (blocking) or "
        "only record (observe_only). REQUIRED for a formal launch — there "
        "is no default, because defaulting would let this run claim "
        "enforcement nobody configured. Must agree with the HealthGate "
        "config's actual enforcement or the launch is refused.",
    )
    parser.add_argument(
        "--result_authority",
        choices=["scientific", "diagnostic"],
        default=None,
        help="V20 PR D: whether this run's results may inform science "
        "(scientific) or are diagnostic only. REQUIRED for a formal "
        "launch. observe_only+scientific is refused as a contradiction; "
        "blocking+diagnostic is legal.",
    )
    parser.add_argument(
        "--health_checks_config",
        type=str,
        default=None,
        help=(
            "Optional HealthGate YAML override forwarded unchanged to the tuner. "
            "None preserves the shipped default configuration."
        ),
    )
    # --- Run-scoped task composition (Step 10 P1) ---
    parser.add_argument(
        "--task_composition",
        type=str,
        required=True,
        help=(
            "Path to a required YAML task-composition manifest. "
            "Supplied, it binds this run's task data path, dataset profile, "
            "metric, Health family, interpretation blocks and task "
            "description/forward contract EXPLICITLY, and every unresolvable "
            "reference fails closed before any LLM call. See "
            "docs/design/generic_framework_upgrade/"
            "step_10_orchestration_task_binding/"
            "pr_10_p1_run_scoped_task_composition.md."
        ),
    )
    # --- DataScope + HealthGate subsystem (DS6c) ---
    parser.add_argument(
        "--data_scope",
        type=str,
        default=None,
        help=(
            "Restrict the chain to a file subset: '4-9', '4,5,6,7,8,9', or "
            "mixed '0-3,7' (both forms canonicalize to one sorted deduplicated "
            "list). Omitted = complete dataset. Pinned per workspace by the "
            "run-invariants lock. See docs/design/enable_partial_file_list.md."
        ),
    )
    parser.add_argument(
        "--health_gate_enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "HealthGate subsystem switch (default: enabled). "
            "--no-health_gate_enabled disables gate evaluation entirely; "
            "successful finite-score records then count as valid candidates. "
            "Pinned per workspace by the run-invariants lock."
        ),
    )
    parser.add_argument(
        "--health_gate_files",
        type=str,
        default=None,
        help=(
            "Run-level shared monitored-file list for ALL HealthGate checks "
            "(same spec format as --data_scope). Omitted + full scope = YAML "
            "defaults; omitted + partial scope = startup error."
        ),
    )
    parser.add_argument(
        "--advice",
        type=str,
        default=None,
        help="Path to a JSON advice file. Recognised keys: interpret, propose, "
        "implement, validate, tune, mindset — a string or a list of lines each. "
        "The key set is CLOSED and an artifact that could inject nothing is "
        "REFUSED at load (unrecognised key, empty declaration, or no recognised "
        "key), because the digest is pinned as the run's treatment identity "
        "whether or not the content ever reaches a prompt. "
        "Overrides --human_advice_file when provided.",
    )
    parser.add_argument(
        "--advice_sha256",
        type=str,
        default=None,
        help=(
            "DECLARED sha256 of the advice artifact's bytes, as observed by "
            "the launcher. Certified against this process's own read and then "
            "discarded — the workspace lock always pins the OBSERVED digest. "
            "A mismatch refuses the launch, which is how an edit between two "
            "band launches of one campaign is caught. Omit for hand-run "
            "chains: the observed digest is still pinned."
        ),
    )
    parser.add_argument(
        "--validation_max_portion",
        # F-RC-1: the SAME `_portion_floor` authority `--trial_portion` and
        # `--eval_portion` already use. This ceiling is clamped onto those
        # very fields, so a value below their 0.01 floor is refused at argv
        # time — before any LLM or GPU spend — instead of failing inside the
        # tuner's retry budget.
        type=_portion_floor,
        default=None,
        help="VALIDATION POSTURE ONLY (V20 FU-D-12). Hard ceiling on the "
        "RESOLVED trial-mode data portions (trial/train/eval), applied as "
        "min(planned, ceiling) beside the existing max_epochs clamp. Those "
        "three values come from the LLM PLAN rather than operator input, so "
        "without this a Gate that requested 0.02 can measure 0.1: time "
        "budgets bound wall time, not workload. A maximum, never a "
        "replacement — it can only reduce a planned portion. Omit for "
        "ordinary campaigns.",
    )
    parser.add_argument(
        "--validation_max_train_samples",
        type=int,
        default=None,
        help="VALIDATION POSTURE ONLY. Absolute ceiling on the ML segments "
        "one training epoch may contain — the Gate workload envelope. "
        "--validation_max_portion bounds the FRACTION; this bounds the "
        "AMOUNT, which the fraction cannot: samples per PSD segment are "
        "psd_segment_length // seg_size and seg_size is the planner's, so "
        "1%% of the scope resolved to 12,500 optimizer steps during "
        "Step 03. Applied where the epoch is BUILT, so fewer segments are "
        "read and fewer steps exist before any run — and it CLAMPS rather "
        "than rejects, unlike --max_steps_per_attempt, whose refusal "
        "skipped every round of a Gate attempt. Omit for ordinary "
        "campaigns.",
    )
    parser.add_argument(
        "--validation_max_samples",
        type=int,
        default=None,
        help="VALIDATION POSTURE ONLY (07c). Absolute ceiling on the ML "
        "segments one VALIDATION pass may contain — the validation-row "
        "counterpart of --validation_max_train_samples, which bounds "
        "TRAINING rows. The two names differ by one word and bound "
        "DIFFERENT sets: 07a's Gate 2 capped the training epoch at 2,000 "
        "rows while validation ran the full 15,000-row eval SampleSet, "
        "7.5x the training work, every epoch. Applied to the REQUESTED "
        "scope before it materializes, so the exact-materialization "
        "invariant is never relaxed. Clamps to whole PSD segments and "
        "never overshoots; a ceiling below one PSD segment's rows is "
        "refused rather than resolving to an empty scope. INTERIM cost "
        "bounding, not the root fix — the priced deadline is. Omit for "
        "ordinary campaigns.",
    )
    parser.add_argument(
        "--validation_max_phase_seconds",
        type=float,
        default=None,
        help="VALIDATION POSTURE ONLY. Emergency wall-clock fuse for one "
        "execution phase, enforced by the existing runtime watchdog and "
        "never by admission (so it cannot skip the attempt). Requires "
        "--runtime_watchdog. NOT a sizing mechanism: normal Gate cost comes "
        "from --validation_max_train_samples and the data scope, which are "
        "enforced BEFORE launch. Set it well above the expected duration — "
        "a run killed at the deadline yields no evidence at all. The "
        "watchdog floor still applies: the effective ceiling is "
        "max(this, --runtime_watchdog_floor_seconds).",
    )
    parser.add_argument(
        "--validation_fixed_candidate_plan",
        type=str,
        default=None,
        help="VALIDATION POSTURE ONLY (V20 FU-D-11). Path to a JSON file "
        "holding a serialised ProposalOutput. When supplied the PROPOSER is "
        "bypassed and this candidate plan is used instead; implement, "
        "validate, trial, HealthGate, formal launch, authority, resume and "
        "aggregation all still run for real. Intended for acceptance runs "
        "that must not depend on which architecture a planner invents. The "
        "file may contain ONLY a candidate plan: unknown keys are REFUSED, "
        "so a stray score, record or verdict fails the launch instead of "
        "being silently dropped. Never use this in a normal campaign.",
    )
    parser.add_argument(
        "--max_impl_attempts",
        type=int,
        default=3,
        help="Max implementation retries per proposal when the validator rejects.",
    )
    parser.add_argument(
        "--target_files",
        type=int,
        nargs="+",
        default=None,
        help="DEPRECATED no-op (DS7) — warns and is ignored. Use --data_scope.",
    )
    parser.add_argument(
        "--sampling_seed",
        type=int,
        default=None,
        help="Seed for build_sample_set(). None auto-generates per gate.",
    )
    parser.add_argument(
        "--trial_time_budget_minutes",
        type=float,
        default=None,
        help="Trial wall-time budget in minutes. None disables Trial time admission.",
    )
    parser.add_argument(
        "--formal_time_budget_minutes",
        type=float,
        default=None,
        help="Formal wall-time budget in minutes. None disables Formal time admission.",
    )
    parser.add_argument(
        "--trial_time_admission_source",
        choices=("forecast", "measured"),
        default="measured",
        help=(
            "Single Trial wall-time admission authority. 'forecast' uses the "
            "advance workload forecast; 'measured' uses executing-device evidence."
        ),
    )
    parser.add_argument(
        "--formal_time_admission_source",
        choices=("forecast", "measured"),
        default="measured",
        help=(
            "Single Formal wall-time admission authority. 'forecast' uses the "
            "advance workload forecast; 'measured' uses executing-device evidence."
        ),
    )
    # --- Runtime-control operator surface (RT6, runtime design §4/§5) ---
    # The chain is the OPERATIONAL surface: §5 provisional defaults live
    # here (schema defaults stay None). Pass 0 to disable a guardrail.
    parser.add_argument(
        "--max_steps_per_attempt",
        type=int,
        default=150_000,
        help="§5 guardrail: skip plans above this resolved optimizer-step "
        "count. 0 disables. Default 150000 (provisional §5 value).",
    )
    parser.add_argument(
        "--min_formal_batch_size",
        type=int,
        default=0,
        help="§5 guardrail: skip FORMAL rounds planned below this batch "
        "size (V18 pathology; trial exempt). 0 disables. Default 0; "
        "task and campaign launchers may opt in explicitly.",
    )
    parser.add_argument(
        "--allow_extreme_steps",
        action="store_true",
        help="§5 operator override: bypass both step/batch guardrails.",
    )
    parser.add_argument(
        "--runtime_watchdog",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="§4 runtime watchdog: deadline-kill training/inference "
        "subprocess groups. Tri-state (arXiv #261 / Q-07c-6): "
        "--runtime_watchdog forces on, --no-runtime_watchdog forces off, "
        "and when NEITHER is passed the device/execution-regime runtime "
        "profile decides (configs/runtime/runtime_profiles.yaml + the measured "
        "overlay in $SIDERIUS_CALIBRATION_DIR). An uncalibrated pair "
        "resolves to the legacy default: off.",
    )
    parser.add_argument(
        "--runtime_safety_factor",
        type=float,
        default=1.0,
        help="§2.10 safety multiplier for admission + watchdog deadline. "
        "Default 1.0 (schema-mirroring); V18 production posture 1.5.",
    )
    parser.add_argument(
        "--runtime_trial_safety_factor",
        type=float,
        default=None,
        help="Phase-specific factor for TRIAL attempts; wins over "
        "--runtime_safety_factor when set. Effective V18r posture 3.0.",
    )
    parser.add_argument(
        "--runtime_formal_safety_factor",
        type=float,
        default=None,
        help="Phase-specific factor for FORMAL attempts; wins over "
        "--runtime_safety_factor when set.",
    )
    parser.add_argument(
        "--runtime_watchdog_safety_factor",
        type=float,
        default=None,
        help="V19 watchdog-only deadline multiplier (admission/watchdog "
        "split). Omitted -> watchdog uses the phase-effective admission "
        "factor exactly as V18. V19 5090 posture: 3.5.",
    )
    parser.add_argument(
        "--runtime_watchdog_floor_seconds",
        type=float,
        default=None,
        help="§4 watchdog deadline floor. Unset -> the device/execution "
        "profile's floor when the profile governs, else the legacy 60.0 "
        "(schema-mirroring); V18 production posture 120.0.",
    )
    parser.add_argument(
        "--runtime_verification_max_wall_seconds",
        type=float,
        default=None,
        help="Maximum wall time for adaptive in-subprocess runtime verification. "
        "Omit to preserve the verifier default. The verification steps are "
        "the first production steps, not a separate probe workload.",
    )
    parser.add_argument(
        "--execution_regime",
        type=str,
        choices=sorted(get_args(ExecutionRegime)),
        default="single",
        help="arXiv #261 — the launch's DECLARED execution topology, one "
        "half of the (device, regime) runtime-profile key. 'single' = one "
        "resident chain per card (the legacy shape); co-resident fleets "
        "declare their regime so watchdog numbers calibrated for one "
        "topology are never borrowed by another. Consulted only when no "
        "explicit --runtime_watchdog/--no-runtime_watchdog flag is passed.",
    )
    parser.add_argument(
        "--required_runtime_profile_path",
        type=str,
        default=None,
        help="F-H100-WD-1-PRETAG — the ABSOLUTE path of the profile artifact "
        "this launch requires. Part of the declaration and never derived: "
        "while the artifact was located by the ordinary discovery rule "
        "($SIDERIUS_CALIBRATION_DIR/runtime_profiles_<gpu_slug>.json), a "
        "binding certified WHAT was found but not that the right file was "
        "consulted — an overlay was used because the directory happened to "
        "hold it. When declared, resolution reads THIS file and never "
        "consults discovery. Must be paired with --required_runtime_profile "
        "and --required_runtime_profile_sha256; a relative path is refused, "
        "because the consuming subprocess has a different working directory.",
    )
    parser.add_argument(
        "--required_runtime_profile",
        type=str,
        default=None,
        help="F-H100-WD-1-PRETAG — DECLARE the runtime profile this launch "
        "REQUIRES, as '<gpu_slug>/<regime>' (e.g. "
        "'nvidia_h100_80gb_hbm3/single'), exactly as recorded in a prior "
        "qualification run's provenance. Must be paired with "
        "--required_runtime_profile_sha256. When declared, profile "
        "resolution is FAIL-CLOSED: the discovered device/regime must match, "
        "the measured overlay must hash to the declared digest, and it must "
        "carry that row — any miss REFUSES the launch instead of falling "
        "back to the shipped or uncalibrated profile. Omit both flags to "
        "keep the legacy ladder (measured > shipped > uncalibrated).",
    )
    parser.add_argument(
        "--required_runtime_profile_sha256",
        type=str,
        default=None,
        help="F-H100-WD-1-PRETAG — the 64-char lowercase-hex sha256 of the "
        "measured-overlay FILE certified for this run (e.g. `sha256sum "
        "$SIDERIUS_CALIBRATION_DIR/runtime_profiles_<slug>.json`). Must be "
        "paired with --required_runtime_profile. The digest is computed over "
        "the exact bytes parsed, so the profile consumed is provably the one "
        "that was qualified.",
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        required=True,
        help="Physical dataset directory for this run. "
        "The value is resolved and validated at launch, before any LLM "
        "or training work, and the resolved path is what reaches the "
        "real-dataset warmup AND the pre-phase GPU measurement.",
    )
    parser.add_argument(
        "--gpu_admission_measurement_source",
        type=str,
        default=None,
        help=(
            "V20 B-G3. Reference naming where an authoritative GPU measurement "
            "would be resolved from. NOT a figure -- there is deliberately no "
            "flag taking a raw MiB number, because one an operator could type "
            "would impersonate a measurement in formal mode. Unresolved before "
            "PR C, so formal rounds refuse with policy_unavailable."
        ),
    )
    parser.add_argument(
        "--gpu_admission_enforcement",
        choices=["observe_only", "enforce", "enforce_resource_limits"],
        default="observe_only",
        help=(
            "V20 B-G3/D-B4/M5. What the run DOES about an adverse GPU "
            "admission decision. Orthogonal to trial/formal. "
            "'observe_only' (default, compatibility) records the decision "
            "and proceeds. 'enforce_resource_limits' is the V20 PRODUCTION "
            "posture: it stops the phase on a resource verdict "
            "(insufficient_headroom) and records an evidence gap. "
            "'enforce' stops on any adverse decision — usable for the B-G "
            "validation harness, but NOT for a campaign, because the "
            "prephase measurement covers training only and every formal "
            "inference phase would refuse policy_unavailable."
        ),
    )
    parser.add_argument(
        "--gpu_pair_ceiling_gib",
        type=float,
        default=None,
        help=(
            "V20 B-G3. Aggregate GPU ceiling (GiB) passed explicitly to the "
            "admission gate. Omitted = defer to SIDERIUS_PAIR_VRAM_CEILING_GIB "
            "and the compatibility default, i.e. pre-B-G3 behaviour."
        ),
    )
    parser.add_argument(
        "--trial_vram_budget_gb",
        type=float,
        default=None,
        help="Per-mode VRAM ceiling (GB) for trial rounds. None uses free×0.8.",
    )
    parser.add_argument(
        "--formal_vram_budget_gb",
        type=float,
        default=None,
        help="Per-mode VRAM ceiling (GB) for formal rounds. None uses free×0.8.",
    )
    parser.add_argument(
        "--vram_probe_step_timeout_seconds",
        type=float,
        default=180.0,
        help=(
            "Maximum wall time for one training-mode or inference VRAM "
            "footprint forward (default: 180). This is not an epoch, "
            "optimizer step, or candidate-runtime budget."
        ),
    )
    parser.add_argument(
        "--vram_preflight_total_timeout_seconds",
        type=float,
        default=900.0,
        help=(
            "Maximum wall time for the complete isolated VRAM preflight "
            "worker (default: 900), independent of Trial/Formal runtime budgets."
        ),
    )
    parser.add_argument(
        "--vram_preflight_host_memory_limit_gb",
        type=float,
        default=None,
        help=(
            "Maximum resident host memory in GiB for the complete isolated "
            "VRAM-preflight process tree. Omission preserves the deployment "
            "default, normally 24 GiB. Independent of the GPU VRAM ceiling."
        ),
    )
    parser.add_argument(
        "--attempts_per_round",
        type=int,
        default=3,
        help="Inner attempt budget for trial rounds.",
    )
    parser.add_argument(
        "--attempts_per_formal_round",
        type=int,
        default=5,
        help="Inner attempt budget for the formal-promotion round.",
    )
    parser.add_argument(
        "--max_fail_rounds",
        type=int,
        default=3,
        help="Consecutive-failure brake for the tuner outer loop.",
    )
    parser.add_argument(
        "--exploration_mode",
        type=str,
        default="auto",
        choices=["auto", "explore", "exploit"],
        help="Reasoning pipeline mode.",
    )
    parser.add_argument(
        "--minimum_boldness",
        type=float,
        default=0.05,
        help="Minimum boldness threshold for FalsifiablePrediction.",
    )
    parser.add_argument(
        "--debug_dump_prompts",
        action="store_true",
        help="Dump rendered proposing-stage prompts to debug/ for audit.",
    )
    # --- Pseudo-mode flags (Stage 3 / Commit 4.5) ---
    # When set, the runner swaps the production ``LLMBridge`` /
    # ``TidmadSandbox`` for stateless ``StubLLMBridge`` / ``StubSandbox``
    # instances at the top of ``main()``. The chain still exercises the
    # full propose→implement→validate→tune wiring, but every LLM call
    # returns canned per-label output at $0 token cost and every training
    # call returns canned trial/formal scores. Defaults preserve the
    # production code path bit-for-bit. See
    # ``docs/audit_and_optimize_token_usage_and_growth.md`` Commit 4.5.
    parser.add_argument(
        "--is_pseudo_llm",
        action="store_true",
        help="Swap LLMBridge → StubLLMBridge for all 5 agents "
        "(interpret/propose/implement/validate/tune). Returns canned, "
        "Pydantic-valid per-label outputs at $0 token cost. Use for "
        "chain-wiring smoke tests; not for production runs.",
    )
    parser.add_argument(
        "--is_pseudo_training",
        action="store_true",
        help="Swap TidmadSandbox → StubSandbox in the tuner agent. Skips "
        "real training and returns canned trial / formal scores. Use "
        "for chain-wiring smoke tests; not for production runs.",
    )
    parser.add_argument(
        "--max_failed_iterations",
        type=_positive_int,
        default=3,
        help="Consecutive-failure brake (Stage 4 / Commit 4.6). Halt the "
        "chain when the most recent N iters all carry "
        "manifest.status='failed' (default 3). Brake is fail-open: "
        "missing or malformed manifests count as 'not failed', and "
        "'no_records' is never counted as a failure. On halt, writes "
        "{workspace}/.chain_halted and exits 3.",
    )
    # External agents (Commit 6 — 2026-06-12, Design Decisions 1 + 2):
    # two CLI flags for the ml_literature_review external agent — (1)
    # enable/disable toggle (BooleanOptionalAction), (2) YAML config
    # path. No other lit-review parameters are exposed at the CLI —
    # root_papers / dynamic_search / synthesis / confidence_rubric live
    # in the YAML; LLM routing lives in WorkflowLLMConfig.lit_review.
    # See docs/commit_plan_ml_literature_review.md Commit 6.
    parser.add_argument(
        "--ml_lit_review_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable / disable the ml_literature_review external agent. "
            "When set, overrides the YAML's top-level 'enabled' flag. "
            "When neither --ml_lit_review_enabled nor "
            "--no-ml_lit_review_enabled is passed (default None), the "
            "YAML's 'enabled' value drives the decision. The 'ml_' "
            "prefix establishes a naming convention for future external "
            "agents (e.g. --ml_physics_agent_enabled)."
        ),
    )
    parser.add_argument(
        "--ml_lit_review_config",
        type=str,
        default=None,
        help=(
            "Explicit path to the task or experiment's lit-review YAML config. "
            "Required when literature review is enabled; relative paths resolve "
            "against SIDERIUS_ROOT."
        ),
    )
    # arXiv U1 (#254) — the OPAQUE experiment-arm label. Pinned into the
    # workspace lock and stamped on every record / output / manifest; never
    # read to decide behaviour (ruling R2). Absent = unlabelled legacy run.
    parser.add_argument(
        "--experiment_arm",
        type=_experiment_arm_label,
        default=None,
        help=(
            "Opaque experiment-arm label for this chain (e.g. "
            "'with-prior-art' / 'without-prior-art'). Pinned into "
            "run_invariants_lock.json and stamped on every record, tuner "
            "output and manifest, so two workspaces differing in arm refuse "
            "to be resumed into one another. Provenance only — it drives NO "
            "behaviour; each arm's behaviour is set by its own explicit "
            "flags. Default: absent (unlabelled). An empty string is refused."
        ),
    )
    # arXiv U3 (#260) — the WITHOUT arm's EXPLICIT behaviour flag (ruling R6).
    parser.add_argument(
        "--baseline_isolation",
        action="store_true",
        default=False,
        help=(
            "Exclude the bundled baselines from this run's LLM-facing surface: "
            "the interpreter and tuner refuse a bundled ml_models/*/description.md "
            "(plugin descriptions still resolve), the proposer's prompts name no "
            "built-in architecture and no baseline score, and a proposal whose "
            "model_type is a bundled built-in is refused before implementation. "
            "Pinned into run_invariants_lock.json (a toggle on the same workspace "
            "is refused) and stamped on the manifest. Default: off."
        ),
    )

    # arXiv #259 (fleet ruling 2026-08-25) — declared output-type constraint.
    parser.add_argument(
        "--allowed_output_types",
        type=str,
        default=None,
        help=(
            "Comma-separated set of output types proposed models may declare "
            "(subset of: classifier,regressor). The proposer's prompt states "
            "the constraint and the deterministic schema gate refuses an "
            "out-of-set proposal before implementation. Omit for the "
            "unconstrained legacy behavior. The X9 campaign pins 'regressor' "
            "via the launcher."
        ),
    )
    parser.add_argument(
        "--print_resolved_launch_config",
        action="store_true",
        default=False,
        help=(
            "Print the resolved launch configuration (lit-review topology and "
            "config sha256, experiment arm, baseline isolation, task "
            "composition, workspace, advice file, declared posture) as ONE JSON "
            "object and exit 0 with NO side effects: no workspace directory, "
            "no LLM call, no lock. Used by the arm launcher's --dry-run."
        ),
    )
    # --- S2 / U5 (#258): explicit same-iteration manifest replacement ---
    parser.add_argument(
        "--replace_iteration_manifest",
        action="store_true",
        default=False,
        help=(
            "Iteration manifests are write-once: launching into an iter_NNN/ that "
            "already holds a manifest.json is REFUSED. Pass this flag (with "
            "--replacement_reason) to rerun the iteration deliberately: the previous "
            "manifest is kept as manifest.replaced.<stamp>.json and its digests are "
            "recorded under the new manifest's 'manifest_replacement' provenance. "
            "Integrity hashes are never regenerated silently."
        ),
    )
    parser.add_argument(
        "--replacement_reason",
        type=str,
        default=None,
        help=(
            "Why the iteration manifest is being replaced (required with "
            "--replace_iteration_manifest; recorded verbatim in the provenance)."
        ),
    )
    parser.add_argument(
        "--auto_resume",
        action="store_true",
        default=False,
        help=(
            "Declares that this launch was selected by the chain's auto-resume "
            "(run_chain.sh forwards it only when scripts/launch/inspect_run_state.py "
            "computed the start iteration). #258 refinement: with this flag, an "
            "existing same-iteration manifest whose terminal status is 'failed' "
            "or 'no_records' is replaced through the EXPLICIT replacement path — "
            "previous manifest kept on disk, provenance recorded with a "
            "recognizable 'auto_resume recovery' reason. A 'completed' manifest "
            "is never replaced by auto-resume; that still requires "
            "--replace_iteration_manifest --replacement_reason."
        ),
    )
    return parser


def _experiment_arm_label(value: str) -> str:
    """argparse type: an arm label is present and non-empty, or absent."""
    if not value.strip():
        raise argparse.ArgumentTypeError(
            "--experiment_arm must be a non-empty label; omit the flag for an "
            "unlabelled run (an empty string is never a label)."
        )
    return value


def resolve_lit_review_enabled(cli_flag: bool | None, config_path: str | None) -> bool:
    """Resolve the lit-review enable flag (Design Decisions 1 + 2, 2026-06-11).

    Priority: CLI flag (when explicitly set) > the YAML's top-level
    ``enabled`` key > ``False``. The workflow opens + parses the YAML
    internally (only when enabled); this peeks at ``enabled`` only for the
    CLI-fallback case. A missing or malformed YAML resolves to ``False``
    (fail-safe: do not run lit-review). Pure — no side effects — so it can
    run before the first manifest is written.
    """
    if cli_flag is not None:
        return cli_flag
    if config_path is None:
        return False
    from workflows.model_exploration import resolve_lit_review_config_path

    yaml_path = resolve_lit_review_config_path(config_path)
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return bool(data.get("enabled", False))
    except (FileNotFoundError, yaml.YAMLError):
        return False


def resolve_launch_identity(args: argparse.Namespace) -> LaunchIdentity:
    """Resolve the launch's identity values from the parsed CLI (arXiv U1).

    Raises:
        ValueError: lit-review is enabled but its config cannot be read (the
            lock must pin the config's sha256, so the launch is refused), or
            the declared advice artifact cannot be certified
            (:class:`AdviceArtifactError`).
    """
    from workflows.model_exploration import lit_review_config_sha256

    enabled = resolve_lit_review_enabled(args.ml_lit_review_enabled, args.ml_lit_review_config)
    # The advice pin comes from the SAME single read the advice CONTENT does
    # (`resolve_advice_artifact` is the one authority and caches on `args`),
    # so the identity locked and the advice injected into the proposer are
    # provably the same bytes.
    advice = resolve_advice_artifact(args)
    return LaunchIdentity(
        experiment_arm=args.experiment_arm,
        lit_review_enabled=enabled,
        lit_review_config_path=args.ml_lit_review_config,
        lit_review_config_sha256=lit_review_config_sha256(
            args.ml_lit_review_config, enabled=enabled
        ),
        baseline_isolation=bool(args.baseline_isolation),
        advice_path=None if advice is None else advice.path,
        advice_sha256=None if advice is None else advice.sha256,
    )


def parse_allowed_output_types(raw: str | None) -> "tuple[OutputTypeName, ...] | None":
    """``--allowed_output_types`` "a,b" -> ("a","b"); None/"" -> None.

    arXiv #259. Refuses unknown names HERE so a typo fails at launch, not as
    a permanently-refusing proposer loop. The legal set mirrors
    ``ProposalOutput.output_type``'s Literal.
    """
    if raw is None or raw.strip() == "":
        return None
    from typing import cast, get_args

    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    legal = set(get_args(OutputTypeName))
    unknown = [p for p in parts if p not in legal]
    if unknown:
        raise SystemExit(
            f"--allowed_output_types: unknown output type(s) {unknown!r}; "
            f"legal values: {sorted(legal)}"
        )
    if not parts:
        return None
    # The refusal above proves every element is a member of the Literal
    # vocabulary; the cast records that guarantee for the type checker.
    return cast("tuple[OutputTypeName, ...]", parts)


def build_required_profile_binding(
    args: argparse.Namespace,
) -> RequiredProfileBinding | None:
    """F-H100-WD-1-PRETAG — turn the declaration flags into a typed binding.

    The declaration is the TRIPLE ``(which artifact, which profile, which
    exact bytes)``; no part means anything alone. A partial declaration is
    therefore REFUSED rather than resolved as undeclared: silently ignoring
    ``--required_runtime_profile`` because its digest was forgotten is
    exactly the fail-open this mechanism exists to remove — the operator
    would believe a requirement is in force while the legacy
    measured > shipped > uncalibrated ladder quietly decides.

    The PATH is part of the declaration and not derived, which is what
    closes ``finding_1_invisible_default``: while the artifact was located
    by the ordinary discovery rule, a binding certified what was found but
    never that the right file was consulted.

    Returns:
        The validated binding, or ``None`` when NO flag was passed — in
        which case resolution keeps the legacy ladder byte-identically.

    Raises:
        SystemExit: some but not all three flags were passed, or the
            declared values are not a valid ``RequiredProfileBinding`` (a
            relative artifact path, a bad key shape, or a digest that is not
            64 lowercase hex characters).
    """
    from pydantic import ValidationError

    declared = {
        "--required_runtime_profile_path": args.required_runtime_profile_path,
        "--required_runtime_profile": args.required_runtime_profile,
        "--required_runtime_profile_sha256": args.required_runtime_profile_sha256,
    }
    supplied = sorted(flag for flag, value in declared.items() if value is not None)
    if not supplied:
        return None
    if len(supplied) != len(declared):
        missing = sorted(flag for flag, value in declared.items() if value is None)
        raise SystemExit(
            f"an incomplete required runtime-profile binding was declared: "
            f"{', '.join(supplied)} passed without {', '.join(missing)}. The "
            f"binding is the TRIPLE (artifact path, profile key, certified "
            f"sha256) — a partial declaration is refused, never treated as "
            f"undeclared, because that would leave the requirement silently "
            f"unenforced."
        )
    try:
        return RequiredProfileBinding(
            artifact_path=args.required_runtime_profile_path,
            profile_key=args.required_runtime_profile,
            expected_sha256=args.required_runtime_profile_sha256,
        )
    except ValidationError as exc:
        raise SystemExit(
            f"invalid required runtime-profile declaration "
            f"(--required_runtime_profile_path="
            f"{args.required_runtime_profile_path!r}, "
            f"--required_runtime_profile={args.required_runtime_profile!r}, "
            f"--required_runtime_profile_sha256="
            f"{args.required_runtime_profile_sha256!r}): {exc}"
        ) from exc


def resolve_watchdog_policy(args: argparse.Namespace) -> ResolvedWatchdogSettings:
    """arXiv #261 / Q-07c-6 — resolve the launch's watchdog policy ONCE.

    Merges the operator's tri-state flags with the ``(device, regime)``
    runtime profile (``core.runtime_control.watchdog_profile`` is the sole
    authority; flags always win) and writes the FINAL values back onto
    ``args``, so the single ``WorkflowLaunchConfig`` construction site and
    the ``--print_resolved_launch_config`` view both read resolved truth.

    Idempotent by construction: the resolved settings are cached on
    ``args.runtime_watchdog_policy`` and returned verbatim on a second
    call, so provenance can never degrade to "cli" after the write-back
    turns the tri-state flag into a concrete bool.
    """
    cached = getattr(args, "runtime_watchdog_policy", None)
    if cached is not None:
        return cached
    required_binding = build_required_profile_binding(args)
    try:
        resolved = resolve_watchdog_launch_settings(
            cli_enabled=args.runtime_watchdog,
            cli_safety_factor=args.runtime_watchdog_safety_factor,
            cli_floor_seconds=args.runtime_watchdog_floor_seconds,
            execution_regime=args.execution_regime,
            required_binding=required_binding,
        )
    except RequiredProfileBindingError as exc:
        # The declared requirement could not be certified. Refuse the launch
        # loudly, naming the flag that declared it — a REQUIRED binding never
        # falls back to the shipped or uncalibrated profile.
        raise SystemExit(f"--required_runtime_profile: {exc}") from exc
    args.runtime_watchdog = resolved.enabled
    args.runtime_watchdog_safety_factor = resolved.safety_factor
    args.runtime_watchdog_floor_seconds = resolved.floor_seconds
    args.runtime_watchdog_policy = resolved
    return resolved


def compute_expected_invariants(
    args: argparse.Namespace,
    *,
    run_composition: RunTaskComposition | None = None,
    launch_identity: LaunchIdentity | None = None,
) -> RunInvariants:
    """DS6c — compute this run's invariants via the ONE shared path.

    Materializes + hashes the effective HealthGate config into the chain
    workspace root (idempotent — ``run_workflow``'s pre-flight recomputes
    the identical body sha) and returns the ``RunInvariants`` used for
    both ``restore_prior_state`` validation and, transitively, the
    workspace lock. Called BEFORE any resume mutation or LLM work.

    Step 10 / P5+P6 **W7**: that idempotence claim is only true when BOTH
    materializations resolve the SAME Health binding. P1 gave ``run_workflow``
    a ``task_health_binding`` but not this earlier pre-flight, so a COMPOSED
    run materialized ``task_health_binding: legacy_default`` here and then
    ``explicit`` in ``run_workflow`` — two different documents, two different
    body shas, and the workspace-immutability check (correctly) refused the
    run. Found by the FIRST real composed chain run; no test caught it because
    none drove the real chain runner under a composition.

    It takes the **composition object**, not individual derived values, and
    derives every composition-dependent invariant here. That is deliberate: a
    first cut of W7 threaded ``task_health_binding`` alone and forgot its
    sibling ``task_composition_fingerprint``, so iteration 2's pre-flight
    computed ``None`` against a lock that already held the fingerprint and the
    chain refused itself. Passing the composition makes the two call sites
    structurally incapable of diverging, and
    ``test_step10_p56_c5_wiring_closures.py`` censuses that they agree.

    ``None`` reproduces the pre-W7 behaviour exactly, which is what every
    un-composed run gets.

    arXiv U1: ``launch_identity`` follows the same rule — ``main`` resolves
    it once and passes the OBJECT; ``None`` resolves it from ``args`` through
    the same function, so a caller that predates the parameter still locks
    the values the workflow will lock.
    """
    identity = launch_identity if launch_identity is not None else resolve_launch_identity(args)
    run_scope = args.data_scope if args.data_scope is not None else DataScope.default()
    # Step 12 / PR-12a **F-12-1** — resolve against the RUN's topology.
    #
    # This pre-flight runs BEFORE `bind_run_task_composition`, so
    # `resolve_dataset_profile()` cannot see a composition yet and would
    # answer TIDMAD for every run. The composition object is already a
    # parameter here (W7 threads its Health binding and fingerprint below),
    # so the composed branch reads it directly — mirroring `run_workflow`'s
    # own composed-aware site (`model_exploration.py`, `_run_dataset`).
    #
    # Un-composed this is byte-identical to the `TIDMAD` constant it
    # replaces: `resolve_dataset_profile()` returns `TIDMAD_PROFILE` and
    # `TIDMAD_PROFILE.dataset` IS that singleton, the same object. Reading
    # it through the resolver rather than importing the task singleton is
    # also what keeps this launcher clean for the F-12-6 census.
    run_partitions = (
        resolve_dataset_profile().partition_count
        if run_composition is None
        else run_composition.dataset_profile.partition_count
    )
    resolved_scope = run_scope.resolve(run_partitions)
    invariants, _ = build_run_invariants(
        resolved_data_scope=resolved_scope,
        health_gate_enabled=args.health_gate_enabled,
        health_gate_files=args.health_gate_files,
        health_checks_config=args.health_checks_config,
        workspace=args.workspace,
        # V19 PR 2 — the ordering override is chain control policy, so it
        # is locked. Must match what the workflow and tuner lock for this
        # same workspace.
        ordering_override_strategy=args.order_strategy_override,
        ordering_override_file_order=args.file_order_override,
        # V19 PR 3 — same rule for the structured-health-feedback policy.
        structured_health_feedback_enabled=args.enable_structured_health_feedback,
        health_feedback_history_window_iterations=(args.health_feedback_history_window_iterations),
        health_feedback_history_max_entries_per_model=(
            args.health_feedback_history_max_entries_per_model
        ),
        # W7 — EVERY composition-derived invariant `run_workflow` passes, so
        # the pre-flight and the workflow agree on both the materialized
        # document AND the workspace lock.
        health_materialization=RunHealthMaterialization(
            task_health_binding=(
                run_composition.task_health_binding if run_composition is not None else None
            ),
            dataset_partition_count=run_partitions,
        ),
        task_composition_fingerprint=(
            run_composition.semantic_fingerprint if run_composition is not None else None
        ),
        # arXiv U1 — the identity the workflow's pre-flight will lock too.
        launch_identity=LockLaunchIdentity(
            lit_review_enabled=identity.lit_review_enabled,
            lit_review_config_sha256=identity.lit_review_config_sha256,
            experiment_arm=identity.experiment_arm,
            baseline_isolation=identity.baseline_isolation,
            # Gold campaign — the OBSERVED advice identity. `run_workflow`
            # locks this SAME workspace, so it must resolve the same pair or
            # the two would write contradictory locks and abort every
            # advice-bound run (the V19 PR 2 rule, one field family over).
            advice_sha256=identity.advice_sha256,
            advice_path=identity.advice_path,
            # F-SCANF-1 — the formal round's evaluation FRACTION, from the
            # SAME namespace `WorkflowLaunchConfig` receives it from, so this
            # pre-flight and `run_workflow`'s own lock for this workspace
            # cannot contradict each other.
            formal_eval_portion=args.formal_eval_portion,
            workflow_parameter_rules=(
                None
                if args.workflow_parameter_rules is None
                else args.workflow_parameter_rules.model_dump(mode="json", exclude_none=True)
            ),
            trial_time_admission_source=args.trial_time_admission_source,
            formal_time_admission_source=args.formal_time_admission_source,
        ),
    )
    return invariants


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    """Resolve the ``--start_iteration`` / ``--iteration`` alias and load
    deferred config (human advice file, plan overrides JSON) into ``args``.

    After this call, ``args.start_iteration`` is guaranteed to be a positive
    int, ``args.iteration_legacy`` is removed, and ``args.plan_overrides`` is
    a dict (or None). The original ``args`` namespace is mutated in place
    and also returned for convenience.

    Raises:
        SystemExit: when both/neither of ``--start_iteration`` and
            ``--iteration`` are supplied, or when ``--start_iteration < 1``.
            ``argparse.ArgumentParser.error`` is used so the message goes to
            stderr with a non-zero exit, matching argparse's own conventions.
    """
    parser = build_parser()  # only used to call .error() with consistent UX

    legacy = getattr(args, "iteration_legacy", None)
    canonical = args.start_iteration

    if legacy is not None and canonical is not None:
        parser.error(
            "--start_iteration and --iteration are mutually exclusive. "
            "--iteration is the deprecated alias; use --start_iteration only."
        )
    if legacy is None and canonical is None:
        parser.error("one of --start_iteration / --iteration is required.")
    if legacy is not None:
        warnings.warn(
            "--iteration is deprecated; use --start_iteration instead. "
            "The deprecated alias will be removed after the next stable run.",
            DeprecationWarning,
            stacklevel=2,
        )
        args.start_iteration = legacy

    # Drop the alias attr so downstream code can't accidentally read it.
    if hasattr(args, "iteration_legacy"):
        delattr(args, "iteration_legacy")

    if args.start_iteration < 1:
        parser.error(f"--start_iteration must be >= 1, got {args.start_iteration}")

    # --seed_paths / --source_paths alias collapse (Phase 6.8 Commit 11).
    # Same pattern as --start_iteration / --iteration above.
    seed_legacy = getattr(args, "source_paths_legacy", None)
    seed_canonical = args.seed_paths

    if seed_legacy is not None and seed_canonical is not None:
        parser.error(
            "--seed_paths and --source_paths are mutually exclusive. "
            "--source_paths is the deprecated alias; use --seed_paths only."
        )
    if seed_legacy is None and seed_canonical is None:
        # Neither flag supplied → cold start: no prior experimental evidence.
        # An empty seed list is valid; the workflow marks the first iteration
        # as cold_start. A bare --seed_paths with zero values is still an
        # argparse error (nargs="+"), so this branch only fires when the flag
        # is omitted entirely.
        args.seed_paths = []
    if seed_legacy is not None:
        warnings.warn(
            "--source_paths is deprecated; use --seed_paths instead. "
            "The deprecated alias will be removed after the next stable run.",
            DeprecationWarning,
            stacklevel=2,
        )
        args.seed_paths = seed_legacy

    if hasattr(args, "source_paths_legacy"):
        delattr(args, "source_paths_legacy")

    # Load human advice through the ONE artifact authority, which resolves
    # the --advice / --human_advice_file precedence, certifies any declared
    # digest and caches the OBSERVED one for `resolve_launch_identity`.
    # Both advice schemas are tolerated during transition; missing keys are
    # None.
    artifact = resolve_advice_artifact(args)
    if artifact is not None:
        advice = artifact.content
        # Normalise list-of-lines form through the SAME authority the loader
        # used to decide these keys carry content (F-SCHED-5): a second
        # rendering rule here is how a key the loader accepted would be
        # dropped in silence anyway.
        advice = {k: render_advice_value(v) for k, v in advice.items()}
        # 4-key schema: propose, implement, tune, mindset
        # Additive schema: analysis is optional and follows the same authority.
        for key in ADVICE_PER_AGENT_KEYS:
            attr = f"human_advice_{key}"
            if getattr(args, attr) is None:
                setattr(args, attr, advice.get(key) or None)
        # 4-key mindset (not a per-agent key, forwarded as-is)
        if not hasattr(args, "human_advice_mindset") or args.human_advice_mindset is None:
            args.human_advice_mindset = advice.get("mindset") or None
    else:
        args.human_advice_mindset = None

    # Parse plan overrides from JSON string into a dict
    if args.plan_overrides:
        args.plan_overrides = json.loads(args.plan_overrides)
    else:
        args.plan_overrides = None
    try:
        args.workflow_parameter_rules = (
            ParameterRules.model_validate_json(args.workflow_parameter_rules)
            if args.workflow_parameter_rules
            else None
        )
    except ValueError as exc:
        parser.error(f"--workflow_parameter_rules is invalid: {exc}")

    # DS7 — deprecated no-op strategy flags (removal tracked as FU-2).
    if args.trial_strategy != "snapshot" or args.target_files is not None:
        warnings.warn(
            "--trial_strategy / --target_files are deprecated and IGNORED "
            "(DS7): the input fields they fed were dead at both ends and have "
            "been removed. Use --data_scope to restrict data.",
            DeprecationWarning,
            stacklevel=2,
        )

    # DS6c — parse DataScope specs. Both '4-9' and '4,5,6,7,8,9' (and mixed)
    # canonicalize to one sorted deduplicated list inside DataScope.
    try:
        args.data_scope = DataScope.from_cli(args.data_scope) if args.data_scope else None
        args.health_gate_files = (
            DataScope.from_cli(args.health_gate_files).file_indices
            if args.health_gate_files
            else None
        )
        # V19 PR 2 — a file ORDER is a sequence, so it must NOT go through
        # DataScope.from_cli, which sorts and dedupes. Doing so would
        # silently rewrite the operator's permutation into ascending order.
        args.file_order_override = (
            parse_file_order_cli(args.file_order_override) if args.file_order_override else None
        )
        # V19 PR 3 — validate the retention policy at STARTUP (fail before
        # any resume mutation or LLM work; ge=1 enforced by the schema).
        # The resolved policy is only consumed by the interpreter, but a
        # bad value must not produce a partial run. Pydantic's
        # ValidationError is a ValueError, so the shared parser.error
        # path below reports it and exits non-zero.
        HealthFeedbackRetentionPolicy(
            history_window_iterations=args.health_feedback_history_window_iterations,
            max_entries_per_model=args.health_feedback_history_max_entries_per_model,
        )
    except ValueError as e:
        parser.error(str(e))

    return args


def print_resolved_launch_config(args: argparse.Namespace) -> int:
    """arXiv U3 (#259) — print the resolved launch configuration as ONE JSON
    object and return the process exit status, without iteration execution or
    run-artifact writes. Resolving the existing workflow owners can import
    plugins with their own import-time effects and stdout.

    Returns ``0`` after printing; ``1`` (with the reason on stderr) when the
    identity cannot be resolved — an enabled lit-review whose config cannot
    be read has no resolved configuration to print.
    """
    from workflows.model_exploration import resolve_lit_review_config_path

    try:
        identity = resolve_launch_identity(args)
    except ValueError as exc:
        print(f"[run_one_iteration] launch identity could not be resolved: {exc}", file=sys.stderr)
        return 1
    # arXiv #261 — idempotent: in the main() path the policy is already
    # resolved and cached on args; a direct caller gets the same one-shot
    # resolution here so the printed values are final, never the raw
    # tri-state defaults.
    watchdog_policy = resolve_watchdog_policy(args)
    resolved = {
        "workspace": os.path.abspath(args.workspace),
        "run_name": args.run_name,
        "start_iteration": args.start_iteration,
        "experiment_arm": identity.experiment_arm,
        "lit_review_enabled": identity.lit_review_enabled,
        "lit_review_config_path": (
            resolve_lit_review_config_path(identity.lit_review_config_path)
            if identity.lit_review_config_path is not None
            else None
        ),
        "lit_review_config_sha256": identity.lit_review_config_sha256,
        "baseline_isolation": identity.baseline_isolation,
        "task_composition": args.task_composition or None,
        "advice_file": args.advice or args.human_advice_file or None,
        # The DECLARED path is above, as given. These two are what the launch
        # RESOLVED and OBSERVED: an operator comparing four bands reads the
        # digest, not the path, because the path is where the treatment lives
        # and the digest is what the treatment IS.
        "advice_path": identity.advice_path,
        "advice_sha256": identity.advice_sha256,
        "healthgate_mode": args.healthgate_mode,
        "result_authority": args.result_authority,
        # arXiv #261 — the resolved watchdog policy with its provenance, so
        # a user can see WHICH values were selected and WHERE they came
        # from (cli / shipped profile / measured overlay / uncalibrated)
        # without reading framework source.
        "execution_regime": args.execution_regime,
        "runtime_watchdog_enabled": watchdog_policy.enabled,
        "runtime_watchdog_safety_factor": watchdog_policy.safety_factor,
        "runtime_watchdog_floor_seconds": watchdog_policy.floor_seconds,
        "runtime_verification_max_wall_seconds": (args.runtime_verification_max_wall_seconds),
        "runtime_watchdog_provenance": watchdog_policy.provenance,
        # F-H100-WD-1-PRETAG — the DECLARED requirement, recorded whether or
        # not it was made, so "no binding was declared" is an observable
        # fact rather than an absent key. Whether the declaration was
        # CONSUMED is read from runtime_watchdog_provenance above, which
        # reads 'bound:<path>#sha256=<hex>' exactly when certification ran.
        "required_runtime_profile_path": args.required_runtime_profile_path,
        "required_runtime_profile": args.required_runtime_profile,
        "required_runtime_profile_sha256": args.required_runtime_profile_sha256,
    }
    json.dump(resolved, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def main():
    args = normalize_args(build_parser().parse_args())
    # Generated-capability identity participates in the run-invariants lock,
    # so bind it before composition preflight, resume validation, or any
    # other operation that can build those invariants.
    from core.generated_library import bind_generated_library_to_workspace

    bind_generated_library_to_workspace(args.workspace)
    from core.local_code import root_code_scope

    with ExitStack() as package_scope:
        package_scope.enter_context(root_code_scope())
        try:
            return _run_bound_iteration(args, package_scope)
        except Exception as exc:
            from workflows.package_failure import halt_on_package_failure

            halt_on_package_failure(
                exc,
                workspace=args.workspace,
                iteration=args.start_iteration,
                write_marker=_write_halt_marker,
            )
            raise


def _run_bound_iteration(args: argparse.Namespace, package_scope: ExitStack):
    """Run the existing lifecycle after root workspace/package decisions."""

    # Both owners transitively load model registries. A cold launch must bind
    # its workspace first so discovery cannot import legacy checkout plugins.
    from core.resume import ResumeError, restore_prior_state
    from workflows.model_exploration import run_workflow

    # Resolve a valid composition before launch-policy validation so the
    # policy reads this run's task-owned Health declaration rather than
    # binding the legacy default first. Preserve the established malformed-
    # composition path below: its error is still recorded after the iteration
    # directory is prepared, so deterministic failures still contribute to
    # the consecutive-failure brake.
    preflight_composition = None
    preflight_composition_error: Exception | None = None
    if args.task_composition:
        try:
            preflight_composition = compose_run_task_bindings(args.task_composition)
        except Exception as exc:
            from core.local_code.failure import raise_if_code_package_failure

            raise_if_code_package_failure(exc)
            preflight_composition_error = exc

    # Launch policy and invariants materialize Health before run activation.
    # They must see the same capture, without creating a transport sidecar.
    from core.local_code import bind_code_package

    package_scope.enter_context(
        bind_code_package(
            preflight_composition.code_package if preflight_composition is not None else None
        )
    )

    # --- V20 PR D (D-C1b): formal-launch policy refusal ----------------
    # THE FIRST thing done with the parsed arguments, and deliberately
    # before the failure-brake preflight below: a launch whose declared
    # policy cannot be honoured must not create an iter_dir, touch a
    # sentinel, call an LLM, construct a model or reach a GPU.
    #
    # Enforced HERE rather than in the tuner's schema, because this is the
    # new-formal-launch boundary. `validate_runtime_config` runs for every
    # tuner invocation including diagnostic tooling
    # (`scripts/bg_admission_validation.py` builds a tuner input), and the
    # permissive schema is what keeps historical artifacts readable —
    # `core/resume.py` reads manifests directly and never constructs a
    # HyperparamTuningInput, so tightening the launch path cannot make an
    # old artifact unopenable.
    try:
        validate_formal_launch(
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            health_checks_config=args.health_checks_config,
            gates_enabled=args.enable_chain_incumbent_formal_gates,
            skip_formal_min_delta=args.skip_formal_min_delta,
            bypass_formal_time_budget_min_delta=args.bypass_formal_time_budget_min_delta,
            task_health_binding=(
                preflight_composition.task_health_binding
                if preflight_composition is not None
                else HealthBindingState.LEGACY_OMITTED
            ),
        )
    except FormalLaunchPolicyError as exc:
        print(f"[run_one_iteration] FORMAL LAUNCH REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)

    # arXiv #261 / Q-07c-6 — resolve the watchdog policy (flags > device/
    # regime profile > explicit uncalibrated state) BEFORE the dry-run view
    # and before any consumer reads the watchdog args. The banner goes to
    # STDERR: stdout is a parsed surface (the dry-run JSON, chain captures).
    watchdog_policy = resolve_watchdog_policy(args)
    print(
        f"[watchdog_policy] enabled={watchdog_policy.enabled} "
        f"safety_factor={watchdog_policy.safety_factor} "
        f"floor_seconds={watchdog_policy.floor_seconds} "
        f"source={watchdog_policy.provenance}",
        file=sys.stderr,
        flush=True,
    )
    if watchdog_policy.profile_calibrated is False:
        print(
            "[watchdog_policy] no calibrated runtime profile exists for this "
            "device/execution regime — watchdog disabled; the outer time "
            "budgets are the runaway bound. Run qualification (write the "
            "measured overlay in $SIDERIUS_CALIBRATION_DIR), add a reviewed "
            "row to configs/runtime/runtime_profiles.yaml, or pass explicit "
            "--runtime_watchdog flags to change this.",
            file=sys.stderr,
            flush=True,
        )

    # arXiv U3 (#259) — the resolved-configuration view. Placed AFTER the
    # policy refusal (a config that could not launch is not "resolved") and
    # BEFORE iteration-side effects below: no halt marker, iteration directory,
    # run-id sidecar, lock, or LLM. Workspace env binding and plugin imports
    # have already occurred; plugin effects/stdout are not suppressed.
    if args.print_resolved_launch_config:
        sys.exit(print_resolved_launch_config(args))

    # --- Consecutive-failure brake preflight (Stage 4 / Commit 4.6) ---
    # Two cheap on-disk checks before we touch anything else. Runs before
    # iter_dir creation so a halted chain leaves no orphan dirs behind.
    #
    # (a) Halt-marker check — SDSC ``afterany`` queues the next iter even
    #     when its predecessor exit-3'd. The sentinel file is how we bail
    #     out without doing any work; iter 1 never sees it (fresh workspace).
    # (b) Streak scan — walks the most recent N=args.max_failed_iterations
    #     ``iter_NNN/manifest.json`` files. If all carry status="failed",
    #     write the sentinel + exit 3. ``no_records`` and ``completed``
    #     both break the streak.
    if _check_halt_marker(args.workspace):
        print(
            f"[HALT] chain halt marker present in this "
            f"workspace — see {os.path.join(args.workspace, '.chain_halted')}",
            file=sys.stderr,
        )
        sys.exit(3)

    _failed_streak = _check_consecutive_failure_brake(
        args.workspace,
        args.max_failed_iterations,
    )
    if _failed_streak is not None:
        halt_path = _write_halt_marker(
            args.workspace,
            {
                "halted_at": datetime.now(UTC).isoformat(),
                "workspace": os.path.abspath(args.workspace),
                "reason": "consecutive_failure_brake",
                "max_failed_iterations": args.max_failed_iterations,
                "failed_iters": _failed_streak,
                "next_iteration_was": args.start_iteration,
            },
        )
        print(
            f"[HALT] consecutive failure brake fired "
            f"(N={args.max_failed_iterations}); failed iters: "
            f"{_failed_streak}. Marker written: {halt_path}",
            file=sys.stderr,
        )
        sys.exit(3)

    # --- Dataset-directory resolution preflight -------------------------
    # Resolve WHERE the data physically lives ONCE, here, before anything
    # expensive. `--data_dir` is an explicit caller-owned input; the generic
    # framework never selects a task or machine-local fallback.
    #
    # Before this existed nothing on the launch path performed that
    # resolution, so a chain launched without `--data_dir` carried
    # `data_dir=None` all the way into the tuner's pre-phase GPU
    # measurement, which fails closed — AFTER a real LLM had generated and
    # validated a candidate. Resolving here converts that into a refusal
    # that costs nothing.
    #
    # Deliberately AFTER the halt/brake checks above: a halted chain must
    # still be able to exit without needing readable data.
    try:
        args.data_dir = resolve_dataset_dir(args.data_dir, purpose="this chain iteration")
    except DatasetDirectoryUnavailable as exc:
        print(f"[run_one_iteration] LAUNCH REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)

    # --- Pseudo-mode factory resolution (Stage 3 / Commit 4.5) ---
    # ``--is_pseudo_llm`` / ``--is_pseudo_training`` request stub
    # implementations of the LLM bridge and sandbox. We resolve the
    # factories here (early, before any other setup) and forward them
    # to ``run_workflow``, which threads them into every agent. ``None``
    # = production class — see ``workflows.model_exploration.run_workflow``.
    # The stderr warning is loud-on-purpose: it must be impossible to
    # mistake a $0-cost smoke run for a real chain when reading logs.
    bridge_factory = None
    sandbox_factory = None
    if args.is_pseudo_llm:
        from agent.llm_bridge import StubLLMBridge

        bridge_factory = StubLLMBridge
    if args.is_pseudo_training:
        from core.sandbox_executor import StubSandbox

        sandbox_factory = StubSandbox
    if args.is_pseudo_llm or args.is_pseudo_training:
        modes = []
        if args.is_pseudo_llm:
            modes.append("LLM")
        if args.is_pseudo_training:
            modes.append("training")
        print(
            f"[PSEUDO-MODE ACTIVE] {' + '.join(modes)} stub(s) engaged — "
            f"this run is a $0-cost wiring smoke; outputs are canned and "
            f"do not reflect real LLM / training behaviour.",
            file=sys.stderr,
        )

    # Iteration directory: {workspace}/iter_{N:03d}. S2 / U5 (#258): the
    # manifest slot is decided HERE — a second launch into an iteration that
    # already committed a manifest is refused before any LLM, model or GPU
    # work, unless the operator requested the explicit replacement.
    try:
        iteration_plan = prepare_iteration_dir(
            args.workspace,
            args.start_iteration,
            replace_iteration_manifest=args.replace_iteration_manifest,
            replacement_reason=args.replacement_reason,
            auto_resume_recovery=args.auto_resume,
        )
    except (ManifestAlreadyPublishedError, ManifestReplacementError) as exc:
        print(f"[run_one_iteration] LAUNCH REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)
    run_name = iteration_plan.run_name
    iter_dir = iteration_plan.iter_dir
    manifest_replacement = iteration_plan.manifest_replacement

    # Process-global anchor — ``ml_models.model_descriptions.get_model_description``
    # reads this to resolve agent-generated plugin descriptions written under
    # ``{workspace}/plugins/iter_NNN/{model_type}/description.md`` by
    # ``workflows.model_exploration._register_plugin``. Set as early as
    # possible so any descendant node call sees it.
    os.environ["SIDERIUS_CHAIN_WORKSPACE"] = os.path.abspath(args.workspace)

    # Resolve the immutable per-chain run_id (§1.4.1). The sidecar file at
    # ``{workspace}/.token_run_id`` carries the value across the subprocess
    # boundary so every iter binds the same run_id — the bridge refuses
    # any mutation. Threaded into ``run_workflow`` via ``chain_run_name``
    # + ``run_id`` so each agent's bridge writes audit rows tagged with
    # this identity.
    chain_run_name = args.run_name
    run_id = _resolve_chain_run_id(args.workspace, chain_run_name)
    print(f"[TOKEN] chain_run_name = {chain_run_name}")
    print(f"[TOKEN] run_id = {run_id}")

    print("=" * 60)
    # --- Resolve reflect provider/model defaults ---
    # The tuner's reflector sub-call does templated extraction (not
    # reasoning), so it benefits from a faster/cheaper/higher-quota model
    # than the planner. For the gemini provider, default the reflector to
    # gemini-2.5-flash (GA model, unlimited daily quota, strong JSON-mode).
    # The planner stays on the main --llm_model.
    reflect_provider = args.reflect_provider
    reflect_model_id = args.reflect_model_id
    if reflect_model_id is None and reflect_provider is None:
        # Apply gemini-specific default (the chain runner only supports gemini today)
        reflect_model_id = "gemini-2.5-flash"

    print("  SIDERIUS PER-ITERATION RUNNER")
    print(f"  Workspace        : {args.workspace}")
    print(f"  Start iteration  : {args.start_iteration}")
    print(f"  Run name         : {run_name}")
    print(f"  Iter directory   : {iter_dir}")
    # Report what will actually run. `--llm_config` supersedes
    # `--llm_model` (deprecated) below, so printing the latter announced
    # `gemini / gemini-3.1-pro-preview` on a run whose every role was
    # openai/gpt-5.5 from `openai_tiered_pro.json`. A Gate whose binding
    # policy IS the LLM tier cannot have its banner name a different one:
    # the operator reads this line to confirm the policy was honoured.
    if args.llm_config:
        print(f"  LLM config       : {args.llm_config} (supersedes --llm_model)")
    else:
        print(f"  LLM (planner)    : gemini / {args.llm_model}")
        eff_reflect_provider = reflect_provider or "gemini"
        eff_reflect_model_id = reflect_model_id or args.llm_model
        print(f"  LLM (reflector)  : {eff_reflect_provider} / {eff_reflect_model_id}")
    print(f"  Seed source paths: {len(args.seed_paths)} entries")
    for p in args.seed_paths:
        print(f"    - {p}")
    print("=" * 60)

    # FU-D-11 — resolved BEFORE any manifest can be written, so a validation
    # run's candidate provenance exists on EVERY branch including the early
    # crash paths. This is the §19.1 lesson applied: a launch fact that only
    # survives the healthy path is absent exactly when it is most needed.
    # Refusing here also means a malformed or results-bearing plan stops the
    # launch before any real work begins.
    _fixed = load_validation_fixed_candidate_plan(args.validation_fixed_candidate_plan)
    fixed_candidate_plan = _fixed["plan"] if _fixed else None
    fixed_candidate_provenance = _fixed["provenance"] if _fixed else None
    if fixed_candidate_provenance is not None:
        print(
            f"[FIXED PLAN] validation posture: the proposer will be bypassed for "
            f"candidate {fixed_candidate_provenance['resolved_model_name']!r} "
            f"(sha256={fixed_candidate_provenance['plan_sha256'][:12]}…, "
            f"source={fixed_candidate_provenance['plan_path']})"
        )

    # arXiv U1 (#253 / #254) — the launch IDENTITY (arm label + lit-review
    # topology + config pin), resolved ONCE and before any manifest can be
    # written, for the same reason as the fixed-plan provenance above: a
    # launch fact that only survives the healthy path is absent exactly when
    # it is most needed. The ONE object feeds the invariants pre-flight, the
    # workflow launch config and every manifest, so they cannot diverge.
    # An enabled lit-review whose config cannot be read is refused HERE —
    # before any LLM call — and still leaves a `failed` manifest (carrying
    # the fixed-plan provenance resolved above) for the consecutive-failure
    # brake; the identity itself is what failed to resolve, so it is the one
    # manifest that cannot carry it.
    try:
        launch_identity = resolve_launch_identity(args)
    except ValueError as e:
        print(f"FAIL: launch identity could not be resolved: {e}")
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            # Integration (S1×S2): this branch was added by U1 after the S2
            # write-once census froze at seven sites; like every other
            # branch it publishes through the write-once path and must carry
            # the operator's explicit replacement request (resolved at
            # :2208, before any manifest can be written).
            replacement=manifest_replacement,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
        )
        sys.exit(1)
    print(f"  Experiment arm   : {launch_identity.experiment_arm or '(unlabelled)'}")
    print(
        f"  Lit-review       : {'ON' if launch_identity.lit_review_enabled else 'OFF'}"
        + (
            f" (config sha256 {launch_identity.lit_review_config_sha256[:12]}…)"
            if launch_identity.lit_review_config_sha256 is not None
            else ""
        )
    )

    # Step 1 — back-compat resolution of @manifest: indirection in the seed
    # list. The legacy chain shell still passes manifests this way; the new
    # run_chain.sh (Commit 11) won't, but we keep the resolver layered in
    # front of restore_prior_state so existing callers don't break.
    # TODO (Phase 6.8 Commit 11): Remove back-compat layer once unified
    #     run_chain.sh ships and no caller still emits @manifest: prefixes.
    try:
        resolved_seeds = resolve_source_paths(args.seed_paths)
    except (FileNotFoundError, ValueError) as e:
        print(f"FAIL: Could not resolve seed source paths: {e}")
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
        sys.exit(1)

    # Step 2 — soul restoration. For start_iteration > 1, this re-registers
    # plugin classes from prior iters' on-disk artifacts and prepends the
    # workspace-discovered run_outputs onto the seeds. For start_iteration == 1
    # it is a no-op that returns resolved_seeds verbatim. There is no
    # separate --resume flag — start_iteration > 1 IS resume. See
    # docs/phase68_orchestrator_memory_and_resume.md §3.3.
    # DS6c — compute the run's invariants (materialize + hash the effective
    # HealthGate config) BEFORE restore, so a contradicting workspace lock
    # or incompatible restored history fails with zero resume mutation.
    #
    # Step 10 / P5+P6 W7 — the composition is resolved HERE, before the
    # pre-flight, because the pre-flight materializes the effective Health
    # config and must resolve the SAME binding `run_workflow` will. Composing
    # is pure resolution; ACTIVATION is still `bind_run_task_composition`
    # below, at the same point P1 put it. Re-composition is idempotent, but the
    # object is resolved once and reused rather than composed twice.
    # The crashed manifest is NOT optional here. Before W7 this composition
    # happened inside the workflow `try` whose handler writes
    # `write_manifest(..., crashed=True)`; resolving it earlier moved it out
    # from under that handler. That matters because the consecutive-failure
    # brake is deliberately fail-OPEN — `_check_consecutive_failure_brake`
    # treats a missing manifest as "not failed" and breaks the streak — and a
    # malformed `--task_composition` is DETERMINISTIC. Without this handler
    # every iteration would crash identically, write nothing, never form a
    # failure streak, and the chain would keep launching iterations that
    # cannot possibly succeed.
    try:
        if preflight_composition_error is not None:
            raise preflight_composition_error
        run_composition = preflight_composition
        if run_composition is None:
            raise ValueError("required task composition was not resolved")
    except Exception as e:
        print(f"FAIL: could not resolve --task_composition {args.task_composition!r}: {e}")
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
        sys.exit(1)

    try:
        expected_invariants = compute_expected_invariants(
            args, run_composition=run_composition, launch_identity=launch_identity
        )
    except ValueError as e:
        print(f"FAIL: run-invariants computation refused to start: {e}")
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
        sys.exit(1)

    from ml_models.plugin_binding import bind_run_model_plugins

    try:
        with (
            bind_code_package(
                run_composition.code_package if run_composition is not None else None
            ),
            bind_run_model_plugins(
                run_composition.model_plugins if run_composition is not None else None
            ),
        ):
            state = restore_prior_state(
                workspace=args.workspace,
                current_iter=args.start_iteration,
                seed_paths=resolved_seeds,
                expected_invariants=expected_invariants,
                dataset_partition_count=(
                    run_composition.dataset_profile.partition_count
                    if run_composition is not None
                    else resolve_dataset_profile().partition_count
                ),
            )
    except (ResumeError, RunInvariantsViolation) as e:
        print(f"FAIL: restore_prior_state refused to chain: {e}")
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
        sys.exit(1)

    if state.committed_iters:
        print(
            f"[CHAIN] Restored {len(state.restored_plugins)} prior plugin(s) "
            f"from iters {state.committed_iters}"
        )
        if state.restored_plugins:
            print(f"        plugins: {state.restored_plugins}")

        # Persist the accumulated_key_findings union as an on-disk sidecar so
        # the cross-iter context iter N consumes is auditable without
        # replaying load_latest_knowledge in memory. The union itself is
        # still communicated to the workflow via the runtime kwarg below; this
        # file is a log, not the channel. See
        # docs/Consistent_growing_vocab_list.md §3.3.5.
        snapshot_path = os.path.join(iter_dir, f"accumulated_findings_{run_name}.json")
        snapshot = {
            "iter_index": args.start_iteration,
            "consumed_by": run_name,
            "source_iters": list(state.committed_iters),
            "count": len(state.accumulated_key_findings),
            "produced_at": datetime.now(UTC).isoformat(),
            "findings": list(state.accumulated_key_findings),
        }
        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        print(f"[CHAIN] Wrote {snapshot['count']} accumulated findings → {snapshot_path}")
    resolved_paths = state.resolved_source_paths

    if args.llm_config:
        llm_config = WorkflowLLMConfig.from_json(args.llm_config)
    else:
        if args.llm_model != "gemini-3.1-pro-preview":
            warnings.warn(
                "--llm_model is deprecated; use --llm_config instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        llm_config = WorkflowLLMConfig.uniform(
            "gemini",
            args.llm_model,
            reflect_provider=reflect_provider,
            reflect_model_id=reflect_model_id,
        )

    # The lit-review enable flag (Design Decisions 1 + 2, 2026-06-11) is
    # resolved ONCE, above, inside `launch_identity` — arXiv U1 moved the
    # peek into `resolve_lit_review_enabled` so the invariants pre-flight,
    # this launch config and every manifest read one resolution.

    try:
        # The launcher is the layer that knows the task, so it resolves the
        # measurement capability and threads it into generic orchestration.
        # `measurement_capability.py` states this contract explicitly:
        # "Callers that know the task supply those." The workflow must not
        # name a task resolver itself.
        # Step 10 / P1 — the composition EDGE.
        #
        # Resolved here, before the workflow, for the same reason the
        # measurement capability is: the launcher is the layer that knows the
        # task. The workflow receives the resolved VALUE and never a path, so
        # it performs no YAML or plugin I/O and rediscovers nothing.
        #
        # The binding is entered HERE too, not inside the workflow, so the
        # binding's lifetime is the composition's lifetime and the region
        # covers the workflow's startup pre-flight as well as its iteration
        # loop — scope resolution and Health materialisation both read the
        # run's profile before iteration 1. `run_workflow` refuses a
        # composition whose authorities are not active, so the split cannot
        # silently produce a half-composed run.
        #
        # `--task_composition` omitted ⇒ `None` ⇒ the context manager is a
        # no-op and the run is byte-identical to its pre-Step-10 behaviour.
        # W7 — resolved once, above, before the invariants pre-flight.
        # ACTIVATION stays exactly where P1 put it.
        # F-MEASCAP-1 — the measurement capability follows the SAME binding
        # the composition does.
        #
        # It used to be `resolve_tidmad_measurement_capability()` written
        # inline in the `run_workflow(...)` call below, twenty-one lines from
        # `task_composition=run_composition`: one argument consulted the bound
        # composition, its neighbour was hardwired to TIDMAD. So a composed
        # non-TIDMAD run declared TIDMAD's identity and tested availability
        # against the import-time `TIDMAD_DATA_DIR` instead of the root it
        # binds — refused up front where TIDMAD data is absent, and silently
        # ADMITTED on the strength of another task's dataset where it is
        # present, which is every campaign host.
        #
        measurement_capability = resolve_composed_measurement_capability(
            run_composition, dataset_root=args.data_dir
        )
        # Step 11 C4 — the run's resolved physical data root travels with
        # the composition binding. `args.data_dir` was already put through
        # `resolve_dataset_dir` above, so this is the SAME authority, not a
        # second convention (R-11-7).
        with bind_run_task_composition(run_composition, physical_data_root=args.data_dir):
            results = run_workflow(
                launch=WorkflowLaunchConfig(
                    source_paths=resolved_paths,
                    require_probe_runner=not (args.is_pseudo_training or args.is_pseudo_llm),
                    healthgate_mode=args.healthgate_mode,
                    result_authority=args.result_authority,
                    max_iterations=1,
                    start_iteration=args.start_iteration,
                    max_rounds=args.max_rounds,
                    max_proposal_attempts=args.max_proposal_attempts,
                    is_trial=args.is_trial,
                    trial_portion=args.trial_portion,
                    train_portion=args.train_portion,
                    eval_portion=args.eval_portion,
                    sampling_seed=args.sampling_seed,
                    formal_strategy=args.formal_strategy,
                    formal_portion=args.formal_portion,
                    formal_train_portion=args.formal_train_portion,
                    formal_eval_portion=args.formal_eval_portion,
                    force_formal_round=args.force_formal_round,
                    formal_round_strategy=args.formal_round_strategy,
                    degenerate_penalty_score=args.degenerate_penalty_score,
                    cleanup_denoised=args.cleanup_denoised,
                    max_epochs=args.max_epochs,
                    # D-BUD-6 — per-mode epoch ceilings, forwarded including
                    # `None` (None = mode-agnostic max_epochs governs).
                    trial_max_epochs=args.trial_max_epochs,
                    formal_max_epochs=args.formal_max_epochs,
                    validation_max_portion=args.validation_max_portion,
                    validation_max_train_samples=args.validation_max_train_samples,
                    validation_max_samples=args.validation_max_samples,
                    validation_max_phase_seconds=args.validation_max_phase_seconds,
                    skip_formal_min_delta=args.skip_formal_min_delta,
                    bypass_formal_time_budget_min_delta=args.bypass_formal_time_budget_min_delta,
                    bypass_formal_time_budget_minutes=args.bypass_formal_time_budget_minutes,
                    trial_time_budget_minutes=args.trial_time_budget_minutes,
                    formal_time_budget_minutes=args.formal_time_budget_minutes,
                    trial_time_admission_source=args.trial_time_admission_source,
                    formal_time_admission_source=args.formal_time_admission_source,
                    data_dir=args.data_dir,
                    gpu_admission_measurement_source=args.gpu_admission_measurement_source,
                    gpu_admission_enforcement=args.gpu_admission_enforcement,
                    gpu_pair_ceiling_gib=args.gpu_pair_ceiling_gib,
                    trial_vram_budget_gb=args.trial_vram_budget_gb,
                    formal_vram_budget_gb=args.formal_vram_budget_gb,
                    vram_probe_step_timeout_seconds=args.vram_probe_step_timeout_seconds,
                    vram_preflight_total_timeout_seconds=(
                        args.vram_preflight_total_timeout_seconds
                    ),
                    vram_preflight_host_memory_limit_gb=(args.vram_preflight_host_memory_limit_gb),
                    attempts_per_round=args.attempts_per_round,
                    attempts_per_formal_round=args.attempts_per_formal_round,
                    max_fail_rounds=args.max_fail_rounds,
                    max_steps_per_attempt=args.max_steps_per_attempt or None,
                    min_formal_batch_size=args.min_formal_batch_size or None,
                    allow_extreme_steps=args.allow_extreme_steps,
                    runtime_watchdog_enabled=args.runtime_watchdog,
                    runtime_safety_factor=args.runtime_safety_factor,
                    runtime_trial_safety_factor=args.runtime_trial_safety_factor,
                    runtime_formal_safety_factor=args.runtime_formal_safety_factor,
                    runtime_watchdog_safety_factor=args.runtime_watchdog_safety_factor,
                    runtime_watchdog_floor_seconds=args.runtime_watchdog_floor_seconds,
                    runtime_verification_max_wall_seconds=(
                        args.runtime_verification_max_wall_seconds
                    ),
                    human_advice_interpret=args.human_advice_interpret,
                    human_advice_analysis=args.human_advice_analysis,
                    human_advice_propose=args.human_advice_propose,
                    human_advice_implement=args.human_advice_implement,
                    human_advice_validate=args.human_advice_validate,
                    human_advice_tune=args.human_advice_tune,
                    human_advice_mindset=args.human_advice_mindset,
                    plan_overrides=args.plan_overrides,
                    workflow_parameter_rules=args.workflow_parameter_rules,
                    exploration_mode=args.exploration_mode,
                    minimum_boldness=args.minimum_boldness,
                    max_impl_attempts=args.max_impl_attempts,
                    debug_dump_prompts=args.debug_dump_prompts,
                    validation_fixed_candidate_plan=fixed_candidate_plan,
                    enable_chain_incumbent_formal_gates=args.enable_chain_incumbent_formal_gates,
                    health_feedback_history_window_iterations=args.health_feedback_history_window_iterations,
                    health_feedback_history_max_entries_per_model=args.health_feedback_history_max_entries_per_model,
                    lit_review_enabled=launch_identity.lit_review_enabled,
                    lit_review_config_path=launch_identity.lit_review_config_path,
                    # arXiv U1 — opaque; locked + stamped, never interpreted.
                    experiment_arm=launch_identity.experiment_arm,
                    # arXiv U3 — the WITHOUT arm's explicit behaviour flag.
                    baseline_isolation=launch_identity.baseline_isolation,
                    # Gold campaign — the OBSERVED advice identity, from the
                    # same resolution the pre-flight lock used, because
                    # `run_workflow` locks the SAME workspace.
                    advice_path=launch_identity.advice_path,
                    advice_sha256=launch_identity.advice_sha256,
                    # arXiv #259 — output-type constraint, transit to the
                    # proposer's schema gate.
                    allowed_output_types=parse_allowed_output_types(args.allowed_output_types),
                ),
                measurement_capability=measurement_capability,
                workspace=args.workspace,
                run_name=run_name,
                chain_run_name=chain_run_name,
                run_id=run_id,
                llm_config=llm_config,
                health_checks_config=args.health_checks_config,
                data_scope=args.data_scope,
                health_gate_enabled=args.health_gate_enabled,
                health_gate_files=args.health_gate_files,
                # Step 10 / P1 C5 — Step 09.5a's C4b hand-off, closed. The nine
                # unpacked kwargs are ONE typed parameter: `RestoredState` is
                # resume's own type and crosses the launcher edge by design
                # (09.5a §16), while `ChainState` still never crosses a process
                # boundary. The workflow unpacks it once, applying the same rules
                # this call site used to apply here.
                restored_state=state,
                order_strategy_override=args.order_strategy_override,
                file_order_override=args.file_order_override,
                enable_structured_health_feedback=args.enable_structured_health_feedback,
                bridge_factory=bridge_factory,
                sandbox_factory=sandbox_factory,
                task_composition=run_composition,
            )
    except LLMBridgeContextError as e:
        # §1.4.2 fail-fast contract. Telemetry-internal corruption (run_id
        # mismatch, backwards iter) means the audit log can no longer be
        # trusted. exit(2) is intentionally distinct from the failure
        # exit(1) below so a downstream classifier can tell them apart.
        print(
            f"[FATAL] LLMBridgeContextError: {e} — aborting iteration to "
            f"prevent telemetry corruption.",
            file=sys.stderr,
        )
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
        sys.exit(2)
    except Exception as e:
        print(f"FAIL: Workflow raised exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            write_manifest(
                iter_dir,
                run_name,
                results=[],
                crashed=True,
                healthgate_mode=args.healthgate_mode,
                result_authority=args.result_authority,
                fixed_candidate_provenance=fixed_candidate_provenance,
                launch_identity=launch_identity,
                replacement=manifest_replacement,
            )
        finally:
            from core.local_code.failure import raise_if_code_package_failure

            raise_if_code_package_failure(e)
        sys.exit(1)

    manifest = write_manifest(
        iter_dir,
        run_name,
        results,
        # V20 PR D: the validated launch declaration, on every branch.
        healthgate_mode=args.healthgate_mode,
        result_authority=args.result_authority,
        # V19 PR 1 (Invariant II): the chain incumbent this iteration
        # consumed, stamped under its own keys — never as an
        # iteration-local best_* field. ``used`` reflects the coupling
        # flag; ``source`` records the reconstruction provenance even
        # when unconsumed.
        chain_incumbent_used=(
            state.chain_best_valid_formal_score
            if args.enable_chain_incumbent_formal_gates
            else None
        ),
        chain_incumbent_source=state.chain_best_valid_formal_provenance,
        # V19 PR 3 — control policy only (per-round evidence stays in the
        # records / interpretation digest).
        fixed_candidate_provenance=fixed_candidate_provenance,
        health_feedback_policy={
            "enable_structured_health_feedback": (args.enable_structured_health_feedback),
            "history_window_iterations": (args.health_feedback_history_window_iterations),
            "max_entries_per_model": (args.health_feedback_history_max_entries_per_model),
        },
        # arXiv U1 — the same identity object every crash branch stamped.
        launch_identity=launch_identity,
        # S2 / U5 (#258): the operator's explicit replacement request, or None.
        replacement=manifest_replacement,
    )

    # C9c — infrastructure ABORT halts the CHAIN, not just this attempt.
    # Checked immediately after the manifest is written so the iteration's
    # diagnostics and artifacts are preserved before we stop: the operator
    # needs them precisely because the environment is broken. The sentinel
    # is what stops a queued next iteration (SDSC `afterany` starts the
    # next job regardless of exit code), and exit 3 is what stops the
    # foreground loop.
    _abort_reason = _infrastructure_abort_reason(results)
    if _abort_reason is not None:
        halt_path = _write_halt_marker(
            args.workspace,
            {
                "halted_at": datetime.now(UTC).isoformat(),
                "workspace": os.path.abspath(args.workspace),
                "reason": "infrastructure_abort",
                "iteration": args.start_iteration,
                "iteration_dir": iter_dir,
                "manifest_status": manifest.get("status"),
                "detail": _abort_reason,
            },
        )
        print(
            "[HALT] runtime evidence-channel failure (infrastructure) — the chain "
            "stops rather than running another candidate on the same broken "
            f"environment. Iteration artifacts preserved in {iter_dir}. "
            f"Marker: {halt_path}",
            file=sys.stderr,
        )
        sys.exit(3)

    # Per-iter [TOKEN_ITER] rollup (§1.6). Best-effort: any IO/JSON error
    # in the rollup must never break the chain — token_usage.jsonl is
    # itself the source of truth.
    try:
        _emit_token_iter_rollup(
            workspace=args.workspace,
            iteration=args.start_iteration,
        )
    except Exception as e:
        print(f"  [TOKEN_ITER] WARN: rollup emit failed: {type(e).__name__}: {e}")

    # V19 PR 1 (P1-C5) — incremental per-file best table. Best-effort:
    # a table-write failure NEVER breaks the chain (the table is
    # analytical bookkeeping, not decision state); on failure the
    # existing table is preserved by atomic replace and can always be
    # regenerated deterministically via
    # ``scripts/runtime/rebuild_per_file_best.py`` from committed artifacts.
    # Only updates on completed manifests (A6).
    if manifest["status"] == "completed":
        try:
            from execute_tools.per_file_best import write_table

            path = write_table(args.workspace)
            print(f"  [PER_FILE_BEST] wrote {path}")
        except Exception as e:
            print(
                f"  [PER_FILE_BEST] WARN: incremental table write failed for "
                f"workspace {args.workspace!r}: {type(e).__name__}: {e} — "
                f"chain continues; regenerate via "
                f"scripts/runtime/rebuild_per_file_best.py."
            )

    if manifest["status"] == "completed":
        print()
        print("=" * 60)
        print(f"  ITERATION {args.start_iteration} COMPLETE")
        print(f"  Model      : {manifest['model_name']}")
        # F-SCANB-3 — labelled for what it now is. This line used to read
        # "Best score" over whichever score topped the MIXED pool, so a
        # trial-only iteration announced a trial number under the word
        # COMPLETE. It is the formal best, and `None` when no formal round
        # produced one.
        print(f"  Formal best: {manifest['best_score']}")
        print(f"  Output     : {manifest['output_path']}")
        print("=" * 60)
        sys.exit(0)

    if manifest["status"] == "no_records":
        # Gate exhaustion or all-rounds-failed without a Python crash.
        # Exit 0 so run_chain.sh's `set -e` does not halt the chain — the
        # next iter's LLM will see the skipped attempts via memory_history
        # restoration and can adapt. See docs/phase68_orchestrator_memory_and_resume.md
        # §3.3 for the no_records contract.
        print()
        print("=" * 60)
        print(
            "[CHAIN] No models passed gates this iteration. "
            "Writing manifest and exiting gracefully to allow chain to continue."
        )
        print(f"  Iteration  : {args.start_iteration}")
        print(f"  Manifest   : {os.path.join(iter_dir, 'manifest.json')} (status=no_records)")
        print("=" * 60)
        sys.exit(0)

    # Defensive: any other status is unexpected and should halt the chain.
    print(f"FAIL: Iteration ended with unexpected manifest status={manifest['status']!r}.")
    sys.exit(1)


if __name__ == "__main__":
    main()
