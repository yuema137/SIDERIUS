"""GlobalMseMetric arithmetic and declared-spec rebinding.

What only this suite catches: the frozen aggregation degrading into a
mean-of-means (which differs from the global mean whenever samples have
unequal sizes — the discriminating case is built here), a partial dense
deliverable being scored anyway, a silent shape mismatch, and a generic
declaration failing to rebind to an executable spec.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from execute_tools.evaluation_metric import (
    GlobalMseMetric,
    MetricResult,
    MetricSpec,
    NotScoreableResult,
    PresenceScoreabilityContract,
    metric_spec_from_declaration,
)

DECLARATION = {
    "id": "mse",
    "direction": "lower",
    "aggregation": "global_mean_squared_error_over_all_declared_elements",
    "transform": "identity",
    "transform_params": {},
    "references": [],
    "scoreability": {"contract_id": "deliverable_presence"},
}


def _spec() -> MetricSpec:
    return metric_spec_from_declaration(DECLARATION)


def _deliverable(tmp_path: Path) -> str:
    path = tmp_path / "predictions.npz"
    path.write_text("x", encoding="utf-8")
    return str(path)


class TestArithmetic:
    def test_exact_global_mean_over_all_elements(self, tmp_path):
        truth = {"a": np.zeros((2, 2), dtype=np.float32)}
        predictions = {"a": np.array([[1.0, 1.0], [1.0, 3.0]], dtype=np.float32)}
        outcome = GlobalMseMetric(_spec()).evaluate(
            {0: _deliverable(tmp_path)}, predictions=predictions, truth=truth
        )
        assert isinstance(outcome, MetricResult)
        assert outcome.metric_id == "mse" and outcome.direction == "lower"
        # (1 + 1 + 1 + 9) / 4 = 3.0
        assert outcome.scalar == pytest.approx(3.0)
        assert outcome.per_sample is None and outcome.references_used == ()

    def test_unequal_sample_sizes_use_the_global_mean_not_a_mean_of_means(self, tmp_path):
        """THE discriminating case for the frozen aggregation. Sample 'big'
        has 4 elements with squared error 4 each; sample 'small' has 1
        element with squared error 0.
            global mean   = (16 + 0) / 5   = 3.2
            mean of means = (4 + 0) / 2    = 2.0
        A mean-of-means implementation returns 2.0 and fails here."""
        truth = {
            "big": np.zeros((2, 2), dtype=np.float32),
            "small": np.zeros((1,), dtype=np.float32),
        }
        predictions = {
            "big": np.full((2, 2), 2.0, dtype=np.float32),
            "small": np.zeros((1,), dtype=np.float32),
        }
        outcome = GlobalMseMetric(_spec()).evaluate(
            {0: _deliverable(tmp_path)}, predictions=predictions, truth=truth
        )
        assert isinstance(outcome, MetricResult)
        assert outcome.scalar == pytest.approx(3.2)
        assert outcome.scalar != pytest.approx(2.0)

    def test_perfect_prediction_scores_zero(self, tmp_path):
        truth = {"a": np.arange(12, dtype=np.float32).reshape(3, 4)}
        outcome = GlobalMseMetric(_spec()).evaluate(
            {0: _deliverable(tmp_path)}, predictions=dict(truth), truth=truth
        )
        assert isinstance(outcome, MetricResult) and outcome.scalar == 0.0

    def test_missing_prediction_is_refused_not_zero_filled(self, tmp_path):
        truth = {"a": np.zeros((2,), dtype=np.float32), "b": np.zeros((2,), dtype=np.float32)}
        with pytest.raises(ValueError, match="no prediction"):
            GlobalMseMetric(_spec()).evaluate(
                {0: _deliverable(tmp_path)},
                predictions={"a": np.zeros((2,), dtype=np.float32)},
                truth=truth,
            )

    def test_shape_mismatch_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="declared output geometry"):
            GlobalMseMetric(_spec()).evaluate(
                {0: _deliverable(tmp_path)},
                predictions={"a": np.zeros((3,), dtype=np.float32)},
                truth={"a": np.zeros((2,), dtype=np.float32)},
            )

    def test_empty_truth_is_a_wiring_defect(self, tmp_path):
        with pytest.raises(ValueError, match="non-empty truth"):
            GlobalMseMetric(_spec()).evaluate({0: _deliverable(tmp_path)}, predictions={}, truth={})


class TestHandleOrder:
    def test_missing_deliverable_refuses_before_arithmetic(self, tmp_path):
        outcome = GlobalMseMetric(_spec()).evaluate(
            {0: str(tmp_path / "absent.npz")}, predictions=None, truth=None
        )
        assert isinstance(outcome, NotScoreableResult)
        assert outcome.metric_id == "mse" and not outcome.verdict.scoreable


class TestDeclarationRebind:
    def test_a_generic_declaration_rebinds_exactly(self):
        spec = _spec()
        assert spec.id == "mse"
        assert spec.direction == "lower"
        assert spec.aggregation == "global_mean_squared_error_over_all_declared_elements"
        assert isinstance(spec.scoreability, PresenceScoreabilityContract)
        assert spec.model_dump(mode="json") == DECLARATION
