#!/usr/bin/env python3
"""Build and validate a diagnostic_pre_v17 model-run summary."""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
from datetime import UTC, datetime
from typing import Any

from execute_tools.data_paths import SIDERIUS_DATA_DIR


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _scalar(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "-inf" if value < 0 else "inf"
    return value


def _round_summary(record: dict[str, Any]) -> dict[str, Any]:
    memory = record.get("memory") or {}
    failure_reason = record.get("failure_reason")
    return {
        "round_number": memory.get("round_index"),
        "exp_id": record.get("exp_id"),
        "status": record.get("status"),
        "scalar_score": _scalar(record.get("denoising_score")),
        "file_vector": [_scalar(value) for value in (record.get("file_vector") or [])],
        "healthgate_result": "failed" if failure_reason else "passed",
        "failure_reason": failure_reason,
        "gate_action": record.get("gate_action"),
        "counted_toward_completed_rounds": record.get("status")
        in {"success", "failed_mode_collapse"},
        "configuration": record.get("params"),
        "planner_hypothesis": memory.get("hypothesis"),
        "planner_memory_update": memory.get("memory_update"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--run_name", default="diagnostic_baseline_pre_v17")
    parser.add_argument(
        "--infrastructure-blocker",
        help="Record an unrecoverable infrastructure blocker in an incomplete summary.",
    )
    args = parser.parse_args()

    model_root = os.path.join(SIDERIUS_DATA_DIR, args.model)
    baseline_dir = os.path.join(model_root, f"{args.run_name}_baseline_trial")
    run_dir = os.path.join(model_root, args.run_name)
    agent_dir = os.path.join(run_dir, "agent")
    baseline_matches = sorted(glob.glob(os.path.join(baseline_dir, "summary_*.json")))
    output_path = os.path.join(agent_dir, f"run_output_{args.run_name}_agent.json")
    history_path = os.path.join(agent_dir, f"summary_{args.run_name}_agent.json")
    if len(baseline_matches) != 1:
        raise SystemExit(f"Expected one baseline summary, found {baseline_matches}")

    baseline_history = _load(baseline_matches[0])
    if os.path.exists(output_path):
        tuner_output = _load(output_path)
        records = tuner_output.get("all_records") or []
    elif args.infrastructure_blocker and os.path.exists(history_path):
        records = _load(history_path)
        tuner_output = {
            "all_records": records,
            "completed_rounds": len(
                {
                    (record.get("memory") or {}).get("round_index")
                    for record in records
                    if record.get("status") in {"success", "failed_mode_collapse"}
                    and (record.get("memory") or {}).get("round_index") is not None
                }
            ),
            "termination_reason": "infrastructure_blocked",
        }
    else:
        raise SystemExit(f"Missing tuner output: {output_path}")
    baseline = baseline_history[0]
    completed_records = [
        record
        for record in records
        if record.get("status") in {"success", "failed_mode_collapse"}
        and (record.get("memory") or {}).get("round_index") is not None
    ]
    infrastructure_records = [
        record
        for record in records
        if (record.get("memory") or {}).get("round_index") is not None
        and record not in completed_records
    ]
    rounds = sorted(
        (_round_summary(record) for record in completed_records),
        key=lambda item: item["round_number"],
    )

    valid = [
        record
        for record in completed_records
        if record.get("status") == "success"
        and isinstance(record.get("denoising_score"), (int, float))
        and math.isfinite(record["denoising_score"])
    ]
    best = max(valid, key=lambda record: record["denoising_score"]) if valid else None
    baseline_exp_id = str(baseline.get("exp_id") or "")
    baseline_h5 = sorted(
        glob.glob(
            os.path.join(baseline_dir, "**", f"*{baseline_exp_id}*.h5"),
            recursive=True,
        )
    )
    # OOM-recovery rounds (scripts/finalize_recovered_diagnostic_round.py)
    # commit a record under ``{source_exp_id}_recovered`` while the .h5
    # artifacts on disk keep the SOURCE exp_id. Remap the glob key so the
    # recovered round finds its files, and exclude the source exp_id from
    # the partial-attempt bucket so the same artifacts are not counted
    # twice (once as completed tuning, once as a partial attempt).
    recovery = tuner_output.get("recovery") or {}
    recovered_exp_id = recovery.get("recovered_exp_id")
    recovery_source_exp_id = recovery.get("source_exp_id")
    tuning_h5_by_round = {}
    for record in completed_records:
        output_exp_id = record.get("exp_id")
        if output_exp_id == recovered_exp_id and recovery_source_exp_id:
            output_exp_id = recovery_source_exp_id
        tuning_h5_by_round[str((record.get("memory") or {}).get("round_index"))] = sorted(
            glob.glob(
                os.path.join(agent_dir, "**", f"*{output_exp_id}*.h5"),
                recursive=True,
            )
        )
    partial_attempt_h5 = {
        str(record.get("exp_id")): sorted(
            glob.glob(
                os.path.join(agent_dir, "**", f"*{record.get('exp_id')}*.h5"),
                recursive=True,
            )
        )
        for record in infrastructure_records
        if record.get("exp_id") != recovery_source_exp_id
    }
    completed_round_numbers = [item["round_number"] for item in rounds]
    complete = (
        tuner_output.get("completed_rounds") == 10
        and len(completed_records) == 10
        and completed_round_numbers == list(range(1, 11))
        and tuner_output.get("termination_reason") == "completed"
    )
    anomalies = []
    for record in completed_records:
        if record.get("status") == "success" and record.get("denoising_score") is None:
            anomalies.append(
                {
                    "exp_id": record.get("exp_id"),
                    "round_number": (record.get("memory") or {}).get("round_index"),
                    "pattern": "success_status_with_null_score_and_no_healthgate_failure",
                }
            )
        reason = str(record.get("failure_reason") or "")
        if "Class-127 collapse artifact" in reason:
            anomalies.append(
                {
                    "exp_id": record.get("exp_id"),
                    "round_number": (record.get("memory") or {}).get("round_index"),
                    "pattern": "class_127_collapse_phantom_score_prevented",
                }
            )
    summary = {
        "run_name": args.run_name,
        "run_class": "diagnostic_pre_v17",
        "model": args.model,
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline": {
            "status": baseline.get("status"),
            "scalar_score": _scalar(baseline.get("denoising_score")),
            "file_vector": [_scalar(value) for value in (baseline.get("file_vector") or [])],
            "healthgate_result": ("failed" if baseline.get("failure_reason") else "passed"),
            "failure_reason": baseline.get("failure_reason"),
            "gate_action": baseline.get("gate_action"),
        },
        "tuning": {
            "reported_completed_rounds": tuner_output.get("completed_rounds"),
            "termination_reason": tuner_output.get("termination_reason"),
            "completed_record_count": len(completed_records),
            "infrastructure_failure_record_count": len(infrastructure_records),
            "record_completeness_and_continuation_correct": complete,
            "rounds": rounds,
            "infrastructure_records": infrastructure_records,
            "best_valid_round": _round_summary(best) if best else None,
            "best_valid_result": "present" if best else "no valid round",
        },
        "infrastructure_blocker": args.infrastructure_blocker,
        "recovery": recovery or None,
        "observed_patterns": anomalies,
        "retained_outputs": {
            "baseline_hdf5_count": len(baseline_h5),
            "baseline_hdf5_paths": baseline_h5,
            "completed_tuning_hdf5_count": sum(len(paths) for paths in tuning_h5_by_round.values()),
            "completed_tuning_hdf5_paths_by_round": tuning_h5_by_round,
            "partial_attempt_hdf5_count": sum(len(paths) for paths in partial_attempt_h5.values()),
            "partial_attempt_hdf5_paths": partial_attempt_h5,
        },
        "source_paths": {
            "baseline_summary": baseline_matches[0],
            "tuner_output": output_path,
            "run_metadata": os.path.join(run_dir, "run_metadata.json"),
        },
        "safe_to_launch_next_model": complete and not args.infrastructure_blocker,
    }
    summary_path = os.path.join(run_dir, "diagnostic_summary.json")
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, allow_nan=False)
    print(summary_path)
    if not complete and not args.infrastructure_blocker:
        raise SystemExit("Diagnostic run is incomplete; PUNet must not launch")


if __name__ == "__main__":
    main()
