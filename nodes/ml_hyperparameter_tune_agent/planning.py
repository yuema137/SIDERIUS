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

from agent.schemas.hyperparam_tuning import (
    ExperimentPlan,
    TrialConfig,
)
from agent.schemas.ordering import resolve_ordering
from execute_tools.dataset_config import tidmad_topology
from execute_tools.health_checks.candidate_eligibility import (
    is_valid_candidate,
)
from execute_tools.sample_set_builder import build_sample_set
from nodes.ml_hyperparameter_tune_agent.contracts import PreparedAttempt, RunBindings
from nodes.ml_hyperparameter_tune_agent.policy import (
    _apply_mode_override_chain,
    _apply_plan_overrides,
    _resolve_sample_set_cfg,
    _score_of,
    _validate_data_config,
)
from nodes.ml_hyperparameter_tune_agent.runtime import (
    _apply_epoch_bound,
)
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import acquire_attempt_scopes


def prepare_attempt(
    bindings: RunBindings,
    *,
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
        if is_valid_candidate(r)
        and isinstance(r.get("score_table"), dict)
        and r["score_table"].get("rendered_markdown")
    ]
    if _records_with_table:
        _best_rec = run_order.best(_records_with_table, key=_score_of)
        best_score_table_md = _best_rec["score_table"]["rendered_markdown"]

    # B. THINK: Plan next experiment
    decision = brain.plan(
        memory_history,
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
        task_description=agent_input.task_description,
        # L6b — loss-registry awareness. Drives both the
        # AVAILABLE CUSTOM LOSSES system-prompt block and
        # the per-architecture loss_note advertisement of
        # ``loss_type="custom"`` as a legal choice. See
        # docs/design/enable_loss_inventory.md § L6b.
        registry=bindings.registry,
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

    # Apply hard overrides from operator config (before other
    # overrides). FU-10 — an invalid effective plan raises
    # PlanOverridesError (run-terminating); see the helper.
    plan = _apply_plan_overrides(plan, agent_input.plan_overrides)

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
    )

    # DataScope DS5 — normalize LLM-planned strategies under a
    # partial scope. LLM plans are proposals (normalized with
    # persisted provenance, not failed); operator config was
    # already validated at startup; the sandbox boundary
    # still fails hard if anything slips through.
    planned_trial_strategy = plan.trial_strategy
    planned_eval_strategy = plan.eval_strategy
    strategy_normalization_reason: str | None = None
    if (
        scope_is_partial
        and plan.is_trial
        and (plan.trial_strategy != "snapshot" or plan.eval_strategy != "snapshot")
    ):
        print(
            f"  [DATASCOPE] normalized strategies: "
            f"trial {plan.trial_strategy} → snapshot, "
            f"eval {plan.eval_strategy} → snapshot "
            f"(partial scope {resolved_data_scope})"
        )
        plan.trial_strategy = "snapshot"
        plan.eval_strategy = "snapshot"
        strategy_normalization_reason = "partial_data_scope"

    # Enforce max_epochs hard cap (prevents LLM from choosing
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
    _apply_epoch_bound(plan.train_cfg, agent_input.max_epochs)

    # Build and validate TrialConfig from plan + overrides
    if plan.is_trial:
        mode = "trial"
    elif trial_allowed:
        mode = "formal"
    else:
        mode = "single_file"

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

    # Validate integer relationships between dataset, PSD, ML segments
    _validate_data_config(
        trial_config,
        plan.model_cfg.get("segmentation_size", 10000),
        tidmad_topology(run_profile).dataset,
    )

    # Build TWO independent SampleSets — training and validation
    if trial_config.mode in ("trial", "formal"):
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
        print(f"  Legacy mode: file_index={file_index}")

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
        validation_max_samples=agent_input.validation_max_samples,
        task_parameters={"seg_size": plan.model_cfg.get("segmentation_size", 10000)},
    )

    # Segment counts for records and reflector context
    if train_sample_set:
        train_psd_segments = sum(len(v) for v in train_sample_set.values())
    else:
        # Legacy single-file: the whole file is used, so the
        # count IS the run topology's segments-per-file.
        # Step-05a reads it from the run-bound profile — under
        # TIDMAD this is byte-identical, and under a bound task
        # the record no longer reports TIDMAD's 200 segments
        # for a file that does not have 200.
        train_psd_segments = tidmad_topology(run_profile).dataset.segments_per_file

    if eval_sample_set:
        eval_psd_segments = sum(len(v) for v in eval_sample_set.values())
    else:
        eval_psd_segments = tidmad_topology(run_profile).dataset.segments_per_file  # legacy

    # When force_model is set, override the LLM's model_type choice.
    # (C7d: ruff SIM108 collapses this to a ternary now that the block sits at
    # function level; the value is identical.)
    model_type = model_type_setting if model_type_setting != "auto" else plan.model_type
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
    active_params = {
        "exp_id": exp_id,
        "run_name": run_name,
        "model_type": model_type,
        "model_config": model_config,
        "train_config": plan.train_cfg,
        "loss_config": plan.loss_cfg,
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
    )
