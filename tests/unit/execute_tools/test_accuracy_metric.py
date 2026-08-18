"""AccuracyMetric + declared-spec rebinding (D14-2 C5).

What only this suite catches: accuracy arithmetic drifting off the declared
aggregation (truth-denominated, missing prediction = not correct), the
handle's scoreability-before-arithmetic order breaking for instance #2, and
the declaration→spec rebind inventing or losing metric identity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from execute_tools.evaluation_metric import (
    AccuracyMetric,
    MetricResult,
    MetricSpec,
    NotScoreableResult,
    PresenceScoreabilityContract,
    metric_spec_from_declaration,
    scoreability_contract_from_declaration,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DECLARED = REPO_ROOT / "examples" / "oxford_iiit_pet" / "declared" / "metric_accuracy.json"


def _spec() -> MetricSpec:
    return metric_spec_from_declaration(json.loads(DECLARED.read_text(encoding="utf-8")))


class TestArithmetic:
    def test_fraction_correct_over_truth(self, tmp_path):
        deliverable = tmp_path / "predictions.csv"
        deliverable.write_text("x", encoding="utf-8")
        metric = AccuracyMetric(_spec())
        outcome = metric.evaluate(
            {0: str(deliverable)},
            predictions={"a": 1, "b": 2, "c": 3},
            truth={"a": 1, "b": 9, "c": 3, "d": 4},
        )
        assert isinstance(outcome, MetricResult)
        assert outcome.metric_id == "accuracy" and outcome.direction == "higher"
        assert outcome.scalar == pytest.approx(2 / 4)  # d missing -> not correct
        assert outcome.per_sample is None and outcome.references_used == ()

    def test_missing_prediction_counts_as_wrong_not_error(self, tmp_path):
        deliverable = tmp_path / "p.csv"
        deliverable.write_text("x", encoding="utf-8")
        outcome = AccuracyMetric(_spec()).evaluate(
            {0: str(deliverable)}, predictions={}, truth={"a": 0}
        )
        assert isinstance(outcome, MetricResult) and outcome.scalar == 0.0

    def test_empty_truth_is_a_wiring_defect(self, tmp_path):
        deliverable = tmp_path / "p.csv"
        deliverable.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="non-empty truth"):
            AccuracyMetric(_spec()).evaluate({0: str(deliverable)}, predictions={}, truth={})


class TestHandleOrder:
    def test_missing_deliverable_refuses_before_arithmetic(self, tmp_path):
        """Step-06 order is load-bearing for instance #2 exactly as for #1:
        the structured refusal fires even when the compute kwargs are
        garbage that would crash `_compute`."""
        outcome = AccuracyMetric(_spec()).evaluate(
            {0: str(tmp_path / "absent.csv")},
            predictions=None,  # would TypeError inside _compute
            truth=None,
        )
        assert isinstance(outcome, NotScoreableResult)
        assert outcome.metric_id == "accuracy"
        assert not outcome.verdict.scoreable


class TestDeclarationRebind:
    def test_the_committed_declaration_rebinds_exactly(self):
        spec = _spec()
        assert spec.id == "accuracy"
        assert spec.direction == "higher"
        assert spec.aggregation == "fraction_correct_over_final_eval_images"
        assert isinstance(spec.scoreability, PresenceScoreabilityContract)
        # Round-trip: the rebound spec re-serializes to the committed payload.
        assert spec.model_dump(mode="json") == json.loads(DECLARED.read_text(encoding="utf-8"))

    def test_unknown_contract_id_fails_closed_naming_the_vocabulary(self):
        with pytest.raises(ValueError, match="deliverable_presence"):
            scoreability_contract_from_declaration({"contract_id": "made_up"})
