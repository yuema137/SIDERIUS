"""
Diagnostic tool: inspect a SIDERIUS exploration run's on-disk state.

Walks ``{run_dir}/{run_name}/iteration_NNN/`` directories, locates the
tuner output for each iteration, and reports whether
``run_output_{run_name}.json`` exists and validates against
``HyperparamTuningOutput``. The ``run_output_*.json`` file is the
iteration's commit fence: if it exists and parses, the iteration is
durable and recoverable; otherwise the iteration is partial or corrupt.

This is read-only foundation work for Phase 6.8 Task 2 (Resume). It does
not modify any files; it only inspects and tabulates.

Usage:
    .venv/bin/python scripts/inspect_run_state.py \\
        --run_dir /home/klz/Data/SIDEREIS_DATA \\
        --run_name exploit_cnn_v4_0425

The ``--run_dir`` is the *parent* of the per-run workspace (typically
``/home/klz/Data/SIDEREIS_DATA``). The script auto-detects whether the
real workspace is ``{run_dir}/exploration_{run_name}/{run_name}/``
(default layout) or a flatter layout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput  # noqa: E402


_ITER_RE = re.compile(r"^iteration_(\d+)$")


@dataclass
class IterationReport:
    """Per-iteration findings for the summary table."""
    iter_idx: int
    iter_dir: Path
    model_subdir: Optional[Path]
    run_output_path: Optional[Path]
    status: str
    model_type: Optional[str]
    best_score: Optional[float]
    detail: str


def _find_workspace_root(run_dir: Path, run_name: str) -> Path:
    """Resolve the directory that holds ``iteration_NNN/`` children."""
    candidates = [
        run_dir / f"exploration_{run_name}" / run_name,
        run_dir / run_name,
        run_dir,
    ]
    for c in candidates:
        if c.is_dir() and any(_ITER_RE.match(p.name) for p in c.iterdir()):
            return c
    raise FileNotFoundError(
        "No iteration_NNN dirs found under any of: "
        + ", ".join(str(c) for c in candidates)
    )


def _find_tuner_subdir(iter_dir: Path) -> Optional[Path]:
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
) -> tuple[Optional[HyperparamTuningOutput], str]:
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
    iter_idx = int(_ITER_RE.match(iter_dir.name).group(1))
    model_subdir = _find_tuner_subdir(iter_dir)

    if model_subdir is None:
        return IterationReport(
            iter_idx, iter_dir, None, None,
            status="MISSING",
            model_type=None,
            best_score=None,
            detail="no tuner subdir (iter never reached the tuner)",
        )

    run_output = model_subdir / f"run_output_{run_name}.json"
    if not run_output.exists():
        return IterationReport(
            iter_idx, iter_dir, model_subdir, None,
            status="PARTIAL",
            model_type=model_subdir.name,
            best_score=None,
            detail="tuner subdir present but no run_output_*.json (mid-round crash)",
        )

    parsed, err = _validate_run_output(run_output)
    if parsed is None:
        return IterationReport(
            iter_idx, iter_dir, model_subdir, run_output,
            status="CORRUPT",
            model_type=model_subdir.name,
            best_score=None,
            detail=err,
        )

    return IterationReport(
        iter_idx, iter_dir, model_subdir, run_output,
        status="COMMITTED",
        model_type=parsed.model_type,
        best_score=parsed.best_denoising_score,
        detail=f"status={parsed.status} rounds={parsed.completed_rounds}",
    )


def render_table(reports: list[IterationReport]) -> str:
    """Render the summary table. Plain text, fixed-width columns."""
    if not reports:
        return "(no iterations found)"
    header = ("Iter", "Model", "Status", "Best Score", "Detail")
    rows = [header] + [
        (
            f"{r.iter_idx:03d}",
            r.model_type or "—",
            r.status,
            f"{r.best_score:.6f}" if r.best_score is not None else "—",
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Inspect a SIDERIUS exploration run's on-disk state. "
                    "Foundation for Phase 6.8 Task 2 (Resume)."
    )
    ap.add_argument("--run_dir", required=True, type=Path,
                    help="Parent dir holding exploration_{run_name}/ "
                         "(typically /home/klz/Data/SIDEREIS_DATA).")
    ap.add_argument("--run_name", required=True, type=str,
                    help="Run identifier matching the exploration_{run_name}/ folder.")
    args = ap.parse_args()

    try:
        ws_root = _find_workspace_root(args.run_dir, args.run_name)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(f"Workspace root: {ws_root}")
    iter_dirs = sorted(
        (p for p in ws_root.iterdir() if p.is_dir() and _ITER_RE.match(p.name)),
        key=lambda p: int(_ITER_RE.match(p.name).group(1)),
    )
    reports = [inspect_iteration(d, args.run_name) for d in iter_dirs]

    print(render_table(reports))
    print()

    counts = {s: sum(1 for r in reports if r.status == s)
              for s in ("COMMITTED", "PARTIAL", "CORRUPT", "MISSING")}
    print(f"Summary: {len(reports)} iter(s) — "
          + ", ".join(f"{k}={v}" for k, v in counts.items()))

    last_committed = max(
        (r.iter_idx for r in reports if r.status == "COMMITTED"),
        default=None,
    )
    if last_committed is not None:
        print(f"Last committed iteration: {last_committed:03d} "
              f"(resume would replay state up to and including this iter)")
    else:
        print("No committed iteration found — resume would start from scratch.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
