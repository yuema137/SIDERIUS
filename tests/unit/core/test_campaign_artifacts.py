"""Focused tests for the V17 pre-gate Phase 1 reuse contract."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# Step 02c C1 / §9 row D1 — the per-file completeness POLICY MATRIX
#
# ``validate_experiment_completeness`` runs a per-file completeness check
# only when ``files_requested`` is EXACTLY the shipped default health-peek
# selection, compared as an ordered list (``campaign_artifacts.py:57``).
# Every other list — including a REORDERED copy of the same three files —
# takes the else-branch and is silently NOT enforced.
#
# Before PR 02c this whole branch had ZERO coverage: every test above
# builds ``aggregation: {"files_requested": []}``. PR 02c replaces the
# literal trigger with the DECLARED health-peek semantic, which is an
# authority change; the matrix below is the pre-change oracle proving it
# is not also a POLICY change.
#
# The sharpest regression this guards is normalization. Comparing with
# ``set()`` or ``sorted()`` would make the reordered case newly ENFORCE
# where it skips today — more enforcing, not merely differently sourced.
# Any genuine policy improvement is Step-08 work, not 02c's.
# ---------------------------------------------------------------------------

# The shipped default health-peek selection, spelled as the record's
# producer spells it (``health_checks/evaluation.py:202`` copies
# ``peek_file_indices`` verbatim from the effective config).
_DEFAULT_HEALTH_PEEK = [3, 10, 17]

_PER_FILE_ERROR_MARKER = "missing per-file entries"


def _peek_gate_result(
    gate_name: str,
    *,
    files_requested: list[int] | None,
    per_file: dict | None,
    include_aggregation: bool = True,
) -> dict:
    """A gate observation carrying an explicit ``files_requested`` list.

    ``_gate_result`` above always requests ``[]``; this variant is what
    actually enters the per-file branch.
    """
    result = _gate_result(gate_name)
    metrics = {"aggregate_statistics": {"count": 3}}
    if per_file is not None:
        metrics["per_file"] = per_file
    result["metrics"] = metrics
    if include_aggregation:
        aggregation: dict = {}
        if files_requested is not None:
            aggregation["files_requested"] = files_requested
        result["aggregation"] = aggregation
    else:
        result.pop("aggregation", None)
    return result


def _peek_record(**kwargs) -> dict:
    """Minimal complete record whose single gate carries the peek payload."""
    gate_id = GATE_IDS[0]
    return {
        "denoising_score": -1.0,
        "file_vector": [1.0] * 20,
        "checkpoint_path": "/checkpoint.pth",
        "params": PARAMS,
        "health_gate_results": [_peek_gate_result(gate_id, **kwargs)],
    }


def _errors(record: dict) -> list[str]:
    return validate_experiment_completeness(record, configured_gate_ids=[GATE_IDS[0]])


def _complete_per_file(indices: list[int]) -> dict:
    return {str(index): {"execution_status": "passed"} for index in indices}


class TestDefaultHealthPeekCompletenessIsEnforced:
    """D1-a / D1-b — the exact default selection DOES trigger the check."""

    def test_complete_per_file_produces_no_error(self):
        record = _peek_record(
            files_requested=list(_DEFAULT_HEALTH_PEEK),
            per_file=_complete_per_file(_DEFAULT_HEALTH_PEEK),
        )
        assert _errors(record) == []

    def test_missing_per_file_entry_is_reported_exactly(self):
        record = _peek_record(
            files_requested=list(_DEFAULT_HEALTH_PEEK),
            per_file=_complete_per_file([3, 17]),
        )
        assert _errors(record) == [f"gate {GATE_IDS[0]}: missing per-file entries ['10']"]

    def test_per_file_lookup_is_str_keyed(self):
        """``str(index) not in per_file`` — an INT-keyed ``per_file`` reads
        as entirely absent.

        This pins the producer/consumer key-type contract. If the lookup
        were changed to accept int keys, or the producer started emitting
        int keys, this record's disposition would silently flip.
        """
        record = _peek_record(
            files_requested=list(_DEFAULT_HEALTH_PEEK),
            per_file={index: {"execution_status": "passed"} for index in _DEFAULT_HEALTH_PEEK},
        )
        assert _errors(record) == [
            f"gate {GATE_IDS[0]}: missing per-file entries ['3', '10', '17']"
        ]

    def test_absent_metrics_reports_both_the_metrics_and_per_file_errors(self):
        """An executed gate with no ``metrics`` at all: today BOTH errors
        fire. Pinned as-is — collapsing them would lose the per-file
        signal."""
        record = _peek_record(files_requested=list(_DEFAULT_HEALTH_PEEK), per_file=None)
        record["health_gate_results"][0]["metrics"] = {}
        assert _errors(record) == [
            f"gate {GATE_IDS[0]}: executed gate has no metrics",
            f"gate {GATE_IDS[0]}: missing per-file entries ['3', '10', '17']",
        ]

    def test_incomplete_per_file_forces_retrain(self, tmp_path):
        """The branch is POLICY, not presentation: an enforced failure
        reaches ``decide_phase1_reuse`` and rejects reuse."""
        outputs = [str(tmp_path / "output.h5")]
        record = _complete_record(tmp_path, outputs)
        record["health_gate_results"] = [
            _peek_gate_result(
                gate_id,
                files_requested=list(_DEFAULT_HEALTH_PEEK),
                per_file=_complete_per_file([3, 17]),
            )
            for gate_id in GATE_IDS
        ]
        decision = _decision(record, outputs)
        assert decision.action == "train"
        assert not decision.validation.valid
        assert any(_PER_FILE_ERROR_MARKER in error for error in decision.validation.errors)


class TestNonDefaultRequestedListIsNeverEnforced:
    """D1-c..D1-f — everything that is not list-equal takes the silent
    else-branch.

    Each case asserts the per-file error is **ABSENT** with a deliberately
    EMPTY ``per_file``. Asserting only ``valid`` would pass even if the
    branch started firing, because a record can be invalid for unrelated
    reasons.
    """

    @pytest.mark.parametrize(
        ("case", "files_requested", "include_aggregation"),
        [
            # The anti-normalization guard: same members, different order.
            # ``set()``/``sorted()`` comparison would newly ENFORCE this.
            ("reordered_default", [10, 3, 17], True),
            ("custom_operator_list", [4, 7, 9], True),
            ("out_of_range_member", [3, 10, 99], True),
            ("all_files_population", list(range(20)), True),
            ("explicitly_empty", [], True),
            ("key_absent", None, True),
            ("aggregation_absent", None, False),
        ],
    )
    def test_no_per_file_enforcement(self, case, files_requested, include_aggregation):
        record = _peek_record(
            files_requested=files_requested,
            per_file={},
            include_aggregation=include_aggregation,
        )
        errors = _errors(record)
        assert not any(_PER_FILE_ERROR_MARKER in error for error in errors), (
            f"{case}: per-file completeness was enforced on a list that is "
            f"not equal to the default health-peek selection — this is a "
            f"POLICY change, not an authority change"
        )
