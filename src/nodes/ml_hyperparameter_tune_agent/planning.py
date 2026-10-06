"""Tuner PLANNING — everything between "what happened so far" and "run this".

Step 07 PR 07b, C7d (operator decision A-prime). PRIVATE node-internal module.

One lifecycle phase, moved VERBATIM out of ``run()``: observe the history,
build the planner's context, ask the LLM, validate its answer, apply the
operator's overrides and the forced-formal chain, normalize the strategy under
a partial scope, clamp the epochs, and resolve the round's sample sets. It ends
where physical work begins — the first guardrail.

The phase reads ~21 run-scoped authorities, which arrive as ONE
:class:`~nodes.ml_hyperparameter_tune_agent.contracts.RunBindings`, and a
handful of genuinely per-attempt facts, which stay explicit arguments. It
returns a :class:`PreparedAttempt`: the products of planning, and nothing else.
"""

import json
import os
from typing import Any

from agent.prompt_templates.timing_attribution import training_validation_disclosure
from agent.schemas.hyperparam_tuning import (
    EpochCapResolution,
    ExperimentPlan,
    TaskCompositionRef,
    TrialConfig,
)
from agent.schemas.ordering import resolve_ordering
from agent.schemas.parameter_rules import (
    ParameterRuleError,
    ParameterRules,
    apply_parameter_rules,
    validate_parameter_rule_ownership,
)
from execute_tools.health_checks.candidate_eligibility import (
    is_valid_candidate,
)
from execute_tools.sample_set_builder import build_sample_set
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AttemptOrdering,
    PreparedAttempt,
    RunBindings,
)
from nodes.ml_hyperparameter_tune_agent.health_coverage import (
    validate_attempt_health_coverage,
)
from nodes.ml_hyperparameter_tune_agent.policy import (
    _apply_mode_override_chain,
    _apply_plan_overrides,
    _disclose_inapplicable_trial_overrides,
    _resolve_sample_set_cfg,
    _score_of,
    _validate_data_config,
)
from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker
from nodes.ml_hyperparameter_tune_agent.runtime import (
    _apply_epoch_bound,
)
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import (
    AttemptTopologyFacts,
    acquire_attempt_scopes,
    project_attempt_topology_facts,
)
from nodes.ml_hyperparameter_tune_agent.timing_context import (
    build_timing_context,
    partial_scope_strategy_overrides,
)


def _apply_declared_objective(plan: Any, composition_ref: Any) -> Any:
    """Bind the task's DECLARED objective onto the plan — F-12d-31 wire B.

    A task that ships its own training objective must not depend on an LLM
    choosing it. Two real composed DAVIS runs trained with ``smooth_l1``
    because the planner is told that is the only valid regressor loss and is
    never shown the task's exact-L1 — so the objective is applied here as a
    typed authority rather than a prompt suggestion.

    **Selection, not vocabulary.** The composed value is an ordinary validated
    ``LossConfig`` on the pre-existing ``custom`` + ``loss_name`` route. No
    enum grows, no task name is read, and nothing here knows what DAVIS is:
    the discriminator is whether the RUN declared an objective.

    **Silent no-op when nothing is declared**, which is every run that exists
    today: ``composition_ref`` is ``None`` for an un-composed run and
    ``objective`` is ``None`` for a composed task that declares none. In both
    cases the plan is returned unchanged and the planner's choice stands.

    The substitution is announced, because a silently overridden objective is
    the same opacity in the other direction.
    """
    declared = getattr(composition_ref, "objective", None) if composition_ref else None
    if declared is None:
        return plan
    planned = dict(plan.loss_cfg or {})
    effective = declared.model_dump()
    if planned.get("loss_type") != effective.get("loss_type") or planned.get(
        "loss_name"
    ) != effective.get("loss_name"):
        print(
            f"  [objective] task-declared objective applied: "
            f"{planned.get('loss_type')!r}/{planned.get('loss_name')!r} -> "
            f"{effective['loss_type']!r}/{effective['loss_name']!r} "
            f"(the task declares this; the planner does not choose it)"
        )
    plan.loss_cfg = effective
    return plan


def _apply_effective_parameter_rules(
    plan: ExperimentPlan,
    *,
    composition_ref: TaskCompositionRef | None,
    workflow_rules: ParameterRules | None,
    epoch_cap: EpochCapResolution,
) -> ExperimentPlan:
    """Apply task rules without bypassing other effective-plan authorities.

    This boundary owns the interaction between parameter rules, a declared
    objective, and the independent epoch safety ceiling. It does not choose an
    objective or an epoch cap; both arrive already resolved by their existing
    authorities.
    """
    task_rules = composition_ref.parameter_rules if composition_ref is not None else None
    validate_parameter_rule_ownership(
        objective_declared=composition_ref is not None and composition_ref.objective is not None,
        task_rules=task_rules,
        workflow_rules=workflow_rules,
    )

    effective = apply_parameter_rules(
        plan,
        task_rules=task_rules,
        workflow_rules=workflow_rules,
    )
    if epoch_cap.cap is not None and effective.train_cfg.get("epochs", 1) > epoch_cap.cap:
        raise ParameterRuleError(
            "parameter_rules resolved train_config.epochs above the active "
            f"{epoch_cap.source or 'max_epochs'} ceiling {epoch_cap.cap}"
        )
    return effective


def _normalize_strategies_for_scope(
    plan: Any,
    *,
    scope_is_partial: bool,
    resolved_data_scope: Any,
    resolution: ResolutionTracker,
) -> tuple[Any, Any, str | None]:
    """DataScope DS5 — snapshot-only sampling under a partial scope.

    Extracted from ``prepare_attempt`` by Lane D under the structural budget
    that guards it ("extract the responsibility first"). Behaviour is verbatim:
    the same condition, the same ``[DATASCOPE]`` line, the same two writes and
    the same reason string.

    LLM plans are PROPOSALS — normalized with persisted provenance rather than
    failed. Operator config was already validated at startup, and the sandbox
    boundary still fails hard if anything slips through.

    Returns the strategies as PLANNED (before normalization) and the reason,
    which the record carries so a normalized round is distinguishable from one
    that asked for ``snapshot`` itself.
    """
    planned_trial_strategy = plan.trial_strategy
    planned_eval_strategy = plan.eval_strategy
    strategy_normalization_reason: str | None = None
    strategy_overrides = partial_scope_strategy_overrides(scope_is_partial, plan.is_trial)
    if any(getattr(plan, field) != value for field, value in strategy_overrides.items()):
        print(
            f"  [DATASCOPE] normalized strategies: "
            f"trial {plan.trial_strategy} → snapshot, "
            f"eval {plan.eval_strategy} → snapshot "
            f"(partial scope {resolved_data_scope})"
        )
        for field, value in strategy_overrides.items():
            setattr(plan, field, value)
        strategy_normalization_reason = "partial_data_scope"
        resolution.record(plan, "partial_scope_strategy_normalization")
    return planned_trial_strategy, planned_eval_strategy, strategy_normalization_reason


def _resolve_declared_segmentation_size(model_type: str, model_cfg: dict) -> int | None:
    """The ``segmentation_size`` the run WILL ACTUALLY USE, or ``None``.

    C12-P / B11 + F-C12P-B11-2. Extracted rather than inlined: ``prepare_attempt``
    is a phase orchestrator under the decomposition rule, and this is a decision
    with its own contract, its own failure mode and its own tests.

    THREE REGIMES, and the middle one is the whole point::

        plan states it              -> that value
        plan omits, model declares  -> the model's declared default
        nothing declares it         -> None, and the TASK refuses by name

    ``.get("segmentation_size", 10000)`` used to check a number nothing in the
    run used: an omitted key makes the model be CONSTRUCTED at its config
    class's declared default (``config_cls(**model_config)`` -- wavenet 40000,
    transformer 20000). Under TIDMAD both divide ``psd_segment_length`` evenly,
    so the check passed and the disagreement stayed silent.

    B11's first repair dropped the literal and let an omitted key stay omitted
    so the task could refuse in its own words. The refusal is right and is
    preserved. Dropping the literal with NOTHING in its place was not: the key
    is legitimately optional (``agent/schemas/proposal.py:1247`` -- "some
    architectures don't have one"), so every run whose plan omitted it died at
    scope construction, on every attempt, and never reached the reflector.
    **A proposal omitting the key does not mean the model declares no
    geometry.**

    So resolve through the ONE authority. This is not the framework inventing a
    task value -- it reads the MODEL's own declaration, in the exact order the
    model itself resolves it (supplied -> config-class default -> margin).

    ``safety_margin=0`` is an internal "nothing declares this" sentinel,
    unreachable as a real segmentation size; ``or None`` turns it back into the
    absence that keeps the task's refusal reachable. The sentinel is proven not
    to escape by ``tests/unit/core/test_c12p_b11_2_zero_sentinel_never_escapes.py``.

    Args:
        model_type: the EFFECTIVE model type, i.e. after the ``force_model``
            override. Passing the plan's own ``model_type`` when an override is
            set would ask the wrong config class.
        model_cfg: the plan's model config; read, never mutated.

    Returns:
        The resolved size, or ``None`` when no authority declares one.
    """
    from agent.skills.training_skill.estimator import resolve_model_field

    return resolve_model_field(model_type, model_cfg, "segmentation_size", safety_margin=0) or None


def _psd_segment_counts(
    train_sample_set: dict | None,
    eval_sample_set: dict | None,
    topology_facts: AttemptTopologyFacts,
    *,
    has_task_scopes: bool = False,
) -> tuple[int | None, int | None]:
    """``(train, eval)`` PSD-segment counts for the record and the reflector.

    Opaque task scopes carry no framework-readable physical segment count;
    report unknown rather than substitute whole-file topology. A built legacy
    SampleSet reports what it actually holds. Without one, the legacy
    single-file round uses the whole file, so the count IS the run topology's
    segments-per-file — and a task that declares no such geometry reports
    ``None``. Both record fields are already ``int | None``; an invented 0
    would be persisted as a measurement.
    """

    if has_task_scopes:
        return None, None

    def _count(sample_set: dict | None) -> int | None:
        if sample_set is not None:
            return sum(len(v) for v in sample_set.values())
        if not topology_facts.declares_physical_geometry:
            return None
        return topology_facts.physical_dataset.segments_per_file

    return _count(train_sample_set), _count(eval_sample_set)


def _disclosed_epoch_caps(agent_input: Any) -> tuple[int | None, int | None]:
    """D-BUD-6 — the (trial, formal) epoch ceilings to DISCLOSE to the planner.

    When a per-mode cap is configured, the prompt must show the SAME
    effective values the clamp will apply — resolved by the ONE schema
    authority ``HyperparamTuningInput.resolve_epoch_cap`` — because a prompt
    that kept saying ``<= max_epochs`` would steer the planner under the
    trial ceiling and make it unreachable. Returns ``(None, None)`` when no
    per-mode cap is set, which renders the legacy FIXED block
    byte-identically.
    """
    if agent_input.trial_max_epochs is None and agent_input.formal_max_epochs is None:
        return (None, None)
    return (
        agent_input.resolve_epoch_cap(is_trial=True).cap,
        agent_input.resolve_epoch_cap(is_trial=False).cap,
    )


def _no_sample_set_notice(mode: str, file_index: int | None) -> str:
    """What to print when no SampleSet was built.

    TWO different states share that branch and saying so matters: the legacy
    single-file round has always been there, and a composed task that declares
    no physical geometry joins it because its scope is the one
    ``acquire_attempt_scopes`` builds, not a SampleSet.
    """
    if mode == "single_file":
        return f"  Legacy mode: file_index={file_index}"
    return (
        "  Task-owned scope: no SampleSet is built for a task that declares "
        "no physical partition geometry"
    )


def prepare_attempt(
    bindings: RunBindings,
    *,
    attempt_ordering: AttemptOrdering,
    iteration: int,
    attempt_in_round: int,
    total_attempts: int,
    attempts_this_round: int,
    is_formal_round: bool,
    formal_trial_winner: dict | None,
) -> PreparedAttempt:
    """Plan one attempt: observe -> think -> resolve the round's data.

    Behaviour is byte-identical to the block it replaces; the differential
    oracle is the evidence. The run-scoped names are unpacked from
    ``bindings`` below so the moved body reads exactly as it did inside
    ``run()`` — a rename here would be a second change riding along with a
    move, and only one of them would be provable.
    """
    agent_input = bindings.agent_input
    sandbox = bindings.sandbox
    brain = bindings.brain
    run_profile = bindings.run_profile
    run_metric = bindings.run_metric
    run_order = bindings.run_order
    run_task_render = bindings.run_task_render
    run_name = bindings.run_name
    file_index = bindings.file_index
    max_rounds = bindings.max_rounds
    model_type_setting = bindings.model_type_setting
    trial_allowed = bindings.trial_allowed
    resolved_data_scope = bindings.resolved_data_scope
    scope_is_partial = bindings.scope_is_partial
    expert_advice_str = bindings.expert_advice_str
    config_manual_data = bindings.config_manual_data
    model_description = bindings.model_description
    trial_vram_budget = bindings.trial_vram_budget
    formal_vram_budget = bindings.formal_vram_budget
    trial_time_budget = bindings.trial_time_budget
    formal_time_budget = bindings.formal_time_budget
    N = attempts_this_round

    print(
        f"\n\n{'=' * 60}\nROUND {iteration}/{max_rounds} "
        f"(attempt {attempt_in_round}/{N}, total {total_attempts}): "
        f"Planning...\n{'=' * 60}"
    )

    # A. OBSERVE: Retrieve full Research Memory from summary.json
    memory_history = sandbox.get_summary()

    # Build exploration checklist from config schema + past records
    from agent.prompts import (
        build_exploration_checklist,
        format_plugin_source_excerpt_block,
    )
    from ml_models.models_format_sandbox import get_config_class

    config_cls = get_config_class(model_type_setting)
    config_schema = config_cls.model_json_schema() if config_cls else {}
    checklist = build_exploration_checklist(
        config_schema=config_schema,
        memory_history=memory_history,
        loss_context=run_task_render.loss_context,
    )
    # Phase D.1 — surface the raw config class source (validator
    # bodies included) so the planner sees cross-field invariants
    # that ``model_json_schema()`` drops. See
    # docs/improving_validation_awareness.md §D.1.
    plugin_source_excerpt = format_plugin_source_excerpt_block(config_cls)

    # Phase K (K.6) — extract the most recent prior attempt's
    # resource snapshot so the [ACTIVE RESOURCE BUDGETS] block can
    # show the LLM a concrete number to react to. Looks at the
    # last memory entry regardless of status (success / skipped):
    # the resource fields are absent on records produced with the
    # gates disabled and on schema-violation records. Round 1
    # gives None on every field, which collapses to "(no prior
    # estimate)" in the rendered block.
    # See docs/resource_estimator_implement.md §10.3 / §10.11.
    last_record = memory_history[-1] if memory_history else {}
    last_memory = last_record.get("memory") or {}
    last_train_cfg = (last_record.get("params") or {}).get("train_config") or {}
    last_vram_estimate_gb = last_memory.get("vram_estimate_gb")
    last_time_estimate_minutes = last_memory.get("time_estimate_minutes")
    last_batch_size = last_train_cfg.get("batch_size")
    last_mode = last_memory.get("time_mode")

    # Pick the best HealthGate-valid score_table for the
    # planner prompt. Raw collapsed winners remain persisted
    # but are not presented as the viable incumbent. Empty
    # history or no
    # populated score_table → None, which the bridge replaces
    # with the "no prior round yet" fallback. See
    # docs/aggregated_score_table_awareness.md §9.1.
    best_score_table_md: str | None = None
    _records_with_table: list[dict] = [
        r
        for r in memory_history
        if is_valid_candidate(
            r,
            required_gate_ids=bindings.run_scientific_gate_ids,
        )
        and isinstance(r.get("score_table"), dict)
        and r["score_table"].get("rendered_markdown")
    ]
    if _records_with_table:
        _best_rec = run_order.best(_records_with_table, key=_score_of)
        best_score_table_md = _best_rec["score_table"]["rendered_markdown"]

    # D-BUD-6 — mode-aware ceiling disclosure (see the helper's docstring).
    disclosed_epoch_caps = _disclosed_epoch_caps(agent_input)

    allocation_kwargs = {}
    if agent_input.training_budget_reserve_fraction is not None:
        allocation_kwargs["training_budget_reserve_fraction"] = (
            agent_input.training_budget_reserve_fraction
        )

    # B. THINK: Plan next experiment
    decision = brain.plan(
        memory_history,
        planner_strategy=agent_input.planner_strategy,
        expected_planner_strategy=bindings.planner_strategy_identity,
        timing_context=build_timing_context(
            agent_input,
            trial_allowed=trial_allowed,
            is_formal_round=is_formal_round,
            current_round=iteration,
            trial_winner=formal_trial_winner,
            memory_history=memory_history,
            scope_is_partial=scope_is_partial,
        ),
        **allocation_kwargs,
        expert_advice=expert_advice_str,
        force_model=model_type_setting,
        config_manual=config_manual_data,
        model_description=model_description,
        exploration_checklist=checklist,
        plugin_source_excerpt=plugin_source_excerpt,
        current_round=iteration,
        max_rounds=max_rounds,
        trial_allowed=trial_allowed,
        force_formal_round=agent_input.force_formal_round,
        plan_overrides=agent_input.plan_overrides,
        max_epochs=agent_input.max_epochs,
        trial_max_epochs=disclosed_epoch_caps[0],
        formal_max_epochs=disclosed_epoch_caps[1],
        # DS5c — partial-scope disclosure (None = full scope).
        resolved_data_scope=resolved_data_scope if scope_is_partial else None,
        trial_vram_budget_gb=trial_vram_budget,
        formal_vram_budget_gb=formal_vram_budget,
        trial_time_budget_minutes=trial_time_budget,
        formal_time_budget_minutes=formal_time_budget,
        last_vram_estimate_gb=last_vram_estimate_gb,
        last_time_estimate_minutes=last_time_estimate_minutes,
        last_batch_size=last_batch_size,
        last_mode=last_mode,
        score_table_md=best_score_table_md,
        # T4a — task config injection. Substituted into the
        # {TASK_DESCRIPTION} placeholder in PLANNER_PROMPT.
        # See docs/design/enable_global_task_config.md § T4a.
        task_description=(
            agent_input.task_description
            + training_validation_disclosure(agent_input.training_validation_portion)
        ),
        # L6b — loss-registry awareness. Drives both the
        # AVAILABLE CUSTOM LOSSES system-prompt block and
        # the per-architecture loss_note advertisement of
        # ``loss_type="custom"`` as a legal choice. See
        # docs/design/enable_loss_inventory.md § L6b.
        custom_loss_inventory=bindings.custom_loss_inventory,
        # Step 07 PR 07b (P2) — the run-scoped task tokens.
        task_render=run_task_render,
        # Step 07 PR 07b (P3) — the run's golden-metric
        # declaration: direction words + metric identity.
        metric_spec=run_metric.spec,
    )

    # Validate LLM output into ExperimentPlan (with fallback).
    # parse_with_fallback also reports an ordering proposal
    # that the fallback discarded, so a rejected proposal is
    # recorded rather than looking like agent silence.
    plan, rejected_ordering = ExperimentPlan.parse_with_fallback(decision)

    # Lane D / F15 — see `provenance.py`; `plan.hypothesis` goes stale here.
    resolution = ResolutionTracker(plan)

    # Apply hard overrides from operator config (before other
    # overrides). FU-10 — an invalid effective plan raises
    # PlanOverridesError (run-terminating); see the helper.
    plan = _apply_plan_overrides(plan, agent_input.plan_overrides)
    resolution.record(plan, "operator_plan_overrides")

    # Override chain: trial-allowed lockout + last-round override
    # + forced-formal hyperparameter inheritance gated on
    # formal_round_strategy. See _apply_mode_override_chain.
    plan = _apply_mode_override_chain(
        plan,
        trial_allowed=trial_allowed,
        is_formal_round=is_formal_round,
        force_formal_round=agent_input.force_formal_round,
        formal_round_strategy=agent_input.formal_round_strategy,
        memory_history=memory_history,
        # FU-D-6: the SAME winner the skip and bypass gates
        # judged, resolved once at the formal-round
        # boundary above — not re-derived here.
        trial_winner=formal_trial_winner,
        current_round=iteration,
    )
    resolution.record(plan, "round_mode_override_chain")

    # Step 12 / PR-12d, F-12d-31 wire B — the task's AUTHORITATIVE objective.
    #
    # Applied AFTER `_apply_mode_override_chain` deliberately. That chain's
    # forced-formal branch copies the winning trial's `loss_config` wholesale
    # (`policy.py:741,764`), so an objective applied before it would be
    # silently replaced by whatever the trial happened to run — the exact
    # class of silent substitution this wire exists to prevent. Last writer on
    # the plan wins, and the declared objective is the last writer.
    #
    # A task that declares none leaves `objective` None and the planner's
    # choice stands, which is every run that exists today.
    plan = _apply_declared_objective(plan, agent_input.task_composition_ref)
    resolution.record(plan, "task_declared_objective")

    (
        planned_trial_strategy,
        planned_eval_strategy,
        strategy_normalization_reason,
    ) = _normalize_strategies_for_scope(
        plan,
        scope_is_partial=scope_is_partial,
        resolved_data_scope=resolved_data_scope,
        resolution=resolution,
    )

    # Enforce the harness epoch cap (prevents LLM from choosing
    # excessively long training).
    #
    # V21 PR B1b — the cap applies to the RESOLVED training
    # configuration, and the effective value is written back so
    # it reaches the trainer.
    #
    # The bypass this closes: the clamp read
    # ``.get("epochs", 1)`` while the trainer builds
    # ``TrainConfig(**t_data)`` and gets its declared **10**.
    # A plan that simply omitted the key therefore trained ten
    # epochs under ``--max_epochs 1`` — the clamp compared
    # 1 > 1, declined to act, and the bound the harness owns
    # was decided by the planner's silence.
    #
    # D-BUD-6: the cap is resolved per ROUND ROLE by the schema's ONE
    # authority, keyed on ``plan.is_trial`` AFTER the override chain above
    # — the same value that becomes ``record.is_trial`` (PR #217), never
    # ``memory.time_mode``. See ``resolve_epoch_cap`` for the precedence.
    epoch_cap = agent_input.resolve_epoch_cap(is_trial=plan.is_trial)
    _apply_epoch_bound(plan.train_cfg, epoch_cap.cap, source=epoch_cap.source or "max_epochs")
    resolution.record(plan, "max_epochs_bound")

    plan = _apply_effective_parameter_rules(
        plan,
        composition_ref=agent_input.task_composition_ref,
        workflow_rules=agent_input.workflow_parameter_rules,
        epoch_cap=epoch_cap,
    )
    resolution.record(plan, "parameter_rules")

    # Build and validate TrialConfig from plan + overrides
    if plan.is_trial:
        mode = "trial"
    elif trial_allowed:
        mode = "formal"
    else:
        mode = "single_file"

    # Lane F / F14 — per-round disclosure when trial-scoped operator
    # overrides do not govern the resolved FORMAL mode (the schema refuses
    # the zero-trial-round combination outright; this covers the legitimate
    # multi-round shape where the last round is formal-forced).
    _disclose_inapplicable_trial_overrides(mode, agent_input)

    # Phase M / Phase R — mode-gated sample-set config. Formal-mode
    # eval strategy is locked to ``snapshot``; the portion defaults
    # to 1.0 (production full-clone, §12.2) but is operator-
    # configurable via ``agent_input.formal_eval_portion`` (Phase R,
    # §13). Formal training levers come from agent_input.formal_*.
    # See docs/resource_estimator_implement.md §12 and §13.
    _cfg = _resolve_sample_set_cfg(mode, agent_input, plan)
    cfg_trial_strategy = _cfg["trial_strategy"]
    cfg_trial_portion = _cfg["trial_portion"]
    cfg_train_portion = _cfg["train_portion"]
    cfg_eval_strategy = _cfg["eval_strategy"]
    cfg_eval_portion = _cfg["eval_portion"]

    # FU-D-12 — VALIDATION-ONLY workload ceiling, applied to
    # the RESOLVED values so it holds whichever branch
    # produced them.
    #
    # Trial-mode portions come from the LLM PLAN, not from
    # operator input, so a Gate that requested 0.02 measured
    # 0.1. Time budgets bound wall time but not WORKLOAD, and
    # the harness must own the maximum. Formal-mode portions
    # already come from `agent_input.formal_*` and are
    # unaffected.
    #
    # A maximum, never a replacement: `min` can only reduce.
    _planned_portions = {
        "trial_portion": cfg_trial_portion,
        "train_portion": cfg_train_portion,
        "eval_portion": cfg_eval_portion,
    }
    if agent_input.validation_max_portion is not None:
        _ceiling = agent_input.validation_max_portion
        for _label, _planned in (
            ("trial_portion", cfg_trial_portion),
            ("train_portion", cfg_train_portion),
            ("eval_portion", cfg_eval_portion),
        ):
            if _planned > _ceiling:
                print(f"  Clamping {_label}: {_planned} → {_ceiling} (validation_max_portion)")
        # Assigned unconditionally: BOTH branches of
        # `_resolve_sample_set_cfg` yield a non-optional float
        # (`ExperimentPlan.trial_portion` and
        # `HyperparamTuningInput.formal_*` are both `float`),
        # and `TrialConfig` requires `float`. Guarding on
        # `is not None` here would widen the inferred type to
        # `float | None` and break the TrialConfig contract —
        # which is exactly what CI caught.
        cfg_trial_portion = min(cfg_trial_portion, _ceiling)
        cfg_train_portion = min(cfg_train_portion, _ceiling)
        cfg_eval_portion = min(cfg_eval_portion, _ceiling)

    # Generate deterministic seeds for reproducibility.
    import hashlib

    seed_input = f"{run_name}_{total_attempts}".encode()
    seed_hash = int(hashlib.sha256(seed_input).hexdigest(), 16)
    train_sampling_seed = (
        agent_input.sampling_seed if agent_input.sampling_seed is not None else seed_hash % (2**31)
    )
    train_base_seed = (
        agent_input.train_base_seed
        if agent_input.train_base_seed is not None
        else (seed_hash >> 31) % (2**31)
    )
    # Eval seed: same as train when aligned, different otherwise
    if plan.train_validation_align:
        eval_sampling_seed = train_sampling_seed
    else:
        eval_sampling_seed = (seed_hash >> 62) % (2**31)

    # V19 PR 2 — the ONE ordering resolution point. Combines
    # the agent's proposal (or its rejection) with the
    # operator's chain override; nothing downstream re-derives
    # precedence, and only the resolved values execute.
    ordering = resolve_ordering(
        resolved_scope=resolved_data_scope,
        proposed_strategy=plan.order_strategy,
        proposed_file_order=plan.file_order,
        override_strategy=agent_input.order_strategy_override,
        override_file_order=agent_input.file_order_override,
        rejected_proposal=rejected_ordering,
    )
    attempt_ordering.selected = ordering
    print(f"[data_order] {ordering.describes_execution()}")

    trial_config = TrialConfig(
        is_trial=plan.is_trial,
        mode=mode,
        # Training
        trial_strategy=cfg_trial_strategy,
        trial_portion=cfg_trial_portion,
        train_portion=cfg_train_portion,
        target_files=plan.target_files if plan.is_trial else [],
        # Validation
        eval_strategy=cfg_eval_strategy,
        eval_portion=cfg_eval_portion,
        # Alignment
        train_validation_align=plan.train_validation_align,
        # Legacy
        file_index=file_index if mode == "single_file" else None,
        # Seeds
        train_sampling_seed=train_sampling_seed,
        eval_sampling_seed=eval_sampling_seed,
        train_base_seed=train_base_seed,
        # Ordering — RESOLVED values only (V19 PR 2).
        # executed_strategy() narrows to non-null inside
        # ordering.py; doing it here pushed pyright past its
        # per-function complexity budget for run().
        resolved_order_strategy=ordering.executed_strategy(),
        resolved_file_order=ordering.resolved_file_order,
    )

    # Step 12 / PR-12d, seam B. The ONE place this package learns what
    # physical geometry the run's task declares. Under TIDMAD — legacy or
    # composed — every fact below is the same object it was before, by
    # construction rather than by a parallel branch.
    topology_facts = project_attempt_topology_facts(run_profile)

    # Validate integer relationships between dataset, PSD, ML segments.
    #
    # SKIPPED, never guessed, for a task that declares no physical geometry:
    # the rule is PSD-segment divisibility and per-file segment counts, which
    # a 37-way image classifier and a frame-window predictor do not have. The
    # D-BC-8 precedent — the partition bound is generic identity and is always
    # checked; the per-partition bound is task topology and is skipped.
    # The effective model type (the `force_model` override), resolved ONCE and
    # early. It used to be computed ~120 lines below, next to `exp_id`; hoisting
    # a pure expression over two values in scope since the unpack changes no
    # behaviour, and it is what lets the resolution below ask the RIGHT config
    # class. See `_resolve_declared_segmentation_size`.
    model_type = model_type_setting if model_type_setting != "auto" else plan.model_type

    declared_segmentation_size = _resolve_declared_segmentation_size(model_type, plan.model_cfg)
    if topology_facts.declares_physical_geometry and declared_segmentation_size is not None:
        _validate_data_config(
            trial_config,
            int(declared_segmentation_size),
            topology_facts.physical_dataset,
        )

    # Build TWO independent SampleSets — training and validation.
    #
    # Step 12 / PR-12d, seam B (B2). `build_sample_set` decodes TIDMAD's
    # topology and fails closed without it, and it was called UNCONDITIONALLY
    # for every trial/formal round — before and independently of
    # `acquire_attempt_scopes`. A composed contrast run therefore died here,
    # holding a perfectly good task scope capability it was never asked to
    # use. The legacy SampleSets are now built only for an UNCOMPOSED caller
    # whose profile declares the geometry they encode. A composed run already
    # owns opaque task scopes. Sending both representations gives the child
    # two scope authorities and is correctly refused by the task-generic
    # training engine. This distinction is by composition presence, never
    # task name.
    if (
        trial_config.mode in ("trial", "formal")
        and topology_facts.declares_physical_geometry
        and agent_input.task_composition_ref is None
    ):
        # Step-02b: the run's profile is supplied EXPLICITLY to
        # both construction sites, rather than each one resolving
        # it ambiently inside the builder. Two consequences: a run
        # bound to a non-default topology can no longer silently
        # select against the ambient one, and train and eval
        # provably select against the same topology.
        #
        # Step-05a: `run_profile` is now the RUN-scoped binding
        # established at run() entry, not a second resolution
        # taken here. The tuner's validation, scope and
        # accounting consumers read that same value, so a round
        # can no longer select against one topology while being
        # validated and accounted against another.
        train_sample_set = build_sample_set(
            is_trial=True,
            trial_strategy=trial_config.trial_strategy,
            trial_portion=trial_config.trial_portion,
            target_files=trial_config.target_files or None,
            seed=trial_config.train_sampling_seed,
            scope=agent_input.data_scope,
            profile=run_profile,
        )
        eval_sample_set = build_sample_set(
            is_trial=True,
            trial_strategy=trial_config.eval_strategy,
            trial_portion=trial_config.eval_portion,
            target_files=trial_config.target_files or None,
            seed=trial_config.eval_sampling_seed,
            scope=agent_input.data_scope,
            profile=run_profile,
        )
        print(
            f"  {trial_config.mode.capitalize()} mode: "
            f"train: {trial_config.trial_strategy} portion={trial_config.trial_portion} "
            f"| eval: {trial_config.eval_strategy} portion={trial_config.eval_portion} "
            f"| train_portion/epoch={trial_config.train_portion} "
            f"| align={trial_config.train_validation_align}"
        )
    else:
        train_sample_set = None
        eval_sample_set = None
        print(_no_sample_set_notice(trial_config.mode, file_index))

    # Step 12 / PR-12bc B5 — task-owned scope acquisition. A CALLED boundary,
    # never a branch family here (§J). Un-composed runs acquire nothing and
    # keep resolving exactly as before; a composed run asks its BOUND
    # implementation to build this attempt's scopes, and a composed
    # implementation without the capability is refused HERE — parent-side,
    # before any subprocess — rather than at first spawn.
    task_scopes = acquire_attempt_scopes(
        composed=agent_input.task_composition_ref is not None,
        mode=trial_config.mode,
        trial_strategy=trial_config.trial_strategy,
        trial_portion=trial_config.trial_portion,
        eval_strategy=trial_config.eval_strategy,
        eval_portion=trial_config.eval_portion,
        train_sampling_seed=trial_config.train_sampling_seed,
        eval_sampling_seed=trial_config.eval_sampling_seed,
        target_files=trial_config.target_files,
        subset=agent_input.data_scope,
        training_validation_portion=agent_input.training_validation_portion,
        validation_max_samples=agent_input.validation_max_samples,
        # C12-P / B11. The DECLARED value travels; nothing becomes `10000`.
        # `task_parameters` is OPAQUE to the framework, and its only production
        # reader (`execute_tools/tidmad_data_path.py:383-395`) explicitly
        # refuses to guess this key — "the framework has no vocabulary for it,
        # so it must be declared by the caller rather than guessed here". The
        # literal defeated that refusal from outside, which is why it had never
        # once been reached; it is reachable now, and a model that declares
        # nothing still arrives here as `None` and is still refused by name.
        #
        # What travels is resolved above from the MODEL's declaration, not
        # authored by the framework. The distinction B11 drew — do not put a
        # framework-invented number into a channel the framework does not
        # speak — is intact: this number is the task's own, read through the
        # single authority, and it is the same one the model is constructed
        # with.
        task_parameters={"seg_size": declared_segmentation_size},
    )

    # 01B2 — a composed Health-enabled attempt may execute only after the
    # bound task confirms that THIS opaque evaluation scope covers its own
    # output-dependent Health demand. The helper is deliberately adjacent to
    # scope acquisition and before any admission/resource effect; it does not
    # inspect or enlarge the scope.
    validate_attempt_health_coverage(
        composed=agent_input.task_composition_ref is not None,
        health_enabled=agent_input.health_gate_enabled,
        data_path=bindings.run_task_data_path,
        evaluation_scope=task_scopes.evaluation,
        round_kind=trial_config.mode,
        health_binding=(
            agent_input.task_composition_ref.task_health_binding
            if agent_input.task_composition_ref is not None
            else None
        ),
        health_gate_files=agent_input.health_gate_files,
    )

    # Segment counts for records and reflector context. EXTRACTED (§E.2):
    # seam B's declared-absence case would otherwise have grown this function
    # by four branch nodes, and the accounting is its own responsibility.
    train_psd_segments, eval_psd_segments = _psd_segment_counts(
        train_sample_set,
        eval_sample_set,
        topology_facts,
        has_task_scopes=task_scopes.training is not None or task_scopes.evaluation is not None,
    )

    # `model_type` (the force_model override) is resolved ONCE, above, before
    # the first site that needs it. It used to be computed here; the assignment
    # was hoisted rather than duplicated, so there is still exactly one.
    exp_id = f"{model_type}_{run_name}_{total_attempts:03d}"
    hypothesis = plan.hypothesis

    print(f"Action: {model_type.upper()} | ID: {exp_id}")
    print(f"Hypothesis: {hypothesis}")
    print(f"Reasoning: {plan.reasoning or 'No reasoning provided.'}")

    # Save validated TrialConfig
    trial_config_path = os.path.join(sandbox.dirs["configs"], f"trial_config_{exp_id}.json")
    with open(trial_config_path, "w", encoding="utf-8") as f:
        json.dump(trial_config.model_dump(), f, indent=2)

    # C. ACT: Execute the Atomic Skill Pipeline (Train -> Inf -> Score)
    model_config = plan.model_cfg.copy()
    # Ensure model_config.model_type matches the forced model type
    model_config["model_type"] = model_type

    expected_custom_loss_snapshot = None
    if plan.loss_cfg.get("loss_type") == "custom":
        expected_custom_loss_snapshot = bindings.custom_loss_inventory.expected_snapshot

    # Lane D / F15 — close the tracker (the model channel is not plan-visible).
    execution_provenance = resolution.finish_with_model(plan, executed_model_type=model_type)
    active_params = {
        "exp_id": exp_id,
        "run_name": run_name,
        "model_type": model_type,
        "model_config": model_config,
        "train_config": plan.train_cfg,
        "loss_config": plan.loss_cfg,
        "expected_custom_loss_snapshot": expected_custom_loss_snapshot,
        "sample_set": train_sample_set,  # training data (from training files)
        # Step 12 / PR-12bc B6 — the composed run's TASK-BUILT scopes.
        # Empty on an un-composed run, so the emitter yields nothing and
        # the child argv is byte-identical.
        "task_scopes": task_scopes,
        "train_portion": trial_config.train_portion,
        "train_base_seed": trial_config.train_base_seed,
        "eval_sample_set": eval_sample_set,  # validation data (from validation files)
        # Ordering — resolved values only (V19 PR 2)
        "order_strategy": trial_config.resolved_order_strategy,
        "file_order": trial_config.resolved_file_order,
    }

    # Clean params for records — exclude bulky SampleSet dicts
    record_params = {
        "exp_id": exp_id,
        "run_name": run_name,
        "model_type": model_type,
        "model_config": model_config,
        "train_config": plan.train_cfg,
        "loss_config": plan.loss_cfg,
    }

    return PreparedAttempt(
        plan=plan,
        trial_config=trial_config,
        active_params=active_params,
        record_params=record_params,
        exp_id=exp_id,
        hypothesis=hypothesis,
        model_type=model_type,
        model_config=model_config,
        memory_history=memory_history,
        train_sample_set=train_sample_set,
        eval_sample_set=eval_sample_set,
        task_scopes=task_scopes,
        train_psd_segments=train_psd_segments,
        eval_psd_segments=eval_psd_segments,
        ordering=ordering,
        planned_trial_strategy=planned_trial_strategy,
        planned_eval_strategy=planned_eval_strategy,
        strategy_normalization_reason=strategy_normalization_reason,
        cfg_trial_portion=cfg_trial_portion,
        cfg_train_portion=cfg_train_portion,
        cfg_eval_portion=cfg_eval_portion,
        _planned_portions=_planned_portions,
        execution_provenance=execution_provenance,
        expected_custom_loss_snapshot=expected_custom_loss_snapshot,
    )
