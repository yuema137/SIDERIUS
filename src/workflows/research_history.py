"""Native completed-body history policy shared by fixed and authored research runs.

No file reads, promotion, scheduling or provider calls. Call only after successful
native body admission; infrastructure-abort/early-branch ownership stays at callers.
"""

from agent.schemas.health_feedback import FormalValidityFeedback
from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput, PredictionMemory
from agent.schemas.proposal import ExpertContextItem, ProposalOutput, VocabEntry
from core.chain_state import ChainState
from core.resume import RestoredState, union_key_findings
from execute_tools.evaluation_metric import MetricSpec, StampedMetricSpec, reconcile_metric_specs
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from workflows.run_bindings import WorkflowRunBindings


def acquire_iteration_order(
    bindings: WorkflowRunBindings, tune_output: HyperparamTuningOutput
) -> MetricOrder | None:
    """Compatibility wrapper for callers carrying native run bindings.

    Bound task metric and native output stamp must agree. Missing identity
    stays unrankable; it never supplies an assumed metric direction.
    """
    composition = getattr(bindings, "task_composition", None)
    bound = getattr(getattr(composition, "metric", None), "spec", None)
    return iteration_order(tune_output, bound=bound)


def iteration_order(
    tune_output: HyperparamTuningOutput, *, bound: MetricSpec | None
) -> MetricOrder | None:
    """Reconcile the native output stamp with the run's bound metric once."""
    spec = reconcile_metric_specs(
        [
            StampedMetricSpec(
                label=f"{tune_output.run_name!r} ({tune_output.model_type!r})",
                spec=tune_output.metric_spec,
            )
        ],
        bound=bound,
    )
    return MetricOrder(spec) if spec is not None else None


def cap_knowledge_cache(
    cache: dict,
    current_model: str,
    max_entries: int = 5,
    *,
    order: MetricOrder | None,
) -> tuple[dict, set[str]]:
    """Keep top-N models by best score + the current iteration's model.

    Native interpreter-memory policy, explicitly selected by authored
    ``native-research/v1`` history. Keep the current model and the highest
    ranked remaining models up to the existing limit. MetricOrder owns
    comparison, including scoreless ordering and stable ties.

    Returns:
        (capped_cache, evicted_model_types)
    """
    if len(cache) <= max_entries:
        return cache, set()

    if order is None:
        raise ValueError(
            "capping the knowledge cache evicts models by score, which requires the "
            "run's MetricOrder. None was supplied and the cache is over its limit — "
            "refusing rather than evicting on an assumed direction."
        )

    scored = [
        (mt, entry.get("_stats", {}).get("best_denoising_score"))
        for mt, entry in cache.items()
        if mt != current_model
    ]
    # Step 09a C3. Was `reverse=True` with a `-inf` fill — both direction
    # literals: under a minimised metric that KEEPS the worst models and
    # evicts the best. `rank` is 1 + (values strictly better) and Python's
    # sort is stable, so equal ranks keep insertion order exactly as
    # `reverse=True` did, and a scoreless entry still ranks last because
    # `worst_sentinel` is the value nothing can be worse than.
    present = [value for _, value in scored if value is not None]
    scored.sort(
        key=lambda x: order.rank(present, x[1] if x[1] is not None else order.worst_sentinel)
    )
    keep = {current_model} | {mt for mt, _ in scored[: max_entries - 1]}
    evicted = set(cache) - keep
    capped = {mt: entry for mt, entry in cache.items() if mt in keep}
    return capped, evicted


def recent_formal_feedback(
    state: ChainState,
    restored: RestoredState | None,
    *,
    initial: list[FormalValidityFeedback] | None = None,
) -> list[FormalValidityFeedback]:
    entries = (
        list(restored.accumulated_formal_feedback) if restored is not None else list(initial or [])
    )
    entries.extend(
        out.formal_validity_feedback
        for out in state.recent_tune_outputs
        if out.formal_validity_feedback is not None
    )
    return entries[-3:]


def advance_completed_history(
    state: ChainState,
    interpretation: InterpretationOutput,
    proposal: ProposalOutput,
    tune_output: HyperparamTuningOutput,
    *,
    required_gate_ids: frozenset[str] | None,
    run_metric_spec: MetricSpec | None,
    bound_metric_spec: MetricSpec | None,
) -> tuple[MetricOrder | None, set[str]]:
    """Apply the existing native completed-body fold without changing its policies.

    iteration_results is retained by the caller before infrastructure-abort handling;
    the bounded feedback window advances only here for a completed body.
    """
    state.recent_tune_outputs.append(tune_output)
    state.all_model_types.append(proposal.model_name)
    summary = tuning_output_to_model_run_summary(
        tune_output,
        order=MetricOrder(tune_output.metric_spec) if tune_output.metric_spec is not None else None,
        required_gate_ids=required_gate_ids,
    )
    summary.model_description = proposal.model_description
    state.latest_new_summary = summary
    evicted = set()
    if interpretation.model_knowledge_cache:
        state.model_knowledge_cache, evicted = cap_knowledge_cache(
            dict(interpretation.model_knowledge_cache),
            current_model=proposal.model_name,
            order=MetricOrder(run_metric_spec) if run_metric_spec is not None else None,
        )
    state.current_prediction_memory = PredictionMemory(
        prediction_outcomes_history=dict(interpretation.prediction_outcomes_history),
        prediction_outcomes_by_semantics={
            k: dict(v) for k, v in interpretation.prediction_outcomes_by_semantics.items()
        },
        cumulative_information_gain=interpretation.cumulative_information_gain,
        cumulative_information_gain_by_semantics=dict(
            interpretation.cumulative_information_gain_by_semantics
        ),
    )
    state.current_vocab_link_confirmations = {
        key: list(runs) for key, runs in interpretation.vocab_link_confirmations.items()
    }
    union_key_findings(state.accumulated_key_findings, interpretation.key_findings)
    state.previous_proposal_data = proposal.model_dump()
    if interpretation.runtime_vocab:
        state.current_runtime_vocab = [
            v if hasattr(v, "name") else VocabEntry.model_validate(v)
            for v in interpretation.runtime_vocab
        ]
    order = iteration_order(tune_output, bound=bound_metric_spec)
    if order is not None:
        formal = tune_output.best_formal_denoising_score
        if formal is not None and (
            state.best_score_overall is None or order.is_better(formal, state.best_score_overall)
        ):
            state.best_score_overall = formal
        valid = tune_output.best_valid_formal_denoising_score
        if valid is not None and (
            state.chain_formal_incumbent_reference is None
            or order.is_better(valid, state.chain_formal_incumbent_reference)
        ):
            state.chain_formal_incumbent_reference = valid
    return order, evicted


def seed_history(value: InterpretationInput) -> ChainState:
    """Preserve explicitly authored initial memory without inventing an incumbent."""
    return ChainState.from_restored(
        restored_runtime_vocab=value.runtime_vocab,
        restored_model_knowledge_cache=value.model_knowledge_cache,
        restored_previous_proposal=value.previous_proposal,
        restored_collapse_fingerprint_history=value.collapse_fingerprint_history,
        restored_prediction_memory=PredictionMemory(
            **{name: getattr(value, name) for name in PredictionMemory.model_fields}
        ),
        restored_vocab_link_confirmations=value.vocab_link_confirmations,
        all_model_types=[item.model_type for item in value.summaries],
    )


def history_metric(state: ChainState, declared: MetricSpec | None) -> MetricSpec | None:
    """An explicit seed binds identity; otherwise retain the latest known native stamp."""
    if declared is not None:
        return declared
    return next(
        (
            output.metric_spec
            for output in reversed(state.iteration_results)
            if output.metric_spec is not None
        ),
        None,
    )


def interpretation_history(state: ChainState, seed: InterpretationInput) -> dict:
    """Project only native carried fields; task, advice and launch values stay authored."""
    summaries = [] if state.latest_new_summary is None else [state.latest_new_summary]
    return {
        "summaries": summaries,
        "metric_spec": history_metric(state, seed.metric_spec),
        "model_knowledge_cache": state.model_knowledge_cache,
        "cold_start": not summaries and not state.model_knowledge_cache,
        **state.current_prediction_memory.model_dump(),
        "vocab_link_confirmations": state.current_vocab_link_confirmations,
        "recent_formal_validity": recent_formal_feedback(
            state, None, initial=seed.recent_formal_validity
        ),
        "runtime_vocab": state.current_runtime_vocab,
        "previous_proposal": state.previous_proposal_data,
        "collapse_fingerprint_history": state.current_collapse_fingerprint_history,
    }


def prior_findings(state: ChainState) -> list[ExpertContextItem]:
    """The native chronological findings channel, shared by both dispatchers."""
    if not state.accumulated_key_findings:
        return []
    bullet_block = "\n".join(f"- {kf}" for kf in state.accumulated_key_findings)
    return [
        ExpertContextItem(
            source="prior_iters",
            kind="findings",
            content=(
                f"Accumulated key findings from "
                f"{len(state.accumulated_key_findings)} prior iter(s):\n{bullet_block}"
            ),
            source_ref="prior_iters_key_findings",
        )
    ]
