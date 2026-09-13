"""Regression #309: offers must query execution, not repeat its matrix."""

from types import SimpleNamespace

import pytest

from agent.prompt_templates.tuner.loss_context import PlannerLossContext
from agent.prompt_templates.tuner.rendering import build_tuner_task_render
from agent.schemas.model_io_contract import ModelIOContract
from ml_models import models_format_sandbox as authority
from ml_models.models_format_sandbox import LossConfig, OutputSemantic
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.helpers.tuner_prompt_fixtures import planner_kwargs


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


def _render(*, categorical=True, temporal=False, objective=None):
    axes = [{"dimension": {"symbolic": "B"}, "role": "batch"}]
    if categorical:
        axes.append({"dimension": {"fixed": 3}, "role": "class"})
    if temporal:
        axes.append({"dimension": {"symbolic": "T"}, "role": "temporal"})
    tensor = {"axes": axes, "dtype": {"admissible": ["float32"]}}
    contract = ModelIOContract.model_validate({"input": tensor, "output": tensor})
    return build_tuner_task_render(
        dataset=None,
        model_io_contract=contract,
        health_config=SimpleNamespace(health_gates=[]),
        efficiency_band_fraction=0.05,
        registry={},
        composed=True,
        objective=objective,
    )


@pytest.mark.parametrize(
    ("categorical", "temporal", "model", "expected", "example"),
    [
        (True, False, "auto", "ce", '"loss_type": "ce"'),
        (True, False, "punet", "ce", '"loss_type": "ce"'),
        (True, True, "punet", "focal, focal_cw, ce", '"loss_type": "focal"'),
        (False, False, "auto", "smooth_l1", '"loss_type": "smooth_l1"'),
        (False, False, "fcnet", "smooth_l1", '"loss_type": "smooth_l1"'),
    ],
)
def test_actual_bridge_system_user_and_example_agree(
    categorical, temporal, model, expected, example
):
    bridge = BoundaryRecorderBridge()
    bridge.plan(
        **{
            **planner_kwargs(),
            "force_model": model,
            "task_render": _render(categorical=categorical, temporal=temporal),
        }
    )
    assert len(bridge.captures) == 1
    _, _, system, user = bridge.captures[0]
    for prompt in (system, user):
        assert f"Compatible builtin loss types: **{expected}**" in prompt
        assert "switch immediately to focal" not in prompt
        assert "ce/focal/smooth_l1" not in prompt
        if not temporal:
            assert "focal" not in prompt
    assert example in user


@pytest.mark.parametrize(
    "loss",
    [
        LossConfig(loss_type="ce", reduction="sum"),
        LossConfig(loss_type="custom", loss_name="external_loss"),
    ],
)
def test_locked_objective_reaches_all_loss_instruction_surfaces(loss):
    from agent.prompts import build_exploration_checklist
    from tests.helpers.tuner_prompt_fixtures import HISTORY

    render = _render(objective=loss)
    checklist = build_exploration_checklist({}, HISTORY, loss_context=render.loss_context)
    bridge = BoundaryRecorderBridge()
    bridge.plan(**{**planner_kwargs(), "task_render": render, "exploration_checklist": checklist})
    assert len(bridge.captures) == 1
    _, _, system, user = bridge.captures[0]
    for prompt in (system, user):
        assert loss.model_dump_json() in prompt
        assert "Task objective is LOCKED" in prompt
        assert "Cycle through" not in prompt
        assert "Valid loss types" not in prompt
    assert "not exploration levers" in user
    assert "loss_config is task-locked (not a control surface)" in user
    assert "architecture, lr, and loss_type" not in user
    assert "cost an extra implementor" not in system


def test_actual_bridge_refuses_model_conflict_before_call():
    bridge = BoundaryRecorderBridge()
    with pytest.raises(ValueError, match="task ModelIO declares continuous"):
        bridge.plan(
            **{
                **planner_kwargs(),
                "force_model": "punet",
                "task_render": _render(categorical=False),
            }
        )
    assert bridge.captures == []


def test_custom_inventory_is_not_presented_as_task_geometry_certification():
    meta = SimpleNamespace(
        name="existing_custom",
        created_at="2026-09-12",
        description="test loss",
        source_iteration="test",
    )
    registry = SimpleNamespace(list=lambda **kwargs: [meta])
    bridge = BoundaryRecorderBridge()
    bridge.plan(**{**planner_kwargs(), "registry": registry, "task_render": _render()})
    _, _, system, user = bridge.captures[0]
    assert "existing_custom" in system
    assert "do NOT certify compatibility" in system
    assert "do NOT certify compatibility" in user
    assert "already generated and validated" not in user
