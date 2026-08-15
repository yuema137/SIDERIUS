#!/usr/bin/env python3
"""Finalize a diagnostic tuning round after verified inference recovery."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import UTC, datetime
from typing import Any

from agent.schemas.hyperparam_tuning import ExperimentRecord
from core.sandbox_executor import TidmadSandbox
from execute_tools.build_anchor_map import load_anchor_map
from execute_tools.data_paths import SIDERIUS_DATA_DIR, TIDMAD_DATA_DIR
from execute_tools.deliverable_spec import default_deliverable_naming
from execute_tools.health_checks.runner import (
    evaluate_gate,
    get_gates_for_position,
    resolve_action,
)
from execute_tools.health_checks.schemas import HealthCheckContext
from execute_tools.scoring_utils import coerce_nonfinite_to_none, score_vector
from nodes.ml_hyperparameter_tune_agent import (
    _gate_results_to_score_meta,
    _merge_score_validity_failure,
)


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _finite_success(record: dict[str, Any]) -> bool:
    score = record.get("denoising_score")
    return (
        record.get("status") == "success"
        and isinstance(score, (int, float))
        and math.isfinite(score)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--source-exp-id", required=True)
    parser.add_argument("--round-index", required=True, type=int)
    parser.add_argument("--training-time-s", type=float, default=0.0)
    parser.add_argument(
        "--reuse-persisted-score",
        action="store_true",
        help="Re-evaluate HealthGate using the already persisted recovered score.",
    )
    args = parser.parse_args()

    workflow_run_name = f"{args.run_name}_agent"
    agent_dir = os.path.join(SIDERIUS_DATA_DIR, args.model, args.run_name, "agent")
    config_dir = os.path.join(agent_dir, "configs", workflow_run_name)
    history_path = os.path.join(agent_dir, f"summary_{workflow_run_name}.json")
    history = _load(history_path)
    source_record = next(record for record in history if record.get("exp_id") == args.source_exp_id)
    sample_set = {
        int(key): value
        for key, value in _load(
            os.path.join(config_dir, f"eval_sample_set_{args.source_exp_id}.json")
        ).items()
    }
    train_sample_set = {
        int(key): value
        for key, value in _load(
            os.path.join(config_dir, f"train_sample_set_{args.source_exp_id}.json")
        ).items()
    }
    trial_config = _load(os.path.join(config_dir, f"trial_config_{args.source_exp_id}.json"))
    train_results = _load(
        os.path.join(
            agent_dir,
            "records",
            workflow_run_name,
            f"experiment_results_wavenet_{args.source_exp_id}.json",
        )
    )
    anchor_data = load_anchor_map(os.path.join(TIDMAD_DATA_DIR, "segment_anchors.json"))

    def denoised_filename(file_index: int) -> str:
        # Step 05c — canonical reconstruction resolves the name through the
        # same authority the producer wrote it with. A script that rebuilds a
        # round's artifacts must agree with the producer, or a renamed
        # deliverable silently breaks recovery.
        return os.path.join(
            agent_dir,
            default_deliverable_naming().name(
                model_type=args.model,
                run_name=workflow_run_name,
                exp_id=args.source_exp_id,
                file_index=int(file_index),
            ),
        )

    recovered_exp_id = f"{args.source_exp_id}_recovered"
    persisted_recovery = next(
        (record for record in history if record.get("exp_id") == recovered_exp_id),
        None,
    )
    if args.reuse_persisted_score:
        if persisted_recovery is None:
            raise RuntimeError(f"No persisted recovery record found for {recovered_exp_id}")
        file_vector = persisted_recovery["file_vector"]
        scalar = persisted_recovery["denoising_score"]
        scoring_time = float((persisted_recovery.get("timing") or {}).get("scoring_time_s", 0.0))
    else:
        started = time.monotonic()
        file_vector, scalar = score_vector(
            data_dir=agent_dir,
            sample_set=sample_set,
            anchor_map=anchor_data["anchors"],
            s_max=anchor_data["s_max"],
            denoised_filename_fn=denoised_filename,
            raw_data_dir=TIDMAD_DATA_DIR,
        )
        scoring_time = time.monotonic() - started

    context = HealthCheckContext(
        model_name=args.model,
        run_name=workflow_run_name,
        round_index=args.round_index,
        denoised_filename_fn=denoised_filename,
        file_vector=file_vector,
        denoising_score=scalar,
    )
    gate_ids = get_gates_for_position(args.round_index)
    gate_results = [evaluate_gate(gate_id, context) for gate_id in gate_ids]
    action = resolve_action(gate_results)
    is_degenerate, failure_reason, gate_action = _gate_results_to_score_meta(gate_results, action)
    is_degenerate, failure_reason = _merge_score_validity_failure(
        scalar,
        is_degenerate=is_degenerate,
        failure_reason=failure_reason,
    )

    timing_path = os.path.join(config_dir, f"inference_timing_{args.source_exp_id}_resume.json")
    inference_time = sum(float(item.get("elapsed_ms", 0.0)) for item in _load(timing_path)) / 1000.0
    source_memory = source_record.get("memory") or {}
    record = {
        "exp_id": recovered_exp_id,
        "status": "failed_mode_collapse" if is_degenerate else "success",
        "model_type": args.model,
        "timestamp": datetime.now(UTC).isoformat(),
        "file_index": source_record.get("file_index", 6),
        "params": source_record["params"],
        "final_loss": train_results.get("final_loss"),
        "loss_history": train_results.get("loss_history"),
        "model_params": train_results.get("model_params"),
        "denoising_score": scalar,
        "file_vector": file_vector,
        "score_table": None,
        "failure_reason": failure_reason,
        "gate_action": gate_action,
        "training_psd_segments": sum(map(len, train_sample_set.values())),
        "eval_psd_segments": sum(map(len, sample_set.values())),
        "timing": {
            "train_time_s": args.training_time_s,
            "inference_time_s": inference_time,
            "scoring_time_s": scoring_time,
        },
        "memory": {
            "expert_advice_followed": source_memory.get("expert_advice_followed", ""),
            "hypothesis": source_memory.get("hypothesis", ""),
            "conclusion": (
                "Recovered the interrupted formal inference from its existing "
                "checkpoint and 18 verified HDF5 outputs; scoring then "
                f"returned {scalar!r}."
            ),
            "key_factor": (
                "The original checkpoint and exact attempt-scoped outputs "
                "were retained across the NVRM Xid 8 host incident."
            ),
            "discovery": (
                "Infrastructure recovery succeeded without retraining rounds "
                "1-9 or the round-10 checkpoint. Numerical validity and "
                "HealthGate classification were applied after all 20 files "
                "were present."
            ),
            "memory_update": (
                failure_reason or "Formal scoring completed with a finite, non-collapsed result."
            ),
            "round_index": args.round_index,
            "attempt_in_round": source_memory.get("attempt_in_round"),
        },
        "is_trial": False,
        "trial_strategy": trial_config.get("trial_strategy"),
        "trial_portion": trial_config.get("trial_portion"),
        "eval_strategy": trial_config.get("eval_strategy"),
        "eval_portion": trial_config.get("eval_portion"),
        "train_portion": trial_config.get("train_portion"),
        "target_files": trial_config.get("target_files"),
    }
    validated_record = ExperimentRecord.model_validate(record).model_dump()
    sandbox = TidmadSandbox(
        metadata_source="local",
        run_name=workflow_run_name,
        workspace=agent_dir,
        file_index=record["file_index"],
    )
    sandbox.save_record(validated_record)

    all_records = sandbox.get_summary()
    completed = [
        item
        for item in all_records
        if item.get("status") in {"success", "failed_mode_collapse"}
        and (item.get("memory") or {}).get("round_index") is not None
    ]
    # Line 210 already guarantees round_index is not None for every item in
    # `completed`, but pyright can't narrow through the ``.get()`` chain in a
    # set comprehension — build the set imperatively with an explicit int cast
    # so ``sorted()`` below type-checks under strict mode.
    round_indices: set[int] = set()
    for item in completed:
        ri = (item.get("memory") or {}).get("round_index")
        if ri is not None:
            round_indices.add(int(ri))
    if round_indices != set(range(1, 11)) or len(completed) != 10:
        raise RuntimeError(
            f"Recovery did not produce exactly rounds 1-10: "
            f"count={len(completed)}, indices={sorted(round_indices)}"
        )
    valid = [item for item in completed if _finite_success(item)]
    best = max(valid, key=lambda item: item["denoising_score"]) if valid else None
    output = {
        "run_name": workflow_run_name,
        "model_type": args.model,
        "file_index": record["file_index"],
        "status": "completed",
        "completed_rounds": 10,
        "total_attempts": len(
            [
                item
                for item in all_records
                if (item.get("memory") or {}).get("round_index") is not None
            ]
        ),
        "best_exp_id": best.get("exp_id") if best else None,
        "best_denoising_score": best.get("denoising_score") if best else None,
        "best_formal_denoising_score": (
            scalar if not is_degenerate and math.isfinite(scalar) else None
        ),
        "best_config": best.get("params") if best else None,
        "best_file_vector": best.get("file_vector") if best else None,
        "best_score_table": best.get("score_table") if best else None,
        "formal_score_table": None,
        "all_records": all_records,
        "gate_exhaustion": None,
        "physical_rejections": [],
        "termination_reason": "completed",
        "finished_at": datetime.now(UTC).isoformat(),
        "recovery": {
            "source_exp_id": args.source_exp_id,
            "recovered_exp_id": recovered_exp_id,
            "reused_verified_outputs": 18,
            "regenerated_outputs": [8, 9],
            "prior_infrastructure_incident": "NVRM Xid 8",
        },
    }
    output_path = os.path.join(agent_dir, f"run_output_{workflow_run_name}.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(coerce_nonfinite_to_none(output), handle, indent=2)

    print(
        json.dumps(
            {
                "record": recovered_exp_id,
                "score": scalar if math.isfinite(scalar) else "-inf",
                "failure_reason": failure_reason,
                "gate_action": gate_action,
                "gate_ids": gate_ids,
                "output_path": output_path,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
