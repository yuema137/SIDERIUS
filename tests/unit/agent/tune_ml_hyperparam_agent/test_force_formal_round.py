"""Unit tests for the ``force_formal_round`` flag.

Three surfaces to verify:

1. Schema — ``HyperparamTuningInput.force_formal_round`` defaults to ``True``
   and accepts both boolean values.

2. Override helper — ``_apply_mode_override_chain`` correctly gates the
   ``plan.is_trial = False`` mutation on the new flag while still applying
   the unconditional ``trial_allowed=False`` lockout.

3. Planner prompt — ``get_planner_user_prompt`` honours the flag in the
   ROUND CONTEXT block: True ⇒ "MANDATORY", False ⇒ "OPTIONAL". This is
   the patch that closes the bug we observed in the Commit 11 gate test
   where the LLM kept picking formal mode despite ``--no-force_formal_round``
   because the prompt told it formal was always required on the last round.
"""
from __future__ import annotations

from agent.prompts import get_planner_user_prompt
from agent.schemas.hyperparam_tuning import (
    ExperimentPlan,
    HyperparamTuningInput,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import _apply_mode_override_chain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_plan(is_trial: bool = True) -> ExperimentPlan:
    """Minimal valid ExperimentPlan with caller-controlled ``is_trial``."""
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


def _make_input(**overrides) -> HyperparamTuningInput:
    base = dict(
        model_type="punet",
        file_index=6,
        max_rounds=1,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="/tmp/force_formal_test", run_name="r"),
        ),
    )
    base.update(overrides)
    return HyperparamTuningInput(**base)


# ---------------------------------------------------------------------------
# 1. Schema — defaults + accepts both values
# ---------------------------------------------------------------------------


def test_default_is_true():
    """Default preserves the production override behaviour."""
    inp = _make_input()
    assert inp.force_formal_round is True


def test_accepts_false():
    inp = _make_input(force_formal_round=False)
    assert inp.force_formal_round is False


def test_accepts_true_explicit():
    inp = _make_input(force_formal_round=True)
    assert inp.force_formal_round is True


# ---------------------------------------------------------------------------
# 2. Override helper — the four-corner truth table
# ---------------------------------------------------------------------------


def test_force_formal_on_forces_formal():
    """Production path: last round + flag on + planner picked trial
    → trial gets forced to formal so the score is cross-architecture
    comparable."""
    plan = _make_plan(is_trial=True)
    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
    )
    assert plan.is_trial is False


def test_force_formal_off_honours_planner():
    """Testing path: last round + flag off + planner picked trial
    → planner's choice survives and the round runs trial."""
    plan = _make_plan(is_trial=True)
    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=False,
    )
    assert plan.is_trial is True


def test_non_last_round_unaffected_by_flag():
    """Non-last rounds never get the formal-promotion override applied,
    regardless of the flag value — only ``trial_allowed=False`` could
    force them to formal, and that's a different gate."""
    for flag in (True, False):
        plan = _make_plan(is_trial=True)
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=False,
            force_formal_round=flag,
        )
        assert plan.is_trial is True, f"flag={flag} flipped a non-last round"


def test_trial_disallowed_overrides_unconditionally():
    """``trial_allowed=False`` is a run-level lockout that fires every
    round and is independent of ``force_formal_round``."""
    for flag in (True, False):
        for is_formal in (True, False):
            plan = _make_plan(is_trial=True)
            _apply_mode_override_chain(
                plan,
                trial_allowed=False,
                is_formal_round=is_formal,
                force_formal_round=flag,
            )
            assert plan.is_trial is False, (
                f"trial_allowed=False missed: flag={flag} is_formal={is_formal}"
            )


def test_planner_already_formal_no_op():
    """If the planner picked formal to begin with, neither gate has any
    visible effect."""
    plan = _make_plan(is_trial=False)
    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=False,
    )
    assert plan.is_trial is False


# ---------------------------------------------------------------------------
# 3. Planner prompt — flag flips MANDATORY ↔ OPTIONAL on the last round
# ---------------------------------------------------------------------------


def test_prompt_says_mandatory_when_force_formal_on_last_round():
    """The exact bug we observed: even with the override helper bypassed,
    the prompt still told the LLM 'you MUST use formal mode' on the last
    round, so the LLM kept picking formal regardless of the flag."""
    prompt = get_planner_user_prompt(
        memory_history=[],
        current_round=3,
        max_rounds=3,  # last round
        trial_allowed=True,
        force_formal_round=True,
    )
    assert "MANDATORY" in prompt, "Prompt must mark final round formal as MANDATORY"
    assert "You MUST set `is_trial`: false" in prompt
    assert "OPTIONAL" not in prompt


def test_prompt_says_optional_when_force_formal_off_last_round():
    """With ``--no-force_formal_round``, the prompt must release the LLM
    to choose trial mode on the last round — otherwise the wiring is moot."""
    prompt = get_planner_user_prompt(
        memory_history=[],
        current_round=3,
        max_rounds=3,
        trial_allowed=True,
        force_formal_round=False,
    )
    assert "OPTIONAL" in prompt, "Prompt must mark final round formal as OPTIONAL"
    assert "MAY use trial mode" in prompt
    assert "MANDATORY" not in prompt


def test_prompt_non_last_round_unaffected_by_flag():
    """For non-last rounds, the flag has no visible effect on the round
    context block — both modes remain free."""
    for flag in (True, False):
        prompt = get_planner_user_prompt(
            memory_history=[],
            current_round=2,
            max_rounds=3,  # round 2 of 3 is NOT the last
            trial_allowed=True,
            force_formal_round=flag,
        )
        assert "MANDATORY" not in prompt, f"flag={flag} leaked MANDATORY on non-last round"
        assert "FINAL ROUND" not in prompt, f"flag={flag} leaked FINAL ROUND on non-last round"


def test_prompt_trial_disabled_directs_formal():
    """``trial_allowed=False`` always directs the LLM to ``is_trial=false``,
    regardless of the flag — though the wording differs:

    * ``flag=True``  → "FINAL ROUND ... MANDATORY" branch fires first (the
      stronger round-specific message wins; same outcome).
    * ``flag=False`` → "Trial mode is DISABLED" branch fires (run-level
      lockout surfaces because the round-specific override is off).
    """
    prompt_t = get_planner_user_prompt(
        memory_history=[],
        current_round=3,
        max_rounds=3,
        trial_allowed=False,
        force_formal_round=True,
    )
    assert "MANDATORY" in prompt_t and "is_trial`: false" in prompt_t

    prompt_f = get_planner_user_prompt(
        memory_history=[],
        current_round=3,
        max_rounds=3,
        trial_allowed=False,
        force_formal_round=False,
    )
    assert "Trial mode is DISABLED" in prompt_f, (
        "flag=False did not surface the trial_allowed=False lockout message"
    )
