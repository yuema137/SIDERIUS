"""Generic evaluation-metric boundary regressions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from execute_tools.evaluation_metric import (
    EvaluationMetric,
    MetricResult,
    MetricSpec,
    NotScoreableResult,
    PersistedScoreabilityContract,
    PresenceScoreabilityContract,
    ScoreabilityFailure,
    ScoreabilityVerdict,
    metric_spec_from_persisted_record,
)


class _SpyMetric(EvaluationMetric):
    def __init__(self, spec: MetricSpec) -> None:
        super().__init__(spec)
        self.calls: list[dict[str, Any]] = []

    def _compute(self, deliverables: Mapping[int, str], /, **kwargs: Any):
        self.calls.append(dict(kwargs))
        return 0.5, None, ()


def test_scoreability_refuses_before_metric_arithmetic(tmp_path):
    """A missing deliverable must not reach task-owned arithmetic."""
    metric = _SpyMetric(
        MetricSpec(
            id="synthetic_metric",
            direction="lower",
            aggregation="single_value",
            scoreability=PresenceScoreabilityContract(),
        )
    )
    outcome = metric.evaluate({0: str(tmp_path / "absent.bin")}, marker=1)
    assert isinstance(outcome, NotScoreableResult)
    assert outcome.verdict.failures[0].requirement == "completeness"
    assert metric.calls == []

    present = tmp_path / "present.bin"
    present.write_bytes(b"x")
    outcome = metric.evaluate({0: str(present)}, marker=1)
    assert isinstance(outcome, MetricResult)
    assert outcome.scalar == 0.5
    assert metric.calls == [{"marker": 1}]


@pytest.mark.parametrize("identity", ["train_loss", "validation_loss", "log_loss"])
def test_metric_identity_is_opaque(identity):
    """Task declarations, not spelling heuristics, define metric meaning."""
    spec = MetricSpec(
        id=identity,
        direction="lower",
        aggregation="mean",
        scoreability=PresenceScoreabilityContract(),
    )
    assert spec.id == identity


@pytest.mark.parametrize("identity", ["", "  ", " padded ", "trailing "])
def test_malformed_metric_identifiers_are_refused(identity):
    with pytest.raises(ValidationError, match="non-empty identifier"):
        MetricSpec(
            id=identity,
            direction="lower",
            aggregation="mean",
            scoreability=PresenceScoreabilityContract(),
        )


def test_loss_history_cannot_enter_a_metric_result():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MetricResult(
            metric_id="synthetic_metric",
            direction="higher",
            scalar=1.0,
            loss_history=[0.5, 0.4],
        )


def test_not_scoreable_result_must_name_a_failure():
    with pytest.raises(ValidationError, match="at least one failure"):
        NotScoreableResult(
            metric_id="synthetic_metric",
            direction="higher",
            verdict=ScoreabilityVerdict(contract_id="synthetic_contract"),
        )


def test_external_contract_fields_survive_data_only_record_replay():
    """Fresh-process replay preserves plugin data without importing task code."""
    spec = metric_spec_from_persisted_record(
        {
            "id": "external_metric",
            "direction": "higher",
            "aggregation": "external_rule",
            "scoreability": {
                "contract_id": "external_contract",
                "required_signal": "prediction",
                "minimum_rows": 3,
            },
        }
    )
    assert isinstance(spec.scoreability, PersistedScoreabilityContract)
    assert spec.scoreability.model_dump() == {
        "contract_id": "external_contract",
        "required_signal": "prediction",
        "minimum_rows": 3,
    }
    with pytest.raises(RuntimeError, match="not executable"):
        spec.scoreability.check({0: "artifact.bin"})


def test_framework_contract_remains_executable_during_replay(tmp_path):
    spec = metric_spec_from_persisted_record(
        {
            "id": "framework_metric",
            "direction": "higher",
            "aggregation": "single_value",
            "scoreability": {"contract_id": "deliverable_presence"},
        }
    )
    verdict = spec.scoreability.check({0: str(tmp_path / "missing.bin")})
    assert verdict.failures == (
        ScoreabilityFailure(
            requirement="completeness",
            input_identity=0,
            detail=f"deliverable not found at {str(tmp_path / 'missing.bin')!r}",
        ),
    )


def test_external_contract_survives_a_fresh_run_output_json_replay():
    """The production persisted schema must use the data-only replay path."""
    payload = {
        "run_name": "iteration_001",
        "model_type": "synthetic",
        "file_index": 0,
        "status": "completed",
        "completed_rounds": 0,
        "total_attempts": 0,
        "started_at": "2026-08-31T00:00:00Z",
        "finished_at": "2026-08-31T00:00:01Z",
        "all_records": [],
        "metric_spec": {
            "id": "external_metric",
            "direction": "higher",
            "aggregation": "external_rule",
            "scoreability": {
                "contract_id": "external_contract",
                "required_signal": "prediction",
            },
        },
    }
    restored = HyperparamTuningOutput.model_validate_json(
        HyperparamTuningOutput.model_validate(payload).model_dump_json()
    )
    assert isinstance(restored.metric_spec.scoreability, PersistedScoreabilityContract)
    assert restored.metric_spec.scoreability.model_dump()["required_signal"] == "prediction"
