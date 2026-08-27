"""Gate integration in the tuner main loop (commit-5b).

Tests the mapping between ``GateResult`` / ``resolved_action`` and the
legacy ``is_degenerate`` / ``failure_reason`` contract that
``_apply_degeneracy_reaction`` consumes, plus the termination-state
precedence at loop exit.

F-SCANC-1 test disposition (operator decision packet v1, 2026-08-26):
the ``_should_break_iteration`` / ``_should_skip_to_formal`` classes and
the SKIP_ITER / SKIP_TO_FORMAL mapping cases were DELETED with the
machinery — they supplied inputs production could no longer produce (the
C7 decomposition had severed the carrier; the finding's "eighth
blindness shape"). The input classes they shared with live behaviour are
preserved: blocking-failure classification by
``test_invalidate_round_single_gate``, multi-gate concatenation and the
empty-reason fallback UPGRADED to the live ``invalidate_round`` action,
and the ``gate_aborted`` termination cases removed with the retired
carrier.

See ``docs/design/pluggable_health_checks.md`` §4 (action semantics),
§8 (severity resolution), and §14 for the migration context.
"""

from __future__ import annotations

import pytest

from execute_tools.health_checks.schemas import (
    GateAction,
    GateResult,
)
from nodes.ml_hyperparameter_tune_agent import (
    _compute_termination_state,
    _gate_results_to_score_meta,
    _merge_score_validity_failure,
)


def _gr(
    gate_id: str,
    action: GateAction,
    passed: bool = True,
    failure_reason: str = "",
) -> GateResult:
    """Minimal GateResult factory for the mapping tests."""
    return GateResult(
        gate_id=gate_id,
        round_index=1,
        passed=passed,
        action=action,
        failure_reason=failure_reason,
    )


# ---------------------------------------------------------------------------
# _gate_results_to_score_meta — the (is_degenerate, reason, action_str) mapping
# ---------------------------------------------------------------------------


class TestGateResultsToScoreMeta:
    def test_continue_with_empty_gate_list(self):
        """No gates fired: resolved_action=CONTINUE, empty list. Clean
        (False, None, "continue") tuple."""
        result = _gate_results_to_score_meta([], GateAction.CONTINUE)
        assert result == (False, None, "continue")

    def test_continue_with_passing_gates(self):
        """Gates ran and all passed: still CONTINUE, still clean tuple."""
        result = _gate_results_to_score_meta(
            [_gr("g1", GateAction.CONTINUE, passed=True)],
            GateAction.CONTINUE,
        )
        assert result == (False, None, "continue")

    def test_invalidate_round_single_gate(self):
        gr = _gr(
            "gate_5",
            GateAction.INVALIDATE_ROUND,
            passed=False,
            failure_reason="output_diversity: 1 unique value",
        )
        is_degen, reason, action = _gate_results_to_score_meta([gr], GateAction.INVALIDATE_ROUND)
        assert is_degen is True
        assert reason == "[gate_5] output_diversity: 1 unique value"
        assert action == "invalidate_round"

    def test_multiple_failed_gates_pipe_concatenated(self):
        """Two gates fire and both fail; failure_reason contains both
        with gate_id prefixes, pipe-separated (AMB-5b-B → A)."""
        gates = [
            _gr(
                "gate_a",
                GateAction.INVALIDATE_ROUND,
                passed=False,
                failure_reason="reason A",
            ),
            _gr(
                "gate_b",
                GateAction.INVALIDATE_ROUND,
                passed=False,
                failure_reason="reason B",
            ),
        ]
        # resolved_action is the severity winner (INVALIDATE_ROUND > CONTINUE).
        is_degen, reason, action = _gate_results_to_score_meta(gates, GateAction.INVALIDATE_ROUND)
        assert is_degen is True
        assert reason == "[gate_a] reason A | [gate_b] reason B"
        assert action == "invalidate_round"

    def test_failed_gate_with_empty_reason_falls_back(self):
        """A failed gate with empty ``failure_reason`` is skipped in the
        concat; the fallback synthetic string fires so downstream never
        sees an empty reason string paired with is_degenerate=True."""
        gates = [
            _gr(
                "gate_a",
                GateAction.INVALIDATE_ROUND,
                passed=False,
                failure_reason="",
            ),
        ]
        is_degen, reason, action = _gate_results_to_score_meta(gates, GateAction.INVALIDATE_ROUND)
        assert is_degen is True
        assert reason == "gate action invalidate_round with no reason"
        assert action == "invalidate_round"

    def test_passing_gate_excluded_from_concat(self):
        """A passing sibling doesn't leak into the failure_reason concat."""
        gates = [
            _gr(
                "gate_a",
                GateAction.CONTINUE,
                passed=True,
                failure_reason="",
            ),
            _gr(
                "gate_b",
                GateAction.INVALIDATE_ROUND,
                passed=False,
                failure_reason="bad",
            ),
        ]
        _is_degen, reason, _action = _gate_results_to_score_meta(gates, GateAction.INVALIDATE_ROUND)
        assert reason == "[gate_b] bad"

    # ------------------------------------------------------------------
    # M8 §3.2 semantic-fix tests (Caveat A): recording-only failures
    # never flag is_degenerate=True. Reasons are still surfaced.
    # ------------------------------------------------------------------

    def test_recording_only_failure_does_not_flag_degenerate(self):
        """Recording gate (action=CONTINUE) that failed must not set
        is_degenerate — it would otherwise silently zero-out a formal
        score via _apply_degeneracy_reaction."""
        gr = _gr(
            "pearson_dispersion_recording",
            GateAction.CONTINUE,
            passed=False,
            failure_reason="pearson: mean=0.001 below noise floor",
        )
        is_degen, reason, action = _gate_results_to_score_meta([gr], GateAction.CONTINUE)
        assert is_degen is False
        # But the reason is still surfaced for observability
        assert reason == "[pearson_dispersion_recording] pearson: mean=0.001 below noise floor"
        assert action == "continue"

    def test_mixed_recording_failure_and_blocking_pass(self):
        """Recording fail + blocking pass: not degenerate; recording
        reason still surfaces so the operator sees what the recording
        gate noticed."""
        gates = [
            _gr("output_diversity_blocking", GateAction.CONTINUE, passed=True),
            _gr(
                "pearson_dispersion_recording",
                GateAction.CONTINUE,
                passed=False,
                failure_reason="pearson: soft threshold",
            ),
        ]
        is_degen, reason, action = _gate_results_to_score_meta(gates, GateAction.CONTINUE)
        assert is_degen is False
        assert reason == "[pearson_dispersion_recording] pearson: soft threshold"
        assert action == "continue"

    def test_mixed_recording_failure_and_blocking_failure(self):
        """Blocking fail wins: is_degenerate=True, reason concatenates
        both so the round record shows the full picture."""
        gates = [
            _gr(
                "output_diversity_blocking",
                GateAction.INVALIDATE_ROUND,
                passed=False,
                failure_reason="unique=2 (threshold 30)",
            ),
            _gr(
                "pearson_dispersion_recording",
                GateAction.CONTINUE,
                passed=False,
                failure_reason="mean pearson=0.001",
            ),
        ]
        is_degen, reason, action = _gate_results_to_score_meta(gates, GateAction.INVALIDATE_ROUND)
        assert is_degen is True
        assert reason == (
            "[output_diversity_blocking] unique=2 (threshold 30) | "
            "[pearson_dispersion_recording] mean pearson=0.001"
        )
        assert action == "invalidate_round"

    def test_recording_failure_with_empty_reason_no_ghost_reason(self):
        """Recording gate fails with empty reason and no blocking failure:
        return None (not the synthetic fallback) — the fallback is only
        appropriate when the routing action is blocking."""
        gr = _gr(
            "recording_check",
            GateAction.CONTINUE,
            passed=False,
            failure_reason="",
        )
        is_degen, reason, action = _gate_results_to_score_meta([gr], GateAction.CONTINUE)
        assert is_degen is False
        assert reason is None
        assert action == "continue"


# ---------------------------------------------------------------------------
# _compute_termination_state — precedence table (audit Gap #3 follow-up)
# ---------------------------------------------------------------------------


class TestComputeTerminationState:
    """Precedence: fails_exceeded → completed → fallback.

    Verifies the ``(run_status, termination_reason)`` selection at loop
    exit — landed as the audit Gap #3 fix in the follow-up to commit-5b.
    The ``gate_aborted`` input and its two precedence cases were retired
    with the SKIP_ITER action (F-SCANC-1): the flag's only writer was the
    unreachable skip branch, so the cases certified a branch production
    could never take.
    """

    def test_completed_when_max_rounds_reached(self):
        assert _compute_termination_state(
            completed_rounds=5,
            max_rounds=5,
            consecutive_fails=0,
            max_fail_rounds=3,
        ) == ("completed", "completed")

    def test_aborted_fail_rounds_when_fails_exceeded(self):
        assert _compute_termination_state(
            completed_rounds=1,
            max_rounds=5,
            consecutive_fails=3,
            max_fail_rounds=3,
        ) == ("partial", "aborted_fail_rounds")

    def test_fallback_partial_completed(self):
        """Defensive fallback — currently unreachable with max_rounds >= 1
        but kept for the same reason the original inline code had it."""
        assert _compute_termination_state(
            completed_rounds=0,
            max_rounds=5,
            consecutive_fails=0,
            max_fail_rounds=3,
        ) == ("partial", "completed")


class TestScoreValidityFailure:
    """Every completed scoring attempt must have a finite scalar."""

    def test_finite_score_preserves_healthy_state(self):
        assert _merge_score_validity_failure(
            -3.14,
            is_degenerate=False,
            failure_reason=None,
        ) == (False, None)

    @pytest.mark.parametrize("score", [None, float("-inf"), float("inf"), float("nan")])
    def test_missing_or_nonfinite_score_is_collapse(self, score):
        is_degenerate, reason = _merge_score_validity_failure(
            score,
            is_degenerate=False,
            failure_reason=None,
        )

        assert is_degenerate is True
        assert reason is not None
        assert "[scoring_validity]" in reason

    def test_preserves_existing_gate_failure(self):
        is_degenerate, reason = _merge_score_validity_failure(
            float("-inf"),
            is_degenerate=True,
            failure_reason="[gate] output_diversity",
        )

        assert is_degenerate is True
        assert reason == (
            "[gate] output_diversity | [scoring_validity] denoising_score is "
            "None or non-finite; the model produced no valid denoising signal"
        )
