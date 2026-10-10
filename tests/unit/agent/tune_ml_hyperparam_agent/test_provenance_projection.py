"""Final workload projection must not retain intermediate values or mutate inputs."""

from agent.prompt_templates.tuner.rendering import render_execution_provenance_block
from agent.schemas.hyperparam_tuning import ExperimentPlan, TrialConfig
from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker


def _config(plan, **overrides):
    fields = {
        name: value for name, value in plan.model_dump().items() if name in TrialConfig.model_fields
    }
    fields.update(mode="formal", train_sampling_seed=1, eval_sampling_seed=1, train_base_seed=1)
    return TrialConfig(**(fields | overrides))


def test_final_projection_restores_authored_value_without_mutating_inputs():
    """An intermediate operator change cannot survive as an EXECUTED claim."""
    authored = ExperimentPlan(trial_portion=0.5)
    tracker = ResolutionTracker(authored)
    intermediate = authored.model_copy(update={"trial_portion": 0.25})
    tracker.record(intermediate, "operator_plan_overrides")
    config = _config(intermediate, trial_portion=0.5)
    before = (authored.model_dump(), intermediate.model_dump(), config.model_dump())
    result = tracker.finish_with_model(
        intermediate, executed_model_type=intermediate.model_type, trial_config=config
    )
    assert not result.events and not result.diverged
    assert render_execution_provenance_block(result) == ""
    assert result.plan_resolution_events is not None
    assert [(e.field_path, e.executed) for e in result.plan_resolution_events] == [
        ("trial_portion", "0.25")
    ]
    assert before == (authored.model_dump(), intermediate.model_dump(), config.model_dump())


def test_final_only_changes_do_not_rewrite_plan_checkpoint_or_prior_authorities():
    """A new execution change must coexist with objective/epoch/model evidence."""
    authored = ExperimentPlan(trial_portion=0.2, train_cfg={"epochs": 20})
    tracker = ResolutionTracker(authored)
    intermediate = authored.model_copy(update={"train_cfg": {"epochs": 3}})
    tracker.record(intermediate, "max_epochs_bound")
    result = tracker.finish_with_model(
        intermediate,
        executed_model_type="custom_model",
        trial_config=_config(intermediate, trial_portion=0.5),
    )
    events = {e.field_path: e for e in result.events}
    assert events["trial_portion"].executed == "0.5"
    assert events["trial_portion"].authority == "resolved_round_workload"
    assert events["train_cfg.epochs"].authority == "max_epochs_bound"
    assert events["model_type"].authority == "forced_model_type"
    assert result.plan_resolution_events is not None
    assert {e.field_path for e in result.plan_resolution_events} == {
        "train_cfg.epochs",
        "model_type",
    }


def test_explicit_ordering_aliases_report_execution_but_unproposed_defaults_do_not():
    """Ordering resolution uses different field names; do not label defaults overrides."""
    for plan in (
        ExperimentPlan(),
        ExperimentPlan(order_strategy="sequential", file_order=[2, 1]),
    ):
        result = ResolutionTracker(plan).finish_with_model(
            plan, executed_model_type=plan.model_type, trial_config=_config(plan)
        )
        if plan.order_strategy is None:
            assert not result.events
        else:
            assert {e.field_path: e.executed for e in result.events} == {
                "order_strategy": "'shuffle'",
                "file_order": "None",
            }


def test_cleared_ordering_proposal_reports_actual_order_not_intermediate_none():
    """Clearing an explicit proposal does not mean that no execution order exists."""
    from nodes.ml_hyperparameter_tune_agent.policy import _apply_plan_overrides

    authored = ExperimentPlan(order_strategy="sequential", file_order=[2, 1])
    tracker = ResolutionTracker(authored)
    intermediate = _apply_plan_overrides(authored, {"order_strategy": None, "file_order": None})
    tracker.record(intermediate, "operator_plan_overrides")
    result = tracker.finish_with_model(
        intermediate,
        executed_model_type=intermediate.model_type,
        trial_config=_config(intermediate),
    )
    events = {e.field_path: e for e in result.events}
    assert events["order_strategy"].executed == "'shuffle'"
    assert events["order_strategy"].authority == "resolved_round_workload"
    assert events["file_order"].executed == "None"

    restored = tracker.finish_with_model(
        intermediate,
        executed_model_type=intermediate.model_type,
        trial_config=_config(
            intermediate, resolved_order_strategy="sequential", resolved_file_order=[2, 1]
        ),
    )
    assert not restored.events
    assert {e.field_path for e in restored.plan_resolution_events} == {
        "order_strategy",
        "file_order",
    }
