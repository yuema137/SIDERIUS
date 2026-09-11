"""Prediction grammar, band and versioned accounting (node-private).

Step 09a C1b (extraction) + C4 (semantics). Design:
``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §3.1, §3.4; parent §8, §13 ¶1;
operator rulings Q-09a-2 and Q-09a-3.

Why this module exists
----------------------
The prediction cluster arrived here from ``nodes/interpretation_helpers.py``,
a MIXED module that also holds discoveries, the vocabulary machinery, the
active-model policy and summary compression. Prediction semantics are
interpreter-owned and are what Step 09a re-specifies, so they belong to the
node. They are DEFINED here exactly once; the helpers module no longer
defines them at all.

What C4 corrected
-----------------
The pre-09a evaluator had three defects that all looked like working code:

1. **direction-blind.** ``actual > sota`` means "confirmed" only for a
   maximised metric. Under a minimised one it labels every REGRESSION a
   confirmation.
2. **sign-degenerate.** The partial band was ``actual >= sota * (1 - margin)``.
   Scaling a NEGATIVE reference by 0.95 moves it toward zero, so for every
   TIDMAD score (all negative) the band sat on the wrong side of the SOTA and
   was unreachable. The band is now a DISTANCE measured against a width taken
   from the reference's MAGNITUDE — same 0.05 margin, frozen.
3. **uncomputable counted as evidence.** A prediction whose metric could not
   be computed returned ``outcome="partial"`` with an explanatory note. That
   is not a weak confirmation; it is NO observation. It polluted the accuracy
   pool and, through ``generate_discoveries``, was published as a scientific
   finding reading "achieved metric=N/A". It is now ``unevaluated`` and is
   counted in neither pool.

Versioned accounting (Q-09a-2)
------------------------------
Corrected outcomes are NOT comparable with outcomes produced by the old rule,
so they are never pooled. ``prediction_outcomes_history`` remains the legacy
v1 pool, carried forward byte-identically and never incremented here; new
outcomes accumulate under
``prediction_outcomes_by_semantics["metric_order_signsafe_v2"]``. Accuracy is
computed from the v2 pool ALONE and labelled with the semantics id that
produced it, and the digest states both pools' sizes so no reader can mistake
a mixed statistic for a comparable one. Old persisted digests are never
rewritten.

Private BY OWNERSHIP; the dependency edge runs main -> here, never back.
"""

from __future__ import annotations

import math
from typing import Any

# The prediction-accounting vocabulary is DECLARED once in the schema that
# owns the fields it keys (`agent/schemas/interpretation.py`) and imported here
# — the schema layer is the lowest point every consumer of these ids can reach
# downward, so this module implements the v2 rule without also owning its name.
# Re-exported under the same names because this module is where the ids are
# consumed and where callers have always imported them from.
from agent.schemas.interpretation import (
    COMPARABLE_OUTCOMES,
    OUTCOME_UNEVALUATED,
    PREDICTION_SEMANTICS_LEGACY_V1,
    PREDICTION_SEMANTICS_SIGNSAFE_V2,
)
from execute_tools.metric_order import MetricOrder

#: LEGACY metric aliases, read-only.
#:
#: Pre-09a proposals were free-form about how they named the golden metric, so
#: predictions already on disk use any of these. They are accepted so a chain
#: crossing the 09a boundary can still evaluate its previous proposal, and the
#: resolution is RECORDED as ``legacy_alias`` rather than silently normalised.
#:
#: This table is FROZEN. It is not the extension point: a new task's metric is
#: recognised by its own bound id, never by being added here (design §3.4,
#: R-09-5). Growing it for Pets or DAVIS would rebuild the per-task vocabulary
#: Step 09 exists to remove.
_LEGACY_METRIC_ALIASES = frozenset(
    {
        "denoising_score",
        "best_score",
        "overall denoising score",
        "score",
        "best_denoising_score",
    }
)

#: The D1-frozen name of the primary scalar inside ``actual_results``.
_PRIMARY_SCALAR_KEY = "best_denoising_score"

#: The D1-frozen name of the per-sample evidence inside ``actual_results``.
_PER_SAMPLE_KEY = "best_file_vector"


def evaluate_prediction(
    prediction: dict[str, Any],
    actual_results: dict[str, Any],
    current_sota: float | None = None,
    partial_margin: float = 0.05,
    *,
    order: MetricOrder,
    bound_metric_id: str,
) -> dict[str, Any]:
    """Evaluate whether this model beat the SOTA it was proposed against.

    The baseline is the SOTA at the time of proposal, not the LLM's predicted
    value: predicting exact scores is unreliable, and the meaningful question
    is whether the architecture surpassed the bar it was designed to beat.

    The frozen band (parent §13 ¶1) — no task branch, no value-sign branch::

        distance   = abs(actual - sota)
        band_width = partial_margin * abs(sota)

        actual or sota unavailable      -> unevaluated  (counted in NO pool)
        order.is_better(actual, sota)   -> confirmed    (gain = distance)
        distance <= band_width          -> partial      (gain = 0)
        otherwise                       -> refuted      (gain = 0)

    Equality belongs to the partial band, and the band edge is INCLUSIVE.

    Args:
        prediction: the serialized ``FalsifiablePrediction``. ``metric``
            defaults to ``bound_metric_id`` — NOT to the literal
            ``"denoising_score"``, which was a task name hardcoded in the
            framework.
        actual_results: ``{best_denoising_score, best_file_vector}`` — the
            D1-frozen names, unchanged.
        current_sota: overrides ``prediction["current_value"]`` when given.
        partial_margin: the band's width as a fraction of ``abs(sota)``.
        order: the run's ``MetricOrder``. Keyword-only and REQUIRED: this is
            the whole point of the correction, and a default would make the
            direction invisible again.
        bound_metric_id: the run's metric identity, keyword-only and REQUIRED.

    Returns:
        A record with a UNIFORM shape on every branch (the uncomputable path
        used to return a different key set, so a consumer reading it had to
        guess): ``metric, metric_resolution, predicted_value, actual_value,
        current_sota, delta_from_sota, outcome, boldness, information_gain,
        notes, prediction_evaluation_semantics``.
    """
    metric = prediction.get("metric") or bound_metric_id
    predicted = prediction.get("predicted_value")
    sota = current_sota if current_sota is not None else prediction.get("current_value")
    actual, resolution = _compute_metric(metric, actual_results, bound_metric_id=bound_metric_id)

    boldness = (
        round(abs(predicted - sota) / max(abs(sota), 1e-6), 4)
        if predicted is not None and sota is not None
        else 0.0
    )

    def _record(
        outcome: str,
        *,
        delta: float | None,
        gain: float,
        notes: str | None,
    ) -> dict[str, Any]:
        return {
            "metric": metric,
            "metric_resolution": resolution,
            "predicted_value": predicted,
            "actual_value": actual,
            "current_sota": sota,
            "delta_from_sota": delta,
            "outcome": outcome,
            "boldness": boldness,
            "information_gain": gain,
            "notes": notes,
            "prediction_evaluation_semantics": PREDICTION_SEMANTICS_SIGNSAFE_V2,
        }

    if actual is None or sota is None:
        # NOT a weak "partial". Nothing was observed, so nothing is counted
        # and no discovery is published (the E5 defect).
        missing = "the metric could not be computed from the results"
        if sota is None:
            missing = (
                "no SOTA baseline was available"
                if actual is not None
                else "neither the metric nor a SOTA baseline was available"
            )
        return _record(
            OUTCOME_UNEVALUATED,
            delta=None,
            gain=0.0,
            notes=(
                f"Prediction not evaluated: {missing} "
                f"(metric={metric!r}, resolution={resolution!r})."
            ),
        )

    delta = actual - sota
    distance = abs(delta)
    band_width = partial_margin * abs(sota)

    if order.is_better(actual, sota):
        outcome, gain = "confirmed", distance
    elif distance <= band_width:
        outcome, gain = "partial", 0.0
    else:
        outcome, gain = "refuted", 0.0

    return _record(
        outcome,
        # SIGNED, deliberately: it says which way the result moved on the
        # metric's own axis, which `distance` alone cannot.
        delta=round(delta, 4),
        gain=round(gain, 4),
        notes=None,
    )


def _compute_metric(
    metric: str,
    results: dict[str, Any],
    *,
    bound_metric_id: str,
) -> tuple[float | None, str]:
    """Resolve a prediction's ``metric`` string against the actual results.

    Returns ``(value, resolution)``. The RESOLUTION is recorded on the
    evaluation so a reader can tell "the metric was the run's own" from "an
    old alias was accepted" from "this form needs per-sample evidence the task
    does not produce" — three situations the old ``None`` return collapsed
    into one.

    | ``metric``                              | resolution              |
    |-----------------------------------------|-------------------------|
    | the run's bound id                      | ``bound_id``            |
    | a frozen legacy alias                   | ``legacy_alias``        |
    | ``mean(file_vector[N:M])``              | ``refused_forbidden_aggregation`` |
    | ``file_vector[N]``                      | ``per_sample_index``    |
    | a per-sample form, no per-sample evidence | ``per_sample_unavailable`` |
    | anything else                           | ``unrecognized``        |
    """
    if metric == bound_metric_id:
        return results.get(_PRIMARY_SCALAR_KEY), "bound_id"
    if metric in _LEGACY_METRIC_ALIASES:
        return results.get(_PRIMARY_SCALAR_KEY), "legacy_alias"

    is_slice = metric.startswith("mean(file_vector[") and metric.endswith("])")
    is_index = metric.startswith("file_vector[") and metric.endswith("]")
    if not (is_slice or is_index):
        return None, "unrecognized"

    fv = results.get(_PER_SAMPLE_KEY)
    if fv is None:
        # Capability, not corruption: a scalar-only task (Pets and DAVIS both
        # are) simply has no per-sample evidence for this form to address.
        return None, "per_sample_unavailable"

    if is_slice:
        # F-SCAND-1 — REFUSED, not computed.
        #
        # This used to return the arithmetic mean of `fv[start:end]`.
        # The values reaching here are per-file LOG_5.27 scores, so a slice
        # mean is a "mean of per-file log scores" — the FIRST form the
        # aggregation standard forbids by name, for JENSEN'S INEQUALITY GAP:
        # the mean of logs is not the log of the mean, so the number is not
        # the score of anything.
        #
        # Trace the value, not the producer: `score_vector` returns LINEAR
        # per-file means, but they do not arrive here in that form. The
        # tuner converts to log space (`file_vector_to_log_space`) before
        # building the score table, the table's `model` field is declared
        # log_5.27 (`agent/schemas/score_table.py`), and the sole caller of
        # `evaluate_prediction` synthesizes this vector from exactly that
        # field. Reading the producer and stopping is how this comment was
        # first written the other way round.
        #
        # A band slice compounds it with a SECOND violation — "mean of
        # per-band linear means", the third forbidden form — because the
        # campaign's bands are 4/6/5/5 and averaging a 4-file band against a
        # 6-file band gives each file in the smaller band 1.5x the influence.
        #
        # The value is refused rather than approximated. A returned number
        # would be indistinguishable from a valid one downstream, which is
        # the whole hazard: the prediction pool would carry an aggregate
        # nobody could reproduce from the run's own scalar.
        #
        # `None` lands this in the EXISTING `unevaluated` pool (counted in
        # NO pool) — the frozen behaviour class for a prediction that cannot
        # be computed. No new outcome, no new pool.
        #
        # Deliberately NOT accompanied by an alternative aggregation: the
        # metric authority is frozen, and inventing a "correct" band score
        # here would be a second scoring authority. If a band breakdown is
        # wanted, `score_vector` on a scoped SampleSet is the supported
        # route.
        return None, "refused_forbidden_aggregation"

    try:
        idx = int(metric[len("file_vector[") : -1])
        val = fv[idx]
        if val is not None and not (isinstance(val, float) and math.isnan(val)):
            return val, "per_sample_index"
    except (ValueError, IndexError):
        return None, "unrecognized"
    return None, "per_sample_index"


def is_comparable(evaluation: dict[str, Any] | None) -> bool:
    """Whether this evaluation contributes to a comparable pool."""
    return bool(evaluation) and evaluation.get("outcome") in COMPARABLE_OUTCOMES


def accumulate_prediction_outcomes(
    outcomes_by_semantics: dict[str, dict[str, int]],
    evaluation: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, int]], dict[str, float] | None]:
    """Phase E.4 — fold this iteration's outcome into the VERSIONED pools.

    Returns ``(new_pools, scientific_accuracy)`` where the accuracy is
    computed from the v2 pool ALONE (Q-09a-2). ``None`` while that pool is
    empty — an absent hit-rate, not a zero one.

    The incoming mapping is deep-copied rather than mutated: the caller
    threads the ORIGINAL through the degraded path unchanged, and an in-place
    update would silently couple the two.

    The legacy ``prediction_outcomes_history`` dict is NOT touched here. It is
    a different pool under a different rule; mixing them would produce a
    fraction that means nothing.
    """
    new_pools = {version: dict(counts) for version, counts in outcomes_by_semantics.items()}
    # Seeded with all three buckets, like the legacy dict it sits beside, so
    # `scientific_accuracy` always reports a fraction PER OUTCOME rather than
    # only for the outcomes that happen to have occurred. The proposer renders
    # those fractions, and a silently missing bucket reads as "no data" when it
    # actually means "zero of these".
    v2 = new_pools.setdefault(
        PREDICTION_SEMANTICS_SIGNSAFE_V2, dict.fromkeys(COMPARABLE_OUTCOMES, 0)
    )
    for bucket in COMPARABLE_OUTCOMES:
        v2.setdefault(bucket, 0)

    if is_comparable(evaluation):
        assert evaluation is not None  # narrowed by is_comparable
        outcome = str(evaluation["outcome"])
        v2[outcome] = v2.get(outcome, 0) + 1

    total = sum(v2.values())
    accuracy = {k: round(v / total, 4) for k, v in v2.items()} if total > 0 else None
    return new_pools, accuracy


def accumulate_information_gain(
    gain_by_semantics: dict[str, float],
    evaluation: dict[str, Any] | None,
) -> dict[str, float]:
    """The v2 running gain sum after this iteration.

    Version-partitioned for the same reason the counts are: a gain measured
    under the corrected band is not commensurable with one measured under the
    old rule, so there is no single scalar meaning "legacy + v2" anywhere.
    ``unevaluated`` contributes nothing.
    """
    new_gains = dict(gain_by_semantics)
    if is_comparable(evaluation):
        assert evaluation is not None  # narrowed by is_comparable
        new_gains[PREDICTION_SEMANTICS_SIGNSAFE_V2] = new_gains.get(
            PREDICTION_SEMANTICS_SIGNSAFE_V2, 0.0
        ) + float(evaluation.get("information_gain", 0.0) or 0.0)
    return new_gains


def prediction_pool_sizes(
    legacy_history: dict[str, int],
    outcomes_by_semantics: dict[str, dict[str, int]],
) -> dict[str, int]:
    """How many outcomes each pool holds — the provenance parent §8 demands.

    Without it a reader sees ``scientific_accuracy`` beside a legacy pool and
    has no way to tell that the fraction was computed over only some of the
    predictions on record.
    """
    sizes = {PREDICTION_SEMANTICS_LEGACY_V1: sum(legacy_history.values())}
    for version, counts in outcomes_by_semantics.items():
        sizes[version] = sum(counts.values())
    sizes.setdefault(PREDICTION_SEMANTICS_SIGNSAFE_V2, 0)
    return sizes
