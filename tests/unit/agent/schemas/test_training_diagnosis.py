"""Step 07a C3 — ``derive_training_diagnosis`` rules (design §3.6).

Every rule below is pinned by a literal expectation on a hand-built history,
so a mutation of that rule (argmin → argmax, degradation sign, gap gating,
trend deadband, truncated, absent / invalid) is RED here. The diagnosis is a
PURE function: determinism is pinned by re-deriving and comparing dumps.
"""

from __future__ import annotations

import math

import pytest

from agent.schemas.training_diagnosis import (
    FLAT_REL_TOL,
    TrainingDiagnosis,
    derive_training_diagnosis,
    symmetric_relative_change,
)
from execute_tools.training_history import TrainingHistory


def _hist(train, validation=None, *, planned=None, comparability="established", **extra):
    n = len(train)
    payload = {
        "objective_kind": "focal",
        "objective_config_fingerprint": "f" * 64,
        "objective_reduction": "mean" if comparability == "established" else "sum",
        "comparability": comparability,
        "comparability_reason": None if comparability == "established" else "reduction=sum",
        "epochs_planned": planned if planned is not None else n,
        "epochs_completed": n,
        "train_objective": list(train),
    }
    if validation is not None:
        payload.update(
            {
                "validation_objective": list(validation),
                "validation_requested_samples": 8,
                "validation_samples": 8,
                "validation_seconds": [0.1] * n,
            }
        )
    payload.update(extra)
    return TrainingHistory.model_validate(payload)


class TestSymmetricRelativeChange:
    def test_zero_reference_pathology_is_gone(self):
        """A relative change with `a` in the denominator explodes at a=0; the
        symmetric form is 0 at (0,0) and 1 at (0,x)."""
        assert symmetric_relative_change(0.0, 0.0) == 0.0
        assert symmetric_relative_change(0.0, 3.0) == 1.0
        assert symmetric_relative_change(3.0, 0.0) == 1.0

    def test_symmetric_and_scale_free(self):
        assert symmetric_relative_change(2.0, 3.0) == symmetric_relative_change(3.0, 2.0)
        assert symmetric_relative_change(2.0, 3.0) == pytest.approx(
            symmetric_relative_change(200.0, 300.0)
        )
        assert symmetric_relative_change(2.0, 3.0) == pytest.approx(1 / 3)


class TestDiagnosisRules:
    def test_absent_history_is_the_absent_state_and_nothing_else(self):
        d = derive_training_diagnosis(None)
        assert d.state == "absent" and d.validation_state == "absent"
        assert d.best_validation_epoch is None and d.train_trend is None
        assert d.flat_rel_tol == FLAT_REL_TOL

    def test_best_validation_epoch_is_the_argmin_and_degradation_is_final_minus_min(self):
        """MUTATIONS caught: argmax instead of argmin; degradation sign flipped;
        min taken over the train curve instead of validation."""
        d = derive_training_diagnosis(_hist([3.0, 2.0, 1.5, 1.2], [3.1, 2.0, 2.2, 2.6]))
        assert d.state == "ok" and d.validation_state == "present"
        assert d.best_validation_epoch == 1
        assert d.validation_min == 2.0 and d.validation_last == 2.6 and d.validation_first == 3.1
        assert d.final_vs_best_validation_degradation == pytest.approx(0.6)
        assert d.final_vs_best_validation_degradation_rel == pytest.approx(0.6 / 2.6)
        assert d.validation_degraded_after_best is True
        assert d.train_min_epoch == 3 and d.train_min == 1.2 and d.train_first == 3.0

    def test_no_degradation_when_the_last_epoch_is_the_best(self):
        d = derive_training_diagnosis(_hist([3.0, 2.0, 1.0], [3.5, 2.5, 1.5]))
        assert d.best_validation_epoch == 2
        assert d.final_vs_best_validation_degradation == 0.0
        assert d.validation_degraded_after_best is False

    def test_a_degradation_inside_the_deadband_is_not_flagged(self):
        """`validation_degraded_after_best` needs r(min, last) > flat_rel_tol —
        a 0.5 % rise is within the 1 % deadband."""
        d = derive_training_diagnosis(_hist([3.0, 2.0, 1.0], [3.0, 2.0, 2.01]))
        assert d.best_validation_epoch == 1
        assert d.validation_degraded_after_best is False
        assert d.final_vs_best_validation_degradation == pytest.approx(0.01)

    def test_gap_is_signed_validation_minus_train_when_comparability_is_established(self):
        d = derive_training_diagnosis(_hist([3.0, 1.0], [3.5, 1.5]))
        assert d.comparability == "established"
        assert d.train_validation_gap_final == pytest.approx(0.5)
        assert d.train_validation_gap_final_rel == pytest.approx(0.5 / 1.5)

    def test_gap_is_none_when_comparability_is_not_established_but_within_curve_facts_stay(self):
        """§3.3: a sum-reduced objective still has valid within-curve facts
        (best epoch, trends, degradation) but NO cross-curve claim."""
        d = derive_training_diagnosis(
            _hist([3.0, 1.0], [3.5, 1.5], comparability="not_established")
        )
        assert d.comparability == "not_established"
        assert d.train_validation_gap_final is None and d.train_validation_gap_final_rel is None
        assert d.best_validation_epoch == 1 and d.validation_trend == "decreasing"
        assert d.train_trend == "decreasing"

    @pytest.mark.parametrize(
        "series, expected",
        [
            ([1.0], "single_point"),
            ([1.0, 1.0], "flat"),
            ([100.0, 99.0], "flat"),  # r == 1.0/100.0 == 0.01: exactly on the deadband → flat (<=)
            ([100.0, 98.9], "decreasing"),  # just outside → sign decides
            ([100.0, 101.2], "increasing"),  # r = 1.2/101.2 ≈ 0.0119 > tol
            ([0.0, 0.0], "flat"),  # both zero → r = 0
            ([0.0, 0.5], "increasing"),  # r = 1 (no division by a zero reference)
            ([5.0, 3.0, 4.0], "decreasing"),  # endpoints only, not monotonicity
        ],
    )
    def test_trend_uses_first_and_last_with_the_symmetric_deadband(self, series, expected):
        d = derive_training_diagnosis(_hist(series))
        assert d.train_trend == expected

    def test_truncated_history_is_flagged_and_diagnosed_over_the_completed_prefix(self):
        d = derive_training_diagnosis(_hist([3.0, 2.0], [3.1, 2.1], planned=5))
        assert d.truncated is True and d.epochs_completed == 2 and d.epochs_planned == 5
        assert d.best_validation_epoch == 1

    def test_validation_absent_is_ok_with_validation_state_absent(self):
        d = derive_training_diagnosis(_hist([3.0, 2.0]))
        assert d.state == "ok" and d.validation_state == "absent"
        assert d.best_validation_epoch is None and d.validation_trend is None
        assert d.train_validation_gap_final is None
        assert d.train_trend == "decreasing"

    @pytest.mark.parametrize(
        "train, validation",
        [
            ([3.0, float("nan")], [3.1, 2.0]),
            ([3.0, 2.0], [3.1, float("inf")]),
            ([float("nan")], None),
        ],
    )
    def test_non_finite_values_give_the_invalid_state_with_counts_but_no_curve_facts(
        self, train, validation
    ):
        d = derive_training_diagnosis(_hist(train, validation))
        assert d.state == "invalid"
        assert d.epochs_completed == len(train)
        assert d.train_first is None and d.best_validation_epoch is None
        assert d.validation_state == ("present" if validation is not None else "absent")

    def test_empty_history_is_invalid(self):
        d = derive_training_diagnosis(_hist([], planned=1))
        assert d.state == "invalid" and d.epochs_completed == 0

    def test_deterministic_and_pure(self):
        h = _hist([3.0, 2.0, 1.5], [3.1, 2.4, 2.5])
        a = derive_training_diagnosis(h)
        b = derive_training_diagnosis(h)
        assert a == b and a.model_dump() == b.model_dump()
        assert h.train_objective == [3.0, 2.0, 1.5]  # input untouched

    def test_flat_rel_tol_is_recorded_and_re_derivable(self):
        d = derive_training_diagnosis(_hist([1.0, 0.995]), flat_rel_tol=0.001)
        assert d.flat_rel_tol == 0.001 and d.train_trend == "decreasing"
        assert derive_training_diagnosis(_hist([1.0, 0.995])).train_trend == "flat"

    def test_no_calibrated_labels_exist_on_the_schema(self):
        """Parent §8.2 item 3 / Q-07a-2: overfitting / underfitting / converged /
        plateau are NOT v1 diagnosis fields."""
        names = set(TrainingDiagnosis.model_fields)
        for forbidden in ("overfitting", "underfitting", "converged", "plateau"):
            assert not any(forbidden in n for n in names), names

    def test_the_diagnosis_dump_round_trips_with_non_finite_free_values(self):
        d = derive_training_diagnosis(_hist([3.0, 2.0], [3.1, 2.1]))
        again = TrainingDiagnosis.model_validate(d.model_dump())
        assert again == d
        assert all(not isinstance(v, float) or math.isfinite(v) for v in d.model_dump().values())
