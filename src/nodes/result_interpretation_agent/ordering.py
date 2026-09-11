"""The interpreter's run-scoped ordering boundary (node-private).

Step 09a C1b (design:
``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §3.1; parent §13a).

``run()`` used to compute its deterministic pre-computation and its enriched
prompt fields inline, interleaved with description loading, health merging and
the LLM phases. Both regions are pure functions of their inputs, and both are
exactly where Step 09a's ordering semantics land (C3), so they move behind
typed boundaries here and ``run()`` keeps only the sequencing.

C1b is behaviour-preserving: both functions reproduce the original regions
line for line, including the direction literals — migrating those onto
``MetricOrder`` is C3's job, against the C1a oracle this commit must not move.

Private BY OWNERSHIP; the dependency edge runs main -> here, never back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from agent.schemas.score_table import ScoreComparisonTable
from execute_tools.metric_order import MetricOrder
from execute_tools.scientific_aggregation import AggregationScope, partition_for_aggregation
from nodes.result_interpretation_agent.evidence import InterpretationContractError


def bind_run_order(inp: InterpretationInput) -> MetricOrder | None:
    """The ONE ``MetricOrder`` this interpretation compares scores through.

    Step 09a C2. Bound once per ``run()``, from the spec the run already
    resolved and transported — the interpreter never derives a metric.

    ``None`` only where the input contract admitted a spec-less input: a cold
    start, or a genuinely scoreless one. Any input carrying a score without a
    spec was already refused at construction (``InterpretationInput``'s
    ``metric_spec_is_present_and_agrees_with_the_evidence``), so a ``None``
    here can never silently become "higher is better".
    """
    if inp.metric_spec is None:
        return None
    return MetricOrder(inp.metric_spec)


@dataclass(frozen=True)
class _CachedAggregationCandidate:
    """A cached-only model, shaped for the authority partition.

    N-2. ``partition_for_aggregation`` reads ``model_type`` and
    ``scientific_authority`` STRUCTURALLY (``HasScientificAuthority``), so a
    cached ``_stats`` block is presented through the same protocol a fresh
    ``ModelRunSummary`` satisfies. A second partitioning rule for cached
    models is exactly what must not exist here: the filter and the aggregate
    have to range over the same set, or the difference is a silence.

    ``scientific_authority`` is ``None`` for a ``_stats`` block written
    before the verdict travelled with the score. That resolves to
    ``unreconstructable_legacy`` and EXCLUDES the model, which is the frozen
    rule for anything missing the authority contract — fail-closed, and now
    reported instead of dropped.
    """

    model_type: str
    scientific_authority: dict[str, Any] | None


@dataclass(frozen=True)
class PrecomputedEvidence:
    """Everything ``run()`` derives from summaries + cache before the LLM block.

    Frozen because it is a snapshot of deterministic facts: once computed for
    an iteration, nothing downstream may rewrite it — the LLM phases READ it.
    """

    per_model_best: dict[str, float | None]
    per_model_best_valid: dict[str, float | None]
    per_model_raw_best_health_validity: dict[str, str]
    per_model_worst: dict[str, float | None]
    per_model_formal: dict[str, float | None]
    #: F-SCANE-1 — model_type → typed exclusion reason, for the models that
    #: HAD a formal score and lost it to the authority filter below. Without
    #: it the exclusion is a SILENCE in the synthesis prompt: the caveat that
    #: warns "best_score above may be from a trial round" is gated on a
    #: non-empty ``per_model_formal``, so the run whose formal evidence is
    #: unusable is exactly the run that renders the trial-mixed best with the
    #: warning removed. Only models whose formal score was actually withheld
    #: appear here — a model that never had one is an absence, not a
    #: withholding, and must not be reported as one.
    per_model_formal_excluded: dict[str, str]
    per_model_best_config: dict[str, dict | None]
    overall_best_score: float | None
    overall_best_valid_score: float | None
    overall_worst_score: float | None
    overall_best_config: dict[str, Any] | None
    overall_best_valid_config: dict[str, Any] | None
    total_experiments: int
    per_model_summary_input: dict[str, ModelRunSummary]
    aggregation_scope: AggregationScope


@dataclass(frozen=True)
class EnrichedFields:
    """The per-model prompt enrichment read from summaries and the cache."""

    per_model_score_tables: dict[str, ScoreComparisonTable]
    per_model_params: dict[str, int]
    per_model_training_segments: dict[str, int]


def precompute_evidence(
    summaries: list[ModelRunSummary],
    model_knowledge_cache: dict[str, Any],
    effective_types: list[str],
    *,
    order: MetricOrder | None,
) -> PrecomputedEvidence:
    """Deterministic pre-computation over new summaries + cached ``_stats``.

    New models are read from ``summaries``; cached models are reconstructed
    from ``model_knowledge_cache[mt]["_stats"]``, with a new summary always
    taking precedence over a cached entry for the same model type.

    The scientific-aggregation filter runs HERE, before any LLM call, because
    ``per_model_formal`` is the formal-score aggregate that reaches the
    synthesis prompt: a non-authoritative formal score left in it would inform
    a scientific claim, which is exactly what the authority verdict exists to
    prevent (V20 PR D, D-C5). Excluded results are not deleted — they stay on
    the summaries and in the returned scope, which the report renders.

    The filter's domain is ``summaries`` PLUS the cached-only models (N-2),
    because that is the domain ``per_model_formal`` itself has. Narrowing the
    partition to the new summaries alone put every cached model outside both
    halves of the verdict, which reads as "nothing was withheld" while its
    formal score is being dropped.

    ``order`` is keyword-only with NO default (Step 09a C3): every ranking
    below is a direction question, and a defaulted argument is exactly how
    "higher is better" became invisible in the first place. ``None`` is
    admitted only for the cold-start / scoreless input the contract allows,
    and the first comparison that actually needs a direction refuses.
    """

    def _authority(what: str) -> MetricOrder:
        if order is None:
            raise InterpretationContractError(
                f"ranking {what} requires the run's MetricOrder, but this input was "
                "admitted without a MetricSpec (cold start / scoreless) and a score "
                "reached the pre-computation anyway. Refusing rather than assuming a "
                "direction."
            )
        return order

    per_model_best: dict[str, float | None] = {}
    per_model_best_valid: dict[str, float | None] = {}
    per_model_raw_best_health_validity: dict[str, str] = {}
    per_model_worst: dict[str, float | None] = {}
    per_model_formal: dict[str, float | None] = {}
    per_model_best_config: dict[str, dict | None] = {}
    overall_best_score: float | None = None
    overall_best_valid_score: float | None = None
    overall_worst_score: float | None = None
    overall_best_config: dict[str, Any] | None = None
    overall_best_valid_config: dict[str, Any] | None = None
    total_experiments = 0

    # Map model_type → ModelRunSummary (new models only)
    per_model_summary_input: dict[str, ModelRunSummary] = {}

    for s in summaries:
        mt = s.model_type
        per_model_summary_input[mt] = s
        total_experiments += s.completed_rounds

        if s.best_denoising_score is not None:
            best_order = _authority("per-model and overall best scores")
            current_best = per_model_best.get(mt)
            if current_best is None or best_order.is_better(s.best_denoising_score, current_best):
                per_model_best[mt] = s.best_denoising_score
                per_model_best_config[mt] = s.best_config
            if overall_best_score is None or best_order.is_better(
                s.best_denoising_score, overall_best_score
            ):
                overall_best_score = s.best_denoising_score
                overall_best_config = s.best_config
        per_model_best_valid[mt] = s.best_valid_denoising_score
        per_model_raw_best_health_validity[mt] = s.best_raw_health_validity
        if s.best_valid_denoising_score is not None and (
            overall_best_valid_score is None
            or _authority("the overall best VALID score").is_better(
                s.best_valid_denoising_score, overall_best_valid_score
            )
        ):
            overall_best_valid_score = s.best_valid_denoising_score
            overall_best_valid_config = s.best_valid_config

        if s.worst_denoising_score is not None:
            # "worse than" is asked as `is_better(incumbent, candidate)` rather
            # than by constructing an opposite-direction order — MetricOrder
            # exists so direction is read in exactly ONE place.
            worst_order = _authority("per-model and overall worst scores")
            current_worst = per_model_worst.get(mt)
            if current_worst is None or worst_order.is_better(
                current_worst, s.worst_denoising_score
            ):
                per_model_worst[mt] = s.worst_denoising_score
            if overall_worst_score is None or worst_order.is_better(
                overall_worst_score, s.worst_denoising_score
            ):
                overall_worst_score = s.worst_denoising_score

        if s.formal_score is not None:
            per_model_formal[mt] = s.formal_score

    # Reconstruct stats for cached models from their _stats block
    #
    # N-2 — a cached model contributes to `per_model_formal` below, so it must
    # also reach the authority partition. Collected in the SAME loop that
    # reads its stats, so the two sets cannot drift apart again.
    cached_aggregation_candidates: list[_CachedAggregationCandidate] = []
    for mt, entry in model_knowledge_cache.items():
        if mt in per_model_summary_input:
            continue  # new summary takes precedence
        stats = entry.get("_stats", {})
        cached_aggregation_candidates.append(
            _CachedAggregationCandidate(
                model_type=mt,
                scientific_authority=stats.get("scientific_authority"),
            )
        )
        best = stats.get("best_denoising_score")
        best_valid = stats.get("best_valid_denoising_score")
        worst = stats.get("worst_denoising_score")
        total_experiments += stats.get("completed_rounds", 0)

        per_model_best[mt] = best
        per_model_best_valid[mt] = best_valid
        per_model_raw_best_health_validity[mt] = stats.get("best_raw_health_validity", "unknown")
        per_model_worst[mt] = worst
        per_model_best_config[mt] = stats.get("best_config")
        if stats.get("formal_score") is not None:
            per_model_formal[mt] = stats["formal_score"]

        if best is not None and (
            overall_best_score is None
            or _authority("the overall best score (cached)").is_better(best, overall_best_score)
        ):
            overall_best_score = best
            overall_best_config = stats.get("best_config")
        if best_valid is not None and (
            overall_best_valid_score is None
            or _authority("the overall best VALID score (cached)").is_better(
                best_valid, overall_best_valid_score
            )
        ):
            overall_best_valid_score = best_valid
            overall_best_valid_config = stats.get("best_valid_config") or stats.get("best_config")
        if worst is not None and (
            overall_worst_score is None
            or _authority("the overall worst score (cached)").is_better(overall_worst_score, worst)
        ):
            overall_worst_score = worst

    # Fill None for any model type still missing
    for mt in effective_types:
        per_model_best.setdefault(mt, None)
        per_model_best_valid.setdefault(mt, None)
        per_model_raw_best_health_validity.setdefault(mt, "unknown")
        per_model_worst.setdefault(mt, None)
        per_model_best_config.setdefault(mt, None)

    # --- V20 PR D (D-C5): the scientific aggregate excludes
    #     non-authoritative formal results, and says so ---
    # Deterministic and BEFORE any LLM call. §4.7 keeps the exclusion
    # rendering deterministic rather than asking the model to mention it — a
    # model may simply not, and exclusion text inside a prompt can steer the
    # interpretation it then writes.
    #
    # N-2 — THE PARTITION RANGES OVER THE SAME SET THE AGGREGATE DOES.
    # `per_model_formal` above is filled from the new summaries AND from the
    # cached `_stats` blocks; partitioning only `summaries` left every
    # cached-only model outside BOTH halves of the verdict — its formal score
    # was deleted by the `_authoritative` filter (it can never be in an
    # `included` list built from summaries) and no exclusion reason existed to
    # report it, so the withholding was a silence. In a chain subprocess that
    # is the normal case, not an edge case: after the first iteration the
    # workflow passes exactly ONE new summary and every other model is cached.
    #
    # A cached entry carries whatever verdict the iteration that produced it
    # recorded (`_stats["scientific_authority"]`); one written before the
    # verdict travelled with the score carries none, resolves to
    # `unreconstructable_legacy`, and is excluded — the frozen rule for
    # anything missing the authority contract.
    aggregation_scope = partition_for_aggregation([*summaries, *cached_aggregation_candidates])
    _authoritative = set(aggregation_scope.included)
    # F-SCANE-1 — captured BEFORE the filter, and only for models that
    # actually had a formal score to lose. Order is load-bearing: computed
    # after the filter, `per_model_formal` no longer knows which entries it
    # dropped, which is precisely how the exclusion became a silence.
    _exclusion_reasons = {item.record_id: item.reason for item in aggregation_scope.excluded}
    per_model_formal_excluded = {
        mt: _exclusion_reasons[mt]
        for mt, score in per_model_formal.items()
        if score is not None and mt in _exclusion_reasons
    }
    per_model_formal = {mt: score for mt, score in per_model_formal.items() if mt in _authoritative}

    return PrecomputedEvidence(
        per_model_best=per_model_best,
        per_model_best_valid=per_model_best_valid,
        per_model_raw_best_health_validity=per_model_raw_best_health_validity,
        per_model_worst=per_model_worst,
        per_model_formal=per_model_formal,
        per_model_formal_excluded=per_model_formal_excluded,
        per_model_best_config=per_model_best_config,
        overall_best_score=overall_best_score,
        overall_best_valid_score=overall_best_valid_score,
        overall_worst_score=overall_worst_score,
        overall_best_config=overall_best_config,
        overall_best_valid_config=overall_best_valid_config,
        total_experiments=total_experiments,
        per_model_summary_input=per_model_summary_input,
        aggregation_scope=aggregation_scope,
    )


def collect_enriched_fields(
    summaries: list[ModelRunSummary],
    model_knowledge_cache: dict[str, Any],
    per_model_summary_input: dict[str, ModelRunSummary],
) -> EnrichedFields:
    """Per-model score tables, parameter counts and training volumes.

    New models are read from ``summaries``; cached models fall back to their
    ``_stats``. The cache stores ``best_score_table`` as a plain dict (JSON
    round-trip safe), so it is re-validated back into a
    ``ScoreComparisonTable`` before registration — a malformed cached table
    RAISES, which is why ``run()`` calls this from inside its LLM try-block:
    the degraded path is the designed outcome, and C1b does not move that.
    """
    per_model_score_tables: dict[str, ScoreComparisonTable] = {}
    per_model_params: dict[str, int] = {}
    per_model_training_segments: dict[str, int] = {}

    def _register_score_table(mt: str, table: ScoreComparisonTable | None):
        if table is None:
            return
        per_model_score_tables[mt] = table

    for s in summaries:
        mt = s.model_type
        _register_score_table(mt, s.best_score_table)
        if s.best_model_params is not None:
            per_model_params[mt] = s.best_model_params
        if s.training_psd_segments is not None:
            per_model_training_segments[mt] = s.training_psd_segments

    # Fill from cache _stats for cached models not in new summaries.
    for mt, entry in model_knowledge_cache.items():
        if mt in per_model_summary_input:
            continue
        stats = entry.get("_stats", {})
        cached_table_data = stats.get("best_score_table")
        cached_table = (
            ScoreComparisonTable.model_validate(cached_table_data)
            if cached_table_data is not None
            else None
        )
        _register_score_table(mt, cached_table)
        if stats.get("best_model_params") is not None:
            per_model_params[mt] = stats["best_model_params"]

    return EnrichedFields(
        per_model_score_tables=per_model_score_tables,
        per_model_params=per_model_params,
        per_model_training_segments=per_model_training_segments,
    )
