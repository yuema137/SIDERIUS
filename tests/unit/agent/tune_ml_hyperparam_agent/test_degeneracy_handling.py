"""Unit tests for the generic degeneracy reaction helper.

The task-specific predicate (amplitude collapse for SQUID denoising)
lives in ``execute_tools/squid_health_checks.py`` and is exercised in
``tests/unit/execute_tools/test_squid_health_checks.py``. By the time
``_apply_degeneracy_reaction`` runs, ``score_results`` already carries
the predicate's verdict on ``is_degenerate`` and the human-readable
``failure_reason``.

These tests pin down the **policy** layer alone — the translation from
``(is_degenerate, plan.is_trial, penalty_score)`` to ``denoising_score``
mutation. Trial rounds must never be penalized (no benchmark exists);
formal rounds must respect the operator-supplied
``degenerate_penalty_score`` (None → null score, float → use verbatim).
"""
from __future__ import annotations

from agent.schemas.hyperparam_tuning import ExperimentPlan
from nodes.ml_hyperparameter_tune_agent import _apply_degeneracy_reaction


def _make_plan(is_trial: bool) -> ExperimentPlan:
    """Minimal valid plan with caller-controlled trial flag."""
    return ExperimentPlan(
        model_type="punet",
        hypothesis="h",
        reasoning="r",
        model_cfg={},
        train_cfg={"epochs": 1},
        loss_cfg={"loss_type": "ce"},
        is_trial=is_trial,
        trial_strategy="snapshot",
        trial_portion=0.1,
        train_portion=0.1,
        eval_strategy="snapshot",
        eval_portion=0.1,
    )


# ---------------------------------------------------------------------------
# 1. Degenerate formal round — penalty=None → null score
# ---------------------------------------------------------------------------


def test_degenerate_formal_with_none_penalty_nulls_score():
    """Default policy (penalty_score=None) nulls the denoising_score so the
    round can never be picked as 'best'. failure_reason is preserved
    in score_results so downstream consumers (final_record, planner
    history) can surface it."""
    plan = _make_plan(is_trial=False)
    score_results = {
        "denoising_score": 1.23,
        "file_vector": [0.005] * 20,
        "is_degenerate": True,
        "failure_reason": "amplitude collapse: 0.0005% of reference",
    }
    is_degen, reason = _apply_degeneracy_reaction(
        score_results, plan, penalty_score=None,
    )
    assert is_degen is True
    assert reason == "amplitude collapse: 0.0005% of reference"
    assert score_results["denoising_score"] is None
    assert score_results["failure_reason"] == "amplitude collapse: 0.0005% of reference"


# ---------------------------------------------------------------------------
# 2. Degenerate formal round — penalty=-2.5 → score replaced with penalty
# ---------------------------------------------------------------------------


def test_degenerate_formal_with_float_penalty_uses_penalty():
    """Operator-supplied penalty (typically large-negative) replaces the
    score so the planner's rank-ordering still includes the failure but
    strictly below any healthy success."""
    plan = _make_plan(is_trial=False)
    score_results = {
        "denoising_score": 1.23,
        "file_vector": [0.005] * 20,
        "is_degenerate": True,
        "failure_reason": "amplitude collapse",
    }
    is_degen, reason = _apply_degeneracy_reaction(
        score_results, plan, penalty_score=-2.5,
    )
    assert is_degen is True
    assert reason == "amplitude collapse"
    assert score_results["denoising_score"] == -2.5


# ---------------------------------------------------------------------------
# 3. Trial rounds are immune even when score_vector flags is_degenerate
# ---------------------------------------------------------------------------


def test_degenerate_trial_round_is_no_op():
    """Trial rounds never get penalized — no magnitude benchmark exists at
    trial time. score_vector should not flag is_degenerate on trial
    rounds (reference_file_vector=None upstream), but defensive: if it
    does, the policy ignores the signal."""
    plan = _make_plan(is_trial=True)
    score_results = {
        "denoising_score": 0.5,
        "file_vector": [0.005] * 20,
        "is_degenerate": True,  # defensive — should not happen upstream
        "failure_reason": "spurious",
    }
    is_degen, reason = _apply_degeneracy_reaction(
        score_results, plan, penalty_score=None,
    )
    # Helper still returns the raw signal (so caller can log/audit)
    assert is_degen is True
    assert reason == "spurious"
    # …but the score is preserved (no penalty fired)
    assert score_results["denoising_score"] == 0.5


# ---------------------------------------------------------------------------
# 4. Non-degenerate formal round — pass-through
# ---------------------------------------------------------------------------


def test_non_degenerate_formal_preserves_score():
    """Healthy formal rounds are untouched. failure_reason must be None
    on a healthy run (the predicate inside score_vector returns None)."""
    plan = _make_plan(is_trial=False)
    score_results = {
        "denoising_score": 5.45,
        "file_vector": [10000.0] * 20,
        "is_degenerate": False,
        "failure_reason": None,
    }
    is_degen, reason = _apply_degeneracy_reaction(
        score_results, plan, penalty_score=-2.5,
    )
    assert is_degen is False
    assert reason is None
    # Penalty must not fire when not degenerate
    assert score_results["denoising_score"] == 5.45


# ---------------------------------------------------------------------------
# 5. Non-degenerate trial round — pass-through
# ---------------------------------------------------------------------------


def test_non_degenerate_trial_preserves_score():
    plan = _make_plan(is_trial=True)
    score_results = {
        "denoising_score": 0.42,
        "file_vector": [200.0] * 20,
        "is_degenerate": False,
        "failure_reason": None,
    }
    is_degen, reason = _apply_degeneracy_reaction(
        score_results, plan, penalty_score=-9.9,
    )
    assert is_degen is False
    assert reason is None
    assert score_results["denoising_score"] == 0.42


# ---------------------------------------------------------------------------
# 6. Defensive: missing keys default to (False, None) — no crash
# ---------------------------------------------------------------------------


def test_missing_keys_default_to_false_none():
    """Legacy single-file scoring path doesn't populate is_degenerate /
    failure_reason on score_results. The helper must not raise, must
    return ``(False, None)``, and must not mutate the score."""
    plan = _make_plan(is_trial=False)
    score_results = {"denoising_score": 1.0, "file_vector": [1.0] * 20}
    is_degen, reason = _apply_degeneracy_reaction(
        score_results, plan, penalty_score=None,
    )
    assert is_degen is False
    assert reason is None
    assert score_results["denoising_score"] == 1.0
