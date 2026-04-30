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
from nodes.ml_hyperparameter_tune_agent import (
    _apply_mode_override_chain,
    _best_trial_winner,
)


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


def _make_trial_record(
    exp_id: str,
    *,
    score,
    loss_type: str = "focal",
    lr: float = 1e-4,
    time_mode: str = "trial",
    status: str = "success",
    file_vector=None,
):
    """Memory-history record with the fields ``_best_trial_winner`` /
    ``_check_zero_output_collapse`` actually read.

    Defaults match the v7 trial-success shape (score≠None, time_mode=trial,
    success status, ~10000-magnitude file_vector). Override per-test for
    edge cases (failure status, missing time_mode, formal mode, etc.).
    """
    return {
        "exp_id": exp_id,
        "status": status,
        "denoising_score": score,
        "params": {
            "loss_config": {
                "loss_type": loss_type,
                "alpha": 0.5,
                "gamma": 2.0,
                "reduction": "mean",
            },
            "train_config": {
                "lr": lr,
                "epochs": 1,
                "batch_size": 1,
                "device": "cuda",
            },
        },
        "file_vector": file_vector if file_vector is not None else [10000.0] * 20,
        "memory": {"time_mode": time_mode},
    }


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


def test_strategy_default_is_inherit_best_trial():
    """The default policy mandates the 'safe' inheritance behaviour
    out-of-the-box."""
    inp = _make_input()
    assert inp.formal_round_strategy == "inherit_best_trial"


def test_strategy_accepts_llm_propose():
    inp = _make_input(formal_round_strategy="llm_propose")
    assert inp.formal_round_strategy == "llm_propose"


def test_strategy_rejects_unknown_value():
    """Schema must reject anything outside the Literal — opt-in policies
    are added explicitly."""
    import pydantic
    try:
        _make_input(formal_round_strategy="freestyle")
    except pydantic.ValidationError:
        return
    raise AssertionError("ValidationError expected for unknown strategy")


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


# ---------------------------------------------------------------------------
# 4. _best_trial_winner — eligibility predicate
# ---------------------------------------------------------------------------


def test_best_trial_winner_picks_max_score():
    history = [
        _make_trial_record("r1", score=5.15),
        _make_trial_record("r2", score=5.45),  # winner
        _make_trial_record("r3", score=4.90),
    ]
    winner = _best_trial_winner(history)
    assert winner is not None
    assert winner["exp_id"] == "r2"


def test_best_trial_winner_excludes_formal_mode():
    """Records with memory.time_mode=='formal' are NOT eligible — even
    if their score is higher than any trial-mode record."""
    history = [
        _make_trial_record("formal_high", score=99.0, time_mode="formal"),
        _make_trial_record("trial_low", score=5.45, time_mode="trial"),
    ]
    winner = _best_trial_winner(history)
    assert winner is not None
    assert winner["exp_id"] == "trial_low"


def test_best_trial_winner_excludes_non_success():
    """Gate-rejected / errored records never qualify as a winner even
    when time_mode is set."""
    history = [
        _make_trial_record("bad", score=None, status="error_inference"),
        _make_trial_record("skipped", score=None, status="skipped_time_risk"),
        _make_trial_record("good", score=5.45),
    ]
    winner = _best_trial_winner(history)
    assert winner is not None
    assert winner["exp_id"] == "good"


def test_best_trial_winner_excludes_missing_time_mode():
    """Records without memory.time_mode are excluded — we cannot prove
    they were a real trial run."""
    rec = _make_trial_record("no_mode", score=5.45)
    rec["memory"].pop("time_mode")
    winner = _best_trial_winner([rec])
    assert winner is None


def test_best_trial_winner_returns_none_on_empty():
    assert _best_trial_winner([]) is None


# ---------------------------------------------------------------------------
# 5. Forced-formal hyperparameter inheritance
# ---------------------------------------------------------------------------


def test_force_formal_inherits_loss_and_lr_from_best_trial():
    """The exact bug we're fixing: LLM picked a different (untested) loss
    for the formal round; override copies the trial winner's loss + lr.
    Default strategy ('inherit_best_trial') applied implicitly."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw", "use_class_weights": True}  # bad LLM choice
    plan.train_cfg = {"lr": 1e-3, "epochs": 1, "batch_size": 4}
    history = [
        _make_trial_record("r1", score=5.15, loss_type="focal", lr=1e-4),
        _make_trial_record("r2", score=5.45, loss_type="focal", lr=5e-5),  # winner
        _make_trial_record("r3", score=None, loss_type="ce", lr=5e-5,
                           status="error_inference"),
    ]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        memory_history=history,
    )
    assert plan.is_trial is False
    assert plan.loss_cfg["loss_type"] == "focal"
    assert plan.loss_cfg.get("use_class_weights") is None  # bad field gone
    assert plan.train_cfg["lr"] == 5e-5
    # Untouched: epochs, batch_size, model_cfg
    assert plan.train_cfg["epochs"] == 1
    assert plan.train_cfg["batch_size"] == 4


def test_no_trial_winner_falls_back_to_planner_with_warning(capsys):
    """No successful trial in history → planner's loss_cfg + lr survive,
    a WARNING is logged, and is_trial is still flipped to False."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 1}
    history = [
        _make_trial_record("r1", score=None, status="error_training"),
    ]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        memory_history=history,
    )
    assert plan.is_trial is False
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert plan.train_cfg["lr"] == 1e-3
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "no successful trial" in out.lower()


def test_inheritance_skipped_when_force_formal_off():
    """force_formal_round=False on the last round → no flip, no inheritance,
    even with a perfectly good trial winner sitting in history."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 1}
    history = [_make_trial_record("r1", score=5.45, loss_type="focal", lr=5e-5)]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=False,
        memory_history=history,
    )
    assert plan.is_trial is True
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert plan.train_cfg["lr"] == 1e-3


def test_inheritance_skipped_on_non_last_rounds():
    """Even with force_formal_round=True, mid-iteration rounds don't get
    inheritance applied because is_formal_round=False."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 1}
    history = [_make_trial_record("r1", score=5.45, loss_type="focal", lr=5e-5)]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=False, force_formal_round=True,
        memory_history=history,
    )
    assert plan.is_trial is True
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert plan.train_cfg["lr"] == 1e-3


def test_inheritance_default_memory_history_none():
    """memory_history defaults to None — older callers shouldn't break.
    With None, no inheritance fires (treated as empty history)."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 1}
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        # memory_history omitted on purpose
    )
    assert plan.is_trial is False
    # No winner → loss/lr untouched
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert plan.train_cfg["lr"] == 1e-3


def test_inheritance_logs_winner_identity(capsys):
    """The success-path log line must surface enough context that an
    operator can audit the inheritance after the fact."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 1}
    history = [_make_trial_record("r2", score=5.4523, loss_type="focal", lr=5e-5)]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        memory_history=history,
    )
    out = capsys.readouterr().out
    assert "FORMAL OVERRIDE" in out
    assert "r2" in out
    assert "focal" in out
    assert "5e-05" in out or "5.0e-05" in out or "5e-5" in out


def test_strategy_llm_propose_keeps_planner_choices(capsys):
    """The escape hatch: with strategy='llm_propose', the planner's
    loss_config and lr survive verbatim even when a perfectly good
    trial winner exists. ``is_trial`` is still flipped to False because
    the formal-round mode flip is independent of the inheritance policy."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw", "experimental_flag": True}
    plan.train_cfg = {"lr": 1e-3, "epochs": 1, "batch_size": 4}
    history = [_make_trial_record("r2", score=5.45, loss_type="focal", lr=5e-5)]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        formal_round_strategy="llm_propose",
        memory_history=history,
    )
    assert plan.is_trial is False  # mode still flipped
    # Planner's choices preserved
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert plan.loss_cfg["experimental_flag"] is True
    assert plan.train_cfg["lr"] == 1e-3
    out = capsys.readouterr().out
    assert "llm_propose" in out
    assert "honored verbatim" in out


def test_strategy_llm_propose_no_warning_without_winner(capsys):
    """With strategy='llm_propose', missing trial winner is not a
    warning condition — the policy explicitly disclaims inheritance."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 1}
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        formal_round_strategy="llm_propose",
        memory_history=[],
    )
    out = capsys.readouterr().out
    assert "WARNING" not in out
    assert "no successful trial" not in out.lower()


# ---------------------------------------------------------------------------
# 6. Zero-output sanity check — REMOVED.
# The legacy `_check_zero_output_collapse` predicate has been replaced by
# the in-process check inside `execute_tools.scoring_utils.score_vector`
# (commits b1+b2) plus the agent-side `_apply_degeneracy_reaction` policy
# helper (commit c2). Coverage now lives in:
#   - tests/unit/execute_tools/test_squid_health_checks.py
#   - tests/unit/agent/tune_ml_hyperparam_agent/test_degeneracy_handling.py
# ---------------------------------------------------------------------------
