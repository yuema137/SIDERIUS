"""Gate integration in the tuner main loop (commit-5b).

Tests the mapping between ``GateResult`` / ``resolved_action`` and the
legacy ``is_degenerate`` / ``failure_reason`` contract that
``_apply_degeneracy_reaction`` consumes, plus the loop-control semantics
for the four ``GateAction`` values.

Loop-control tests target the small helper functions
``_should_break_iteration`` and ``_should_skip_to_formal`` directly;
end-to-end tuner-loop integration (with real sandbox + registry) is out
of scope for this file — it would require heavy mocking of the tuner's
plan → train → infer → score pipeline. The helpers are simple enough
that unit tests + code review of the tuner's inline usage are the right
verification split.

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
    _should_break_iteration,
    _should_skip_to_formal,
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

    def test_skip_to_formal_single_gate(self):
        gr = _gr(
            "gate_3",
            GateAction.SKIP_TO_FORMAL,
            passed=False,
            failure_reason="output_diversity: only 10 unique",
        )
        is_degen, reason, action = _gate_results_to_score_meta([gr], GateAction.SKIP_TO_FORMAL)
        assert is_degen is True
        assert reason == "[gate_3] output_diversity: only 10 unique"
        assert action == "skip_to_formal"

    def test_skip_iter_single_gate(self):
        gr = _gr(
            "gate_1",
            GateAction.SKIP_ITER,
            passed=False,
            failure_reason="output_diversity: only 1 unique",
        )
        is_degen, reason, action = _gate_results_to_score_meta([gr], GateAction.SKIP_ITER)
        assert is_degen is True
        assert reason == "[gate_1] output_diversity: only 1 unique"
        assert action == "skip_iter"

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
                GateAction.SKIP_ITER,
                passed=False,
                failure_reason="reason B",
            ),
        ]
        # resolved_action is the severity winner (SKIP_ITER > INVALIDATE_ROUND).
        is_degen, reason, action = _gate_results_to_score_meta(gates, GateAction.SKIP_ITER)
        assert is_degen is True
        assert reason == "[gate_a] reason A | [gate_b] reason B"
        assert action == "skip_iter"

    def test_failed_gate_with_empty_reason_falls_back(self):
        """A failed gate with empty ``failure_reason`` is skipped in the
        concat; the fallback synthetic string fires so downstream never
        sees an empty reason string paired with is_degenerate=True."""
        gates = [
            _gr(
                "gate_a",
                GateAction.SKIP_ITER,
                passed=False,
                failure_reason="",
            ),
        ]
        is_degen, reason, action = _gate_results_to_score_meta(gates, GateAction.SKIP_ITER)
        assert is_degen is True
        assert reason == "gate action skip_iter with no reason"
        assert action == "skip_iter"

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


# ---------------------------------------------------------------------------
# _should_break_iteration — SKIP_ITER only
# ---------------------------------------------------------------------------


class TestShouldBreakIteration:
    def test_skip_iter_returns_true(self):
        assert _should_break_iteration(GateAction.SKIP_ITER) is True

    @pytest.mark.parametrize(
        "action",
        [
            GateAction.CONTINUE,
            GateAction.SKIP_TO_FORMAL,
            GateAction.INVALIDATE_ROUND,
        ],
    )
    def test_non_skip_iter_returns_false(self, action: GateAction):
        assert _should_break_iteration(action) is False


# ---------------------------------------------------------------------------
# _should_skip_to_formal — SKIP_TO_FORMAL guarded by not is_formal_round
# ---------------------------------------------------------------------------


class TestShouldSkipToFormal:
    def test_skip_to_formal_not_yet_formal_returns_true(self):
        assert _should_skip_to_formal(GateAction.SKIP_TO_FORMAL, False) is True

    def test_skip_to_formal_already_formal_returns_false(self):
        """Guard against re-running the formal round — the tuner is already
        on the formal round when SKIP_TO_FORMAL fires, no jump needed."""
        assert _should_skip_to_formal(GateAction.SKIP_TO_FORMAL, True) is False

    @pytest.mark.parametrize(
        "action",
        [
            GateAction.CONTINUE,
            GateAction.SKIP_ITER,
            GateAction.INVALIDATE_ROUND,
        ],
    )
    @pytest.mark.parametrize("is_formal_round", [False, True])
    def test_non_skip_to_formal_returns_false(self, action: GateAction, is_formal_round: bool):
        assert _should_skip_to_formal(action, is_formal_round) is False


# ---------------------------------------------------------------------------
# _compute_termination_state — precedence table (audit Gap #3 follow-up)
# ---------------------------------------------------------------------------


class TestComputeTerminationState:
    """Precedence: gate_aborted → fails_exceeded → completed → fallback.

    Verifies the ``(run_status, termination_reason)`` selection at loop
    exit — landed as the audit Gap #3 fix in the follow-up to commit-5b.
    """

    def test_gate_abort_takes_precedence_over_completed(self):
        """gate_aborted=True beats even completed_rounds >= max_rounds.
        In practice this can't happen (SKIP_ITER breaks before completion)
        but the precedence guarantee is defensive."""
        assert _compute_termination_state(
            completed_rounds=5,
            max_rounds=5,
            consecutive_fails=0,
            max_fail_rounds=3,
            gate_aborted=True,
        ) == ("partial", "aborted_by_gate")

    def test_gate_abort_takes_precedence_over_fail_rounds(self):
        """gate_aborted=True + consecutive_fails=max should still report
        aborted_by_gate (the gate is the more specific signal)."""
        assert _compute_termination_state(
            completed_rounds=1,
            max_rounds=5,
            consecutive_fails=3,
            max_fail_rounds=3,
            gate_aborted=True,
        ) == ("partial", "aborted_by_gate")

    def test_completed_when_max_rounds_reached(self):
        assert _compute_termination_state(
            completed_rounds=5,
            max_rounds=5,
            consecutive_fails=0,
            max_fail_rounds=3,
            gate_aborted=False,
        ) == ("completed", "completed")

    def test_aborted_fail_rounds_when_fails_exceeded(self):
        assert _compute_termination_state(
            completed_rounds=1,
            max_rounds=5,
            consecutive_fails=3,
            max_fail_rounds=3,
            gate_aborted=False,
        ) == ("partial", "aborted_fail_rounds")

    def test_fallback_partial_completed(self):
        """Defensive fallback — currently unreachable with max_rounds >= 1
        but kept for the same reason the original inline code had it."""
        assert _compute_termination_state(
            completed_rounds=0,
            max_rounds=5,
            consecutive_fails=0,
            max_fail_rounds=3,
            gate_aborted=False,
        ) == ("partial", "completed")
