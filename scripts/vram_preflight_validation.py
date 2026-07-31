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
import hashlib
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
#:
#: Every config here was checked against the model's actual schema bounds
#: before being written down. The first version of this file guessed
#: `residual_channels=256` for WaveNet, whose schema caps it at 128; the
#: harness then reported the rejection as "completed", which is why
#: schema validation now happens before any worker is launched.
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
        "expected_parameters": 323_281_352,
        "expected": "COMPLETED_MEASUREMENT",
    },
    {
        "label": "wavenet@17M",
        "model_type": "wavenet",
        # 17,110,528 params — verified against the schema bounds
        # (residual<=128, gate<=256, skip<=128, kernel<=32, blocks<=20).
        "config": {
            "segmentation_size": 16000,
            "batch_size": 4,
            "residual_channels": 128,
            "gate_channels": 256,
            "skip_channels": 128,
            "kernel_size": 24,
            "num_blocks": 20,
        },
        "why": "the 10M-20M convolutional range the advice now encourages",
        "expected_parameters": 17_110_528,
        "expected": "COMPLETED_MEASUREMENT",
    },
    {
        "label": "transformer@medium",
        "model_type": "transformer",
        # This is the candidate that OOM-killed the host on 2026-07-31 at
        # T=8000. It is kept deliberately: the repair's central claim is
        # that it now yields a BOUNDED, typed outcome instead of taking
        # the machine down with it.
        "config": {
            "segmentation_size": 8000,
            "batch_size": 2,
            "embedding_dim": 128,
            "nhead": 8,
            "num_layers": 4,
            "dim_feedforward": 512,
        },
        "why": (
            "attention cost grows with sequence length; this exact shape "
            "previously grew to 60.5 GB host RSS and killed the parent, so "
            "it is the direct regression case for host-memory isolation"
        ),
        "expected": "any bounded typed outcome (must NOT kill the parent)",
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


def validate_config(entry: dict) -> tuple[dict | None, str | None]:
    """Schema-validate WITHOUT constructing the model.

    Returns (normalized_config, error). The parent must never instantiate
    a candidate: once the model is resident here, a worker memory limit is
    already too late.
    """
    from ml_models.models_format_sandbox import get_config_class

    config_class = get_config_class(entry["model_type"])
    if config_class is None:
        return None, f"no config class registered for {entry['model_type']!r}"
    try:
        validated = config_class(**dict(entry["config"]))
    except Exception as exc:
        return None, str(exc)[:400]
    return validated.model_dump(mode="json"), None


def config_identity(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def run_candidate(entry: dict, output_root: Path) -> dict:
    """Schema-validate, then probe in ONE isolated, memory-bounded worker."""
    from agent.skills.evaluate_vram_skill.isolated_probe import (
        IsolatedProbeSpec,
        default_worker_memory_limit_bytes,
        run_isolated_preflight,
    )

    output_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    normalized, schema_error = validate_config(entry)
    # Checked on `normalized` rather than `schema_error` so the type
    # narrows: the two are correlated by construction but not by the
    # signature, and a strict checker cannot know that.
    if normalized is None:
        record = {
            "label": entry["label"],
            "model_type": entry["model_type"],
            "config": entry["config"],
            "expected": entry["expected"],
            "outcome": "SCHEMA_REJECTED",
            "schema_message": schema_error or "configuration could not be validated",
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "note": "rejected before any worker was launched",
        }
        (output_root / f"{entry['label']}.json").write_text(json.dumps(record, indent=2))
        return record

    limit = default_worker_memory_limit_bytes()
    result = run_isolated_preflight(
        IsolatedProbeSpec(
            label=entry["label"],
            model_type=entry["model_type"],
            model_config_payload=normalized,
            train_config={"batch_size": normalized.get("batch_size", 1), "device": "cuda"},
            loss_config={"loss_type": "ce"},
            vram_budget_gb=VRAM_BUDGET_GB,
            result_path=str(output_root / "workers" / f"{entry['label']}.json"),
            worker_memory_limit_bytes=limit,
        ),
        deadline_seconds=600.0,
    )

    record = {
        **result.model_dump(mode="json"),
        "model_type": entry["model_type"],
        "normalized_config": normalized,
        "config_identity": config_identity(normalized),
        "expected": entry["expected"],
        "expected_parameters": entry.get("expected_parameters"),
        "agent_facing_message": result.agent_facing_message(),
        "may_recommend_vram_downsizing": result.may_recommend_vram_downsizing,
        "may_recommend_host_memory_reduction": result.may_recommend_host_memory_reduction,
        "has_capacity_authority": result.has_capacity_authority,
    }
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
        host = record.get("host_memory") or {}
        print(
            f"  outcome={record['outcome']} "
            f"params={record.get('realized_parameter_count')} "
            f"est={record.get('estimated_gb')} GB "
            f"peak_host_rss={host.get('peak_worker_rss_gib')} GiB "
            f"elapsed={record.get('elapsed_seconds')}s"
        )

    # A schema rejection of a REQUIRED candidate fails the validation: the
    # set is chosen deliberately, so skipping one silently would leave the
    # failure mode untested.
    bad = [
        r for r in records if r["outcome"] in ("PROBE_INFRASTRUCTURE_FAILURE", "SCHEMA_REJECTED")
    ]
    orphaned = [r for r in records if r.get("orphans_remaining")]
    print(f"\n{len(records)} candidate(s); {len(bad)} unusable; {len(orphaned)} left orphans")
    for r in records:
        print(f"  {r['label']:24} {r['outcome']}")
    if bad or orphaned:
        print("VALIDATION FAILED.")
        for r in bad:
            print(f"  {r['label']}: {r.get('schema_message') or r.get('detail', '')[:160]}")
    return 1 if (bad or orphaned) else 0


if __name__ == "__main__":
    raise SystemExit(main())
