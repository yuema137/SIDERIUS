"""The enforcement and authority axes are DECLARED, not reconstructed.

V20 PR D, commit D-C1a — declaration and recording only. Nothing consumes
these fields yet; enforcement of mandatoriness and of the invalid
combination is D-C1b.

Two axes, not one (D-D-5):

    healthgate_mode  ∈ {blocking, observe_only}   what a verdict DOES
    result_authority ∈ {scientific, diagnostic}   what a result MAY inform

Collapsing them was the original design error. `blocking + diagnostic` is
coherent — a fully-enforced run whose results are deliberately not
promoted — and cannot be expressed if the two are one field.

**Why declared rather than inferred.** The predecessor role hotfix
(`af5339ce`) already measured what inference costs: deriving a scientific
property from the enforcement action inverted the answer under an
observe-only config, and every record classified valid. The same reasoning
applies here one level up — a mode reconstructed by diffing the effective
YAML against the shipped one would make every config self-consistent by
construction, so the consistency check in D-C1b would pass V19's own
configuration.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
)

MODES = ("blocking", "observe_only")
AUTHORITIES = ("scientific", "diagnostic")


def _input(**overrides) -> HyperparamTuningInput:
    return HyperparamTuningInput(model_type="punet", run_name="r", **overrides)


class TestBothAxesAreAccepted:
    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("authority", AUTHORITIES)
    def test_every_combination_loads_at_the_schema_level(self, mode, authority):
        """Including `observe_only + scientific`.

        The contradiction is refused by the LAUNCHER (D-C1b), not by the
        schema — deliberately, so a historical artifact recorded under any
        combination still loads for forensics. A schema that refused it
        would make the incident it documents unreadable.
        """
        parsed = _input(healthgate_mode=mode, result_authority=authority)
        assert parsed.healthgate_mode == mode
        assert parsed.result_authority == authority

    def test_blocking_diagnostic_is_expressible(self):
        """The combination that proves the axes are independent. If these
        were one field this could not be written down."""
        parsed = _input(healthgate_mode="blocking", result_authority="diagnostic")
        assert (parsed.healthgate_mode, parsed.result_authority) == ("blocking", "diagnostic")


class TestOmissionDoesNotBecomeAPosture:
    def test_neither_axis_has_a_default_value(self):
        """THE OPERATOR'S RULING. Omission must not fall back to
        `blocking` — a run would then claim an authority nobody granted
        it. `None` means undeclared, and D-C1b refuses to launch on it.
        """
        parsed = _input()
        assert parsed.healthgate_mode is None
        assert parsed.result_authority is None

    def test_declaring_one_axis_does_not_imply_the_other(self):
        """The failure mode of a single collapsed field: setting the mode
        must not silently decide authority."""
        assert _input(healthgate_mode="blocking").result_authority is None
        assert _input(result_authority="diagnostic").healthgate_mode is None


class TestAnUnknownValueIsRefusedByTheSchema:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("healthgate_mode", "nonsense"),
            ("healthgate_mode", "observe"),  # near-miss
            ("healthgate_mode", "scientific"),  # the OTHER axis's vocabulary
            ("result_authority", "nonsense"),
            ("result_authority", "blocking"),  # the OTHER axis's vocabulary
        ],
    )
    def test_it_is_rejected_by_the_literal_not_a_hand_rolled_check(self, field, value):
        """Cross-axis values are in the list on purpose: two Literals that
        each accept the other's vocabulary would be one field wearing two
        names."""
        with pytest.raises(ValidationError):
            _input(**{field: value})


#: The output schema's pre-existing required fields. Spelled out so a test
#: below can assert the new axes did NOT join them.
_REQUIRED_OUTPUT = {
    "run_name": "r",
    "model_type": "punet",
    "file_index": 0,
    "status": "completed",
    "completed_rounds": 1,
    "total_attempts": 1,
    "started_at": "2026-08-05T00:00:00",
    "finished_at": "2026-08-05T01:00:00",
}


class TestTheOutputCarriesTheDeclaration:
    def test_both_axes_reach_the_output_schema(self):
        out = HyperparamTuningOutput(
            **_REQUIRED_OUTPUT,
            healthgate_mode="observe_only",
            result_authority="diagnostic",
        )
        assert out.healthgate_mode == "observe_only"
        assert out.result_authority == "diagnostic"

    def test_a_legacy_output_without_the_fields_still_loads(self):
        """BACKWARD COMPATIBILITY. Every artifact written before this
        commit lacks both keys; resume must not require them."""
        out = HyperparamTuningOutput(**_REQUIRED_OUTPUT)
        assert out.healthgate_mode is None
        assert out.result_authority is None

    def test_neither_axis_became_a_required_output_field(self):
        """A pure addition must stay pure: making either required would
        break every historical artifact at load time."""
        required = {
            name for name, f in HyperparamTuningOutput.model_fields.items() if f.is_required()
        }
        assert "healthgate_mode" not in required
        assert "result_authority" not in required
