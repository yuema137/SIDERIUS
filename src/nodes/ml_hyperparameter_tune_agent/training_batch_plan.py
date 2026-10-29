"""Resolve one executable batch size before measurement and execution diverge."""

from collections.abc import Sized

from agent.schemas.execution_provenance import ExecutionProvenance, TrainingBatchFit
from agent.schemas.hyperparam_tuning import ExperimentPlan, TrialConfig
from agent.schemas.parameter_rules import apply_parameter_rules
from core.training_seeds import TrainingSeedPlan
from execute_tools.task_data_path import EpochSamplingParams, TrainingScopeError
from ml_models.models_format_sandbox import TrainConfig
from nodes.ml_hyperparameter_tune_agent.contracts import RunBindings
from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import AttemptScopes


class TrainingBatchPlanError(TrainingScopeError):
    """The resolved role scope cannot train under its declared batch constraints."""


def training_batch_fit_record(provenance: ExecutionProvenance) -> dict[str, object]:
    """Persist only an actual adjustment; fitting attempts retain record bytes."""
    receipt = provenance.training_batch_fit
    return {} if receipt is None else {"training_batch_fit": receipt.model_dump(mode="json")}


def _batch_lock(bindings: RunBindings) -> str | None:
    inputs = bindings.agent_input
    composition = inputs.task_composition_ref
    for owner, rules in (
        ("task", composition.parameter_rules if composition is not None else None),
        ("workflow", inputs.workflow_parameter_rules),
    ):
        rule = rules.rules.get("train_config.batch_size") if rules is not None else None
        if rule is not None and rule.kind == "exact":
            return f"{owner} parameter_rules exact lock on train_config.batch_size"
    override = inputs.plan_overrides.get("train_config", {})
    if "batch_size" in override:
        return "operator plan_overrides lock on train_config.batch_size"
    return None


def resolve_training_batch_plan(
    plan: ExperimentPlan,
    *,
    bindings: RunBindings,
    trial_config: TrialConfig,
    scopes: AttemptScopes,
    resolution: ResolutionTracker,
    model_type: str,
) -> ExperimentPlan:
    """Keep fitting plans byte-identical; adjust only an empty full-batch epoch.

    Count the task's materialized first-epoch dataset with the same seed,
    portion and row ceiling that training/measurement consume. No sample is
    read by this owner. Dataset construction costs remain task-owned, as in
    the existing task workload resolver. Legacy uncomposed scopes are unchanged.
    """
    if scopes.training is None:
        return plan
    inputs = bindings.agent_input
    config = TrainConfig.model_validate(plan.train_cfg)
    if not bindings.time_data_dir:
        raise TrainingBatchPlanError("Training batch planning requires the resolved data root")
    dataset = bindings.run_task_data_path.training_dataset(
        scopes.training,
        EpochSamplingParams(
            data_dir=bindings.time_data_dir,
            epoch_seed=TrainingSeedPlan(trial_config.seed_context).epoch(0).subsample,
            train_portion=trial_config.train_portion,
            max_samples=inputs.validation_max_train_samples,
        ),
    )
    if not isinstance(dataset, Sized):
        raise TrainingBatchPlanError("Training batch planning requires a sized training dataset")
    rows = len(dataset)
    if rows == 0:
        raise TrainingBatchPlanError(
            f"{trial_config.mode} training scope contains no training samples"
        )
    if not config.drop_last or rows >= config.batch_size:
        return plan
    lock = _batch_lock(bindings)
    if lock is not None:
        raise TrainingBatchPlanError(
            f"{trial_config.mode} training scope has {rows} samples, but batch_size "
            f"{config.batch_size} with drop_last=True cannot train one step; {lock} prevents clamping"
        )
    adjusted = plan.model_copy(deep=True)
    adjusted.train_cfg["batch_size"] = rows
    composition = inputs.task_composition_ref
    # Revalidate range/allowed/predicate rules after adjustment. Their existing
    # typed refusal must not be bypassed by this later resolution step.
    adjusted = apply_parameter_rules(
        adjusted,
        task_rules=composition.parameter_rules if composition is not None else None,
        workflow_rules=inputs.workflow_parameter_rules,
        executed_model_type=model_type,
    )
    resolution.record_training_batch_fit(
        adjusted,
        TrainingBatchFit(
            role=trial_config.mode,
            requested_batch_size=config.batch_size,
            resolved_batch_size=rows,
            available_samples=rows,
        ),
    )
    print(
        f"[training_batch] {trial_config.mode} batch_size clamped from "
        f"{config.batch_size} to {rows}: the training scope has {rows} samples"
    )
    return adjusted
