from __future__ import annotations

from agent.schemas.hyperparam_tuning import ExperimentPlan
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _apply_mode_override_chain,
    _best_trial_winner,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
)

BLOCKING_IDS = (
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
)


def _gates(*, passed: bool) -> list[dict]:
    return [
        {
            "gate_name": gate_id,
            "execution_status": "passed" if passed else "failed",
            "check_passed": passed,
            "would_invalidate_under_production_policy": not passed,
            "resolved_action": "continue",
        }
        for gate_id in BLOCKING_IDS
    ]


def _trial(exp_id: str, score: float, *, healthy: bool = True, **overrides) -> dict:
    record = {
        "exp_id": exp_id,
        "status": "success",
        "denoising_score": score,
        "is_trial": True,
        "health_gate_results": _gates(passed=healthy),
        "params": {
            "model_config": {"depth": 2},
            "train_config": {"lr": 0.001, "epochs": 1, "batch_size": 2},
            "loss_config": {"loss_type": "focal"},
        },
        "memory": {"time_mode": "trial"},
    }
    record.update(overrides)
    return record


def _plan() -> ExperimentPlan:
    return ExperimentPlan.with_defaults(
        {
            "model_cfg": {"depth": 4},
            "train_cfg": {"lr": 0.002, "epochs": 1, "batch_size": 4},
            "loss_cfg": {"loss_type": "ce"},
            "is_trial": True,
        }
    )


def test_valid_lower_score_beats_collapsed_higher_score() -> None:
    winner = _best_trial_winner([_trial("collapsed", 9.0, healthy=False), _trial("healthy", -0.5)])
    assert winner is not None
    assert winner["exp_id"] == "healthy"


def test_no_valid_trial_returns_none() -> None:
    assert _best_trial_winner([_trial("collapsed", 9.0, healthy=False)]) is None


def test_skip_formal_uses_valid_candidate_and_zero_reference() -> None:
    # V19 PR 1: the helpers take the RESOLVED threshold
    # (reference 0.0 + delta 0.0 → 0.0).
    assert _should_skip_formal([_trial("valid", -0.1)], threshold=0.0)
    assert not _should_skip_formal([_trial("valid", 0.0)], threshold=0.0)
    assert not _should_skip_formal([_trial("collapsed", 9.0, healthy=False)], threshold=0.0)
    # None threshold (no chain incumbent) → never fires, even on a
    # score that would fail any numeric threshold.
    assert not _should_skip_formal([_trial("valid", -99.0)], threshold=None)


def test_bypass_uses_valid_candidate_and_half_point_threshold() -> None:
    # Resolved threshold: reference 0.0 + delta 0.5 → 0.5.
    assert not _should_bypass_formal_time_budget([_trial("valid", 0.49)], threshold=0.5)
    assert _should_bypass_formal_time_budget([_trial("valid", 0.5)], threshold=0.5)
    assert not _should_bypass_formal_time_budget(
        [_trial("collapsed", 9.0, healthy=False)], threshold=0.5
    )
    # None threshold (no chain incumbent) → never fires.
    assert not _should_bypass_formal_time_budget([_trial("valid", 99.0)], threshold=None)


def test_failed_nontrial_and_contradictory_records_are_excluded() -> None:
    records = [
        _trial("failed", 5.0, status="error"),
        _trial("formal", 4.0, is_trial=False),
        _trial("contradictory", 3.0, memory={"time_mode": "formal"}),
    ]
    assert _best_trial_winner(records) is None


def test_forced_formal_inherits_best_valid_trial() -> None:
    plan = _apply_mode_override_chain(
        _plan(),
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
        formal_round_strategy="inherit_best_trial",
        memory_history=[
            _trial("collapsed", 9.0, healthy=False),
            _trial("healthy", -0.5),
        ],
    )
    assert plan.is_trial is False
    assert plan.model_cfg == {"depth": 2}
    assert plan.train_cfg["lr"] == 0.001


def test_forced_formal_with_no_valid_trial_preserves_planner_config() -> None:
    plan = _plan()
    original_model_cfg = dict(plan.model_cfg)
    result = _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
        formal_round_strategy="inherit_best_trial",
        memory_history=[_trial("collapsed", 9.0, healthy=False)],
    )
    assert result.is_trial is False
    assert result.model_cfg == original_model_cfg
