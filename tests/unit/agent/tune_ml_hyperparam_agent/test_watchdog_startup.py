"""Invalid watchdog declarations are configuration errors before candidate work."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.ml_hyperparameter_tune_agent.runtime import validate_watchdog_startup


def _input(**settings):
    return HyperparamTuningInput(
        model_type="punet",
        planner_strategy="native-timing-v1",
        **({"runtime_watchdog_enabled": True, "is_trial": True, "max_rounds": 2} | settings),
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"is_trial": False, "formal_time_budget_minutes": 1},
        {"max_rounds": 1, "formal_time_budget_minutes": 1},
        {"plan_overrides": {"is_trial": False}, "formal_time_budget_minutes": 1},
        {"plan_overrides": {"is_trial": "false"}, "formal_time_budget_minutes": 1},
        {
            "plan_overrides": {"is_trial": True},
            "force_formal_round": False,
            "trial_time_budget_minutes": 1,
        },
        {
            "plan_overrides": {"is_trial": "true"},
            "force_formal_round": False,
            "trial_time_budget_minutes": 1,
        },
        {"trial_time_budget_minutes": 1, "formal_time_budget_minutes": 2},
        {"validation_max_phase_seconds": 10},
        {"runtime_watchdog_enabled": False},
        {"runtime_watchdog_deadline_policy": "forecast-tightening-v1"},
    ],
)
def test_unused_role_budget_is_not_required(settings):
    validate_watchdog_startup(_input(**settings))


@pytest.mark.parametrize(
    "settings, role",
    [
        ({}, "Trial"),
        ({"formal_time_budget_minutes": 1}, "Trial"),
        ({"trial_time_budget_minutes": 1}, "Formal"),
        ({"is_trial": False, "trial_time_budget_minutes": 1}, "Formal"),
        ({"max_rounds": 1, "trial_time_budget_minutes": 1}, "Formal"),
        (
            {"plan_overrides": {"is_trial": False}, "trial_time_budget_minutes": 1},
            "Formal",
        ),
        (
            {"plan_overrides": {"is_trial": True}, "trial_time_budget_minutes": 1},
            "Formal",
        ),
        ({"force_formal_round": False, "trial_time_budget_minutes": 1}, "Formal"),
        (
            {
                "is_trial": False,
                "bypass_formal_time_budget_minutes": 30,
                "enable_chain_incumbent_formal_gates": True,
            },
            "Formal",
        ),
    ],
)
def test_invalid_declaration_refused_by_real_run_before_any_runtime_or_llm(
    settings, role, tmp_path, monkeypatch
):
    from importlib import import_module

    node = import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")

    forbidden = Mock(side_effect=AssertionError("startup reached effectful work"))
    monkeypatch.setattr(node, "_run_skill", forbidden)
    monkeypatch.setattr(node, "run_bound_model_io_contract", forbidden)
    inp = _input(
        **settings,
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "invalid"},
        },
    )
    agent = HyperparamTuningAgent(bridge_factory=forbidden, sandbox_factory=forbidden)
    with pytest.raises(ValueError, match=f"Runtime watchdog configuration for {role}"):
        agent.run(inp)
    forbidden.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("composed", [True, False])
def test_composed_single_file_run_on_a_non_tidmad_profile_refused_before_effects(
    composed, tmp_path, monkeypatch
):
    """Defect: with is_trial false every round is single_file, which trains on one
    TIDMAD file; a composed non-TIDMAD task then spends planner calls on attempts that
    can never train. The real run() must refuse at startup, naming the cause, for every
    entry point (fails if the startup check is removed or ignores the profile)."""
    from importlib import import_module

    from agent.schemas.hyperparam_tuning import TaskCompositionRef
    from execute_tools.dataset_config import bind_dataset_profile
    from workflows.task_composition import compose_dataset_profile_from_manifest

    node = import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")
    forbidden = Mock(side_effect=AssertionError("startup reached effectful work"))
    monkeypatch.setattr(node, "_run_skill", forbidden)
    monkeypatch.setattr(node, "run_bound_model_io_contract", forbidden)
    # The output-inventory owner runs first and has its own tests; let it pass here.
    monkeypatch.setattr(node, "resolve_bound_task_data_path", lambda: object())
    monkeypatch.setattr(
        import_module("execute_tools.model_output_retention"),
        "require_local_output_inventory",
        lambda **kwargs: None,
    )
    ref = TaskCompositionRef(
        semantic_fingerprint="quickstart-fixture",
        task_data_path_id="quickstart_tabular",
        task_health_binding=None,
    )
    inp = _input(
        is_trial=False,
        runtime_watchdog_enabled=False,
        task_composition_ref=ref if composed else None,
        storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r"}},
    )
    root = Path(__file__).resolve().parents[4]
    profile = compose_dataset_profile_from_manifest(
        str(root / "configs/task_composition/quickstart.yaml")
    )
    agent = HyperparamTuningAgent(bridge_factory=forbidden, sandbox_factory=forbidden)
    with bind_dataset_profile(profile):
        if composed:
            with pytest.raises(ValueError, match="declares no TIDMAD topology"):
                agent.run(inp)
        else:
            # Un-composed runs keep their legacy path: startup moves on to the next owner.
            with pytest.raises(AssertionError, match="effectful work"):
                agent.run(inp)
    assert not list(tmp_path.iterdir())


def test_tidmad_profile_keeps_single_file_mode():
    """TIDMAD (paper) behavior is unchanged: is_trial false with TIDMAD topology passes."""
    from agent.schemas.hyperparam_tuning import TaskCompositionRef
    from execute_tools.dataset_config import TIDMAD_PROFILE
    from nodes.ml_hyperparameter_tune_agent.runtime import validate_training_mode_startup

    ref = TaskCompositionRef(
        semantic_fingerprint="tidmad", task_data_path_id="tidmad", task_health_binding=None
    )
    validate_training_mode_startup(_input(is_trial=False, task_composition_ref=ref), TIDMAD_PROFILE)
