"""Invalid watchdog declarations are configuration errors before candidate work."""

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
