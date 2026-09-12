"""
Diagnostic tool: inspect a SIDERIUS exploration run's on-disk state.

Two layouts are supported:

* ``--layout run`` (default, legacy in-process layout, retired in
  Commit 15): walks ``{run_dir}/exploration_{run_name}/{run_name}/
  iteration_NNN/`` directories and locates the tuner output for each
  iteration. The commit fence is ``run_output_{run_name}.json``.

* ``--layout chain`` (Phase 6.8 Task 2 chain layout): walks
  ``{workspace}/iter_NNN/`` directories. The commit fence is
  ``manifest.json`` with ``status="completed"`` plus the referenced
  ``output_path`` validating against ``HyperparamTuningOutput``.

In chain mode the tool also supports ``--next-iter``, a machine-
readable mode that prints **only** the integer index of the first
non-COMMITTED iteration on stdout (1 if no committed iters,
``max_seen + 1`` if all clean), suitable for shell capture by
``run_chain.sh --auto_resume``. Errors and warnings still go to stderr;
non-zero exit on legacy-layout detection or non-contiguous iters.

The {COMMITTED, PARTIAL, CORRUPT, TAMPERED, MISSING} predicate must agree
with ``core.resume._read_manifest`` + replay integrity +
``_validate_run_output`` — that is the contract auto-resume relies on. Both
call sites encode the same rule: manifest.json exists, parses, ``status ==
"completed"``, ``output_path`` points at a file, the manifest and artifact
pass ``core.iteration_manifest.verify_iteration_manifest`` (the SAME
predicate resume raises ``ReplayIntegrityError`` from), and that file
validates against ``HyperparamTuningOutput``.

``TAMPERED`` (S2 / U5) is what resume would STOP on: an edited manifest, a
removed artifact hash, or a changed artifact. It is never advanced past —
``--next-iter`` refuses with a non-zero exit, because relaunching would
fail at ``restore_prior_state`` anyway, after the job was queued.

Usage (legacy run layout):
    .venv/bin/python scripts/launch/inspect_run_state.py \\
        --layout run \\
        --run_dir /home/klz/Data/SIDEREIS_DATA \\
        --run_name exploit_cnn_v4_0425

Usage (chain layout, human view):
    .venv/bin/python scripts/launch/inspect_run_state.py \\
        --layout chain \\
        --workspace /home/klz/Data/SIDEREIS_DATA/exploration_<name>

Usage (chain layout, machine view for shell capture):
    NEXT=$(.venv/bin/python scripts/launch/inspect_run_state.py \\
        --layout chain --workspace "$WORKSPACE" --next-iter)

This is a read-only foundation tool. It does not modify any files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.iteration_manifest import verify_iteration_manifest
from core.record_role import RecordRoleError, formal_evidence_of
from core.resume import ResumeError, validate_workspace_layout

_RUN_ITER_RE = re.compile(r"^iteration_(\d+)$")
_CHAIN_ITER_RE = re.compile(r"^iter_(\d+)$")


@dataclass
class IterationReport:
    """Per-iteration findings for the summary table.

    Same shape for both layouts so :func:`render_table` is layout-agnostic.
    ``model_subdir`` and ``run_output_path`` are only populated by the
    legacy run-layout walk; chain-layout reports leave them ``None``.

    ``best_score`` is the tuner's MIXED best — ``top_record`` over all
    records, trial and formal — and is rendered under a column that says so.
    ``formal_best_score`` is the authoritative one (F-SCANB-3): it is
    ``None`` for an iteration that ran only trial rounds, which is exactly
    the state the single mixed column used to conceal. Defaulted, so the
    dozen non-COMMITTED constructions below are unchanged.
    """

    iter_idx: int
    iter_dir: Path
    model_subdir: Path | None
    run_output_path: Path | None
    status: str
    model_type: str | None
    best_score: float | None
    detail: str
    formal_best_score: float | None = None


# ---------------------------------------------------------------------------
# Legacy run-layout walk (unchanged behaviour)
# ---------------------------------------------------------------------------


def _formal_evidence_detail(parsed: HyperparamTuningOutput) -> str:
    """The formal-evidence fragment of a report's ``detail`` (F-SCANB-3).

    Degrades rather than raises. The role authority refuses an anomalous
    ``is_trial`` / ``trial_portion`` shape because a silent choice could
    select the wrong record. This inspector owns chain bookkeeping, so it
    reports the anomaly in the row instead of turning reporting into an
    uncaught crash.
    """
    try:
        evidence = formal_evidence_of(parsed)
    except RecordRoleError as exc:
        return f"formal_success=? anomalous_role_shape ({exc})"
    return f"formal_success={evidence.formal_success_count}/{evidence.record_count}"


def _find_workspace_root(run_dir: Path, run_name: str) -> Path:
    """Resolve the directory that holds ``iteration_NNN/`` children."""
    candidates = [
        run_dir / f"exploration_{run_name}" / run_name,
        run_dir / run_name,
        run_dir,
    ]
    for c in candidates:
        if c.is_dir() and any(_RUN_ITER_RE.match(p.name) for p in c.iterdir()):
            return c
    raise FileNotFoundError(
        "No iteration_NNN dirs found under any of: " + ", ".join(str(c) for c in candidates)
    )


def _find_tuner_subdir(iter_dir: Path) -> Path | None:
    """Return the model-type subdir inside an iteration_NNN/ folder.

    Tuner outputs live in ``iteration_NNN/{model_type}/``. Sibling
    ``attempt_NNN_*`` dirs hold proposer/implementor/validator artifacts
    and are skipped.
    """
    for child in sorted(iter_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("attempt_"):
            continue
        return child
    return None


def _validate_run_output(
    path: Path,
) -> tuple[HyperparamTuningOutput | None, str]:
    """Try to load + validate ``run_output_*.json``. Returns (parsed, err)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"read error: {e}"
    try:
        return HyperparamTuningOutput.model_validate_json(text), ""
    except ValidationError as e:
        return None, f"validation: {e.error_count()} error(s)"
    except json.JSONDecodeError as e:
        return None, f"malformed JSON: {e.msg}"


def inspect_iteration(iter_dir: Path, run_name: str) -> IterationReport:
    """Classify a single iteration_NNN/ dir under the legacy run layout."""
    m = _RUN_ITER_RE.match(iter_dir.name)
    if m is None:
        raise ValueError(
            f"inspect_iteration: {iter_dir.name!r} does not match {_RUN_ITER_RE.pattern!r}"
        )
    iter_idx = int(m.group(1))
    model_subdir = _find_tuner_subdir(iter_dir)

    if model_subdir is None:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="MISSING",
            model_type=None,
            best_score=None,
            detail="no tuner subdir (iter never reached the tuner)",
        )

    run_output = model_subdir / f"run_output_{run_name}.json"
    if not run_output.exists():
        return IterationReport(
            iter_idx,
            iter_dir,
            model_subdir,
            None,
            status="PARTIAL",
            model_type=model_subdir.name,
            best_score=None,
            detail="tuner subdir present but no run_output_*.json (mid-round crash)",
        )

    parsed, err = _validate_run_output(run_output)
    if parsed is None:
        return IterationReport(
            iter_idx,
            iter_dir,
            model_subdir,
            run_output,
            status="CORRUPT",
            model_type=model_subdir.name,
            best_score=None,
            detail=err,
        )

    return IterationReport(
        iter_idx,
        iter_dir,
        model_subdir,
        run_output,
        status="COMMITTED",
        model_type=parsed.model_type,
        best_score=parsed.best_denoising_score,
        detail=(
            f"status={parsed.status} rounds={parsed.completed_rounds} "
            f"{_formal_evidence_detail(parsed)}"
        ),
        formal_best_score=parsed.best_formal_denoising_score,
    )


# ---------------------------------------------------------------------------
# Chain-layout walk (Phase 6.8 Task 2)
# ---------------------------------------------------------------------------


def _find_chain_iter_dirs(workspace: Path) -> list[Path]:
    """Return ``iter_NNN/`` children of ``workspace`` sorted by index.

    Empty list if the workspace has no chain iters yet (clean start).
    """
    if not workspace.is_dir():
        return []
    # Match each name once and pair with its extracted index, so the sort
    # key is plain ``int`` (no second regex pass, no .group() on Optional).
    matched: list[tuple[int, Path]] = []
    for p in workspace.iterdir():
        if not p.is_dir():
            continue
        m = _CHAIN_ITER_RE.match(p.name)
        if m is None:
            continue
        matched.append((int(m.group(1)), p))
    return [p for _, p in sorted(matched)]


def inspect_chain_iteration(iter_dir: Path) -> IterationReport:
    """Classify a single ``iter_NNN/`` dir under the chain layout.

    Mirrors the predicate in ``core.resume._read_manifest`` +
    ``_validate_run_output`` so the inspector's "COMMITTED" matches what
    ``restore_prior_state`` will accept.
    """
    m = _CHAIN_ITER_RE.match(iter_dir.name)
    if m is None:
        raise ValueError(
            f"inspect_chain_iteration: {iter_dir.name!r} does not match {_CHAIN_ITER_RE.pattern!r}"
        )
    iter_idx = int(m.group(1))
    manifest_path = iter_dir / "manifest.json"

    if not manifest_path.is_file():
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="MISSING",
            model_type=None,
            best_score=None,
            detail="no manifest.json (iter never committed)",
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="CORRUPT",
            model_type=None,
            best_score=None,
            detail=f"manifest malformed JSON: {e.msg}",
        )
    except OSError as e:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="CORRUPT",
            model_type=None,
            best_score=None,
            detail=f"manifest read error: {e}",
        )

    status = manifest.get("status")
    model_name = manifest.get("model_name")
    if status != "completed":
        # S2 / U5 — a non-completed manifest names no artifact, but its own
        # self-digest is still verified, exactly as resume does before it
        # skips a no_records iter.
        verdict = verify_iteration_manifest(
            manifest, iter_idx=iter_idx, manifest_path=str(manifest_path), output_path=None
        )
        if verdict.problem is not None:
            return IterationReport(
                iter_idx,
                iter_dir,
                None,
                None,
                status="TAMPERED",
                model_type=model_name,
                best_score=None,
                detail=f"REPLAY-INTEGRITY: {verdict.problem}",
            )
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="PARTIAL",
            model_type=model_name,
            best_score=None,
            detail=f"manifest status={status!r}, expected 'completed'",
        )

    output_path_str = manifest.get("output_path")
    if not output_path_str:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="CORRUPT",
            model_type=model_name,
            best_score=None,
            detail="manifest has no output_path field",
        )
    output_path = Path(output_path_str)
    if not output_path.is_file():
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            output_path,
            status="CORRUPT",
            model_type=model_name,
            best_score=None,
            detail=f"manifest output_path does not exist: {output_path}",
        )

    # S2 / U5 — replay integrity BEFORE the artifact is trusted, from the
    # one predicate resume and per_file_best share. A manifest that resume
    # would stop the chain on is never called COMMITTED here.
    verdict = verify_iteration_manifest(
        manifest,
        iter_idx=iter_idx,
        manifest_path=str(manifest_path),
        output_path=str(output_path),
    )
    if verdict.problem is not None:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            output_path,
            status="TAMPERED",
            model_type=model_name,
            best_score=None,
            detail=f"REPLAY-INTEGRITY: {verdict.problem}",
        )

    parsed, err = _validate_run_output(output_path)
    if parsed is None:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            output_path,
            status="CORRUPT",
            model_type=model_name,
            best_score=None,
            detail=f"run_output {err}",
        )

    return IterationReport(
        iter_idx,
        iter_dir,
        None,
        output_path,
        status="COMMITTED",
        model_type=parsed.model_type,
        best_score=parsed.best_denoising_score,
        detail=(
            f"status={parsed.status} rounds={parsed.completed_rounds} "
            f"{_formal_evidence_detail(parsed)}"
        ),
        formal_best_score=parsed.best_formal_denoising_score,
    )


def find_iter_gap(reports: list[IterationReport]) -> int | None:
    """Return the first missing iter index in a non-contiguous sequence.

    None if the indices form a contiguous ``[1..N]`` (or are empty).
    Used to refuse ambiguous chains where iter_002 is gone but iter_003
    exists — operator intervention required.
    """
    if not reports:
        return None
    indices = [r.iter_idx for r in reports]
    expected = set(range(1, max(indices) + 1))
    actual = set(indices)
    missing = expected - actual
    if missing:
        return min(missing)
    return None


# ---------------------------------------------------------------------------
# Rendering + summary
# ---------------------------------------------------------------------------


def render_table(reports: list[IterationReport]) -> str:
    """Render the summary table. Plain text, fixed-width columns.

    Same columns for both layouts (Iter, Model, Status, Mixed Best, Formal
    Best, Detail). Chain-layout reports populate them from the parsed
    run_output, identical to the legacy walk.

    F-SCANB-3 — the two score columns are separate on purpose. A single
    "Best Score" column carrying ``best_denoising_score`` renders a TRIAL
    score whenever an iteration ran no formal round, which is what every
    v20 attempt-3 iteration did; the operator had no way to see it. "Formal
    Best" is the authoritative number and shows "—" precisely then.
    """
    if not reports:
        return "(no iterations found)"
    header = ("Iter", "Model", "Status", "Mixed Best", "Formal Best", "Detail")
    rows = [header] + [
        (
            f"{r.iter_idx:03d}",
            r.model_type or "—",
            r.status,
            f"{r.best_score:.6f}" if r.best_score is not None else "—",
            f"{r.formal_best_score:.6f}" if r.formal_best_score is not None else "—",
            r.detail,
        )
        for r in reports
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    sep = "  "
    out = []
    for i, row in enumerate(rows):
        out.append(sep.join(cell.ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            out.append(sep.join("-" * widths[j] for j in range(len(header))))
    return "\n".join(out)


def compute_next_iter(
    reports: list[IterationReport],
    gap: int | None,
) -> int:
    """Return the index the next chain iter should run as.

    ``gap`` must be the result of :func:`find_iter_gap` on the same
    reports. The caller is responsible for refusing to call this when
    ``gap is not None`` — gap presence is the operator's signal to
    intervene, not auto-resume's signal to plough through.

    Rules (chain mode only):
      * empty workspace → 1
      * any iter COMMITTED → ``max(committed_iter_idx) + 1`` (advance past
        the verified history; do NOT retry a non-COMMITTED iter that sits
        below a later committed one — overwriting later successful work
        is a far worse failure mode than leaving a broken iter on disk)
      * no iter COMMITTED → first non-COMMITTED iter index (retry the
        broken first iter; nothing useful would be lost)

    The "any committed → max+1" rule is what diverges from earlier
    revisions: previously this function returned the first non-COMMITTED
    iter even when later iters had committed, causing auto-resume to
    launch into a directory whose neighbours were finished. See
    :func:`find_dangling_broken_iters` for the partial-below-committed
    case operators should know about.
    """
    if gap is not None:
        raise ValueError(
            f"compute_next_iter called with non-contiguous chain "
            f"(missing iter_{gap:03d}); refuse before this point."
        )
    tampered = find_tampered_iters(reports)
    if tampered:
        # S2 / U5 — resume raises ReplayIntegrityError on ANY tampered prior
        # iter, wherever it sits, so there is no index that could be
        # launched next. Same contract as the gap: the caller refuses first.
        raise ValueError(
            f"compute_next_iter called with tampered iter(s) "
            f"{', '.join(f'iter_{i:03d}' for i in tampered)}; refuse before this point."
        )
    if not reports:
        return 1
    committed = [r for r in reports if r.status == "COMMITTED"]
    if committed:
        return max(r.iter_idx for r in committed) + 1
    # No committed history — retry the first broken iter (legacy fallback).
    for r in reports:
        if r.status != "COMMITTED":
            return r.iter_idx
    raise AssertionError(
        "unreachable: reports non-empty but no committed AND no non-committed entries"
    )


def find_tampered_iters(reports: list[IterationReport]) -> list[int]:
    """Iter indices whose manifest or artifact failed replay integrity.

    Any such iter means ``restore_prior_state`` will raise
    ``ReplayIntegrityError`` for every later launch; the operator must
    restore the artifact or replace the iteration explicitly.
    """
    return sorted(r.iter_idx for r in reports if r.status == "TAMPERED")


def find_dangling_broken_iters(
    reports: list[IterationReport],
) -> list[int]:
    """Iter indices that are non-COMMITTED but below max(COMMITTED).

    These represent broken state left behind when a later iter
    succeeded. Auto-resume's :func:`compute_next_iter` advances past
    them; this helper surfaces them so operators can choose to clean
    them up. Returns an empty list when no committed iters exist or
    when all non-COMMITTED iters are already above max(committed).
    """
    if not reports:
        return []
    committed_idxs = [r.iter_idx for r in reports if r.status == "COMMITTED"]
    if not committed_idxs:
        return []
    max_committed = max(committed_idxs)
    return sorted(
        r.iter_idx for r in reports if r.status != "COMMITTED" and r.iter_idx < max_committed
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Inspect a SIDERIUS exploration run's on-disk state. "
            "Supports both the legacy run layout (--layout run) and the "
            "chain layout (--layout chain) introduced by Phase 6.8 Task 2."
        ),
    )
    ap.add_argument(
        "--layout",
        choices=("run", "chain"),
        default="run",
        help="Workspace layout to walk. Default 'run' for back-compat; "
        "chain runners must pass --layout chain. Default flips in Commit 15.",
    )
    ap.add_argument(
        "--run_dir",
        type=Path,
        help="(--layout run) Parent dir holding exploration_{run_name}/.",
    )
    ap.add_argument(
        "--run_name",
        type=str,
        help="(--layout run) Run identifier matching exploration_{run_name}/.",
    )
    ap.add_argument(
        "--workspace",
        type=Path,
        help="(--layout chain) Chain workspace root containing iter_NNN/.",
    )
    ap.add_argument(
        "--next-iter",
        action="store_true",
        dest="next_iter",
        help="(--layout chain) Print only the integer index of the next "
        "iter to run on stdout. Suppresses the table. Used by "
        "run_chain.sh --auto_resume.",
    )
    return ap


def _validate_args(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    if args.layout == "run":
        if args.next_iter:
            ap.error("--next-iter requires --layout chain")
        if args.run_dir is None or args.run_name is None:
            ap.error("--layout run requires --run_dir and --run_name")
        if args.workspace is not None:
            ap.error("--workspace is only valid with --layout chain")
    else:  # chain
        if args.workspace is None:
            ap.error("--layout chain requires --workspace")
        if args.run_dir is not None or args.run_name is not None:
            ap.error("--run_dir/--run_name are only valid with --layout run")


def _run_layout_run(args: argparse.Namespace) -> int:
    try:
        ws_root = _find_workspace_root(args.run_dir, args.run_name)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(f"Workspace root: {ws_root}")
    # Match each name once and pair with its extracted index — sort key is
    # then plain ``int``, with no .group() on Optional.
    matched: list[tuple[int, Path]] = []
    for p in ws_root.iterdir():
        if not p.is_dir():
            continue
        m = _RUN_ITER_RE.match(p.name)
        if m is None:
            continue
        matched.append((int(m.group(1)), p))
    iter_dirs = [p for _, p in sorted(matched)]
    reports = [inspect_iteration(d, args.run_name) for d in iter_dirs]

    print(render_table(reports))
    print()

    counts = {
        s: sum(1 for r in reports if r.status == s)
        for s in ("COMMITTED", "PARTIAL", "CORRUPT", "MISSING")
    }
    print(f"Summary: {len(reports)} iter(s) — " + ", ".join(f"{k}={v}" for k, v in counts.items()))

    last_committed = max(
        (r.iter_idx for r in reports if r.status == "COMMITTED"),
        default=None,
    )
    if last_committed is not None:
        print(
            f"Last committed iteration: {last_committed:03d} "
            f"(resume would replay state up to and including this iter)"
        )
    else:
        print("No committed iteration found — resume would start from scratch.")

    return 0


def _print_tampered_refusal(
    workspace: Path, reports: list[IterationReport], tampered: list[int]
) -> None:
    """stderr only — stdout must stay clean for the shell capture."""
    names = ", ".join(f"iter_{i:03d}" for i in tampered)
    print(
        f"ERROR: replay integrity failed at {workspace} — {names}. "
        f"restore_prior_state would raise ReplayIntegrityError for every later "
        f"iteration; restore the original artifact(s) or replace the iteration "
        f"explicitly (run_one_iteration.py --replace_iteration_manifest "
        f"--replacement_reason '<why>') before resuming.",
        file=sys.stderr,
    )
    for r in reports:
        if r.status == "TAMPERED":
            print(f"  iter_{r.iter_idx:03d}: {r.detail}", file=sys.stderr)


def _run_layout_chain(args: argparse.Namespace) -> int:
    workspace: Path = args.workspace.resolve()

    # Legacy guard: refuse to walk a workspace that holds v5/v6 artifacts.
    # Reuses the same helper used at runtime by the chain runner so
    # "what counts as legacy" has a single source of truth.
    try:
        validate_workspace_layout(str(workspace))
    except ResumeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    iter_dirs = _find_chain_iter_dirs(workspace)
    reports = [inspect_chain_iteration(d) for d in iter_dirs]
    gap = find_iter_gap(reports)

    dangling = find_dangling_broken_iters(reports)
    tampered = find_tampered_iters(reports)

    if args.next_iter:
        if gap is not None:
            print(
                f"ERROR: non-contiguous chain at {workspace} — "
                f"missing iter_{gap:03d}. Operator must inspect before "
                f"resuming.",
                file=sys.stderr,
            )
            return 2
        if tampered:
            _print_tampered_refusal(workspace, reports, tampered)
            return 2
        if dangling:
            dangling_str = ", ".join(f"iter_{i:03d}" for i in dangling)
            print(
                f"WARN: dangling broken iter(s) below latest committed: "
                f"{dangling_str}. Auto-resume advances past them; clean "
                f"up at your discretion.",
                file=sys.stderr,
            )
        print(compute_next_iter(reports, gap))
        return 0

    # Human view (table + summary).
    print(f"Workspace root: {workspace}")
    print(render_table(reports))
    print()

    counts = {
        s: sum(1 for r in reports if r.status == s)
        for s in ("COMMITTED", "PARTIAL", "CORRUPT", "TAMPERED", "MISSING")
    }
    print(f"Summary: {len(reports)} iter(s) — " + ", ".join(f"{k}={v}" for k, v in counts.items()))

    if gap is not None:
        print(
            f"\nERROR: non-contiguous chain — missing iter_{gap:03d}. "
            f"Operator must inspect before resuming.",
            file=sys.stderr,
        )
        return 2
    if tampered:
        _print_tampered_refusal(workspace, reports, tampered)
        return 2

    next_idx = compute_next_iter(reports, gap)
    if not reports:
        print("No iterations on disk — chain would start at iter_001.")
    else:
        last_committed = max(
            (r.iter_idx for r in reports if r.status == "COMMITTED"),
            default=None,
        )
        if last_committed is not None:
            print(
                f"Last committed iter: iter_{last_committed:03d} "
                f"(--auto_resume would launch iter_{next_idx:03d} next)."
            )
        else:
            print(f"No committed iter — --auto_resume would launch iter_{next_idx:03d}.")
        if dangling:
            dangling_str = ", ".join(f"iter_{i:03d}" for i in dangling)
            print(
                f"WARN: dangling broken iter(s) below latest committed: "
                f"{dangling_str}. Auto-resume advances past them; clean "
                f"up at your discretion.",
                file=sys.stderr,
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = _build_parser()
    args = ap.parse_args(argv)
    _validate_args(args, ap)

    if args.layout == "run":
        return _run_layout_run(args)
    return _run_layout_chain(args)


if __name__ == "__main__":
    sys.exit(main())
