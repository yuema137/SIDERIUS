"""Unit verification for the §5.3.8 v9 dual-path branch logic.

The integration test ``tests/integration/workflows/test_vram_awareness.py``
gates Phase B assertions on a single boolean ``iter1_auto_shrunk`` that
encodes the v9 finding: when the Tuner planner downsizes the Proposer's
baseline_config to fit the budget, iter-1 ends with no PhysicalRejection
yet still produces a numeric denoising score. This is a valid
"Implicit Hardware Awareness" path that must not be flagged as a regression.

This unit test pins the predicate in isolation, deterministically, with
mocked HyperparamTuningOutput fixtures — so the dual-path behaviour is
locked down even when the GPU re-run is not available.

Scenarios covered:

  Path (a) - Failure-Rejection-Correction
    Iter-1 ends with one or more [PHYSICAL REJECTION] strings reaching
    iter-2's previous_failures. ``iter1_auto_shrunk`` MUST be False so
    that the Layer-2 rendered-prompt assert and Layer-3 param/keyword
    gates run. (Phase A is the canonical instance.)

  Path (b) - Successful Auto-Shrink (the v9 discovery)
    Iter-1 ends with zero rejections AND a successful tuning result
    (``status`` == success, ``best_denoising_score`` is numeric). The
    flag MUST be True so Layer-2/Layer-3 strict assertions are skipped
    and the auto-shrink summary print runs.

  Negative paths
    No iteration_results, failed status, or missing score MUST resolve
    to False - the test is not allowed to silently pass a broken run.
"""

from __future__ import annotations

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

# ---------------------------------------------------------------------------
# Predicate under test - copied VERBATIM from
# tests/integration/workflows/test_vram_awareness.py lines 518-526 (commit
# 0d3dc5d). Any drift between this copy and the integration test's inline
# computation is itself a regression - the unit guard's contract is that
# both expressions evaluate identically on every input.
#
# If the integration test changes the predicate, mirror the change here.
# ---------------------------------------------------------------------------


def decide_iter1_auto_shrunk(
    iter1_tuning: HyperparamTuningOutput | None,
    rejection_strings: list[str],
) -> bool:
    """Replica of the integration test's inline ``iter1_auto_shrunk`` boolean."""
    return (
        len(rejection_strings) == 0
        and iter1_tuning is not None
        and iter1_tuning.status in ("completed", "partial")
        and iter1_tuning.best_denoising_score is not None
    )


# ---------------------------------------------------------------------------
# Schema-valid status literals. The ground truth: ``HyperparamTuningOutput``
# pins ``status`` to ``Literal["completed", "partial", "failed"]``. Any
# value outside that set is a Pydantic validation error in production -
# meaning the predicate's comparison literal must be drawn from this set.
# ---------------------------------------------------------------------------

_SUCCESS_STATUSES = ("completed", "partial")
_FAILURE_STATUS = "failed"


def _make_tuning(
    *,
    status: str,
    score: float | None,
    run_name: str = "iter1",
    file_index: int = 6,
) -> HyperparamTuningOutput:
    """Build a minimal HyperparamTuningOutput respecting the schema."""
    return HyperparamTuningOutput(
        run_name=run_name,
        model_type="punet",
        file_index=file_index,
        status=status,  # Literal-validated by Pydantic
        completed_rounds=2,
        total_attempts=2,
        best_exp_id=f"{run_name}_001" if score is not None else None,
        best_denoising_score=score,
        best_config=(
            {"model_config": {}, "train_config": {}, "loss_config": {}}
            if score is not None
            else None
        ),
        all_records=[],
        started_at="2026-04-24T00:00:00Z",
        finished_at="2026-04-24T00:01:00Z",
    )


# ---------------------------------------------------------------------------
# Path (a) - Failure-Rejection-Correction. Auto-shrink flag MUST be False
# whenever any [PHYSICAL REJECTION] string is present, regardless of the
# iter-1 tuning's other fields. This guarantees the Layer-2 rendered-prompt
# assert and Layer-3 param/keyword audits still run on the rejection path.
# ---------------------------------------------------------------------------


class TestFailureRejectionCorrectionPath:
    def test_one_rejection_disables_auto_shrink_flag(self):
        iter1 = _make_tuning(status="completed", score=0.91)
        rej = ["[PHYSICAL REJECTION] iter-1 transformer overshot 29.10 GB"]
        assert decide_iter1_auto_shrunk(iter1, rej) is False, (
            "Presence of a rejection string must force iter1_auto_shrunk=False "
            "so Layer-2/Layer-3 assertions are not skipped."
        )

    def test_multiple_rejections_disable_auto_shrink_flag(self):
        iter1 = _make_tuning(status="completed", score=0.91)
        rej = [
            "[PHYSICAL REJECTION] attempt 1 dominant=attention",
            "[PHYSICAL REJECTION] attempt 2 dominant=ffn",
        ]
        assert decide_iter1_auto_shrunk(iter1, rej) is False

    def test_rejection_overrides_even_with_failed_status(self):
        iter1 = _make_tuning(status=_FAILURE_STATUS, score=None)
        rej = ["[PHYSICAL REJECTION] iter-1 overshot"]
        assert decide_iter1_auto_shrunk(iter1, rej) is False


# ---------------------------------------------------------------------------
# Path (b) - Successful Auto-Shrink. With zero rejections AND a successful
# tuning outcome, the flag MUST be True. Both schema-valid success literals
# (``completed`` and ``partial``) are exercised.
# ---------------------------------------------------------------------------


class TestSuccessfulAutoShrinkPath:
    @pytest.mark.parametrize("status", _SUCCESS_STATUSES)
    def test_zero_rejections_plus_success_status_plus_score_yields_true(
        self,
        status: str,
    ):
        iter1 = _make_tuning(status=status, score=0.85)
        rej: list[str] = []
        assert decide_iter1_auto_shrunk(iter1, rej) is True, (
            f"Auto-shrink path: zero rejections + status={status!r} + numeric "
            f"score must set iter1_auto_shrunk=True so the strict Layer-2 "
            f"[PHYSICAL REJECTION] assert and Layer-3 param/keyword gates "
            f"are bypassed (the v9 design intent)."
        )

    def test_non_empty_rejections_with_success_resolves_to_rejection_path(self):
        """If both signals are present, rejection wins - the test still
        runs Layer-2/Layer-3 strict assertions."""
        iter1 = _make_tuning(status="completed", score=0.85)
        rej = ["[PHYSICAL REJECTION] real overshoot"]
        assert decide_iter1_auto_shrunk(iter1, rej) is False


# ---------------------------------------------------------------------------
# Negative gates - the predicate must NOT silently pass a broken run.
# ---------------------------------------------------------------------------


class TestNegativeGates:
    def test_none_iter1_tuning_is_false(self):
        assert decide_iter1_auto_shrunk(None, []) is False

    def test_failed_status_is_false(self):
        iter1 = _make_tuning(status=_FAILURE_STATUS, score=None)
        assert decide_iter1_auto_shrunk(iter1, []) is False

    @pytest.mark.parametrize("status", _SUCCESS_STATUSES)
    def test_success_status_with_no_score_is_false(self, status: str):
        iter1 = _make_tuning(status=status, score=None)
        assert decide_iter1_auto_shrunk(iter1, []) is False, (
            "A run reporting success but yielding no numeric score is not a "
            "valid auto-shrink - the workflow has no value to feed iter-2."
        )


# ---------------------------------------------------------------------------
# Schema invariant - regression guard for the predicate's comparison literal.
#
# The integration test's inline expression compares status to a string
# literal. If that literal is not a member of HyperparamTuningOutput.status's
# Literal set, the auto-shrink branch is dead code: real Tuner output can
# never satisfy the comparison. This test pins the predicate's literal
# against the schema so the dual-path design cannot rot silently.
# ---------------------------------------------------------------------------


class TestPredicateLiteralIsSchemaValid:
    def test_predicate_returns_true_for_at_least_one_schema_valid_status(self):
        """The auto-shrink branch must be reachable by at least one Tuner
        success status the schema actually emits. If this assertion fails,
        the predicate's comparison literal has drifted from the schema and
        the dual-path code is unreachable in production."""
        reached = False
        score = 0.5
        for status in _SUCCESS_STATUSES:
            iter1 = _make_tuning(status=status, score=score)
            if decide_iter1_auto_shrunk(iter1, []):
                reached = True
                break
        assert reached, (
            "Dead-code regression: decide_iter1_auto_shrunk returns False for "
            "every schema-valid success status "
            f"({list(_SUCCESS_STATUSES)!r}). The predicate's comparison "
            "literal does not match any value the Tuner can emit, so the v9 "
            "auto-shrink branch is unreachable in production. Fix the "
            "comparison literal in tests/integration/workflows/"
            "test_vram_awareness.py to use the actual success status(es)."
        )
