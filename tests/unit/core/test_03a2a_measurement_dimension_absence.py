"""03A2a: fixed task probes do not acquire temporal identity."""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_context import (
    CalibrationContextInputs,
    build_calibration_context,
)
from core.runtime_control.calibration_derivation import (
    QuarantinedDerivation,
    derive_duration_calibration_record,
)
from core.runtime_control.gpu_measurement_identity import (
    build_planned_identity,
    build_realized_identity,
    compare_identities,
)


def test_fixed_probe_identity_round_trips_without_a_segmentation_default():
    planned = build_planned_identity(
        model_type="tabular_mlp",
        model_config={},
        train_config={"batch_size": 4},
        segmentation_applicability="not_applicable",
    )
    realized = build_realized_identity(
        model_type="tabular_mlp",
        optimizer_type="adamw",
        seg_size=None,
        batch_size=4,
        precision="float32",
        parameter_count=100,
        trainable_parameter_count=100,
        segmentation_applicability="not_applicable",
    )

    assert planned.seg_size is None
    assert realized.seg_size is None
    assert planned.model_dump(mode="json")["seg_size"] is None
    assert realized.model_dump(mode="json")["seg_size"] is None
    assert compare_identities(planned, realized, requested_id="r", reported_id="r") is None


def test_temporal_identity_cannot_be_constructed_without_its_dimension():
    with pytest.raises(ValueError, match="temporal measurement identity requires seg_size"):
        build_realized_identity(
            model_type="wavenet",
            optimizer_type="adamw",
            seg_size=None,
            batch_size=1,
            precision="float32",
            parameter_count=100,
            trainable_parameter_count=100,
        )


def test_fixed_probe_context_is_named_and_not_temporal_calibration():
    context = build_calibration_context(
        CalibrationContextInputs(
            precision="float32",
            optimizer_type="adamw",
            model_family="tabular_mlp",
            param_count=100,
            batch_size=4,
            segmentation_applicability="not_applicable",
        )
    )
    assert context["segmentation_applicability"] == "not_applicable"
    assert "seg_size" not in context

    # This uses the established persisted-observation fixture and exercises
    # the real derivation boundary, not a hand-written registry record.
    from tests.unit.core.test_calibration_derivation import CONTEXT, _observation

    observation = _observation()
    observation = observation.model_copy(
        update={
            "calibration_context": context,
        }
    )
    result = derive_duration_calibration_record(observation, "training", identity=CONTEXT)
    assert isinstance(result, QuarantinedDerivation)
    assert result.missing_identity_fields == ("seg_size",)
    assert "cannot enter temporal calibration" in result.reason
