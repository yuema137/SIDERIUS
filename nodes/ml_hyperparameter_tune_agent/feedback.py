"""Tuner FEEDBACK — evidence assembled for the NEXT agent, not for this round.

Step 07 PR 07b, C7 (operator scope amendment): moved VERBATIM out of
``ml_hyperparameter_tune_agent.py``. Zero behaviour change.

What belongs here: the structured signals a finished iteration hands forward —
gate exhaustion (the architecture was too heavy for the budgets), trial-validity
feedback (trials ran, succeeded, then failed their scientific gates), the
disallowed-pattern collection, and the compact summaries that render them.

What does NOT belong here: LLM prompt rendering. The planner's and reflector's
prompt text is owned by ``agent/prompt_templates/tuner/rendering.py``; this
module produces the typed evidence that travels TO those surfaces.
"""

from typing import Literal

from agent.schemas.health_feedback import (
    InvalidTrialOutcome,
    TrialValidityFeedback,
)
from agent.schemas.hyperparam_tuning import (
    GateExhaustionInfo,
)
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

    Returns a deterministic sorted list (empty if no attempt qualifies).
    """
    tags: set = set()
    for r in records:
        if r.get("status") not in {"skipped_oom_risk", "skipped_time_risk"}:
            continue
        mem = r.get("memory") or {}

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
    if any(is_valid_candidate(r) for r in trials):
        return None  # a valid winner exists; nothing to report

    outcomes: list[InvalidTrialOutcome] = []
    invalid = unknown = execution_failures = 0
    evidence_absent: list[str] = []

    for record in trials:
        exp_id = record.get("exp_id")
        status = str(record.get("status", "unknown"))
        validity = classify_candidate_health(record)

        if status != "success":
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
            InvalidTrialOutcome(
                exp_id=exp_id,
                status=status,
                health_validity=validity,
                failed_gate_names=failed_names,
                failure_reasons=reasons,
                key_metrics=metrics,
            )
        )

    return TrialValidityFeedback(
        trial_records_considered=len(trials),
        invalid_count=invalid,
        unknown_validity_count=unknown,
        execution_failure_count=execution_failures,
        outcomes=outcomes,
        formal_skipped_for_no_valid_winner=formal_skipped_for_no_valid_winner,
        healthgate_mode=healthgate_mode,
        evidence_absent=evidence_absent,
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
        )

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
) -> str:
    """One-paragraph LLM-readable synthesis of the gate-exhaustion state.

    The wording adapts to which axis was the binding ceiling — VRAM-only,
    time-only, or mixed — so the next proposer reads a clear instruction
    rather than a generic "everything failed" line. See §10.13.3.
    """
    parts = []

    # Lead sentence — what failed and how widely.
    if vram_gated and not time_gated:
        parts.append(
            f"All {total} attempt(s) ({vram_gated} VRAM-gated, {other} other "
            f"failures) were rejected by the pre-flight VRAM gate."
        )
    elif time_gated and not vram_gated:
        parts.append(
            f"All {total} attempt(s) ({time_gated} time-gated, {other} other "
            f"failures) were rejected by the pre-flight time gate."
        )
    else:
        parts.append(
            f"Of {total} attempt(s), {vram_gated} were rejected by the VRAM "
            f"gate and {time_gated} by the time gate "
            f"({other} other failures); none ever trained successfully."
        )

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
            "Verdict: the proposed architecture is too heavy for the active "
            "VRAM budget. Reduce parameter count and/or layer count so the "
            "next baseline lands below the budget."
        )
    elif time_gated and not vram_gated:
        parts.append(
            "Verdict: the proposed architecture is too slow for the active "
            "time budget. Reduce model depth/width or computation per step "
            "so the next baseline lands below the budget."
        )
    else:
        parts.append(
            "Verdict: the proposed architecture is over budget on multiple "
            "axes. Both parameter count AND per-step compute must come down."
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
    "model too large after K successful rounds" framing explicit so the
    next proposer reduces model size before exploring further.
    """
    # Lead sentence — Trigger B framing per §11.4 spec.
    if vram_gated and not time_gated:
        gated_axis = "VRAM"
    elif time_gated and not vram_gated:
        gated_axis = "time"
    else:
        gated_axis = "VRAM/time"
    parts = [
        f"Model too large — {consecutive_fail_rounds_at_exit} consecutive "
        f"rounds exhausted attempts at the {gated_axis} gate after "
        f"{completed_rounds} successful round(s); proposer should reduce "
        f"model size before the next iteration."
    ]
    parts.append(
        f"Burst breakdown: {total} attempt(s) "
        f"({vram_gated} VRAM-gated, {time_gated} time-gated, "
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
