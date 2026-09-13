"""Regression #309: offers must query execution, not repeat its matrix."""

from types import SimpleNamespace

import pytest

from agent.prompt_templates.tuner.loss_context import PlannerLossContext
from agent.prompt_templates.tuner.rendering import build_tuner_task_render
from ml_models import models_format_sandbox as authority
from ml_models.models_format_sandbox import LossConfig, OutputSemantic


@pytest.mark.parametrize(
    ("semantic", "temporal", "expected"),
    [
        (OutputSemantic.CATEGORICAL, False, ("ce",)),
        (OutputSemantic.CATEGORICAL, True, ("focal", "focal_cw", "ce")),
        (OutputSemantic.CATEGORICAL, None, ("focal", "focal_cw", "ce")),
        (OutputSemantic.CONTINUOUS, False, ("smooth_l1",)),
        (OutputSemantic.CONTINUOUS, True, ("smooth_l1",)),
    ],
)
def test_offers_follow_execution_geometry(semantic, temporal, expected):
    assert (
        authority.eligible_builtin_loss_types(semantic, output_has_temporal_axis=temporal)
        == expected
    )


def test_refusing_execution_authority_removes_offers_and_refuses_before_planning(monkeypatch):
    def refuse(*args, **kwargs):
        raise ValueError("test-owned execution refusal")

    monkeypatch.setattr(authority, "validate_semantic_loss_compatibility", refuse)
    with pytest.raises(ValueError, match="No compatible builtin loss offers"):
        PlannerLossContext(output_semantic="categorical", output_has_temporal_axis=False)
    # Custom objectives deliberately retain their independent, unqualified route.
    context = PlannerLossContext(
        output_semantic="continuous",
        output_has_temporal_axis=False,
        objective=LossConfig(loss_type="custom", loss_name="external_exact_loss"),
    )
    assert context.objective.loss_name == "external_exact_loss"


def test_locked_builtin_is_checked_but_custom_math_is_not_reinterpreted():
    with pytest.raises(ValueError, match="no temporal axis"):
        PlannerLossContext(
            output_semantic="categorical",
            output_has_temporal_axis=False,
            objective=LossConfig(loss_type="focal"),
        )
    locked = PlannerLossContext(
        output_semantic="categorical",
        output_has_temporal_axis=False,
        objective=LossConfig(loss_type="ce", reduction="sum"),
    )
    assert locked.objective.model_dump()["reduction"] == "sum"


def test_composed_absence_refuses_instead_of_borrowing_legacy_geometry():
    kwargs = dict(
        dataset=None,
        model_io_contract=None,
        health_config=SimpleNamespace(health_gates=[]),
        efficiency_band_fraction=0.05,
        registry={},
    )
    with pytest.raises(ValueError, match="requires declared ModelIO"):
        build_tuner_task_render(**kwargs, composed=True)
    assert build_tuner_task_render(**kwargs, composed=False).loss_context is None


def test_fixed_model_disagreement_and_unknown_refuse_while_hybrid_uses_task():
    continuous = PlannerLossContext(
        output_semantic="continuous",
        output_has_temporal_axis=False,
    )
    with pytest.raises(ValueError, match=r"declares output.*task ModelIO declares"):
        continuous.validate_fixed_model("punet")
    from ml_models.plugin_loader import UnknownOutputContractError

    with pytest.raises(UnknownOutputContractError):
        continuous.validate_fixed_model("not_registered_309")
    continuous.validate_fixed_model("fcnet")
    continuous.validate_fixed_model("auto")
