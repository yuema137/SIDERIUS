"""Tuner FEEDBACK — evidence assembled for the NEXT agent, not for this round.

Step 07 PR 07b, C7 (operator scope amendment): moved VERBATIM out of
``ml_hyperparameter_tune_agent.py``. Zero behaviour change.

What belongs here: the structured signals a finished iteration hands forward —
gate exhaustion (attempts were refused by resource checks), trial-validity
feedback (trials ran, succeeded, then failed their scientific gates), the
disallowed-pattern collection, and the compact summaries that render them.

What does NOT belong here: LLM prompt rendering. The planner's and reflector's
prompt text is owned by ``agent/prompt_templates/tuner/rendering.py``; this
module produces the typed evidence that travels TO those surfaces.
"""

from typing import Literal

from agent.schemas.health_feedback import (
    FormalValidityFeedback,
    InvalidCandidateOutcome,
    InvalidTrialOutcome,
    TrialValidityFeedback,
)
from agent.schemas.hyperparam_tuning import (
    GateExhaustionInfo,
)
from agent.schemas.preflight import StaticPreflightEvidence
from agent.skills.evaluate_vram_skill.evidence import preflight_memory_fields, render_static_refusal
from agent.utils.architectural_pattern_tagger import (
    TIME_FACTOR_THRESHOLD,
    VRAM_FACTOR_THRESHOLD,
    tag_architecture,
)
from execute_tools.health_checks.candidate_eligibility import (
    classify_candidate_health,
    is_valid_candidate,
)
from execute_tools.health_checks.schemas import (
    CandidateHealthValidity,
)


def _attempts_that_trained(records: list) -> int:
    """How many of ``records`` describe an attempt that ACTUALLY trained.

    F-C12P-OBS-1. The gate-exhaustion triggers test *"no record reached
    ``status == 'success'``"*, which is a statement about OUTCOMES. It is
    NOT the same fact as *"training never ran"*: an attempt that trains and
    then fails a HealthGate satisfies the trigger while having trained.

    Read from the two record fields that already own the fact — no new
    field, schema or transport:

    * ``training_history.epochs_completed`` — Step 07a's typed payload,
      schema-pinned to ``len(train_objective)`` (``TrainingHistory._consistent``),
      so ``> 0`` means at least one epoch's objective was observed. Zero
      means the attempt entered training and crashed before finishing an
      epoch, which is NOT "trained".
    * ``final_loss`` — the same fact from a producer that predates 07a (the
      baseline runner). Only the completed-attempt record builder writes it
      (``records.py``: ``"final_loss": train_results.get("final_loss")``);
      skip, admission-refusal and execution-failure records never carry it.
    """
    trained = 0
    for record in records:
        history = record.get("training_history") or {}
        epochs = history.get("epochs_completed") if isinstance(history, dict) else None
        if isinstance(epochs, int) and epochs > 0:
            trained += 1
            continue
        if record.get("final_loss") is not None:
            trained += 1
    return trained


def _render_gate_exhaustion_log_line(info: GateExhaustionInfo, records: list) -> str:
    """The operator-facing one-liner for a surfaced gate-exhaustion report.

    F-C12P-OBS-1. Extracted from the emission site in ``records.py`` so the
    claim it makes is testable without running the finalisation orchestrator.
    It states counts only: the previous wording ("iteration ended without
    ever training") was false for every trained-then-failed attempt, and
    false unconditionally under Trigger B, which requires a successful round.

    ``records`` is the iteration's full record list; ``info`` may describe a
    narrower set (Trigger B reports the failure burst), so the two scopes are
    labelled separately rather than blended into one number.
    """
    return (
        f"[gate-exhaustion] surfacing gate-exhaustion report to next proposer: "
        f"{_attempts_that_trained(records)} of {len(records)} attempt(s) in this "
        f"iteration reached training; report covers {info.total_attempts} "
        f"attempt(s) — {info.vram_gated_attempts} VRAM-gated, "
        f"{info.time_gated_attempts} time-gated, "
        f"{info.other_failure_attempts} other failures."
    )


def _collect_disallowed_patterns(
    records: list,
    *,
    vram_budget_gb: float | None,
    time_budget_minutes: float | None,
) -> list:
    """Return the sorted union of architectural-pattern tags for records that
    exceeded the §7 Decision 2 thresholds.

    For each gate-rejected attempt (``status in {"skipped_oom_risk",
    "skipped_time_risk"}``) we compute its individual ``time_factor`` and
    ``vram_factor`` from the per-attempt ``memory`` block. Only attempts that
    overshot by at least ``TIME_FACTOR_THRESHOLD`` (time) or
    ``VRAM_FACTOR_THRESHOLD`` (VRAM) contribute tags — a marginal 1.3× is a
    hyperparameter choice, not an architectural infeasibility, and banning the
    whole class on it would over-constrain the next proposer. See
    ``docs/reliable_resource_proposer.md`` §7 Decision 2 + §9 Commit 3.

    Non-gate failures (code bugs, schema violations) are skipped regardless of
    factor — their failure mode is not resource-structural.

    **F-RC-6**: an ACTUAL watchdog kill (``failure_type ==
    "wall_clock_timeout"``) also qualifies, and does so CATEGORICALLY rather
    than through the factor test — see the inline note. Predicted skips and
    real timeouts are the two ways a candidate can be shown time-infeasible;
    only the first was consulted before.

    Returns a deterministic sorted list (empty if no attempt qualifies).
    """
    tags: set = set()
    for r in records:
        # F-RC-6 — an ACTUAL watchdog kill is time-infeasibility evidence too.
        #
        # Before this, only PREDICTED gate skips were considered, so a run that
        # was admitted, executed and then killed by the watchdog produced no
        # architectural feedback at all: it is recorded with `status="error"`
        # (`ml_hyperparameter_tune_agent.py:1404`), which this filter excluded.
        # The one structured signal designed to tell the next proposer "this
        # shape is too slow" was therefore unavailable for the very failure
        # that proves it.
        #
        # Discriminated by the EXISTING typed `failure_type`, never by
        # `status == "error"`: a code bug, a schema violation and an OOM are
        # all `"error"` too, and none of them is evidence about architecture.
        # `_classify_attempt_failure` (`runtime.py:518`) already emits
        # `"wall_clock_timeout"` for exactly this, and its docstring states
        # that downstream feedback keys off the name.
        is_predicted_gate_skip = r.get("status") in {
            "skipped_oom_risk",
            "skipped_time_risk",
        }
        is_actual_timeout = r.get("failure_type") == "wall_clock_timeout"
        if not (is_predicted_gate_skip or is_actual_timeout):
            continue

        if is_actual_timeout:
            # CATEGORICAL, not a magnitude — and it must be, because the
            # factor test below cannot express it. The watchdog kills AT the
            # deadline, so `elapsed / deadline` is ~1.003 by construction
            # (60.166 s against 60.0 s in the run that found this) and could
            # never clear TIME_FACTOR_THRESHOLD = 5.0. That threshold exists
            # to separate a marginal PREDICTION overshoot from a structural
            # one; for a real kill there is nothing to separate — the attempt
            # demonstrably did not finish, which is the qualifying evidence.
            tags.update(tag_architecture(r.get("model_type") or "", r.get("model_config") or {}))
            continue

        mem = r.get("memory") or {}
        if preflight_memory_fields(mem).get("preflight_outcome") == "STATIC_PREFLIGHT_REFUSAL":
            # A structural estimate cannot establish architectural infeasibility.
            # The independent time-refusal/actual-timeout paths retain their policy.
            continue

        vram_factor = None
        if vram_budget_gb and vram_budget_gb > 0:
            vram_est = mem.get("vram_estimate_gb")
            if vram_est is not None:
                vram_factor = float(vram_est) / float(vram_budget_gb)

        time_factor = None
        if time_budget_minutes and time_budget_minutes > 0:
            time_est = mem.get("time_estimate_minutes")
            if time_est is not None:
                time_factor = float(time_est) / float(time_budget_minutes)

        exceeds_time = time_factor is not None and time_factor > TIME_FACTOR_THRESHOLD
        exceeds_vram = vram_factor is not None and vram_factor > VRAM_FACTOR_THRESHOLD
        if not (exceeds_time or exceeds_vram):
            continue

        model_type = r.get("model_type") or ""
        model_config = r.get("model_config") or {}
        tags.update(tag_architecture(model_type, model_config))

    return sorted(tags)


def _build_trial_validity_feedback(
    records: list,
    *,
    formal_skipped_for_no_valid_winner: bool,
    healthgate_mode: str | None,
    required_gate_ids: frozenset[str] | None = None,
) -> TrialValidityFeedback | None:
    """Report an iteration whose trials produced no valid candidate.

    V20 PR D (D-C6). Fires when trial-mode records exist but
    :func:`_best_trial_winner` would return ``None`` — the planner
    otherwise sees an iteration that simply produced no good score, with no
    way to tell "nothing ran" from "everything collapsed".

    **A separate carrier from `_build_gate_exhaustion`, and the audit is
    why.** That helper's two triggers both require budget-gated records
    (``skipped_oom_risk`` / ``skipped_time_risk``); an all-invalid
    iteration has records that RAN and SUCCEEDED and then failed their
    scientific gates, so neither trigger fires and the block would be
    ``None``. Merging them would need a third trigger with unrelated
    semantics inside a structure whose every field means "budget
    exhaustion", and would tell the planner to propose something
    *lighter* when the actual evidence says propose something that does
    not *collapse*.

    **Facts only, task-generic.** Gate names, reasons and metrics are
    passed through exactly as the gate system recorded them. Nothing here
    interprets a metric or suggests a remedy — that is the planner's job,
    and task-specific advice in workflow code is what §3.3 forbids.

    Returns ``None`` when at least one trial is valid, so a healthy run's
    downstream prompt is byte-identical to before.

    **The trial predicate mirrors :func:`_best_trial_winner` exactly** — the
    typed ``is_trial`` field, nothing else. Step 07 correction (2026-08-16):
    both used to additionally require ``memory.time_mode == "trial"``, which
    is written only when the wall-time gate ran. Under time budgets disabled
    this helper therefore found NO trials and returned ``None`` at precisely
    the moment the skip gate reported ``no_valid_trial_winner`` — the
    planner lost the report explaining why the formal round did not run.
    """
    trials = [r for r in records if r.get("is_trial") is True]
    if not trials:
        return None  # no trial stage at all is a different fact, not this one
    if any(is_valid_candidate(r, required_gate_ids=required_gate_ids) for r in trials):
        return None  # a valid winner exists; nothing to report

    outcomes, invalid, unknown, execution_failures, evidence_absent = _collect_invalid_outcomes(
        trials, required_gate_ids=required_gate_ids
    )

    return TrialValidityFeedback(
        trial_records_considered=len(trials),
        invalid_count=invalid,
        unknown_validity_count=unknown,
        execution_failure_count=execution_failures,
        outcomes=[InvalidTrialOutcome.model_validate(item.model_dump()) for item in outcomes],
        formal_skipped_for_no_valid_winner=formal_skipped_for_no_valid_winner,
        healthgate_mode=healthgate_mode,
        evidence_absent=evidence_absent,
    )


def _collect_invalid_outcomes(
    records: list, *, required_gate_ids: frozenset[str] | None
) -> tuple[list[InvalidCandidateOutcome], int, int, int, list[str]]:
    """One owner for factual failure classification in both execution stages."""
    outcomes: list[InvalidCandidateOutcome] = []
    invalid = unknown = execution_failures = 0
    evidence_absent: list[str] = []

    for record in records:
        exp_id = record.get("exp_id")
        status = str(record.get("status", "unknown"))
        validity = classify_candidate_health(record, required_gate_ids=required_gate_ids)

        if status == "failed_mode_collapse" and validity is CandidateHealthValidity.INVALID:
            # Health-invalid records use ``failed_mode_collapse`` as their
            # durable status.  They executed and were scientifically judged;
            # classifying them as execution failures would erase that fact
            # from the next proposer's feedback.
            invalid += 1
        elif status != "success":
            # The evidence is ABSENT, not negative: nothing was scored, so
            # no gate could have judged it.
            execution_failures += 1
        elif validity is CandidateHealthValidity.INVALID:
            invalid += 1
        else:
            unknown += 1

        results = [r for r in (record.get("health_gate_results") or []) if isinstance(r, dict)]
        if status == "success" and validity is CandidateHealthValidity.UNKNOWN:
            # UNKNOWN is not a soft "invalid" — it means the gate evidence
            # was incomplete, and saying WHICH way is the difference
            # between "the model collapsed" and "we cannot tell". A
            # partial gate set reads exactly like a pass unless named.
            evidence_absent.append(
                f"{exp_id or '<unidentified>'}: validity unknown — "
                + (
                    "no gate results persisted"
                    if not results
                    else f"only {len(results)} gate result(s) persisted, required set incomplete"
                )
            )

        failed_names = sorted(
            str(r.get("gate_name"))
            for r in results
            if r.get("gate_name")
            and (
                r.get("check_passed") is False or r.get("would_invalidate_under_production_policy")
            )
        )
        reasons = sorted({str(r["failure_reason"]) for r in results if r.get("failure_reason")})
        metrics: dict[str, float | int | str] = {}
        for r in results:
            for key, value in (r.get("key_metrics") or {}).items():
                if isinstance(value, (int, float, str)) and not isinstance(value, bool):
                    metrics[f"{r.get('gate_name')}.{key}"] = value

        outcomes.append(
            InvalidCandidateOutcome(
                exp_id=exp_id,
                status=status,
                health_validity=validity,
                failed_gate_names=failed_names,
                failure_reasons=reasons,
                key_metrics=metrics,
            )
        )

    return outcomes, invalid, unknown, execution_failures, evidence_absent


def _build_formal_validity_feedback(
    records: list,
    *,
    model_type: str,
    healthgate_mode: str | None,
    required_gate_ids: frozenset[str] | None = None,
) -> FormalValidityFeedback | None:
    """Never label Formal evidence as Trial evidence or make it an incumbent."""
    # Match the persisted role contract used by BestTracks: Formal writers
    # omit is_trial; schema-normalized outputs carry explicit False.
    formal = [record for record in records if not record.get("is_trial", False)]
    if not formal or any(
        is_valid_candidate(r, required_gate_ids=required_gate_ids) for r in formal
    ):
        return None
    outcomes, invalid, unknown, failures, absent = _collect_invalid_outcomes(
        formal, required_gate_ids=required_gate_ids
    )
    return FormalValidityFeedback(
        model_type=model_type,
        formal_records_considered=len(formal),
        invalid_count=invalid,
        unknown_validity_count=unknown,
        execution_failure_count=failures,
        outcomes=outcomes[-8:],
        healthgate_mode=healthgate_mode,
        evidence_absent=absent[-8:],
    )


def _build_gate_exhaustion(
    records: list,
    active_mode: Literal["trial", "formal"],
    vram_budget_gb: float | None,
    time_budget_minutes: float | None,
    *,
    consecutive_fail_rounds_at_exit: int = 0,
    max_fail_rounds: int = 0,
    completed_rounds: int = 0,
) -> GateExhaustionInfo | None:
    """
    Build the structured gate-exhaustion report for the next iteration's
    proposer (§10.13). Two triggers can fire:

    **Trigger A (Phase K, §10.13.1)** — *no rounds ever succeeded*. Fires when:

      * ``records`` is non-empty (the tuner actually ran).
      * No record has ``status == "success"``.
      * At least one record has ``status in {"skipped_oom_risk",
        "skipped_time_risk"}`` (failure was budget-related, not a code
        bug or schema violation).

    **Trigger B (Phase L, §11.4)** — *some rounds succeeded then the
    search collapsed*. Fires when:

      * ``consecutive_fail_rounds_at_exit >= max_fail_rounds > 0``
        (the outer loop aborted on the consecutive-failure brake, not
        on ``max_rounds``).
      * ``completed_rounds > 0`` (at least one round succeeded — this
        is the "after K successful rounds" framing that distinguishes
        Trigger B from Trigger A).
      * Burst gate-skip ratio ``>= 0.5`` — the trailing failure burst
        (records whose ``round_index == completed_rounds + 1``) was
        dominated by VRAM/time gate skips, not by code bugs.

    Returns ``None`` if neither trigger fires. When Trigger B fires, the
    report is keyed off the burst records (focused on the round that
    repeatedly failed). When Trigger A fires, the report is keyed off
    the full record list (no successful round to anchor on).
    """
    if not records:
        return None

    def _factor(estimate, budget):
        if estimate is None or budget is None or budget <= 0:
            return None
        return round(float(estimate) / float(budget), 3)

    def _worst_factor(rs, key, budget):
        if budget is None or budget <= 0:
            return None
        ests = [(r.get("memory") or {}).get(key) for r in rs]
        ests = [e for e in ests if e is not None]
        if not ests:
            return None
        return round(max(float(e) for e in ests) / float(budget), 3)

    # --- Trigger B (Phase L) — some successes, then a fail-round burst.
    trigger_b_fired = False
    burst_records: list = []
    if (
        max_fail_rounds > 0
        and consecutive_fail_rounds_at_exit >= max_fail_rounds
        and completed_rounds > 0
    ):
        burst_round_idx = completed_rounds + 1
        burst_records = [
            r for r in records if (r.get("memory") or {}).get("round_index") == burst_round_idx
        ]
        if burst_records:
            burst_gate = [
                r
                for r in burst_records
                if r.get("status") in {"skipped_oom_risk", "skipped_time_risk"}
            ]
            if len(burst_gate) / len(burst_records) >= 0.5:
                trigger_b_fired = True

    # --- Trigger A (Phase K) — no successes at all + budget-gated.
    trigger_a_fired = False
    if not any(r.get("status") == "success" for r in records) and any(
        r.get("status") in {"skipped_oom_risk", "skipped_time_risk"} for r in records
    ):
        trigger_a_fired = True

    if not (trigger_a_fired or trigger_b_fired):
        return None

    # When Trigger B fires, focus the report on the burst (more
    # actionable for the proposer); otherwise fall back to all records.
    report_records = burst_records if trigger_b_fired else records

    vram_gated = [r for r in report_records if r.get("status") == "skipped_oom_risk"]
    time_gated = [r for r in report_records if r.get("status") == "skipped_time_risk"]
    other = [
        r
        for r in report_records
        if r.get("status") not in {"skipped_oom_risk", "skipped_time_risk"}
    ]

    baseline_mem = report_records[0].get("memory") or {}
    baseline_vram = baseline_mem.get("vram_estimate_gb")
    baseline_time = baseline_mem.get("time_estimate_minutes")

    baseline_vram_factor = _factor(baseline_vram, vram_budget_gb)
    baseline_time_factor = _factor(baseline_time, time_budget_minutes)
    worst_vram_factor = _worst_factor(report_records, "vram_estimate_gb", vram_budget_gb)
    worst_time_factor = _worst_factor(report_records, "time_estimate_minutes", time_budget_minutes)

    disallowed_patterns = _collect_disallowed_patterns(
        report_records,
        vram_budget_gb=vram_budget_gb,
        time_budget_minutes=time_budget_minutes,
    )

    if trigger_b_fired:
        summary = _render_gate_exhaustion_trigger_b_summary(
            total=len(report_records),
            vram_gated=len(vram_gated),
            time_gated=len(time_gated),
            other=len(other),
            active_mode=active_mode,
            vram_budget_gb=vram_budget_gb,
            time_budget_minutes=time_budget_minutes,
            baseline_vram=baseline_vram,
            baseline_vram_factor=baseline_vram_factor,
            baseline_time=baseline_time,
            baseline_time_factor=baseline_time_factor,
            worst_vram_factor=worst_vram_factor,
            worst_time_factor=worst_time_factor,
            consecutive_fail_rounds_at_exit=consecutive_fail_rounds_at_exit,
            completed_rounds=completed_rounds,
        )
    else:
        summary = _render_gate_exhaustion_summary(
            total=len(report_records),
            vram_gated=len(vram_gated),
            time_gated=len(time_gated),
            other=len(other),
            active_mode=active_mode,
            vram_budget_gb=vram_budget_gb,
            time_budget_minutes=time_budget_minutes,
            baseline_vram=baseline_vram,
            baseline_vram_factor=baseline_vram_factor,
            baseline_time=baseline_time,
            baseline_time_factor=baseline_time_factor,
            worst_vram_factor=worst_vram_factor,
            worst_time_factor=worst_time_factor,
            trained=_attempts_that_trained(report_records),
        )

    static_refusals: set[str] = set()
    for record in report_records:
        fields = preflight_memory_fields(record.get("memory") or {})
        if fields.get("preflight_outcome") == "STATIC_PREFLIGHT_REFUSAL":
            evidence = StaticPreflightEvidence.model_validate(fields["static_preflight_evidence"])
            static_refusals.add(render_static_refusal(evidence))
    if static_refusals:
        summary += " " + " ".join(sorted(static_refusals))

    return GateExhaustionInfo(
        total_attempts=len(report_records),
        vram_gated_attempts=len(vram_gated),
        time_gated_attempts=len(time_gated),
        other_failure_attempts=len(other),
        active_mode=active_mode,
        vram_budget_gb=vram_budget_gb,
        time_budget_minutes=time_budget_minutes,
        baseline_vram_estimate_gb=baseline_vram,
        baseline_vram_factor=baseline_vram_factor,
        baseline_time_estimate_minutes=baseline_time,
        baseline_time_factor=baseline_time_factor,
        worst_vram_factor=worst_vram_factor,
        worst_time_factor=worst_time_factor,
        summary_message=summary,
        disallowed_architectural_patterns=disallowed_patterns,
    )


def _render_gate_exhaustion_summary(
    *,
    total: int,
    vram_gated: int,
    time_gated: int,
    other: int,
    active_mode: str,
    vram_budget_gb: float | None,
    time_budget_minutes: float | None,
    baseline_vram: float | None,
    baseline_vram_factor: float | None,
    baseline_time: float | None,
    baseline_time_factor: float | None,
    worst_vram_factor: float | None,
    worst_time_factor: float | None,
    trained: int,
) -> str:
    """One-paragraph LLM-readable synthesis of the gate-exhaustion state.

    The wording adapts to which axis was the binding ceiling — VRAM-only,
    time-only, or mixed — so the next proposer reads a clear instruction
    rather than a generic "everything failed" line. See §10.13.3.

    ``trained`` is :func:`_attempts_that_trained` over the same records this
    summary describes. It is REQUIRED, not defaulted: this text is spliced
    into the next proposal agent's prompt by
    ``_format_recent_gate_exhaustions_block``, and a caller that omitted it
    would silently re-publish F-C12P-OBS-1's false "nothing ever trained"
    framing to the LLM.
    """
    parts = []

    # Lead sentence — what failed and how widely. NOT "All N attempt(s) were
    # rejected by the gate": the trigger only requires >= 1 gate rejection,
    # so the `other` failures may well have trained (F-C12P-OBS-1).
    if vram_gated and not time_gated:
        parts.append(
            f"Of {total} attempt(s), {vram_gated} were rejected by the "
            f"resource preflight ({other} other failure(s))."
        )
    elif time_gated and not vram_gated:
        parts.append(
            f"Of {total} attempt(s), {time_gated} were rejected by the "
            f"pre-flight time gate ({other} other failure(s))."
        )
    else:
        parts.append(
            f"Of {total} attempt(s), {vram_gated} were rejected by resource "
            f"preflight and {time_gated} by the time gate "
            f"({other} other failure(s))."
        )

    # F-C12P-OBS-1 — separate the fact the trigger tests (no SUCCESSFUL
    # outcome) from the fact the old wording asserted (training never ran).
    parts.append("No attempt produced a successful training outcome.")
    if trained:
        parts.append(
            f"{trained} attempt(s) did reach training and recorded training "
            f"results before failing, so this is not a pure pre-flight "
            f"rejection — the training itself is evidence to reason from."
        )
    else:
        parts.append("No attempt reached the training stage.")

    # VRAM diagnostic.
    if vram_budget_gb is not None and baseline_vram is not None:
        parts.append(
            f"The baseline already estimated {baseline_vram:.2f} GB VRAM vs "
            f"the {vram_budget_gb:.2f} GB {active_mode} budget "
            f"(factor {baseline_vram_factor:.2f}×); the tuner's mutations "
            f"reached factor {worst_vram_factor:.2f}× at worst."
        )
    elif vram_budget_gb is not None and worst_vram_factor is not None:
        parts.append(
            f"VRAM estimates reached factor {worst_vram_factor:.2f}× of the "
            f"{vram_budget_gb:.2f} GB {active_mode} budget at worst "
            f"(baseline estimate not recorded)."
        )

    # Time diagnostic.
    if time_budget_minutes is not None and baseline_time is not None:
        parts.append(
            f"The baseline estimated {baseline_time:.2f} min wall-time vs the "
            f"{time_budget_minutes:.2f} min {active_mode} budget "
            f"(factor {baseline_time_factor:.2f}×); worst was factor "
            f"{worst_time_factor:.2f}×."
        )
    elif time_budget_minutes is not None and worst_time_factor is not None:
        parts.append(
            f"Time estimates reached factor {worst_time_factor:.2f}× of the "
            f"{time_budget_minutes:.2f} min {active_mode} budget at worst "
            f"(baseline estimate not recorded)."
        )

    # Verdict line — point the next proposer at the right lever.
    if vram_gated and not time_gated:
        parts.append(
            "Inspect each resource refusal's recorded cause and evidence basis. "
            "A structural estimate or compute-intensity rule does not establish "
            "measured GPU excess or a need to shrink the architecture."
        )
    elif time_gated and not vram_gated:
        parts.append(
            "Verdict: the proposed architecture is too slow for the active "
            "time budget. Reduce model depth/width or computation per step "
            "so the next baseline lands below the budget."
        )
    else:
        parts.append(
            "Inspect resource and time refusals separately. Their recorded "
            "causes and evidence determine which changes are justified; static "
            "resource checks do not establish measured GPU excess."
        )

    return " ".join(parts)


def _render_gate_exhaustion_trigger_b_summary(
    *,
    total: int,
    vram_gated: int,
    time_gated: int,
    other: int,
    active_mode: str,
    vram_budget_gb: float | None,
    time_budget_minutes: float | None,
    baseline_vram: float | None,
    baseline_vram_factor: float | None,
    baseline_time: float | None,
    baseline_time_factor: float | None,
    worst_vram_factor: float | None,
    worst_time_factor: float | None,
    consecutive_fail_rounds_at_exit: int,
    completed_rounds: int,
) -> str:
    """One-paragraph LLM-readable synthesis for the Phase L Trigger B
    case — the search collapsed into a fail-round burst after some
    successful rounds (§11.4). Lead sentence makes the
    failed-round burst explicit without inferring GPU capacity from a
    historical status name. Time-only wording remains unchanged.
    """
    # Lead sentence — Trigger B framing per §11.4 spec.
    if vram_gated and not time_gated:
        gated_axis = "VRAM"
    elif time_gated and not vram_gated:
        gated_axis = "time"
    else:
        gated_axis = "VRAM/time"
    if vram_gated:
        parts = [
            f"{consecutive_fail_rounds_at_exit} consecutive rounds exhausted attempts "
            f"at resource preflight{' and the time gate' if time_gated else ''} "
            f"after {completed_rounds} successful round(s). Inspect the recorded "
            "causes and evidence before choosing changes; a static refusal "
            "does not establish measured GPU excess."
        ]
    else:
        parts = [
            f"Model too large — {consecutive_fail_rounds_at_exit} consecutive "
            f"rounds exhausted attempts at the {gated_axis} gate after "
            f"{completed_rounds} successful round(s); proposer should reduce "
            f"model size before the next iteration."
        ]
    resource_count = f"{vram_gated} resource-preflight refusals" if vram_gated else "0 VRAM-gated"
    parts.append(
        f"Burst breakdown: {total} attempt(s) "
        f"({resource_count}, {time_gated} time-gated, "
        f"{other} other failures)."
    )

    # VRAM diagnostic.
    if vram_budget_gb is not None and baseline_vram is not None:
        parts.append(
            f"Burst baseline estimated {baseline_vram:.2f} GB VRAM vs the "
            f"{vram_budget_gb:.2f} GB {active_mode} budget "
            f"(factor {baseline_vram_factor:.2f}×); worst factor in burst "
            f"reached {worst_vram_factor:.2f}×."
        )
    elif vram_budget_gb is not None and worst_vram_factor is not None:
        parts.append(
            f"Burst VRAM estimates reached factor {worst_vram_factor:.2f}× "
            f"of the {vram_budget_gb:.2f} GB {active_mode} budget at worst "
            f"(burst baseline estimate not recorded)."
        )

    # Time diagnostic.
    if time_budget_minutes is not None and baseline_time is not None:
        parts.append(
            f"Burst baseline estimated {baseline_time:.2f} min wall-time vs "
            f"the {time_budget_minutes:.2f} min {active_mode} budget "
            f"(factor {baseline_time_factor:.2f}×); worst factor in burst "
            f"reached {worst_time_factor:.2f}×."
        )
    elif time_budget_minutes is not None and worst_time_factor is not None:
        parts.append(
            f"Burst time estimates reached factor {worst_time_factor:.2f}× "
            f"of the {time_budget_minutes:.2f} min {active_mode} budget at "
            f"worst (burst baseline estimate not recorded)."
        )

    return " ".join(parts)


def invoke_reflection(
    brain,
    *,
    exp_id: str,
    prepared,
    reflect_results: dict,
    reflection_context: dict | None,
    metric_spec,
    training_diagnosis,
    task_render,
) -> dict:
    """Ask the reflector to turn one attempt's results into memory.

    Extracted from ``run()`` by Lane D under the structural budget that guards
    it ("extract the responsibility first"). Behaviour is verbatim — same
    arguments, same order, same single call.

    It belongs in this module because this module is *what the next agent is
    told*, and it is now the ONE place that decides what the reflector knows
    about an attempt.

    **Both narrative inputs come from ``prepared``, and they are not the same
    kind of thing.** ``prepared.hypothesis`` is prose the planner authored
    BEFORE the framework resolved the plan; ``prepared.execution_provenance``
    is the typed record of what resolution then overruled. Passing the first
    without the second is the F15 defect — a reflection that narrated a
    proposed loss as though it had run. They travel together from here on.
    """
    return brain.reflect(
        exp_id,
        prepared.hypothesis,
        reflect_results,
        reflection_context,
        # Step 07 PR 07b (P3) — sequencing only. The spec tells the reflector
        # which direction counts as GOOD; the diagnosis is the one 07a already
        # derived, never recomputed, and it is the ONLY diagnosis transport to
        # this surface (the raw TrainingHistory stays out).
        metric_spec=metric_spec,
        training_diagnosis=training_diagnosis,
        # Step 12 / PR-12a C7 — the reflector's task-science gating. Same
        # run-scoped render the planner receives.
        task_render=task_render,
        # Lane D / F15 — what RESOLUTION overruled, so the reflector describes
        # the run that executed rather than the one that was proposed.
        execution_provenance=prepared.execution_provenance,
    )
