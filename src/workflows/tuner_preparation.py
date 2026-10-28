"""Native workflow context projection into the validator-to-tuner protocol.

The caller owns validation admission, staging, promotion and agent execution.
This boundary maps their established values and loads task prose after protocol
construction, preserving the native workflow's input failure order.
"""

from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from agent.schemas.storage import StorageConfig
from agent.schemas.validator import ValidatorOutput
from core.run_invariants import RunInvariants
from core.seeding import SeedCoordinates
from workflows.llm_config import resolve_standard_tuner_llm_options
from workflows.run_bindings import WorkflowRunBindings
from workflows.run_config import WorkflowLaunchConfig, frozen_portion_overrides
from workflows.task_composition import build_task_composition_ref
from workflows.task_config import get_task_description, load_task_config

# Transit-only portions retain their input-schema defaults when agent-controlled.
# Executed experiment-fixed portions remain owned by frozen_portion_overrides.
_TUNER_INPUT_PORTION_DEFAULTS: dict[str, float] = {
    name: HyperparamTuningInput.model_fields[name].default
    for name in ("trial_portion", "train_portion", "eval_portion")
}


def _portion_or(value: float | None, fallback: float) -> float:
    return fallback if value is None else value


def prepare_native_tuner_input(
    *,
    validation: ValidatorOutput,
    proposal: ProposalOutput,
    storage: StorageConfig,
    launch: WorkflowLaunchConfig,
    bindings: WorkflowRunBindings,
    run_invariants: RunInvariants,
    constraint_context: ConstraintContext | None,
    chain_formal_incumbent_reference: float | None,
    seed_coordinates: SeedCoordinates,
) -> HyperparamTuningInput:
    """Build the native tuner request from already admitted workflow context.

    Protocol/schema and late task-loading failures propagate to the caller.
    No launch, bindings, state, artifact or execution policy is mutated here.
    """
    # Startup always normalizes routing before constructing run bindings.
    assert bindings.llm_config is not None
    tune_llm = resolve_standard_tuner_llm_options(bindings.llm_config.get("tune"))
    tune_input = local_validated_model(
        validation,
        proposal,
        storage,
        max_rounds=launch.max_rounds,
        health_checks_config=bindings.health_checks_config,
        measurement_capability=bindings.measurement_capability,
        # Step 12 / PR-12a (D-12a-1) — the composition projection crosses
        # the edge on the INPUT, beside every other run-scoped decision
        # this protocol already maps.
        constraint_context=constraint_context,
        task_composition_ref=build_task_composition_ref(bindings.task_composition),
        workflow_parameter_rules=launch.workflow_parameter_rules,
        disclose_execution_constraints=launch.disclose_execution_constraints,
        data_scope=bindings.data_scope,
        health_gate_enabled=bindings.health_gate_enabled,
        health_gate_files=(
            list(bindings.health_gate_files) if bindings.health_gate_files is not None else None
        ),
        # V21 PR D — hop 7 -> hop 8, unchanged including `None`.
        healthgate_mode=launch.healthgate_mode,
        result_authority=launch.result_authority,
        file_index=launch.file_index,
        llm_provider=tune_llm["provider"],
        llm_model_id=tune_llm["model_id"],
        reasoning_effort=tune_llm.get("reasoning_effort"),
        max_output_tokens=tune_llm.get("max_output_tokens"),
        reflect_max_output_tokens=tune_llm.get("reflect_max_output_tokens"),
        planner_strategy=tune_llm.get("planner_strategy"),
        expected_planner_strategy=run_invariants.planner_strategy_identity,
        reflect_provider=tune_llm.get("reflect_provider"),
        reflect_model_id=tune_llm.get("reflect_model_id"),
        reflect_reasoning_effort=tune_llm.get("reflect_reasoning_effort"),
        reflect_retry_policy=tune_llm.get("reflect_retry_policy"),
        is_trial=launch.is_trial,
        # Lane F2 — TRANSIT-ONLY fields (no tuner consumer); a bare
        # launch restores the input-schema default so input bytes are
        # byte-identical to pre-F2 runs. The EXECUTED lock is the
        # plan_overrides merge above.
        trial_portion=_portion_or(
            launch.trial_portion, _TUNER_INPUT_PORTION_DEFAULTS["trial_portion"]
        ),
        train_portion=_portion_or(
            launch.train_portion, _TUNER_INPUT_PORTION_DEFAULTS["train_portion"]
        ),
        eval_portion=_portion_or(
            launch.eval_portion, _TUNER_INPUT_PORTION_DEFAULTS["eval_portion"]
        ),
        train_validation_align=launch.train_validation_align,
        run_seed=run_invariants.run_seed,
        judge_routes=run_invariants.judge_routes,
        seed_coordinates=seed_coordinates,
        cleanup_denoised=launch.cleanup_denoised,
        retain_model_outputs=launch.retain_model_outputs,
        retain_training_checkpoints=launch.retain_training_checkpoints,
        max_epochs=launch.max_epochs,
        # D-BUD-6 — per-mode epoch ceilings, carried through unchanged
        # including `None` (None = mode-agnostic max_epochs governs).
        training_budget_reserve_fraction=launch.training_budget_reserve_fraction,
        trial_max_epochs=launch.trial_max_epochs,
        formal_max_epochs=launch.formal_max_epochs,
        validation_max_portion=launch.validation_max_portion,
        validation_max_train_samples=launch.validation_max_train_samples,
        training_validation_portion=launch.training_validation_portion,
        validation_max_samples=launch.validation_max_samples,
        validation_max_phase_seconds=launch.validation_max_phase_seconds,
        skip_formal_min_delta=launch.skip_formal_min_delta,
        bypass_formal_time_budget_min_delta=launch.bypass_formal_time_budget_min_delta,
        bypass_formal_time_budget_minutes=launch.bypass_formal_time_budget_minutes,
        max_retries=tune_llm.get("max_retries"),
        # Lane F2 — EXPERIMENT_FIXED portions join the plan_overrides
        # lock here (typed-only; conflict with explicit JSON refuses).
        plan_overrides=frozen_portion_overrides(launch),
        trial_time_budget_minutes=launch.trial_time_budget_minutes,
        formal_time_budget_minutes=launch.formal_time_budget_minutes,
        trial_time_admission_source=launch.trial_time_admission_source,
        formal_time_admission_source=launch.formal_time_admission_source,
        runtime_completion_policy=launch.runtime_completion_policy,
        runtime_verifier=launch.runtime_verifier,
        runtime_verifier_identity=launch.runtime_verifier_identity,
        data_dir=launch.data_dir,
        gpu_execution_policy=launch.gpu_execution_policy,
        gpu_admission_measurement_source=launch.gpu_admission_measurement_source,
        gpu_admission_enforcement=launch.gpu_admission_enforcement,
        gpu_pair_ceiling_gib=launch.gpu_pair_ceiling_gib,
        trial_vram_budget_gb=launch.trial_vram_budget_gb,
        formal_vram_budget_gb=launch.formal_vram_budget_gb,
        vram_probe_step_timeout_seconds=launch.vram_probe_step_timeout_seconds,
        vram_preflight_total_timeout_seconds=(launch.vram_preflight_total_timeout_seconds),
        vram_preflight_host_memory_limit_gb=(launch.vram_preflight_host_memory_limit_gb),
        formal_strategy=launch.formal_strategy,
        formal_training_scope_source=launch.formal_training_scope_source,
        formal_portion=launch.formal_portion,
        formal_train_portion=launch.formal_train_portion,
        formal_eval_portion=launch.formal_eval_portion,
        force_formal_round=launch.force_formal_round,
        formal_round_strategy=launch.formal_round_strategy,
        degenerate_penalty_score=launch.degenerate_penalty_score,
        attempts_per_round=launch.attempts_per_round,
        attempts_per_formal_round=launch.attempts_per_formal_round,
        max_fail_rounds=launch.max_fail_rounds,
        max_steps_per_attempt=launch.max_steps_per_attempt,
        min_formal_batch_size=launch.min_formal_batch_size,
        allow_extreme_steps=launch.allow_extreme_steps,
        runtime_watchdog_deadline_policy=launch.runtime_watchdog_deadline_policy,
        runtime_watchdog_enabled=launch.runtime_watchdog_enabled,
        runtime_safety_factor=launch.runtime_safety_factor,
        runtime_trial_safety_factor=launch.runtime_trial_safety_factor,
        runtime_formal_safety_factor=launch.runtime_formal_safety_factor,
        runtime_watchdog_safety_factor=launch.runtime_watchdog_safety_factor,
        runtime_watchdog_floor_seconds=launch.runtime_watchdog_floor_seconds,
        runtime_verification_max_wall_seconds=(launch.runtime_verification_max_wall_seconds),
        # V19 PR 1 (P1-C3) — the chain incumbent travels as a NAMED
        # protocol parameter (two-state design, design doc §3.4).
        # ``chain_formal_incumbent_reference`` is decision state:
        # seeded from RestoredState, updated only from committed
        # VALID formals. ``best_score_overall`` (raw progress) is
        # deliberately NOT used here — the pre-V19 post-hoc mutation
        # that fed it to the tuner is removed.
        current_run_best_formal_score=chain_formal_incumbent_reference,
        enable_chain_incumbent_formal_gates=launch.enable_chain_incumbent_formal_gates,
        # V19 PR 2 — operator ordering override for every round of this
        # iteration. The agent's per-round proposal is resolved against
        # it inside the tuner; the workflow never resolves ordering.
        order_strategy_override=bindings.order_strategy_override,
        file_order_override=(
            list(bindings.file_order_override) if bindings.file_order_override is not None else None
        ),
        # V19 PR 3 — policy pass-through so the TUNER's lock matches
        # the workflow's (contradictory locks abort the run).
        enable_structured_health_feedback=bindings.enable_structured_health_feedback,
        health_feedback_history_window_iterations=(
            launch.health_feedback_history_window_iterations
        ),
        health_feedback_history_max_entries_per_model=(
            launch.health_feedback_history_max_entries_per_model
        ),
        # arXiv U1 (#253 / #254) — read from the ONE lock object this
        # pre-flight built (never re-derived here), so the tuner's
        # per-model lock and the chain lock cannot disagree — the
        # F-11-C10-a lesson: two derivations of one identity are two
        # chances to diverge.
        experiment_arm=run_invariants.experiment_arm,
        lit_review_enabled=run_invariants.lit_review_enabled,
        data_analysis_enabled=run_invariants.data_analysis_enabled,
        lit_review_config_sha256=run_invariants.lit_review_config_sha256,
        scientific_evidence_order=run_invariants.scientific_evidence_order,
        baseline_isolation=run_invariants.baseline_isolation,
    )
    if launch.human_advice_tune is not None:
        tune_input.human_advice = launch.human_advice_tune
    # Task config injection (T4a) — substituted into the {TASK_DESCRIPTION}
    # placeholder in PLANNER_PROMPT via brain.plan(task_description=...).
    # See docs/design/enable_global_task_config.md § Commit T4a.
    tune_input.task_description = get_task_description(load_task_config())
    return tune_input
