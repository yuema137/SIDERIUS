"""F-SCANE-2 — the diagnosis names what it cannot observe, and never fakes it.

Frozen row: ``docs/campaign/official_campaign_decisions.yaml`` ``F-SCANE-2``,
``status: FROZEN``::

    ruling_2026_08_26: ACCEPTED. ... The diagnosis must report
    insufficient_history or not_applicable in the degenerate case and must
    NEVER FABRICATE a trend it cannot observe.

    why_this_is_the_right_shape: ... "single_point" already says so honestly;
    what must not happen is a fabricated "flat" or a degradation figure of 0.0
    read as evidence of no degradation.

The defect only this file catches
---------------------------------
At ``epochs_completed == 1`` the validation series has length 1, so
``r3[-1] - r3[best]`` is ``x − x`` and ``r(x, x)`` is ``0.0``. The derivation
wrote those out as ``final_vs_best_validation_degradation = 0.0``,
``..._rel = 0.0`` and ``validation_degraded_after_best = False`` — three values
that read as "measured, and the run did not degrade". They were persisted on
every ``ExperimentRecord`` and carried into the operator report. The campaign
freezes ``formal_max_epochs = 1``, so this was EVERY formal round.

Restoring the ungated ``fields.update`` turns
``test_a_one_epoch_validation_curve_reports_insufficient_history`` and
``test_the_persisted_record_payload_carries_the_named_absence`` red.

What must NOT change, and is asserted here so a later edit cannot drift:
``validation_trend`` stays ``single_point`` (the ruling calls that honest),
``validation_min`` / ``best_validation_epoch`` / the endpoints stay real
facts, and the tuner prompt line is byte-identical.
"""

from __future__ import annotations

import pytest

from agent.prompt_templates.tuner.rendering import render_training_dynamics_line
from agent.schemas.training_diagnosis import derive_training_diagnosis
from execute_tools.training_history import TrainingHistory

#: The three fields the ruling names. Held as one set so a fourth degradation
#: field added later without a verdict gate fails these tests rather than
#: slipping past a hand-listed pair.
DEGRADATION_FIELDS = (
    "final_vs_best_validation_degradation",
    "final_vs_best_validation_degradation_rel",
    "validation_degraded_after_best",
)


def _history(
    train: list[float],
    validation: list[float] | None,
    *,
    planned: int | None = None,
) -> TrainingHistory:
    """A real ``TrainingHistory`` — the derivation's actual input type."""
    n = len(train)
    payload: dict = {
        "objective_kind": "focal",
        "objective_config_fingerprint": "f" * 64,
        "objective_reduction": "mean",
        "comparability": "established",
        "epochs_planned": planned if planned is not None else n,
        "epochs_completed": n,
        "train_objective": train,
    }
    if validation is not None:
        payload.update(
            {
                "validation_objective": validation,
                "validation_requested_samples": 128,
                "validation_samples": 128,
                "validation_seconds": [1.0] * n,
            }
        )
    return TrainingHistory.model_validate(payload)


class TestTheDegenerateCaseIsNamed:
    def test_a_one_epoch_validation_curve_reports_insufficient_history(self):
        """The campaign's own formal-round shape: `formal_max_epochs = 1`."""
        d = derive_training_diagnosis(_history([2.9], [2.95]))

        assert d.state == "ok" and d.validation_state == "present"
        assert d.epochs_completed == 1
        assert d.validation_degradation_verdict == "insufficient_history"
        for field in DEGRADATION_FIELDS:
            assert getattr(d, field) is None, (
                f"{field} is not None at one epoch — a degradation figure the "
                f"curve cannot support is exactly what the ruling forbids"
            )

    def test_the_honest_facts_at_one_epoch_are_untouched(self):
        """The ruling preserves what `single_point` already said honestly.

        The minimum of a one-element series IS that element at index 0 — a
        true fact, not a fabrication — and this must not be blanked along
        with the degradation triple."""
        d = derive_training_diagnosis(_history([2.9], [2.95]))

        assert d.validation_trend == "single_point"
        assert d.train_trend == "single_point"
        assert d.validation_first == 2.95
        assert d.validation_last == 2.95
        assert d.validation_min == 2.95
        assert d.best_validation_epoch == 0
        # The gap is a two-CURVE fact, not a two-EPOCH one, so it still holds.
        assert d.train_validation_gap_final == pytest.approx(0.05)

    def test_a_two_epoch_curve_is_observed_and_still_measures(self):
        """The complement. Without it every assertion above would pass on a
        derivation that had simply stopped computing degradation at all."""
        d = derive_training_diagnosis(_history([3.0, 2.0], [2.0, 2.6]))

        assert d.validation_degradation_verdict == "observed"
        assert d.final_vs_best_validation_degradation == pytest.approx(0.6)
        assert d.final_vs_best_validation_degradation_rel == pytest.approx(0.6 / 2.6)
        assert d.validation_degraded_after_best is True

    def test_an_observed_zero_degradation_is_still_a_measurement(self):
        """`observed` + `0.0` is a REAL finding (the last epoch was the best)
        and must stay distinguishable from the unobservable case, which is
        the whole point of naming the absence instead of using `0.0` for
        both."""
        d = derive_training_diagnosis(_history([3.0, 2.0], [3.0, 2.0]))

        assert d.validation_degradation_verdict == "observed"
        assert d.final_vs_best_validation_degradation == 0.0
        assert d.validation_degraded_after_best is False

    @pytest.mark.parametrize(
        ("history", "why"),
        [
            (None, "no history payload at all (legacy trainer / crash)"),
            (_history([3.0, 2.0], None), "a training curve with no validation pass"),
            (_history([float("nan"), 2.0], [3.0, 2.0]), "a diverged (non-finite) history"),
        ],
    )
    def test_no_usable_validation_curve_reports_not_applicable(self, history, why):
        d = derive_training_diagnosis(history)

        assert d.validation_degradation_verdict == "not_applicable", why
        for field in DEGRADATION_FIELDS:
            assert getattr(d, field) is None, f"{field} populated for {why}"


class TestTheNamedAbsenceTravels:
    def test_the_persisted_record_payload_carries_the_named_absence(self):
        """`records.py` writes `training_diagnosis.model_dump()` verbatim onto
        the ExperimentRecord, so the dump IS the persisted payload — the
        surface the row says the LLM-side falsy-test accident never
        protected."""
        payload = derive_training_diagnosis(_history([2.9], [2.95])).model_dump()

        assert payload["validation_degradation_verdict"] == "insufficient_history"
        assert payload["final_vs_best_validation_degradation"] is None
        assert payload["validation_degraded_after_best"] is None
        assert payload["validation_trend"] == "single_point"

    def test_the_operator_report_projection_carries_the_verdict(self):
        """`run_report.DiagnosisView` is the ONE projection the operator
        report and the HTML view read. A bare `None` there does not say WHY —
        `insufficient_history` (one epoch) and `not_applicable` (no
        validation at all) are different facts about the run."""
        from execute_tools.run_report import DiagnosisView

        degenerate = DiagnosisView.from_diagnosis(
            derive_training_diagnosis(_history([2.9], [2.95])), objective_kind="focal"
        )
        assert degenerate.validation_degradation_verdict == "insufficient_history"
        assert degenerate.validation_degraded_after_best is None

        no_validation = DiagnosisView.from_diagnosis(
            derive_training_diagnosis(_history([3.0, 2.0], None)), objective_kind="focal"
        )
        assert no_validation.validation_degradation_verdict == "not_applicable"

        observed = DiagnosisView.from_diagnosis(
            derive_training_diagnosis(_history([3.0, 2.0], [2.0, 2.6])), objective_kind="focal"
        )
        assert observed.validation_degradation_verdict == "observed"
        assert observed.validation_degraded_after_best is True


#: Captured by rendering each shape in a PRISTINE `3995400b` worktree, before
#: any part of this fix existed. Hardcoded, never read back from the renderer:
#: the whole claim is that these bytes did not move, and an expectation read
#: from the thing under test cannot make that claim.
_PRISTINE_DYNAMICS_LINES = {
    "one_epoch": (
        "[focal] train 2.90->2.90 (single_point, 1 ep) · "
        "val 2.95->2.95 (single_point; best ep 0) · gap +0.05 (comparable)"
    ),
    "two_epoch_observed": (
        "[focal] train 3.00->2.00 (decreasing, 2 ep) · "
        "val 2.00->2.60 (increasing; best ep 0, +0.60 after best) · gap +0.60 (comparable)"
    ),
    "two_epoch_zero_degradation": (
        "[focal] train 3.00->2.00 (decreasing, 2 ep) · "
        "val 3.00->2.00 (decreasing; best ep 1) · gap +0.00 (comparable)"
    ),
    "no_validation": (
        "[focal] train 3.00->2.00 (decreasing, 2 ep) · val not recorded · gap n/a (unavailable)"
    ),
}


class TestTheTunerPromptBytesDoNotMove:
    """The LLM surface was already accidentally correct — `0.0` is falsy, so
    no fabricated "+0.0 after best" note ever rendered. The ruling makes that
    suppression intentional; it must not also make it VISIBLE, or this fix
    would be a silent prompt change dressed as a record fix.

    The one-epoch row is the load-bearing one: that diagnosis now carries
    THREE Nones where it carried two numbers and a bool, and the rendered
    bytes are the same."""

    @pytest.mark.parametrize(
        ("shape", "train", "validation"),
        [
            ("one_epoch", [2.90], [2.95]),
            ("two_epoch_observed", [3.0, 2.0], [2.0, 2.6]),
            ("two_epoch_zero_degradation", [3.0, 2.0], [3.0, 2.0]),
            ("no_validation", [3.0, 2.0], None),
        ],
    )
    def test_the_dynamics_line_is_byte_identical_to_the_pristine_render(
        self, shape, train, validation
    ):
        line = render_training_dynamics_line(
            derive_training_diagnosis(_history(train, validation)), "focal"
        )
        assert line == _PRISTINE_DYNAMICS_LINES[shape]
