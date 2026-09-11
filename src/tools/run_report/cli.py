"""The frozen command-line contract for the static run report.

    python -m tools.run_report --workspace <chain_workspace_dir> --out <report_dir>
    python -m tools.run_report --run-output <path/to/run_output_*.json> --out <report_dir>

Writes ``<report_dir>/index.html``, the PNG figures it references, and a
machine-readable ``report.json``.

**Exit status is part of the contract.** ``0`` on success; non-zero with a
NAMED error on stderr when no consumable artifact is found. A report is never
silently empty: pointing this at the wrong directory must say so, because the
three example packs publish this command in their READMEs and a blank page is
indistinguishable from a run that produced nothing.

The flags above are FROZEN (§V.15 — the shared contract that had to freeze
before workstreams D and R implemented). Everything else here is
implementation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from execute_tools.run_report import (
    RUN_OUTPUT_GLOB,
    RunReport,
    RunReportError,
    build_report,
)
from tools.run_report.figures import render_figures
from tools.run_report.html import write_html

#: Exit codes. Named constants because the packs' READMEs and workstream D's
#: bounded integration check both assert on them, and a bare integer at three
#: call sites is three chances for one of them to drift.
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NO_ARTIFACT = 3

#: The report's machine-readable sibling. The dashboard and any downstream
#: consumer read THIS, never the HTML — §V.5's "one projection, multiple
#: presentation consumers" is only true if the data has a non-HTML form.
REPORT_JSON = "report.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.run_report",
        description=(
            "Render a static, self-contained report from a completed SIDERIUS "
            "run. Reads only persisted run_output_*.json artifacts; needs no "
            "dashboard, no server and no network."
        ),
        epilog=(
            "The report shows generic run semantics only — training objective "
            "history, primary and secondary metric trajectories, attempt "
            "outcomes and reproducibility identity. Task-specific presentation "
            "(waveforms, images, video frames) belongs to the example pack."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--workspace",
        type=Path,
        help=(
            "A chain workspace directory. Every "
            f"{RUN_OUTPUT_GLOB} beneath it is consumed, in the order of the "
            "artifacts' own started_at timestamps."
        ),
    )
    source.add_argument(
        "--run-output",
        type=Path,
        action="append",
        metavar="PATH",
        help=("One run_output_*.json artifact. Repeatable, to report on a hand-picked set."),
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Directory to write index.html, the PNG figures and report.json into.",
    )
    return parser


def write_report(report: RunReport, out_dir: Path) -> tuple[Path, Path]:
    """Render ``report`` into ``out_dir``; return ``(index.html, report.json)``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    figures = render_figures(report, out_dir)
    index = write_html(report, figures, out_dir)
    payload = out_dir / REPORT_JSON
    payload.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return index, payload


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit status rather than raising."""
    args = build_parser().parse_args(argv)
    try:
        report = build_report(
            workspace=args.workspace,
            run_outputs=None if args.run_output is None else list(args.run_output),
        )
    except RunReportError as exc:
        # NAMED, on stderr, non-zero. Never a silently empty report.
        print(f"[run_report] {exc.name}: {exc}", file=sys.stderr)
        return EXIT_NO_ARTIFACT

    index, payload = write_report(report, args.out)
    print(f"[run_report] {len(report.runs)} run(s) -> {index}")
    print(f"[run_report] machine-readable projection -> {payload}")
    for item in report.unreadable:
        print(f"[run_report] skipped {item}", file=sys.stderr)
    if report.trajectory.refusal is not None:
        print(f"[run_report] {report.trajectory.refusal}", file=sys.stderr)
    return EXIT_OK
