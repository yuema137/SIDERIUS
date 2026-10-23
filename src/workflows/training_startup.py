"""Native scope, Health and launch-lock preparation, without lock publication.

Callers validate their ingress and run the launch self-test before publishing
these invariants. This boundary never loads history or mutates chain state.
"""

from dataclasses import dataclass

from agent.schemas.ordering import OrderStrategy
from core.run_invariants import (
    LockLaunchIdentity,
    RunHealthMaterialization,
    RunInvariants,
    build_run_invariants,
    effective_watchdog_deadline_policy,
)
from execute_tools.dataset_config import DataScope, resolve_dataset_profile
from workflows.literature_config import lit_review_config_sha256
from workflows.llm_config import WorkflowLLMConfig
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import RunTaskComposition
from workflows.task_settings import validate_scope_settings


@dataclass(frozen=True)
class TrainingRunPreparation:
    resolved_scope: tuple[int, ...]
    partition_count: int
    scope_is_partial: bool
    invariants: RunInvariants
    effective_health_config: str | None
    tuner_health_source: str | None


def resolve_tuner_health_config_source(
    *,
    task_composition: object | None,
    effective_config_path: str | None,
    operator_config: str | None,
) -> str | None:
    """The original HealthGate source the workflow hands the tuner.

    The chain and tuner each materialize the effective config in their own
    workspace. They must start from the same original source and the same
    task binding. Passing the chain's already-materialized file through a
    second materialization drops its ``resolved_plugins`` provenance marker,
    changes ``health_config_sha256``, and makes iteration two refuse iteration
    one's otherwise-comparable records.

    The tuner now receives the task binding through ``TaskCompositionRef``.
    Therefore the old workaround of substituting the chain-level effective
    path is no longer needed and is actively incorrect. Keeping this named
    boundary documents the transport rule and avoids reintroducing an inline
    branch at the orchestration site.

    Args:
        task_composition: retained for call-site compatibility; the binding
            itself crosses through ``TaskCompositionRef``.
        effective_config_path: retained for call-site compatibility and never
            forwarded because an effective artifact is not an input source.
        operator_config: the operator's raw ``--health_checks_config`` value.

    Returns:
        ``operator_config`` unchanged.
    """
    del task_composition, effective_config_path
    return operator_config


# ---------------------------------------------------------------------------
# L6c — Loss promotion to the global library
# ---------------------------------------------------------------------------


def workflow_lock_identity(
    launch: WorkflowLaunchConfig, llm_config: WorkflowLLMConfig
) -> LockLaunchIdentity:
    """The workflow's arXiv-U1/U3 lock identity, from the launch config.

    Pure construction, extracted from ``run_workflow`` under the 12a
    structural budget (the SE.2 idiom). An unlabelled, lit-review-OFF launch
    yields the defaults, so its lock is byte-identical (the keys are
    omitted, never null); the config sha is derived from the SAME resolved
    path the lit-review branch later opens, so the lock always pins the file
    the run reads.
    """
    from agent.data_analysis.source_scope import source_prompt_identity
    from agent.planner_strategy import resolve_planner_strategy

    return LockLaunchIdentity(
        gpu_execution_policy=launch.gpu_execution_policy,
        planner_strategy_identity=resolve_planner_strategy(
            llm_config.get("tune").get("planner_strategy")
        ).identity,
        lit_review_enabled=launch.lit_review_enabled,
        data_analysis_enabled=launch.data_analysis_enabled,
        lit_review_config_sha256=lit_review_config_sha256(
            launch.lit_review_config_path, enabled=launch.lit_review_enabled
        ),
        scientific_evidence_order=launch.scientific_evidence_order,
        experiment_arm=launch.experiment_arm,
        # arXiv U3 — the WITHOUT arm's isolation flag is a prompt-surface
        # identity, so it is locked like the topology.
        baseline_isolation=launch.baseline_isolation,
        # Gold campaign — the advice pin the LAUNCHER observed, carried on
        # the launch config and never re-derived here. Re-hashing the file at
        # this point would describe whatever is on disk when the workflow
        # starts rather than what the launch certified, which is the
        # recomputation defect F-12bc-7 named: a pin that follows the very
        # edit it exists to catch.
        advice_sha256=launch.advice_sha256,
        advice_path=launch.advice_path,
        analysis_source_prompt_sha256=source_prompt_identity(launch.analysis_source_prompt),
        retain_model_outputs=launch.retain_model_outputs,
        retain_training_checkpoints=launch.retain_training_checkpoints,
        # F-SCANF-1 — the formal round's evaluation FRACTION, from the SAME
        # launch config the tuner child receives it from, so the chain lock
        # and the tuner sub-workspace lock cannot disagree.
        training_validation_portion=launch.training_validation_portion,
        formal_eval_portion=launch.formal_eval_portion,
        validation_max_portion=launch.validation_max_portion,
        validation_max_samples=launch.validation_max_samples,
        formal_training_scope_source=launch.formal_training_scope_source,
        disclose_execution_constraints=launch.disclose_execution_constraints,
        workflow_parameter_rules=(
            None
            if launch.workflow_parameter_rules is None
            else launch.workflow_parameter_rules.model_dump(mode="json", exclude_none=True)
        ),
        trial_time_admission_source=launch.trial_time_admission_source,
        formal_time_admission_source=launch.formal_time_admission_source,
        runtime_watchdog_deadline_policy=effective_watchdog_deadline_policy(
            launch.runtime_watchdog_enabled, launch.runtime_watchdog_deadline_policy
        ),
        runtime_completion_policy=launch.runtime_completion_policy,
        runtime_verifier_identity=launch.runtime_verifier_identity,
    )


def prepare_training_run(
    *,
    launch: WorkflowLaunchConfig,
    workspace: str,
    llm_config: WorkflowLLMConfig,
    task_composition: RunTaskComposition | None,
    data_scope: DataScope | None,
    health_gate_enabled: bool,
    health_gate_files: list[int] | None,
    health_checks_config: str | None,
    order_strategy_override: OrderStrategy | None,
    file_order_override: list[int] | None,
    enable_structured_health_feedback: bool,
) -> TrainingRunPreparation:
    """Resolve scope and materialize Health; leave lock publication to the caller."""
    _run_scope = data_scope if data_scope is not None else DataScope.default()
    # Step 10 / P1 (S1) — the run's OWN dataset topology, not the module-level
    # TIDMAD import this file used to resolve scope against. Un-composed this
    # is byte-identical: `resolve_dataset_profile()` returns `TIDMAD_PROFILE`
    # and `TIDMAD_PROFILE.dataset` IS the `TIDMAD` singleton (same object).
    # Composed, it is the composed profile — without this a composed 4-file
    # task would have had its scope resolved against TIDMAD's 20 files and
    # its `scope_is_partial` computed from somebody else's topology.
    _run_partitions = resolve_dataset_profile().partition_count
    _resolved_scope = _run_scope.resolve(_run_partitions)
    _scope_is_partial = _resolved_scope != list(range(_run_partitions))
    validate_scope_settings(
        scope_is_partial=_scope_is_partial,
        formal_strategy=launch.formal_strategy,
        task_composition=task_composition,
        health_gate_enabled=health_gate_enabled,
        health_gate_files=health_gate_files,
    )
    _run_invariants, _run_effective_health_config = build_run_invariants(
        resolved_data_scope=_resolved_scope,
        health_gate_enabled=health_gate_enabled,
        health_gate_files=health_gate_files,
        health_checks_config=health_checks_config,
        workspace=workspace,
        # V19 PR 2 — must match what the tuner locks for this workspace,
        # or the two would write contradictory locks and abort the run.
        ordering_override_strategy=order_strategy_override,
        ordering_override_file_order=file_order_override,
        # V19 PR 3 — same rule for the structured-health-feedback policy.
        structured_health_feedback_enabled=enable_structured_health_feedback,
        health_feedback_history_window_iterations=(
            launch.health_feedback_history_window_iterations
        ),
        health_feedback_history_max_entries_per_model=(
            launch.health_feedback_history_max_entries_per_model
        ),
        # Step 10 / P1 — the composed task Health binding and the composed
        # run's semantic identity. Both are `None` for an un-composed run,
        # which keeps 08b's `LEGACY_OMITTED` resolution and leaves the
        # workspace lock byte-identical (the fingerprint key is OMITTED, not
        # serialized as null — design §5.9).
        health_materialization=RunHealthMaterialization(
            task_health_binding=(
                task_composition.task_health_binding if task_composition is not None else None
            )
        ),
        task_composition_fingerprint=(
            task_composition.semantic_fingerprint if task_composition is not None else None
        ),
        # arXiv U1 (#253 / #254) — workflow topology + experiment arm,
        # built by the ONE module-level helper (the SE.2 extraction under the
        # 12a budget); the config sha is derived from the same resolved path
        # the lit-review branch below opens.
        launch_identity=workflow_lock_identity(launch, llm_config),
    )
    return TrainingRunPreparation(
        tuple(_resolved_scope),
        _run_partitions,
        _scope_is_partial,
        _run_invariants,
        _run_effective_health_config,
        resolve_tuner_health_config_source(
            task_composition=task_composition,
            effective_config_path=_run_effective_health_config,
            operator_config=health_checks_config,
        ),
    )
