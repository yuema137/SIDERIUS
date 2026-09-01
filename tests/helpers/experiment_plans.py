"""Task-neutral ExperimentPlan fixtures shared across tuner tests."""

from __future__ import annotations

from agent.schemas.hyperparam_tuning import ExperimentPlan


def make_scope_plan(**overrides) -> ExperimentPlan:
    """Build a plan whose Trial and evaluation scopes are independently visible."""
    payload = {
        "model_cfg": {"segmentation_size": 10_000},
        "train_cfg": {"epochs": 1},
        "loss_cfg": {"loss_type": "ce"},
        "is_trial": True,
        "trial_strategy": "anchors",
        "trial_portion": 0.02,
        "train_portion": 0.3,
        "eval_strategy": "anchors",
        "eval_portion": 0.02,
        "hypothesis": "scope policy witness",
        "expected_score": 1.0,
        "memory_update": "none",
    }
    payload.update(overrides)
    return ExperimentPlan(**payload)
