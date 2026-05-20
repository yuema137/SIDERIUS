"""
Tests for Phase M — formal-mode sample-set fix.

Regression guards for the bug documented in
``docs/resource_estimator_implement.md §12``: formal rounds were silently
inheriting the planner's trial_strategy (often ``"anchors"``) and training /
evaluating on only the 3 anchor files. After Phase M:

  * Formal training side is operator-configurable via
    ``agent_input.formal_strategy`` / ``formal_portion`` / ``formal_train_portion``
    (defaults snapshot / 0.1 / 1.0).
  * Formal eval side is **locked** to snapshot + eval_portion=1.0 in the
    tuner and cannot be configured by the planner or the operator — this is
    what makes formal scores architecturally comparable across architectures.

The fix is centralised in the pure helper ``_resolve_sample_set_cfg``; these
tests exercise that helper and confirm its output drives
``build_sample_set`` to produce full 20-file coverage in formal mode.
"""

import pytest

from agent.schemas.hyperparam_tuning import (
    ExperimentPlan,
    HyperparamTuningInput,
)
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.scoring_utils import NUM_FILES, SEGMENTS_PER_FILE
from nodes.ml_hyperparameter_tune_agent import _resolve_sample_set_cfg

# ---------------------------------------------------------------------------
# Fixtures — a minimal valid HyperparamTuningInput and planner ExperimentPlan
# that we can mutate per test.
# ---------------------------------------------------------------------------


def _make_input(**overrides) -> HyperparamTuningInput:
    base = dict(
        model_type="punet",
        file_index=6,
        max_rounds=1,
        storage={
            "backend": "local",
            "local": {"workspace": "/tmp/phase_m_test", "run_name": "r"},
        },
    )
    base.update(overrides)
    return HyperparamTuningInput(**base)


def _make_plan(**overrides) -> ExperimentPlan:
    """Planner output with intentionally-anchor trial config so the fix is
    visible: if formal mode mistakenly inherited plan values, we would see
    ``"anchors"`` leak into the eval side."""
    base = dict(
        model_cfg={"segmentation_size": 10000},
        train_cfg={"epochs": 1},
        loss_cfg={"loss_type": "ce"},
        is_trial=True,
        trial_strategy="anchors",
        trial_portion=0.02,
        train_portion=0.3,
        eval_strategy="anchors",
        eval_portion=0.02,
        hypothesis="h",
        expected_score=1.0,
        memory_update="m",
    )
    base.update(overrides)
    return ExperimentPlan(**base)


# ---------------------------------------------------------------------------
# 1. Formal defaults — training side picks up schema defaults (snapshot / 0.1
#    / 1.0) and build_sample_set expands to 20 files x 20 segments each.
# ---------------------------------------------------------------------------


def test_formal_default_training_produces_20_file_snapshot():
    agent_input = _make_input()  # formal_* fields use schema defaults
    plan = _make_plan()  # planner picked anchors / 0.02

    cfg = _resolve_sample_set_cfg("formal", agent_input, plan)

    assert cfg["trial_strategy"] == "snapshot"
    assert cfg["trial_portion"] == 0.1
    assert cfg["train_portion"] == 1.0

    sample_set = build_sample_set(
        is_trial=True,
        trial_strategy=cfg["trial_strategy"],
        trial_portion=cfg["trial_portion"],
        seed=0,
    )
    assert len(sample_set) == NUM_FILES == 20
    expected_per_file = round(0.1 * SEGMENTS_PER_FILE)  # 20
    for fi, segs in sample_set.items():
        assert len(segs) == expected_per_file, (
            f"file {fi}: got {len(segs)} segments, expected {expected_per_file}"
        )


# ---------------------------------------------------------------------------
# 2. Formal eval — locked to snapshot + eval_portion=1.0 regardless of what
#    the planner chose. build_sample_set on the eval cfg must return all 20
#    files with all 200 segments each.
# ---------------------------------------------------------------------------


def test_formal_eval_is_locked_to_full_snapshot():
    agent_input = _make_input()
    plan = _make_plan(eval_strategy="anchors", eval_portion=0.02)

    cfg = _resolve_sample_set_cfg("formal", agent_input, plan)

    assert cfg["eval_strategy"] == "snapshot"
    assert cfg["eval_portion"] == 1.0

    eval_sample_set = build_sample_set(
        is_trial=True,
        trial_strategy=cfg["eval_strategy"],
        trial_portion=cfg["eval_portion"],
        seed=0,
    )
    assert len(eval_sample_set) == NUM_FILES == 20
    for fi, segs in eval_sample_set.items():
        assert len(segs) == SEGMENTS_PER_FILE == 200, (
            f"file {fi}: got {len(segs)} segments, expected 200"
        )


# ---------------------------------------------------------------------------
# 3. Operator override on the formal training side is respected.
# ---------------------------------------------------------------------------


def test_formal_training_override_respected():
    agent_input = _make_input(formal_portion=0.5)
    plan = _make_plan()

    cfg = _resolve_sample_set_cfg("formal", agent_input, plan)
    assert cfg["trial_portion"] == 0.5

    sample_set = build_sample_set(
        is_trial=True,
        trial_strategy=cfg["trial_strategy"],
        trial_portion=cfg["trial_portion"],
        seed=0,
    )
    expected_per_file = round(0.5 * SEGMENTS_PER_FILE)  # 100
    for fi, segs in sample_set.items():
        assert len(segs) == expected_per_file


# ---------------------------------------------------------------------------
# 4. Eval lock is immovable — even a planner that emits a tiny eval_portion
#    cannot narrow the formal eval scope.
# ---------------------------------------------------------------------------


def test_formal_eval_lock_is_immovable_against_plan_overrides():
    agent_input = _make_input()
    # Planner chose a very small eval scope. The formal cfg must ignore it.
    plan = _make_plan(eval_strategy="anchors", eval_portion=0.01)

    cfg = _resolve_sample_set_cfg("formal", agent_input, plan)
    assert cfg["eval_strategy"] == "snapshot"
    assert cfg["eval_portion"] == 1.0

    eval_sample_set = build_sample_set(
        is_trial=True,
        trial_strategy=cfg["eval_strategy"],
        trial_portion=cfg["eval_portion"],
        seed=0,
    )
    assert len(eval_sample_set) == NUM_FILES
    for segs in eval_sample_set.values():
        assert len(segs) == SEGMENTS_PER_FILE


# ---------------------------------------------------------------------------
# 5. Trial mode is untouched — regression guard that the helper still
#    forwards planner values verbatim when mode == "trial".
# ---------------------------------------------------------------------------


def test_trial_mode_still_uses_planner_values():
    agent_input = _make_input()
    plan = _make_plan(
        trial_strategy="anchors",
        trial_portion=0.05,
        eval_strategy="anchors",
        eval_portion=0.05,
        train_portion=0.25,
    )

    cfg = _resolve_sample_set_cfg("trial", agent_input, plan)
    assert cfg["trial_strategy"] == "anchors"
    assert cfg["trial_portion"] == 0.05
    assert cfg["train_portion"] == 0.25
    assert cfg["eval_strategy"] == "anchors"
    assert cfg["eval_portion"] == 0.05

    sample_set = build_sample_set(
        is_trial=True,
        trial_strategy=cfg["trial_strategy"],
        trial_portion=cfg["trial_portion"],
        seed=0,
    )
    # ANCHOR_FILES = [0, 10, 19] — 3-file sample set
    assert len(sample_set) == 3
    assert set(sample_set.keys()) == {0, 10, 19}


# ---------------------------------------------------------------------------
# 6. Single-file mode — ``trial_strategy`` / ``eval_strategy`` are always
#    snapshot, eval is always full, and the planner's train-side values flow
#    through. (Not in the doc's 5-case list, but cheap to guard.)
# ---------------------------------------------------------------------------


def test_single_file_mode_defaults():
    agent_input = _make_input()
    plan = _make_plan(
        trial_strategy="anchors",
        eval_strategy="anchors",
        trial_portion=0.03,
        eval_portion=0.03,
        train_portion=0.4,
    )

    cfg = _resolve_sample_set_cfg("single_file", agent_input, plan)
    assert cfg["trial_strategy"] == "snapshot"
    assert cfg["eval_strategy"] == "snapshot"
    assert cfg["eval_portion"] == 1.0
    # Train-side portions still come from the plan.
    assert cfg["trial_portion"] == 0.03
    assert cfg["train_portion"] == 0.4
