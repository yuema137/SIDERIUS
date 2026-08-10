"""V21 PR F — the frozen point-level classification (design §0.F).

One pure function; the report may only CALL it, never inline a second
rule. Conservative by construction: conflicting evidence about a
production boundary moves a point toward INDETERMINATE, never silently
across it — and unioning more evidence (re-runs) can only preserve a
verdict or move it to INDETERMINATE.
"""

from __future__ import annotations

from scripts.inspection_cost_study.schemas import Measurement, PointClass, PointVerdict


def classify_point(
    measurements: list[Measurement],
    *,
    budget_name: str,
    budget_seconds: float,
) -> PointVerdict:
    """Classify one operation point's repeats against ONE production budget.

    Per repeat (design §0.F):
      under         completed with exact elapsed <  budget
      over-exact    an EXACT observation >= budget — a completed post-hoc
                    overrun, or a native_timeout whose record carries a
                    real elapsed >= budget
      over-censored a lower bound >= budget — the native preemptive
                    training timeout or a harness backstop
    """
    if not measurements:
        raise ValueError("classify_point needs at least one measurement")
    heads = {(m.entry_id, m.operation, m.candidate_batch) for m in measurements}
    if len(heads) != 1:
        raise ValueError(f"measurements span {len(heads)} operation points; expected one")
    first = measurements[0]
    entry_id, operation, candidate_batch = (
        first.entry_id,
        first.operation,
        first.candidate_batch,
    )

    n_under = n_over_exact = n_over_censored = n_deadline = 0
    for m in measurements:
        if m.execution_outcome == "harness_deadline":
            n_deadline += 1
        elif m.elapsed_seconds is not None:
            if m.elapsed_seconds < budget_seconds:
                n_under += 1
            else:
                n_over_exact += 1
        elif m.lower_bound_seconds is not None:
            if m.lower_bound_seconds >= budget_seconds:
                n_over_censored += 1
            else:
                # A lower bound BELOW the budget says nothing about which
                # side the true value falls on. Unreachable with the
                # current constants (backstops/native bounds all >= their
                # budgets) but the pure rule must not depend on that —
                # counted with the deadline class, whose meaning here is
                # "evidence that cannot place the point", forcing
                # INDETERMINATE.
                n_deadline += 1
        else:
            # unloadable / invalid_config carry no timing claim at all.
            continue

    n_over = n_over_exact + n_over_censored
    verdict: PointClass
    if n_deadline > 0:
        verdict, reason = "INDETERMINATE", "deadline-or-unbounded evidence present"
    elif n_under > 0 and n_over > 0:
        verdict, reason = "INDETERMINATE", "repeats straddle the budget"
    elif n_over > 0:
        verdict, reason = "WOULD_BE_CENSORED", "every timed repeat at/over the budget"
    elif n_under > 0:
        verdict, reason = "CLEAR", "every timed repeat under the budget"
    else:
        verdict, reason = "INDETERMINATE", "no timing evidence (unloadable/invalid only)"

    return PointVerdict(
        entry_id=entry_id,
        operation=operation,
        candidate_batch=candidate_batch,
        budget_name=budget_name,
        budget_seconds=budget_seconds,
        verdict=verdict,
        n_under=n_under,
        n_over_exact=n_over_exact,
        n_over_censored=n_over_censored,
        n_deadline=n_deadline,
        reason=reason,
    )


def summarize_exact(measurements: list[Measurement]) -> dict[str, float | int | None]:
    """Timing summary over EXACT completed observations only (§0.F).

    Native-timeout exact values are deliberately EXCLUDED here — they are
    summarised separately per native operation by the report — and
    censored lower bounds never enter any timing statistic.
    """
    exact = sorted(
        m.elapsed_seconds
        for m in measurements
        if m.execution_outcome == "completed" and m.elapsed_seconds is not None
    )
    n_native = sum(1 for m in measurements if m.execution_outcome == "native_timeout")
    n_backstop = sum(1 for m in measurements if m.execution_outcome == "harness_backstop")
    n_deadline = sum(1 for m in measurements if m.execution_outcome == "harness_deadline")
    if not exact:
        median = mn = mx = None
    else:
        mid = len(exact) // 2
        median = exact[mid] if len(exact) % 2 == 1 else (exact[mid - 1] + exact[mid]) / 2.0
        mn, mx = exact[0], exact[-1]
    return {
        "n_completed": len(exact),
        "n_native_timeout": n_native,
        "n_backstop": n_backstop,
        "n_deadline": n_deadline,
        "median_s": median,
        "min_s": mn,
        "max_s": mx,
    }
