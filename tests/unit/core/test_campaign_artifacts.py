"""Focused tests for the V17 pre-gate Phase 1 reuse contract."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from core.campaign_artifacts import (
    decide_phase1_reuse,
    validate_experiment_completeness,
)

GATE_IDS = ["output_diversity_blocking", "pearson_dispersion_recording"]
PARAMS = {
    "model_config": {"channels": 8},
    "train_config": {"epochs": 1, "lr": 0.0005},
    "loss_config": {"loss_type": "focal"},
}
TRAINING_FILES = [f"/data/abra_training_{index:04d}.h5" for index in range(20)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gate_result(gate_name: str) -> dict:
    return {
        "gate_name": gate_name,
        "execution_status": "passed",
        "check_passed": True,
        "would_invalidate_under_production_policy": False,
        "resolved_action": "continue",
        "failure_reason": None,
        "threshold": None,
        "aggregation": {"files_requested": []},
        "metrics": {"aggregate_statistics": {"count": 3}},
    }


def _complete_record(tmp_path: Path, outputs: list[str]) -> dict:
    checkpoint = tmp_path / "checkpoint.pth"
    checkpoint.write_bytes(b"valid checkpoint identity")
    for output in outputs:
        Path(output).write_bytes(b"hdf5-placeholder")
    return {
        "campaign_run_name": "v17_pregate_baseline",
        "model_type": "wavenet",
        "status": "success",
        "params": copy.deepcopy(PARAMS),
        "training_files": TRAINING_FILES,
        "checkpoint_path": str(checkpoint),
        "checkpoint_sha256": _sha256(checkpoint),
        "denoising_score": -2.5,
        "file_vector": [1.0] * 20,
        "health_gate_results": [_gate_result(gate_id) for gate_id in GATE_IDS],
    }


def _decision(record: dict | None, outputs: list[str]):
    return decide_phase1_reuse(
        record,
        campaign_name="v17_pregate_baseline",
        model_type="wavenet",
        expected_params=PARAMS,
        expected_training_files=TRAINING_FILES,
        configured_gate_ids=GATE_IDS,
        expected_output_paths=outputs,
    )


def test_fresh_campaign_trains_phase1(tmp_path):
    outputs = [str(tmp_path / "output.h5")]
    assert _decision(None, outputs).action == "train"


def test_complete_matching_same_campaign_phase1_is_reused(tmp_path):
    outputs = [str(tmp_path / "output.h5")]
    assert _decision(_complete_record(tmp_path, outputs), outputs).action == "reuse"


def test_historical_baseline_is_not_reused(tmp_path):
    outputs = [str(tmp_path / "output.h5")]
    record = _complete_record(tmp_path, outputs)
    record["campaign_run_name"] = "diagnostic_baseline_pre_v17"
    decision = _decision(record, outputs)
    assert decision.action == "train"
    assert "campaign_run_name mismatch" in decision.validation.errors


def test_mismatched_or_incomplete_phase1_is_rejected(tmp_path):
    outputs = [str(tmp_path / "output.h5")]
    record = _complete_record(tmp_path, outputs)
    record["params"]["train_config"] = {"epochs": 99}
    record["health_gate_results"] = []
    decision = _decision(record, outputs)
    assert decision.action == "train"
    assert "effective train_config mismatch" in decision.validation.errors
    assert any("missing HealthGate results" in error for error in decision.validation.errors)


def test_reuse_decision_is_side_effect_free(tmp_path):
    outputs = [str(tmp_path / "output.h5")]
    record = _complete_record(tmp_path, outputs)
    checkpoint = Path(record["checkpoint_path"])
    before = checkpoint.stat().st_mtime_ns
    assert _decision(record, outputs).action == "reuse"
    assert checkpoint.stat().st_mtime_ns == before


def test_missing_inference_is_regenerated_without_retraining(tmp_path):
    outputs = [str(tmp_path / "missing_output.h5")]
    record = _complete_record(tmp_path, [])
    decision = _decision(record, outputs)
    assert decision.action == "regenerate_inference"
    assert decision.validation.valid
    assert decision.validation.missing_inference_outputs == outputs


def test_completeness_rejects_non_continue_observe_action():
    record = {
        "denoising_score": -1.0,
        "file_vector": [1.0],
        "checkpoint_path": "/checkpoint.pth",
        "params": PARAMS,
        "health_gate_results": [
            {**_gate_result(GATE_IDS[0]), "resolved_action": "invalidate_round"}
        ],
    }
    errors = validate_experiment_completeness(record, configured_gate_ids=[GATE_IDS[0]])
    assert errors == [f"gate {GATE_IDS[0]}: observe action is not continue"]


# ---------------------------------------------------------------------------
# DS6d — functional campaign identity: data_scope joins campaign_run_name
# ---------------------------------------------------------------------------

_FULL_SCOPE = list(range(20))
_PARTIAL_SCOPE = [4, 5, 6, 7, 8, 9]


def _scoped_decision(record, outputs, expected_scope):
    return decide_phase1_reuse(
        record,
        campaign_name="v17_pregate_baseline",
        model_type="wavenet",
        expected_params=PARAMS,
        expected_training_files=TRAINING_FILES,
        configured_gate_ids=GATE_IDS,
        expected_output_paths=outputs,
        expected_resolved_data_scope=expected_scope,
    )


def test_legacy_unstamped_record_matches_full_scope(tmp_path):
    outputs = [str(tmp_path / f"out_{i:04d}.h5") for i in range(2)]
    record = _complete_record(tmp_path, outputs)
    assert _scoped_decision(record, outputs, _FULL_SCOPE).action == "reuse"


def test_legacy_unstamped_record_rejected_under_partial_scope(tmp_path):
    outputs = [str(tmp_path / f"out_{i:04d}.h5") for i in range(2)]
    record = _complete_record(tmp_path, outputs)
    decision = _scoped_decision(record, outputs, _PARTIAL_SCOPE)
    assert decision.action == "train"
    assert "data_scope mismatch" in decision.validation.errors


def test_stamped_matching_scope_is_reused(tmp_path):
    outputs = [str(tmp_path / f"out_{i:04d}.h5") for i in range(2)]
    record = _complete_record(tmp_path, outputs)
    record["resolved_data_scope"] = _PARTIAL_SCOPE
    assert _scoped_decision(record, outputs, _PARTIAL_SCOPE).action == "reuse"


def test_stamped_mismatched_scope_is_rejected(tmp_path):
    outputs = [str(tmp_path / f"out_{i:04d}.h5") for i in range(2)]
    record = _complete_record(tmp_path, outputs)
    record["resolved_data_scope"] = _PARTIAL_SCOPE
    decision = _scoped_decision(record, outputs, _FULL_SCOPE)
    assert decision.action == "train"
    assert "data_scope mismatch" in decision.validation.errors


def test_none_expected_scope_skips_check(tmp_path):
    """Back-compat: legacy callers that don't pass the scope get the
    pre-DS6d behavior."""
    outputs = [str(tmp_path / f"out_{i:04d}.h5") for i in range(2)]
    record = _complete_record(tmp_path, outputs)
    record["resolved_data_scope"] = _PARTIAL_SCOPE
    assert _decision(record, outputs).action == "reuse"
