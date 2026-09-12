"""Replay CLI (C11).

    # what the stopped run believed — reads only, no GPU, no LLM
    .venv/bin/python -m tools.runtime_replay metadata \
        --snapshot /home/klz/Data/SIDEREIS_DATA/v19/forensics

    # what an executable replay WOULD probe (no device touched)
    .venv/bin/python -m tools.runtime_replay executable --snapshot ... --plan

    # register the legacy k-table by content hash (never imports it)
    .venv/bin/python -m tools.runtime_replay legacy --dry-run

Executable replay with `--run` touches the GPU and is operator-gated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.runtime_replay.executable_replay import (
    plan_executable_replay,
    production_probe,
    run_executable_replay,
)
from tools.runtime_replay.legacy_migration import (
    discover_legacy_tables,
    migrate_legacy_table,
)
from tools.runtime_replay.metadata_replay import run_metadata_replay


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runtime_replay",
        description="Replay a stopped run's proposals and migrate legacy calibration.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    meta = sub.add_parser("metadata", help="Report what the snapshot recorded. Reads only.")
    meta.add_argument("--snapshot", required=True)
    meta.add_argument("--json", dest="as_json", action="store_true")

    ex = sub.add_parser("executable", help="Probe candidates that still have implementations.")
    ex.add_argument("--snapshot", required=True)
    ex.add_argument("--plan", action="store_true", help="Report what would run; touch nothing.")
    ex.add_argument(
        "--run",
        action="store_true",
        help="ACTUALLY probe on the GPU (operator-gated).",
    )
    ex.add_argument("--segmentation-size", type=int, default=40_000)
    ex.add_argument("--batch-size", type=int, default=8)
    ex.add_argument("--data-dir", default=None)
    ex.add_argument("--json", dest="as_json", action="store_true")

    legacy = sub.add_parser("legacy", help="Register legacy k-tables by content hash.")
    legacy.add_argument("--path", default=None, help="A specific table; default: discover.")
    legacy.add_argument("--dry-run", action="store_true")
    legacy.add_argument("--json", dest="as_json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "metadata":
        report = run_metadata_replay(args.snapshot)
        print(
            json.dumps(report.model_dump(mode="json"), indent=2)
            if args.as_json
            else report.render()
        )
        return 0

    if args.command == "executable":
        report = run_metadata_replay(args.snapshot)
        if not args.run:
            plan = plan_executable_replay(report)
            print(json.dumps(plan, indent=2) if args.as_json else _render_plan(plan))
            return 0
        probe = production_probe(
            model_config={"segmentation_size": args.segmentation_size},
            train_config={
                "lr": 1e-4,
                "batch_size": args.batch_size,
                "epochs": 1,
                "optimizer_type": "adamw",
                "weight_decay": 1e-5,
                "device": "cuda",
            },
            loss_config={"loss_type": "ce"},
            data_dir=args.data_dir,
        )
        measured_report = run_executable_replay(report, probe=probe)
        print(
            json.dumps(measured_report.model_dump(mode="json"), indent=2)
            if args.as_json
            else measured_report.render()
        )
        return 0

    tables = [Path(args.path)] if args.path else discover_legacy_tables()
    if not tables:
        print("No legacy k-tables found.")
        return 0
    summaries = [migrate_legacy_table(path, dry_run=args.dry_run) for path in tables]
    if args.as_json:
        print(json.dumps(summaries, indent=2))
    else:
        for summary in summaries:
            print(f"\n  {summary['path']}")
            for key in (
                "gpu_slug",
                "file_sha256",
                "entry_count",
                "provenance_of_entries",
                "imported_as_observations",
                "registered",
                "source_unmodified",
            ):
                print(f"    {key:24}: {summary[key]}")
    return 0


def _render_plan(plan: dict) -> str:
    lines = ["", "  Executable replay plan (nothing executed)"]
    lines.append(f"    probes to run : {plan['probes']}")
    for name in plan["eligible"]:
        lines.append(f"      + {name}")
    lines.append("    skipped:")
    for entry in plan["skipped"]:
        lines.append(f"      - {entry['model_name'] or '<unnamed draft>'}: {entry['reason']}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
