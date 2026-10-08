"""The standard runner's launch projection, shared with setup inspection.

Callers supply launch-ready CLI arguments and resolved identities. This
module neither launches work nor invents defaults for downstream node choices.
"""

from __future__ import annotations

import argparse
from typing import get_args

from agent.schemas.proposal import OutputTypeName
from workflows.launch_identity import LaunchIdentity
from workflows.run_config import WorkflowLaunchConfig


def parse_allowed_output_types(raw: str | None) -> tuple[OutputTypeName, ...] | None:
    """``--allowed_output_types`` "a,b" -> ("a","b"); None/"" -> None.

    arXiv #259. Refuses unknown names HERE so a typo fails at launch, not as
    a permanently-refusing proposer loop. The legal set mirrors
    ``ProposalOutput.output_type``'s Literal.
    """
    if raw is None or raw.strip() == "":
        return None
    from typing import cast

    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    legal = set(get_args(OutputTypeName))
    unknown = [p for p in parts if p not in legal]
    if unknown:
        raise SystemExit(
            f"--allowed_output_types: unknown output type(s) {unknown!r}; "
            f"legal values: {sorted(legal)}"
        )
    if not parts:
        return None
    # The refusal above proves every element is a member of the Literal
    # vocabulary; the cast records that guarantee for the type checker.
    return cast("tuple[OutputTypeName, ...]", parts)


def build_standard_launch_config(
    args: argparse.Namespace,
    launch_identity: LaunchIdentity,
    *,
    resolved_paths: list[str],
    fixed_candidate_plan: dict | None,
) -> WorkflowLaunchConfig:
    """Project resolved standard-runner inputs into its existing transit type.

    The caller must normalize CLI arguments, resolve the physical data directory
    and apply watchdog resolution before calling. Source restoration, task
    composition and fixed-plan validation remain caller responsibilities. This
    projection does not prove that a workspace or an environment is ready to run.
    """
    return WorkflowLaunchConfig(
        source_paths=resolved_paths,
        require_probe_runner=not (args.is_pseudo_training or args.is_pseudo_llm),
        healthgate_mode=args.healthgate_mode,
        result_authority=args.result_authority,
        max_iterations=1,
        start_iteration=args.start_iteration,
        max_rounds=args.max_rounds,
        max_proposal_attempts=args.max_proposal_attempts,
        is_trial=args.is_trial,
        trial_portion=args.trial_portion,
        train_portion=args.train_portion,
        eval_portion=args.eval_portion,
        sampling_seed=args.sampling_seed,
        formal_strategy=args.formal_strategy,
        formal_training_scope_source=args.formal_training_scope_source,
        formal_portion=args.formal_portion,
        formal_train_portion=args.formal_train_portion,
        formal_eval_portion=args.formal_eval_portion,
        force_formal_round=args.force_formal_round,
        formal_round_strategy=args.formal_round_strategy,
        degenerate_penalty_score=args.degenerate_penalty_score,
        cleanup_denoised=args.cleanup_denoised,
        retain_model_outputs=launch_identity.retain_model_outputs,
        retain_training_checkpoints=launch_identity.retain_training_checkpoints,
        max_epochs=args.max_epochs,
        # D-BUD-6 — per-mode epoch ceilings, forwarded including
        # `None` (None = mode-agnostic max_epochs governs).
        training_budget_reserve_fraction=args.training_budget_reserve_fraction,
        trial_max_epochs=args.trial_max_epochs,
        formal_max_epochs=args.formal_max_epochs,
        validation_max_portion=args.validation_max_portion,
        validation_max_train_samples=args.validation_max_train_samples,
        training_validation_portion=args.training_validation_portion,
        validation_max_samples=args.validation_max_samples,
        validation_max_phase_seconds=args.validation_max_phase_seconds,
        skip_formal_min_delta=args.skip_formal_min_delta,
        bypass_formal_time_budget_min_delta=args.bypass_formal_time_budget_min_delta,
        bypass_formal_time_budget_minutes=args.bypass_formal_time_budget_minutes,
        trial_time_budget_minutes=args.trial_time_budget_minutes,
        formal_time_budget_minutes=args.formal_time_budget_minutes,
        trial_time_admission_source=args.trial_time_admission_source,
        formal_time_admission_source=args.formal_time_admission_source,
        runtime_completion_policy=args.runtime_completion_policy,
        runtime_verifier=args.runtime_verifier,
        runtime_verifier_identity=launch_identity.runtime_verifier_identity,
        data_dir=args.data_dir,
        gpu_execution_policy=launch_identity.gpu_execution_policy,
        gpu_admission_measurement_source=args.gpu_admission_measurement_source,
        gpu_admission_enforcement=args.gpu_admission_enforcement,
        gpu_pair_ceiling_gib=args.gpu_pair_ceiling_gib,
        trial_vram_budget_gb=args.trial_vram_budget_gb,
        formal_vram_budget_gb=args.formal_vram_budget_gb,
        vram_probe_step_timeout_seconds=args.vram_probe_step_timeout_seconds,
        vram_preflight_total_timeout_seconds=(args.vram_preflight_total_timeout_seconds),
        vram_preflight_host_memory_limit_gb=(args.vram_preflight_host_memory_limit_gb),
        attempts_per_round=args.attempts_per_round,
        attempts_per_formal_round=args.attempts_per_formal_round,
        max_fail_rounds=args.max_fail_rounds,
        max_steps_per_attempt=args.max_steps_per_attempt or None,
        min_formal_batch_size=args.min_formal_batch_size or None,
        allow_extreme_steps=args.allow_extreme_steps,
        runtime_watchdog_enabled=args.runtime_watchdog,
        runtime_safety_factor=args.runtime_safety_factor,
        runtime_trial_safety_factor=args.runtime_trial_safety_factor,
        runtime_formal_safety_factor=args.runtime_formal_safety_factor,
        runtime_watchdog_safety_factor=args.runtime_watchdog_safety_factor,
        runtime_watchdog_floor_seconds=args.runtime_watchdog_floor_seconds,
        runtime_verification_max_wall_seconds=(args.runtime_verification_max_wall_seconds),
        human_advice_interpret=args.human_advice_interpret,
        human_advice_analysis=args.human_advice_analysis,
        analysis_source_prompt=args.analysis_source_prompt,
        data_analysis_enabled=launch_identity.data_analysis_enabled,
        human_advice_propose=args.human_advice_propose,
        human_advice_implement=args.human_advice_implement,
        human_advice_validate=args.human_advice_validate,
        human_advice_tune=args.human_advice_tune,
        human_advice_mindset=args.human_advice_mindset,
        plan_overrides=args.plan_overrides,
        workflow_parameter_rules=args.workflow_parameter_rules,
        exploration_mode=args.exploration_mode,
        minimum_boldness=args.minimum_boldness,
        max_impl_attempts=args.max_impl_attempts,
        debug_dump_prompts=args.debug_dump_prompts,
        validation_fixed_candidate_plan=fixed_candidate_plan,
        enable_chain_incumbent_formal_gates=args.enable_chain_incumbent_formal_gates,
        health_feedback_history_window_iterations=args.health_feedback_history_window_iterations,
        health_feedback_history_max_entries_per_model=args.health_feedback_history_max_entries_per_model,
        lit_review_enabled=launch_identity.lit_review_enabled,
        lit_review_config_path=launch_identity.lit_review_config_path,
        scientific_evidence_order=launch_identity.scientific_evidence_order,
        # arXiv U1 — opaque; locked + stamped, never interpreted.
        experiment_arm=launch_identity.experiment_arm,
        # arXiv U3 — the WITHOUT arm's explicit behaviour flag.
        baseline_isolation=launch_identity.baseline_isolation,
        # Gold campaign — the OBSERVED advice identity, from the
        # same resolution the pre-flight lock used, because
        # `run_workflow` locks the SAME workspace.
        advice_path=launch_identity.advice_path,
        advice_sha256=launch_identity.advice_sha256,
        # arXiv #259 — output-type constraint, transit to the
        # proposer's schema gate.
        allowed_output_types=parse_allowed_output_types(args.allowed_output_types),
    )
