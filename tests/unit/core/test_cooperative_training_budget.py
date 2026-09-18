"""Budget allocation must expand fast work, preserve reserve, and never reset time."""

from core.runtime_control.training_budget import TrainingBudgetEnvelope, decide_training_budget


def envelope(**changes):
    return TrainingBudgetEnvelope.model_validate(
        {
            "budget_seconds": 120,
            "reserve_fraction": 0.2,
            "max_epochs": 100,
            "started_monotonic_seconds": 0,
            **changes,
        }
    )


def test_fast_work_extends_until_next_complete_epoch_no_longer_fits():
    policy = envelope()
    costs = []
    elapsed = 5
    while (
        decide_training_budget(
            policy,
            elapsed_seconds=elapsed,
            completed_epochs=len(costs),
            observed_epoch_seconds=costs,
        ).action
        == "continue"
    ):
        elapsed += 2
        costs.append(2)
    decision = decide_training_budget(
        policy, elapsed_seconds=elapsed, completed_epochs=len(costs), observed_epoch_seconds=costs
    )
    assert len(costs) == 45  # 95 + next 2 + reserve 24 > total 120.
    assert decision.reason == "time_budget"
    assert decision.remaining_seconds == 25


def test_slowdown_and_explicit_cap_have_distinct_stop_reasons():
    slowed = decide_training_budget(
        envelope(), elapsed_seconds=67, completed_epochs=2, observed_epoch_seconds=[2, 60]
    )
    assert slowed.action == "stop" and slowed.reason == "time_budget"
    capped = decide_training_budget(
        envelope(max_epochs=2), elapsed_seconds=9, completed_epochs=2, observed_epoch_seconds=[2, 2]
    )
    assert capped.action == "stop" and capped.reason == "epoch_cap"
    exhausted = decide_training_budget(
        envelope(), elapsed_seconds=97, completed_epochs=0, observed_epoch_seconds=[]
    )
    assert exhausted.action == "stop"


def test_forecast_and_formal_receive_independent_allocations(tmp_path):
    """Forecast record-only admission must not drop the execution allowance."""
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from core.runtime_control.session import RuntimeControlPolicy
    from nodes.ml_hyperparameter_tune_agent import _build_runtime_policy

    inputs = HyperparamTuningInput.model_construct(
        training_budget_reserve_fraction=0.2,
        trial_max_epochs=100,
        formal_max_epochs=80,
    )
    for trial, minutes, cap in ((True, 30, 100), (False, 120, 80)):
        policy = RuntimeControlPolicy.model_validate(
            _build_runtime_policy(
                inputs,
                chosen_time_budget=minutes,
                admission_source="forecast",
                is_trial=trial,
                base_dir=str(tmp_path),
            )
        )
        assert policy.operator_budget_seconds is None
        assert policy.training_budget.budget_seconds == minutes * 60
        assert policy.training_budget.max_epochs == cap
        assert policy.training_budget.reserved_seconds == minutes * 12


def test_reserve_cli_is_parsed_and_has_a_protocol_destination():
    """Catch the formerly missed protocol hop between workflow and tuner."""
    import inspect

    from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
    from workflows.run_one_iteration import build_parser

    args = build_parser().parse_args(
        [
            "--workspace",
            "/tmp/budget-test",
            "--run_name",
            "budget-test",
            "--task_composition",
            "/tmp/composition.yaml",
            "--data_dir",
            "/tmp/data",
            "--training_budget_reserve_fraction",
            ".2",
        ]
    )
    assert args.training_budget_reserve_fraction == 0.2
    assert "training_budget_reserve_fraction" in inspect.signature(local_validated_model).parameters


def test_completed_workload_reprices_verified_rate_without_losing_initial_forecast(tmp_path):
    from core.runtime_control.session import RuntimeVerificationSession
    from core.runtime_control.workload import ResolvedPhaseWorkload

    session = RuntimeVerificationSession(str(tmp_path / "runtime.json"), attempt_id="reprice")
    session.complete_setup(
        storage_provenance={},
        training_workload=ResolvedPhaseWorkload(
            phase="training",
            unit="optimizer_step",
            unit_count=100,
        ),
    )
    verifier = session.start_phase_verification("training", unit="optimizer_step")
    for _ in range(200):
        verifier.feed(20)
        if verifier.is_terminal:
            break
    session.complete_phase_verification("training", verifier, source="real_training_verification")
    session.record_executed_workload(
        ResolvedPhaseWorkload(
            phase="training",
            unit="optimizer_step",
            unit_count=300,
        ),
        extra_predicted_seconds=0.5,
    )
    component = session.observation.components["training"]
    assert component.prediction.predicted_seconds == 6.5
    assert component.prediction.unit_count == component.workload.unit_count == 300
    assert component.prediction.formal_execution_eligible
    assert component.workload.detail["initial_prediction"]["predicted_seconds"] == 2
    assert component.prediction.detail["scope_resolution"] == "post_execution_reprojection"


def test_existing_step_guard_and_explicit_override_reach_executor(tmp_path):
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from core.runtime_control.session import RuntimeControlPolicy
    from nodes.ml_hyperparameter_tune_agent import _build_runtime_policy

    for override in (False, True):
        inputs = HyperparamTuningInput.model_construct(
            training_budget_reserve_fraction=0.2,
            max_epochs=100,
            max_steps_per_attempt=150000,
            allow_extreme_steps=override,
        )
        policy = RuntimeControlPolicy.model_validate(
            _build_runtime_policy(
                inputs,
                chosen_time_budget=30,
                admission_source="forecast",
                is_trial=True,
                base_dir=str(tmp_path),
            )
        )
        assert policy.training_budget.max_optimizer_steps == (None if override else 150000)


def test_materialized_epoch_step_guard_refuses_before_first_optimizer():
    import time

    import pytest

    from execute_tools.training_budget_execution import TrainingBudgetExecution

    executor = TrainingBudgetExecution(
        envelope(max_optimizer_steps=10, started_monotonic_seconds=time.monotonic()),
        proposed_epochs=1,
    )
    executor.start_epoch()
    with pytest.raises(ValueError, match="reason=step_limit, next_optimizer_steps=11"):
        executor.admit_materialized_epoch(optimizer_steps=11)
    assert executor.optimizer_steps == 0
