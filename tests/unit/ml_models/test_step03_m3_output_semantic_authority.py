"""Canonical output semantics and the re-keyed loss authority — M3.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§8a (loss authority RE-KEYED, never re-declared), §8b (``output_type``
becomes a derived projection), §8c (``hybrid`` stays a legacy adapter),
§21 (a changed accept/reject cell is a STOP).

**What baseline A2 already covers, and what it cannot.** A2
(``test_step03_a2_loss_compatibility_matrix.py``) pins all 15 verdict
cells and is the oracle proving the re-key changed no verdict. It is
deliberately blind to *how* the verdict is reached, so it would stay
green if the re-key had produced a SECOND rule that happened to agree —
which is exactly the duplicate authority §8a forbids.

This module covers the structural failure classes A2 cannot see:

============================================  ==========================
failure class                                  caught here by
============================================  ==========================
the legacy entry point keeps its own copy of   ``TestOneImplementation``
the rule instead of delegating
``output_type`` remains an independent         ``TestProjectionIsOneWay``
authority rather than a projection
``hybrid`` acquires tensor semantics           ``TestHybridStaysLegacy``
the contract's output semantic is declared     ``TestSemanticIsDerived``
rather than derived, so it can disagree
with the tensor it describes
============================================  ==========================
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from ml_models.models_format_sandbox import (
    OutputSemantic,
    legacy_output_type_for,
    output_semantic_from_legacy,
    validate_output_loss_compatibility,
    validate_semantic_loss_compatibility,
)


def _axis(role: AxisRole | None = None, **dim) -> TensorAxis:
    return TensorAxis(dimension=Dimension(**dim), role=role)


def _contract(*, categorical: bool) -> ModelIOContract:
    """TIDMAD-shaped, with ONLY the class axis varying."""
    output_axes = [
        _axis(AxisRole.BATCH, symbolic="B"),
        _axis(AxisRole.TEMPORAL, symbolic="T"),
    ]
    if categorical:
        output_axes.insert(1, _axis(AxisRole.CLASS, fixed=256))
    return ModelIOContract(
        input=TensorContract(
            axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
            dtype=DtypeAdmissibility(admissible=("int64", "int32")),
        ),
        output=TensorContract(
            axes=tuple(output_axes),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
    )


class TestSemanticIsDerived:
    """§8b — the authority is the normalized OUTPUT TENSOR, not a field."""

    def test_a_class_axis_makes_the_output_categorical(self):
        assert _contract(categorical=True).output_semantic is OutputSemantic.CATEGORICAL

    def test_no_class_axis_makes_the_output_continuous(self):
        assert _contract(categorical=False).output_semantic is OutputSemantic.CONTINUOUS

    def test_the_semantic_cannot_be_declared_independently(self):
        """A declared field could contradict the tensor it describes. The
        contract exposes no competing semantic field; the optional inference
        reconstruction contract is orthogonal to tensor semantics."""
        assert set(ModelIOContract.model_fields) == {"input", "output", "inference"}
        with pytest.raises(ValidationError):
            ModelIOContract(
                input=_contract(categorical=True).input,
                output=_contract(categorical=True).output,
                output_semantic="continuous",  # type: ignore[call-arg]
            )

    def test_the_semantic_tracks_the_tensor_it_is_derived_from(self):
        """The property that makes derivation worth having: changing the
        tensor changes the semantic, with nothing to keep in sync."""
        assert (
            _contract(categorical=True).output_semantic
            is not _contract(categorical=False).output_semantic
        )


class TestProjectionIsOneWay:
    """§8b — ``output_type`` is a derived view, not a second authority."""

    def test_the_projection_maps_each_semantic_to_its_legacy_word(self):
        assert legacy_output_type_for(OutputSemantic.CATEGORICAL) == "classifier"
        assert legacy_output_type_for(OutputSemantic.CONTINUOUS) == "regressor"

    def test_the_contract_projects_the_legacy_word(self):
        assert _contract(categorical=True).legacy_output_type == "classifier"
        assert _contract(categorical=False).legacy_output_type == "regressor"

    def test_the_projection_round_trips_for_the_two_real_semantics(self):
        """Adapting a legacy word and projecting it back is the identity —
        so the compatibility view loses nothing for the values that DO
        carry a canonical semantic."""
        for semantic in OutputSemantic:
            assert output_semantic_from_legacy(legacy_output_type_for(semantic)) is semantic

    def test_the_projection_never_produces_hybrid(self):
        """§8c: ``hybrid`` is not a tensor semantic, so no contract can
        project onto it. If this ever fails, tensor semantics were invented
        for a legacy adapter value."""
        assert "hybrid" not in {legacy_output_type_for(s) for s in OutputSemantic}


class TestHybridStaysLegacy:
    """§8c — legacy builtin compatibility, never a generic promise."""

    def test_hybrid_adapts_to_no_canonical_semantic(self):
        assert output_semantic_from_legacy("hybrid") is None

    def test_hybrid_still_accepts_every_loss(self):
        """The shipped behaviour, preserved through the re-key. A2 pins the
        cells; this states the rule they embody."""
        for loss in ("ce", "focal", "focal_cw", "smooth_l1", "custom"):
            validate_output_loss_compatibility("hybrid", loss, model_type="m3_probe")

    def test_hybrid_is_not_a_member_of_the_canonical_enum(self):
        assert {s.value for s in OutputSemantic} == {"categorical", "continuous"}


class TestOneImplementation:
    """§8a — RE-KEYED, not duplicated. One rule, two entry points."""

    def test_the_legacy_entry_point_delegates_rather_than_reimplementing(self):
        """The duplicate-authority failure class A2 is blind to.

        Asserted on source: the legacy function must call the re-keyed rule
        and must NOT carry its own copy of the guard conditions. A second
        copy would agree today and drift tomorrow — which is precisely how
        ``LossConfig.check_compatibility`` became a contradictory second
        rule before V21 PR A deleted it.
        """
        body = inspect.getsource(validate_output_loss_compatibility)
        assert "validate_semantic_loss_compatibility(" in body
        assert "REGRESSION_LOSSES" not in body
        assert "CLASSIFICATION_LOSSES" not in body

    def test_the_rule_itself_keys_on_the_semantic_not_the_legacy_string(self):
        """The re-key. A rule still comparing to ``"classifier"`` would pass
        every A2 cell while leaving legality keyed on the legacy alphabet.
        """
        body = inspect.getsource(validate_semantic_loss_compatibility)
        assert "OutputSemantic.CATEGORICAL" in body
        assert "OutputSemantic.CONTINUOUS" in body
        assert '== "classifier"' not in body
        assert '== "regressor"' not in body

    @pytest.mark.parametrize(
        ("semantic", "loss", "raises"),
        [
            (OutputSemantic.CATEGORICAL, "ce", False),
            (OutputSemantic.CATEGORICAL, "smooth_l1", True),
            (OutputSemantic.CATEGORICAL, "custom", False),
            (OutputSemantic.CONTINUOUS, "smooth_l1", False),
            (OutputSemantic.CONTINUOUS, "focal", True),
            (OutputSemantic.CONTINUOUS, "custom", False),
            (None, "smooth_l1", False),
            (None, "focal", False),
        ],
    )
    def test_the_semantic_entry_point_gives_the_same_verdicts(self, semantic, loss, raises):
        """The new entry point is usable directly by a contract-derived
        caller — which is the point of the re-key — and agrees with the
        legacy one cell for cell."""
        if raises:
            with pytest.raises(ValueError):
                validate_semantic_loss_compatibility(semantic, loss, model_type="m3_probe")
        else:
            validate_semantic_loss_compatibility(semantic, loss, model_type="m3_probe")

    def test_a_contract_can_drive_loss_legality_directly(self):
        """End to end: normalized contract -> canonical semantic -> verdict,
        with the legacy string never appearing. This is what §8a's re-key
        exists to enable."""
        categorical = _contract(categorical=True)
        validate_semantic_loss_compatibility(
            categorical.output_semantic, "focal", model_type="m3_probe"
        )
        with pytest.raises(ValueError):
            validate_semantic_loss_compatibility(
                categorical.output_semantic, "smooth_l1", model_type="m3_probe"
            )

        continuous = _contract(categorical=False)
        validate_semantic_loss_compatibility(
            continuous.output_semantic, "smooth_l1", model_type="m3_probe"
        )
        with pytest.raises(ValueError):
            validate_semantic_loss_compatibility(
                continuous.output_semantic, "focal", model_type="m3_probe"
            )


class TestUnknownValuesKeepTheirShippedTolerance:
    """An unrecognised ``output_type`` still raises nothing (A2 pins this).

    Stated here as a RULE rather than only as A2's two cells, because the
    re-key is exactly where it could have been tightened by accident.
    Tightening is a changed verdict and therefore a §21 STOP — if this
    reds, stop and decide, do not update the expectation.
    """

    def test_an_unrecognised_output_type_carries_no_semantic(self):
        assert output_semantic_from_legacy("no_such_output_type") is None

    def test_and_therefore_permits_every_loss(self):
        for loss in ("ce", "focal", "focal_cw", "smooth_l1", "custom"):
            validate_output_loss_compatibility("no_such_output_type", loss, model_type="m3_probe")
