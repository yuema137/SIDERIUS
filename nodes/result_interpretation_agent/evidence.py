"""Persisted evidence -> typed interpreter projections (node-private).

Step 09a C1b (design:
``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §3.1; parent §13a).

This module owns ONE responsibility: reading what the tuner PERSISTED and
projecting it into the typed shapes the interpreter reasons over. It derives
no policy, calls no LLM, writes no file, and never orchestrates a phase.

Private BY OWNERSHIP. The plain filename is a guard convention, not
public-API status: ``tests/unit/nodes/test_node_public_boundary.py`` only
sees non-underscore modules, so an underscore name would remove these
functions from the very rule that protects them. Import them from inside the
node; outside callers use the node's main module, which re-exports
``tuning_output_to_model_run_summary`` for its five production importers.

The dependency edge runs one way: the main module imports this one, never the
reverse.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from agent.schemas.health_feedback import (
    RoundHealth,
    build_collapse_fingerprint,
    build_gate_outcomes,
    classify_round_provenance,
)
from agent.schemas.hyperparam_tuning import ExperimentRecord
from agent.schemas.interpretation import (
    MetricIdentity,
    ModelRunSummary,
    RecordFailureCounts,
    RoundOrdering,
    SecondaryMetricEvidence,
)
from agent.schemas.ordering import ResolvedOrdering
from agent.schemas.score_table import ScoreComparisonTable
from execute_tools.evaluation_metric import (
    MetricDirection,
    MetricIdentityConflictError,
    MetricSpec,
    StampedMetricSpec,
    reconcile_metric_specs,
)
from execute_tools.metric_order import MetricOrder

if TYPE_CHECKING:
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput


class InterpretationContractError(ValueError):
    """The interpreter refuses to proceed because its inputs contradict.

    Step 09a C2. Raised BEFORE any ordering, prediction or LLM call — the
    interpreter would otherwise have to pick a winner between two authorities
    that disagree, and every available way of picking is wrong.
    """


def reconcile_metric_spec(
    outputs: Sequence[HyperparamTuningOutput],
) -> MetricSpec | None:
    """The ONE run ``MetricSpec`` behind a set of tuning outputs.

    One interpretation covers one run, and one run has one metric. The tuner
    stamped its already-resolved spec on every output it wrote (Step 09a C2),
    so this COMPARES transported values — it derives nothing and has no
    fallback.

    Step 10 P2a C1 (Q-P2a-3 = PROMOTE): the DECISION now lives in
    :func:`execute_tools.evaluation_metric.reconcile_metric_specs`, beside
    ``MetricSpec`` itself, because three generic consumers outside this node
    need the same answer. What remains here is the node's PROJECTION — tuning
    outputs to labelled identity sources — and its own error type. There is
    exactly one reconciliation implementation, and it is not this function.

    Returns the common spec; ``None`` when no output carries one (a legacy set,
    or a cold start), which is a NAMED absence the input contract then judges.

    Raises:
        InterpretationContractError: if two outputs carry different specs, or
            if some carry one and others do not. Both cases mean the set spans
            more than one metric binding, and silently picking either would
            order results on a metric they were not scored under. Semantics
            are unchanged by the promotion, message text included.
    """
    stamped = [
        StampedMetricSpec(
            label=f"{o.run_name!r} ({o.model_type!r})",
            spec=getattr(o, "metric_spec", None),
        )
        for o in outputs
    ]
    try:
        return reconcile_metric_specs(stamped)
    except MetricIdentityConflictError as exc:
        # The node keeps its own public error type: `InterpretationContractError`
        # is what the interpreter's callers catch, and the promotion must not
        # change that contract. The message is the shared authority's, unchanged.
        raise InterpretationContractError(str(exc)) from exc


def _project_secondary_metrics(
    output: HyperparamTuningOutput, record: ExperimentRecord | None
) -> list[SecondaryMetricEvidence]:
    """The run's DECLARED secondaries, joined against ONE record's outcomes.

    Step 10 / P2b C3 (design §4.4, §4.5). The declared set comes from the
    output's ``secondary_metric_specs`` stamp and the outcomes from the record
    the summary's headline score came from, so a secondary number always
    describes the SAME experiment as the score beside it — the per-role
    reasoning Step 09a applied to the training diagnosis.

    The stamp is what makes an absence honest. Three states result, and the
    fourth possibility is deliberately absent:

    * a matching entry in ``secondary_metric_results`` -> ``scored``;
    * a matching entry in ``secondary_metric_refusals`` -> ``refused``;
    * declared but neither -> ``unavailable``, a NAMED absence. This also
      covers a secondary whose evaluation CRASHED: the crash keeps its
      separate diagnostic provenance on ``record.secondary_metric_errors``,
      but it is not a scientific state and never becomes a fourth one.

    NO stamp -> ``[]``. An output that never declared a secondary set — a
    legacy output, or a run of a task that has none — gets zero absence rows
    and therefore zero rendered bytes. Fabricating "unavailable" rows for a
    run that declared nothing would report a silence as a measurement.

    Each entry carries its OWN ``spec``, so a secondary is rendered with its
    own direction words. DAVIS declares ``psnr`` (higher) beside a ``mse``
    primary that is lower-is-better; an inherited direction would render it
    backwards.
    """
    declared = output.secondary_metric_specs
    if not declared:
        return []
    results = {r.metric_id: r for r in record.secondary_metric_results} if record else {}
    refusals = {r.metric_id: r for r in record.secondary_metric_refusals} if record else {}
    return [
        SecondaryMetricEvidence(
            spec=spec,
            result=results.get(spec.id),
            refusal=refusals.get(spec.id) if spec.id not in results else None,
        )
        for spec in declared
    ]


def _project_metric_identity(records: list[ExperimentRecord]) -> MetricIdentity | None:
    """The identity the SCORED records were actually evaluated under.

    Every record carrying a primary ``MetricResult`` in one tuning output must
    agree; a corrupt output that mixes two metrics fails closed HERE, before any
    consumer reads a number off it. ``None`` when no record carries a
    ``MetricResult`` — outputs written before Step 06 — which is an absence, not
    a default.
    """
    # The annotation is load-bearing: an unannotated comprehension widens
    # `direction` to `str`, and MetricIdentity then rejects it as a
    # MetricDirection Literal violation. Tuples rather than models because a
    # `frozen=True` Pydantic model's hashability is a runtime property a type
    # checker cannot see (both defects caught by CI, runs 32310070368 and
    # 32310562165).
    identities: set[tuple[str, MetricDirection]] = {
        (r.metric_result.metric_id, r.metric_result.direction)
        for r in records
        if r.metric_result is not None
    }
    if not identities:
        return None
    if len(identities) > 1:
        raise InterpretationContractError(
            "records in one tuning output disagree about the metric they were scored "
            f"under: {sorted(identities)}. A summary cannot describe two metrics."
        )
    metric_id, direction = identities.pop()
    return MetricIdentity(metric_id=metric_id, direction=direction)


def project_failure_counts(records: list[ExperimentRecord]) -> RecordFailureCounts:
    """Count what went wrong, using ONLY vocabularies that already exist.

    Step 09a C6 (parent §5). Every key comes from an authority that owns it:
    ``ExperimentRecord.status``, ``TrainingDiagnosis.state`` and
    ``validation_state``, ``NotScoreableResult``'s opaque contract id, and
    Health's ``gate_action`` / ``provenance``. Nothing here classifies a
    failure itself — the interpreter is a projection layer, and a private
    taxonomy would mean a fourth task's novel pathology needs a SIDERIUS
    source change before it can be reported.

    An unknown future value simply appears under its own key, which is why
    these are open dicts rather than enums.
    """

    def _bump(counter: dict[str, int], key: str) -> None:
        counter[key] = counter.get(key, 0) + 1

    status_counts: dict[str, int] = {}
    diagnosis_state_counts: dict[str, int] = {}
    validation_state_counts: dict[str, int] = {}
    refusal_contract_ids: dict[str, int] = {}
    gate_action_counts: dict[str, int] = {}
    health_provenance_counts: dict[str, int] = {}
    metric_refusal_count = 0

    for record in records:
        _bump(status_counts, str(record.status))

        diagnosis = record.training_diagnosis
        if diagnosis is None:
            # An absence, counted as one. Folding it into "absent" would
            # conflate "no diagnosis object" with "the diagnosis says the
            # history was absent" — different facts about different records.
            _bump(diagnosis_state_counts, "diagnosis_missing")
        else:
            _bump(diagnosis_state_counts, str(diagnosis.state))
            _bump(validation_state_counts, str(diagnosis.validation_state))

        if record.metric_refusal is not None:
            metric_refusal_count += 1
            _bump(refusal_contract_ids, str(record.metric_refusal.verdict.contract_id))

        # `gate_action` is None on rounds where no gate fired; counted under
        # its own key so "no gate fired" stays distinguishable from "the gate
        # said continue".
        _bump(gate_action_counts, str(record.gate_action) if record.gate_action else "none")
        _bump(health_provenance_counts, str(classify_round_provenance(record)))

    return RecordFailureCounts(
        records_total=len(records),
        status_counts=status_counts,
        diagnosis_state_counts=diagnosis_state_counts,
        validation_state_counts=validation_state_counts,
        metric_refusal_count=metric_refusal_count,
        refusal_contract_ids=refusal_contract_ids,
        gate_action_counts=gate_action_counts,
        health_provenance_counts=health_provenance_counts,
    )


def _required_denoising_score(record: ExperimentRecord) -> float:
    """Return a score after enforcing the valid-record invariant."""

    score = record.denoising_score
    if score is None:
        raise ValueError(
            f"Experiment {record.exp_id!r} entered valid-record ranking without a score."
        )
    return score


def _round_ordering(record) -> RoundOrdering:
    """Read one record's ordering provenance for the interpreter.

    A record written before the ordering option existed carries no ordering
    fields at all. That is read explicitly as the global shuffle with source
    ``legacy_default`` — never guessed at, and never confused with a run that
    actively chose the default.
    """
    ordering = ResolvedOrdering.from_record(record)
    return RoundOrdering(
        exp_id=record.exp_id,
        resolved_order_strategy=ordering.resolved_strategy,
        resolved_file_order=ordering.resolved_file_order,
        resolution_source=ordering.resolution_source,
        proposed_order_strategy=ordering.proposed_strategy,
        proposal_rejected=ordering.proposal_rejected,
        proposal_rejection_reason=ordering.proposal_rejection_reason,
    )


def _round_health(record, *, required_gate_ids: frozenset[str] | None = None) -> RoundHealth:
    """Condense one record's HealthGate evidence for the interpreter.

    Deterministic — never reads LLM output (V19 PR 3,
    ``docs/design/v19_priorities/pr3_healthgate_feedback.md`` §3.2/§3.5).
    Classification follows the evidence-precedence ladder in
    ``classify_round_provenance``: persisted gate evidence is never
    discarded by a status rule, and nothing is inferred from missing
    fields — a round without evidence is carried LABELED (its
    ``provenance``), never guessed at.

    ``failure_reason`` is carried verbatim for every provenance. On
    ``gate_not_evaluated`` records (attempt failures, pre-gate errors)
    it holds the execution failure, NOT gate evidence — the provenance
    label is what keeps downstream from misreading it (the §2.5
    field-overload finding).
    """
    # Same lazy-import precedent as the summary builder below.
    from execute_tools.health_checks.candidate_eligibility import (
        classify_candidate_health,
    )

    provenance = classify_round_provenance(record)
    gate_results = record.health_gate_results if provenance == "gated" else []
    return RoundHealth(
        exp_id=record.exp_id,
        status=record.status,
        health_validity=classify_candidate_health(record, required_gate_ids=required_gate_ids),
        gate_action=record.gate_action,
        failure_reason=record.failure_reason,
        gate_outcomes=build_gate_outcomes(gate_results),
        fingerprint=build_collapse_fingerprint(gate_results, record.gate_action),
        provenance=provenance,
    )


def _collect_health_evidence(
    summaries: list[ModelRunSummary],
) -> tuple[
    dict[str, dict[str, int]],
    dict[str, list],
    dict[str, list],
]:
    """Deterministic per-iteration health aggregates from ``round_health``.

    Returns ``(counts_by_model, distinct_fingerprints_by_model,
    merge_input_by_model)`` where merge_input maps model_type →
    ``[(fingerprint, exp_id)]`` in CHRONOLOGICAL round order (the
    representative-observation rule relies on this order — design §3.8).
    Reads ONLY the deterministic RoundHealth data CB2 placed on the
    summary — never LLM output (§3.1 principle 5).
    """
    counts: dict[str, dict[str, int]] = {}
    distinct: dict[str, list] = {}
    merge_input: dict[str, list] = {}
    for summary in summaries:
        mt = summary.model_type
        for health in summary.round_health:
            bucket = counts.setdefault(mt, {"valid": 0, "invalid": 0, "unknown": 0})
            bucket[str(health.health_validity)] += 1
            if health.fingerprint is not None:
                merge_input.setdefault(mt, []).append((health.fingerprint, health.exp_id))
                seen = distinct.setdefault(mt, [])
                if health.fingerprint.signature not in {f.signature for f in seen}:
                    seen.append(health.fingerprint)
    return counts, distinct, merge_input


def tuning_output_to_model_run_summary(
    output: HyperparamTuningOutput,
    *,
    order: MetricOrder | None,
    required_gate_ids: frozenset[str] | None = None,
) -> ModelRunSummary:
    # ``required_gate_ids`` is the RUN's scientific gate set, already resolved
    # from its own Health declaration at the composition edge (Step 10 /
    # P5+P6 W6). It is threaded as a RESOLVED VALUE, never as a config path:
    # a classifier that re-loaded the config would have to know which task it
    # is looking at, and — before W6 — resolved the LEGACY TIDMAD default,
    # binding that family process-globally for every composed run (F-P56-2).
    # ``None`` keeps the pre-W6 behaviour exactly, which is what every
    # un-composed caller gets.
    """
    Convert a HyperparamTuningOutput to a condensed ModelRunSummary.

    Extracts aggregates, per-round trajectory, file_vector, data volume,
    and efficiency metrics from the all_records field. The raw records
    are NOT carried forward — only the condensed summary.

    ``order`` is keyword-only with NO default (Step 09a C3). This function
    RANKS records — best, best-valid, best-valid-formal, worst — so it needs
    the run's direction, and it is called by the workflow, the CLI, the
    calibration scripts and the protocol BEFORE any ``InterpretationInput``
    exists. It therefore carries its own fail-closed clause rather than
    relying on the input contract: ``None`` is accepted only while nothing
    needs ranking.
    """
    records = output.all_records

    def _authority(what: str) -> MetricOrder:
        if order is None:
            raise InterpretationContractError(
                f"selecting {what} for {output.run_name!r} ({output.model_type!r}) requires "
                "the run's MetricOrder, but none was supplied and the output carries "
                "scored records. Pass order=MetricOrder(<the run's spec>); a direction "
                "is never assumed."
            )
        return order

    # Per-round extraction
    round_scores: list[float | None] = []
    round_conclusions: list[str] = []
    round_trial_portions: list[float | None] = []
    round_model_params: list[int | None] = []
    round_ordering: list[RoundOrdering] = []
    round_health: list[RoundHealth] = []

    for r in records:
        round_scores.append(r.denoising_score)
        round_trial_portions.append(r.trial_portion)
        round_model_params.append(r.model_params)
        if r.memory is None:
            round_conclusions.append("")
        else:
            round_conclusions.append(r.memory.conclusion or "")
        round_ordering.append(_round_ordering(r))
        round_health.append(_round_health(r, required_gate_ids=required_gate_ids))

    from execute_tools.health_checks.candidate_eligibility import (
        CandidateHealthValidity,
        classify_candidate_health,
        is_valid_candidate,
    )

    # Find the raw best record. `success` is already filtered on
    # `denoising_score is not None`, so the old `float("-inf")` fallback arm
    # was unreachable; it is deleted with the filter it duplicated, and
    # `_required_denoising_score` states the invariant instead.
    success = [r for r in records if r.status == "success" and r.denoising_score is not None]
    best_rec = (
        _authority("the best record").best(success, key=_required_denoising_score)
        if success
        else None
    )
    valid_records = [
        r for r in success if is_valid_candidate(r, required_gate_ids=required_gate_ids)
    ]
    valid_best_rec = (
        _authority("the best VALID record").best(valid_records, key=_required_denoising_score)
        if valid_records
        else None
    )
    valid_formal_records = [r for r in valid_records if not r.is_trial]
    valid_formal_rec = (
        _authority("the best VALID FORMAL record").best(
            valid_formal_records, key=_required_denoising_score
        )
        if valid_formal_records
        else None
    )

    # Find formal round (last record with is_trial=False)
    formal_rec = None
    for r in reversed(success):
        if not r.is_trial:
            formal_rec = r
            break

    # Compute worst score
    valid_scores = [s for s in round_scores if s is not None]
    worst_score = (
        _authority("the worst round score").worst(valid_scores, key=lambda value: value)
        if valid_scores
        else None
    )

    # --- Score tables (Phase 4 — enriched replacement for file_vector) ---
    # best_score_table prefers the pre-computed top-level field on the tuning
    # output (populated by the tuner per §7.1). The best_rec's own score_table
    # is a fallback in case the top-level field is None but the record carries
    # one. formal_score_table comes from the tuning output's top-level field
    # directly — it points at the last successful formal round's table.
    def _as_table(value) -> ScoreComparisonTable | None:
        if value is None:
            return None
        if isinstance(value, ScoreComparisonTable):
            return value
        return ScoreComparisonTable.model_validate(value)

    best_score_table = _as_table(output.best_score_table)
    if best_score_table is None and best_rec is not None:
        best_score_table = _as_table(best_rec.score_table)

    formal_score_table = _as_table(output.formal_score_table)
    if formal_score_table is None and formal_rec is not None:
        formal_score_table = _as_table(formal_rec.score_table)

    return ModelRunSummary(
        model_type=output.model_type,
        run_name=output.run_name,
        status=output.status,
        completed_rounds=output.completed_rounds,
        best_denoising_score=output.best_denoising_score,
        best_valid_denoising_score=(valid_best_rec.denoising_score if valid_best_rec else None),
        best_raw_health_validity=(
            classify_candidate_health(best_rec, required_gate_ids=required_gate_ids).value
            if best_rec
            else CandidateHealthValidity.UNKNOWN.value
        ),
        worst_denoising_score=worst_score,
        best_config=output.best_config,
        best_valid_config=(valid_best_rec.params if valid_best_rec else None),
        round_scores=round_scores,
        round_conclusions=round_conclusions,
        round_ordering=round_ordering,
        round_health=round_health,
        # Per-file performance (raw primitive retained per §7.2 scope note)
        best_file_vector=best_rec.file_vector if best_rec else None,
        formal_score=formal_rec.denoising_score if formal_rec else None,
        best_valid_formal_score=(valid_formal_rec.denoising_score if valid_formal_rec else None),
        # D-C5: the verdict of the SAME formal record `formal_score` came
        # from, so the score and its authority cannot describe different
        # experiments. None when no formal record exists — which excludes
        # this model from the scientific aggregate rather than admitting it
        # on an unestablished authority.
        scientific_authority=(formal_rec.scientific_authority if formal_rec else None),
        formal_file_vector=formal_rec.file_vector if formal_rec else None,
        # Per-file performance (enriched — Phase 4)
        best_score_table=best_score_table,
        best_valid_score_table=(
            _as_table(output.best_valid_score_table)
            or (_as_table(valid_best_rec.score_table) if valid_best_rec else None)
        ),
        formal_score_table=formal_score_table,
        # Efficiency
        best_model_params=best_rec.model_params if best_rec else None,
        # Compute cost
        best_timing=best_rec.timing.model_dump() if best_rec and best_rec.timing else None,
        # Data volume
        training_psd_segments=best_rec.training_psd_segments if best_rec else None,
        eval_psd_segments=best_rec.eval_psd_segments if best_rec else None,
        trial_portion=best_rec.trial_portion if best_rec else None,
        # Per-round trends
        round_trial_portions=round_trial_portions,
        round_model_params=round_model_params,
        # Step 09a C2 — the identity the scored records actually carry. The
        # input contract checks it against the run's bound MetricSpec; the two
        # have different owners and are never substituted for each other.
        metric_identity=_project_metric_identity(records),
        # Step 09a C6 — the 07a diagnosis of the SAME records the best and
        # formal scores came from, carried verbatim. One per role: a best
        # trial round and the formal round are different experiments.
        best_training_diagnosis=(best_rec.training_diagnosis if best_rec else None),
        formal_training_diagnosis=(formal_rec.training_diagnosis if formal_rec else None),
        # Step 10 / P2b C3 — the declared secondaries, joined against the SAME
        # record `best_denoising_score` came from. Empty for a run that
        # declared none and for every output predating the stamp; a declared
        # secondary with no outcome is a NAMED absence, never an omission.
        secondary_metrics=_project_secondary_metrics(output, best_rec),
        failure_counts=project_failure_counts(records),
    )
