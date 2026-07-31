#!/usr/bin/env python
"""Baseline-scale validation of the repaired VRAM pre-flight.

Every candidate must end with ONE explicit disposition:

    completed | measured_oom | measured_peak_over_cap | measured_hard_timeout

A generic "VRAMEval runtime error" is itself a failure of this validation:
the whole point of the repair is that a candidate's outcome is now a typed
fact rather than an ambiguous error string.

The set spans the range the V19 campaign was prevented from exploring —
an official-scale 323M FCNet, a 10-20M convolutional candidate, and a
medium/large Transformer — because the defect only manifested above a
certain inspection cost, and a validation that used only small models
would have passed before the repair too.

    python scripts/vram_preflight_validation.py --plan          # no GPU
    python scripts/vram_preflight_validation.py --run           # GPU
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUTPUT = Path("/home/klz/Data/SIDEREIS_DATA/runtime_validation/vram_preflight")

#: Candidates chosen for INSPECTION COST, not for science. Each names why
#: it is in the set, so a later reader can tell whether the set still
#: covers the failure mode.
CANDIDATES: tuple[dict, ...] = (
    {
        "label": "fcnet@323M-official",
        "model_type": "fcnet",
        "config": {"segmentation_size": 40000, "batch_size": 1},
        "why": (
            "official TIDMAD baseline scale; C12 measured 323,280,840 params "
            "at 6.04 GiB peak, so it MUST fit the 12 GiB cap and must not be "
            "rejected by an inspection timeout"
        ),
        "expected": "completed",
    },
    {
        "label": "wavenet@~15M",
        "model_type": "wavenet",
        "config": {"segmentation_size": 16000, "batch_size": 4, "residual_channels": 256},
        "why": "the 10M-20M convolutional range the advice now encourages",
        "expected": "completed",
    },
    {
        "label": "transformer@medium",
        "model_type": "transformer",
        "config": {"segmentation_size": 8000, "batch_size": 2},
        "why": (
            "attention cost grows with sequence length, so this is the most "
            "likely candidate to produce a MEASURED capacity result rather "
            "than an inspection timeout"
        ),
        "expected": "completed_or_measured_capacity_failure",
    },
)

VRAM_BUDGET_GB = 12.0


def plan() -> dict:
    from agent.skills.evaluate_vram_skill.probe_budgets import ProbeBudgets

    return {
        "vram_budget_gb": VRAM_BUDGET_GB,
        "budgets": ProbeBudgets().model_dump(),
        "candidates": [dict(c) for c in CANDIDATES],
        "acceptance": {
            "every_candidate_has_an_explicit_disposition": True,
            "no_generic_runtime_error": True,
            "inconclusive_creates_no_downsizing_context": True,
        },
        "output_root": str(DEFAULT_OUTPUT),
    }


def run_candidate(entry: dict, output_root: Path) -> dict:
    """Run one pre-flight and reduce it to a single typed disposition."""
    from agent.skills.evaluate_vram_skill.wrapper import run_skill

    started = time.perf_counter()
    result = run_skill(
        None,  # no sandbox: this harness probes in-process, like the tuner's pre-flight
        model_type=entry["model_type"],
        model_config=dict(entry["config"]),
        train_config={"batch_size": entry["config"].get("batch_size", 1), "device": "cuda"},
        loss_config={"loss_type": "ce"},
        vram_budget_gb=VRAM_BUDGET_GB,
    )
    elapsed = round(time.perf_counter() - started, 2)

    status = result.get("status")
    if status == "inconclusive":
        disposition = "inconclusive"
    elif status == "error":
        disposition = "AMBIGUOUS_RUNTIME_ERROR"  # a validation failure in itself
    elif result.get("feasible") is False:
        disposition = "measured_peak_over_cap"
    else:
        disposition = "completed"

    record = {
        "label": entry["label"],
        "model_type": entry["model_type"],
        "config": entry["config"],
        "expected": entry["expected"],
        "disposition": disposition,
        "elapsed_seconds": elapsed,
        "realized_parameter_count": result.get("num_params"),
        "estimated_gb": result.get("estimated_gb"),
        "limit_gb": result.get("limit_gb"),
        "inference_batch": result.get("inference_batch"),
        "timeout_record": result.get("timeout_record"),
        "agent_facing_message": (result.get("message") or "")[:400],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / f"{entry['label']}.json").write_text(json.dumps(record, indent=2))
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only", default=None, help="single candidate label")
    args = parser.parse_args(argv)

    if not args.run:
        print(json.dumps(plan(), indent=2))
        return 0

    records = []
    for entry in CANDIDATES:
        if args.only and entry["label"] != args.only:
            continue
        print(f"\n=== {entry['label']} ===")
        record = run_candidate(entry, args.output_root)
        records.append(record)
        print(
            f"  disposition={record['disposition']} "
            f"params={record['realized_parameter_count']} "
            f"est={record['estimated_gb']} GB elapsed={record['elapsed_seconds']}s"
        )

    ambiguous = [r for r in records if r["disposition"] == "AMBIGUOUS_RUNTIME_ERROR"]
    print(f"\n{len(records)} candidate(s); {len(ambiguous)} ambiguous")
    if ambiguous:
        print("VALIDATION FAILED: a candidate produced a generic runtime error.")
        for r in ambiguous:
            print(f"  {r['label']}: {r['agent_facing_message'][:160]}")
    return 1 if ambiguous else 0


if __name__ == "__main__":
    raise SystemExit(main())
