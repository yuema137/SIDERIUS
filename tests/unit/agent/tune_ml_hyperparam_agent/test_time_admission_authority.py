"""Single-authority wall-time admission regressions.

These tests distinguish the two executable postures. They fail if forecast
and measured admission both receive an enforcement budget, if Trial and
Formal cannot select independently, or if the Formal bypass ceiling is lost
when measured admission is selected.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    validate_run_invariants,
    write_run_invariants,
)
from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.execution import run_admission_preflight
from nodes.ml_hyperparameter_tune_agent.policy import resolve_measured_time_budget
from nodes.ml_hyperparameter_tune_agent.runtime import (
    RuntimeEvidenceChannelError,
    _build_runtime_policy,
    apply_forecast_time_authority,
)
from tests.helpers.metric_fixtures import accuracy_like_spec


@pytest.mark.parametrize("is_trial", [True, False])
def test_measured_is_the_only_in_process_admission_authority(is_trial, tmp_path):
    policy = _build_runtime_policy(
        HyperparamTuningInput.model_construct(
            runtime_watchdog_enabled=False,
            runtime_safety_factor=1.0,
            runtime_trial_safety_factor=None,
            runtime_formal_safety_factor=None,
            runtime_watchdog_floor_seconds=60.0,
        ),
        chosen_time_budget=7.0,
        admission_source="measured",
        is_trial=is_trial,
        base_dir=str(tmp_path),
    )

    assert policy["operator_budget_seconds"] == 420.0
    assert policy["time_admission_source"] == "measured"


@pytest.mark.parametrize("is_trial", [True, False])
def test_forecast_keeps_in_process_measurement_record_only(is_trial, tmp_path):
    policy = _build_runtime_policy(
        HyperparamTuningInput.model_construct(
            runtime_watchdog_enabled=False,
            runtime_safety_factor=1.0,
            runtime_trial_safety_factor=None,
            runtime_formal_safety_factor=None,
            runtime_watchdog_floor_seconds=60.0,
        ),
        chosen_time_budget=7.0,
        admission_source="forecast",
        is_trial=is_trial,
        base_dir=str(tmp_path),
    )

    assert policy["operator_budget_seconds"] is None
    assert policy["time_admission_source"] == "forecast"


@pytest.mark.parametrize(("over_budget", "expected_feasible"), [(False, True), (True, False)])
def test_forecast_budget_comparison_is_authoritative(over_budget, expected_feasible):
    """Static policy advice cannot override an explicitly selected forecast."""
    result = {
        "feasible": True,
        "breakdown": {
            "runtime_decision": "ALLOW",
            "over_effective_budget": over_budget,
        },
    }

    apply_forecast_time_authority(result)

    assert result["feasible"] is expected_feasible
    assert result["breakdown"]["selected_admission_authority"] == "forecast"


def test_forecast_without_a_budget_comparison_fails_closed():
    with pytest.raises(RuntimeEvidenceChannelError, match="over_effective_budget"):
        apply_forecast_time_authority({"feasible": True, "breakdown": {}})


def test_production_preflight_selects_forecast_without_resolving_a_probe():
    """The live tuner must not silently combine forecast and measurement."""
    tree = ast.parse(inspect.getsource(run_admission_preflight))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "apply_forecast_time_authority" in calls
    assert "_resolve_time_check_probe_request" not in calls


def test_measured_formal_bypass_raises_only_a_qualified_attempt():
    order = MetricOrder(accuracy_like_spec())
    qualified = {"denoising_score": 0.8}

    assert (
        resolve_measured_time_budget(
            base_budget_minutes=120.0,
            admission_source="measured",
            is_formal_round=True,
            formal_trial_winner=qualified,
            bypass_threshold=0.7,
            bypass_ceiling_minutes=200.0,
            order=order,
        )
        == 200.0
    )
    assert (
        resolve_measured_time_budget(
            base_budget_minutes=120.0,
            admission_source="measured",
            is_formal_round=True,
            formal_trial_winner=qualified,
            bypass_threshold=0.9,
            bypass_ceiling_minutes=200.0,
            order=order,
        )
        == 120.0
    )


def test_forecast_bypass_remains_owned_by_forecast_re_evaluation():
    assert (
        resolve_measured_time_budget(
            base_budget_minutes=120.0,
            admission_source="forecast",
            is_formal_round=True,
            formal_trial_winner={"denoising_score": 0.8},
            bypass_threshold=0.7,
            bypass_ceiling_minutes=200.0,
            order=MetricOrder(accuracy_like_spec()),
        )
        == 120.0
    )


def test_resume_refuses_a_changed_time_admission_authority(tmp_path):
    """A source change cannot fold two decision policies into one workspace."""
    locked = RunInvariants(
        resolved_data_scope=[0],
        health_gate_enabled=False,
        health_config_sha256=None,
        runtime_estimator_identity="estimator-v1",
        runtime_policy_identity="policy-v1",
        trial_time_admission_source="measured",
        formal_time_admission_source="measured",
    )
    write_run_invariants(str(tmp_path), locked)

    changed = locked.model_copy(update={"trial_time_admission_source": "forecast"})
    with pytest.raises(RunInvariantsViolation, match="trial_time_admission_source"):
        validate_run_invariants(str(tmp_path), changed)
