"""2026-10-08 Assistant transport regression: validated state must survive hops.

Removing the typed projection fields makes Python/JSON reconstruction hand
dictionaries to objective application and strings to the Health sentinel loader.
"""

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    ExperimentPlan,
    HyperparamTuningInput,
    TaskCompositionRef,
)
from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.config import _load_task_binding
from ml_models.models_format_sandbox import LossConfig
from nodes.ml_hyperparameter_tune_agent.planning import _apply_declared_objective


def _input(tmp_path, **projection):
    return HyperparamTuningInput(
        model_type="roundtrip_fixture",
        run_name="roundtrip",
        workspace=str(tmp_path),
        task_composition_ref=TaskCompositionRef(
            semantic_fingerprint="roundtrip-fixture",
            task_data_path_id="fixture-data",
            task_health_binding=projection.pop(
                "task_health_binding", HealthBindingState.EXPLICIT_NONE
            ),
            **projection,
        ),
    )


def _roundtrip(value, mode, *, exclude_unset=False):
    if mode == "python":
        return HyperparamTuningInput.model_validate(
            value.model_dump(mode="python", exclude_unset=exclude_unset)
        )
    return HyperparamTuningInput.model_validate_json(
        value.model_dump_json(exclude_unset=exclude_unset)
    )


@pytest.mark.parametrize("mode", ["python", "json"])
@pytest.mark.parametrize(
    "objective",
    [LossConfig(loss_type="ce"), LossConfig(loss_type="custom", loss_name="fixture_loss")],
    ids=["builtin", "custom"],
)
def test_nested_objective_roundtrip_reaches_real_application(tmp_path, mode, objective):
    """The pre-training incident raised AttributeError at model_dump here."""
    original = _input(tmp_path, objective=objective)
    assert original.task_composition_ref.objective is objective
    restored = _roundtrip(original, mode)
    plan = ExperimentPlan(loss_cfg={"loss_type": "smooth_l1", "beta": 0.5})

    applied = _apply_declared_objective(plan, restored.task_composition_ref)

    assert isinstance(restored.task_composition_ref.objective, LossConfig)
    assert applied.loss_cfg == objective.model_dump()


@pytest.mark.parametrize("mode", ["python", "json"])
@pytest.mark.parametrize("projection", [{}, {"objective": None}], ids=["historical", "none"])
def test_undeclared_objective_keeps_planner_choice_after_transport(tmp_path, mode, projection):
    """The repair must not manufacture a default focal loss for absent objectives."""
    restored = _roundtrip(
        _input(tmp_path, **projection), mode, exclude_unset="objective" not in projection
    )
    plan = ExperimentPlan(loss_cfg={"loss_type": "smooth_l1", "beta": 0.5})
    assert _apply_declared_objective(plan, restored.task_composition_ref).loss_cfg == {
        "loss_type": "smooth_l1",
        "beta": 0.5,
    }


@pytest.mark.parametrize(
    "objective",
    [
        {"loss_type": "unknown"},
        {"loss_type": "custom"},
        {"loss_type": "ce", "loss_name": "fixture_loss"},
        {"loss_type": "focal", "gamma": -1},
        "ce",
    ],
)
def test_nested_transport_rejects_unvalidated_objectives(tmp_path, objective):
    """An Any projection previously let every malformed payload reach execution."""
    payload = _input(tmp_path).model_dump(mode="python")
    payload["task_composition_ref"]["objective"] = objective
    with pytest.raises(ValidationError, match=r"task_composition_ref\.objective"):
        HyperparamTuningInput.model_validate(payload)


@pytest.mark.parametrize("mode", ["python", "json"])
@pytest.mark.parametrize("binding", list(HealthBindingState))
def test_health_absence_roundtrip_never_opens_a_sentinel_as_a_path(tmp_path, mode, binding):
    """JSON previously stripped enum identity and made the loader open its value."""
    restored = _roundtrip(_input(tmp_path, task_health_binding=binding), mode)
    assert restored.task_composition_ref.task_health_binding is binding
    assert _load_task_binding(restored.task_composition_ref.task_health_binding) == (None, ())


@pytest.mark.parametrize("mode", ["python", "json"])
@pytest.mark.parametrize("relative", [False, True], ids=["absolute", "relative"])
def test_health_config_path_roundtrip_still_loads_the_declared_file(
    tmp_path, monkeypatch, mode, relative
):
    """Restoring sentinel identity must preserve the third, explicit-path state."""
    path = tmp_path / "health.yaml"
    path.write_text("roster: []\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    binding = path.name if relative else str(path)
    restored = _roundtrip(_input(tmp_path, task_health_binding=binding), mode)
    assert restored.task_composition_ref.task_health_binding == binding
    assert type(restored.task_composition_ref.task_health_binding) is str
    config, plugins = _load_task_binding(restored.task_composition_ref.task_health_binding)
    assert config is not None
    assert plugins == ()
