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
    epochs: int = 1,
    batch_size: int = 1,
    model_config: dict | None = None,
    time_mode: str = "trial",
    status: str = "success",
    file_vector=None,
):
    """Memory-history record with the fields ``_best_trial_winner`` /
    ``_check_zero_output_collapse`` / ``_apply_mode_override_chain``
    actually read.

    Defaults match the v7+ trial-success shape (score≠None, time_mode=trial,
    success status, ~10000-magnitude file_vector). Override per-test for
    edge cases (failure status, missing time_mode, formal mode, etc.).
    """
    if model_config is None:
        model_config = {
            "segmentation_size": 1000,
            "kernel_size": 3,
            "use_same_padding": True,
            "num_blocks": 4,
        }
    return {
        "exp_id": exp_id,
        "status": status,
        "denoising_score": score,
        "params": {
            "model_config": dict(model_config),
            "loss_config": {
                "loss_type": loss_type,
                "alpha": 0.5,
                "gamma": 2.0,
                "reduction": "mean",
            },
            "train_config": {
                "lr": lr,
                "epochs": epochs,
                "batch_size": batch_size,
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


def test_strategy_default_is_full_clone():
    """Phase 1 of refactor_formal_round_strategy.md flipped the schema
    default from the legacy ``inherit_best_trial`` literal to its
    canonical equivalent ``full_clone``. The behavior is unchanged —
    just the name on disk."""
    inp = _make_input()
    assert inp.formal_round_strategy == "full_clone"


def test_strategy_accepts_canonical_full_clone():
    inp = _make_input(formal_round_strategy="full_clone")
    assert inp.formal_round_strategy == "full_clone"


def test_strategy_accepts_canonical_independent():
    inp = _make_input(formal_round_strategy="independent")
    assert inp.formal_round_strategy == "independent"


def test_strategy_legacy_inherit_best_trial_aliases_to_full_clone():
    """Backward-compat: live V9 chains and pre-2026-05-02
    ``tuner_advice/*.json`` configs still pass ``inherit_best_trial``.
    The schema validator must canonicalise it to ``full_clone`` so
    downstream code only handles canonical names."""
    inp = _make_input(formal_round_strategy="inherit_best_trial")
    assert inp.formal_round_strategy == "full_clone"


def test_strategy_legacy_llm_propose_aliases_to_independent():
    """Same backward-compat contract for the second legacy literal."""
    inp = _make_input(formal_round_strategy="llm_propose")
    assert inp.formal_round_strategy == "independent"


def test_strategy_hybrid_params_rejected_in_phase_1():
    """Regression guard: ``hybrid_params`` is reserved for Phase 2 of
    refactor_formal_round_strategy.md and must NOT be acceptable in
    Phase 1 — accepting it before the registry handler exists would
    let users select a strategy that silently falls into the
    ``independent`` branch.

    When Phase 2 lands, this test should be deleted (or flipped to
    assert ``hybrid_params`` is now accepted)."""
    import pydantic
    try:
        _make_input(formal_round_strategy="hybrid_params")
    except pydantic.ValidationError:
        return
    raise AssertionError(
        "ValidationError expected — hybrid_params is reserved for Phase 2"
    )


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


def test_force_formal_inherits_full_winner_config():
    """The exact bug we're fixing: LLM picked a different (untested) loss
    AND architecture for the formal round; override copies the trial
    winner's model_config, loss_config, and the lr/epochs/batch_size of
    its train_config. Default strategy ('inherit_best_trial') applied
    implicitly."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw", "use_class_weights": True}  # bad LLM choice
    plan.train_cfg = {"lr": 1e-3, "epochs": 4, "batch_size": 16}
    plan.model_cfg = {"kernel_size": 2, "use_same_padding": False}  # bad LLM choice (V9 §7)
    winner_model = {"segmentation_size": 1000, "kernel_size": 3,
                    "use_same_padding": True, "num_blocks": 4}
    history = [
        _make_trial_record("r1", score=5.15, loss_type="focal", lr=1e-4),
        _make_trial_record("r2", score=5.45, loss_type="focal", lr=5e-5,
                           epochs=1, batch_size=1, model_config=winner_model),  # winner
        _make_trial_record("r3", score=None, loss_type="ce", lr=5e-5,
                           status="error_inference"),
    ]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        memory_history=history,
    )
    assert plan.is_trial is False
    # Loss inherited
    assert plan.loss_cfg["loss_type"] == "focal"
    assert plan.loss_cfg.get("use_class_weights") is None  # bad field gone
    # lr / epochs / batch_size inherited (V9 §7 fix)
    assert plan.train_cfg["lr"] == 5e-5
    assert plan.train_cfg["epochs"] == 1
    assert plan.train_cfg["batch_size"] == 1
    # model_cfg inherited (V9 §7 fix — required for trial→formal timing reuse)
    assert plan.model_cfg == winner_model
    assert plan.model_cfg["kernel_size"] == 3
    assert plan.model_cfg["use_same_padding"] is True


def test_force_formal_inheritance_resilient_to_missing_train_keys():
    """Production records sometimes omit `batch_size` or `epochs` from
    `train_config` (e.g. legacy fixtures with batch_size in model_config).
    The override must not crash on a missing key — it should keep the
    planner's value for that key and continue. lr remains required."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 5, "batch_size": 16}
    history = [_make_trial_record("r1", score=5.45, lr=5e-5)]
    # Strip batch_size + epochs to simulate a legacy/sparse record
    history[0]["params"]["train_config"].pop("batch_size", None)
    history[0]["params"]["train_config"].pop("epochs", None)
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        memory_history=history,
    )
    assert plan.is_trial is False
    # lr inherited (always present in winner)
    assert plan.train_cfg["lr"] == 5e-5
    # Missing keys → planner's values preserved
    assert plan.train_cfg["epochs"] == 5
    assert plan.train_cfg["batch_size"] == 16


def test_force_formal_model_cfg_inheritance_isolated_from_winner():
    """Mutating plan.model_cfg post-override must NOT mutate the winner's
    record (defensive copy)."""
    plan = _make_plan(is_trial=True)
    winner_model = {"segmentation_size": 1000, "kernel_size": 3}
    history = [
        _make_trial_record("r1", score=5.45, model_config=winner_model),
    ]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        memory_history=history,
    )
    plan.model_cfg["kernel_size"] = 99
    assert history[0]["params"]["model_config"]["kernel_size"] == 3, (
        "model_cfg copy aliased the winner record"
    )


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
    history = [_make_trial_record("r2", score=5.4523, loss_type="focal", lr=5e-5,
                                   epochs=2, batch_size=8)]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        memory_history=history,
    )
    out = capsys.readouterr().out
    assert "FORMAL OVERRIDE" in out
    assert "r2" in out
    assert "focal" in out
    assert "5e-05" in out or "5.0e-05" in out or "5e-5" in out
    # V9 §7 fix — print must surface the inherited training + model_cfg fields
    assert "epochs=2" in out
    assert "batch_size=8" in out
    assert "model_cfg_keys=" in out


def test_strategy_llm_propose_keeps_planner_choices(capsys):
    """The escape hatch: with strategy='llm_propose', the planner's
    model_config, loss_config, and train_config survive verbatim even
    when a perfectly good trial winner exists. ``is_trial`` is still
    flipped to False because the formal-round mode flip is independent
    of the inheritance policy."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw", "experimental_flag": True}
    plan.train_cfg = {"lr": 1e-3, "epochs": 4, "batch_size": 16}
    plan.model_cfg = {"kernel_size": 2, "use_same_padding": False}  # planner's choice
    history = [_make_trial_record("r2", score=5.45, loss_type="focal", lr=5e-5,
                                   epochs=1, batch_size=1)]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        formal_round_strategy="llm_propose",
        memory_history=history,
    )
    assert plan.is_trial is False  # mode still flipped
    # Planner's choices preserved across all three configs
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert plan.loss_cfg["experimental_flag"] is True
    assert plan.train_cfg["lr"] == 1e-3
    assert plan.train_cfg["epochs"] == 4
    assert plan.train_cfg["batch_size"] == 16
    assert plan.model_cfg["kernel_size"] == 2
    assert plan.model_cfg["use_same_padding"] is False
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
# 5b. Phase 1 transitional shim — canonical names reach the same code paths
# ---------------------------------------------------------------------------
# Phase 1 of refactor_formal_round_strategy.md adds ``_canonical_strategy``
# to the override chain so callers may pass either the legacy literal
# (``inherit_best_trial`` / ``llm_propose``) OR the new canonical name
# (``full_clone`` / ``independent``) and reach the same behavior. Phase 2
# replaces the if/elif with a registry; deleting these tests is fine then,
# but until the registry lands they pin the shim's correctness.


def test_shim_canonical_full_clone_inherits_like_legacy(capsys):
    """``full_clone`` (canonical) must trigger the same 5-field
    inheritance as ``inherit_best_trial`` (legacy). The shim resolves
    the alias inside ``_apply_mode_override_chain`` so the comparison
    works regardless of which name the caller used."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 4, "batch_size": 16}
    plan.model_cfg = {"kernel_size": 2}  # planner's wrong choice
    history = [_make_trial_record(
        "r1", score=5.45, loss_type="focal", lr=5e-5,
        epochs=2, batch_size=8,
        model_config={"kernel_size": 3, "use_same_padding": True, "num_blocks": 4},
    )]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        formal_round_strategy="full_clone",  # canonical, not legacy
        memory_history=history,
    )
    # All 5 inheritance fields applied — proves the shim hit the inherit path.
    assert plan.loss_cfg["loss_type"] == "focal"
    assert plan.train_cfg["lr"] == 5e-5
    assert plan.train_cfg["epochs"] == 2
    assert plan.train_cfg["batch_size"] == 8
    assert plan.model_cfg["kernel_size"] == 3  # winner's value, not planner's


def test_shim_canonical_independent_skips_inheritance(capsys):
    """``independent`` (canonical) must take the no-inheritance branch
    and emit the same 'honored verbatim' log as the legacy
    ``llm_propose``."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3}
    plan.model_cfg = {"kernel_size": 2}
    history = [_make_trial_record("r1", score=5.45)]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        formal_round_strategy="independent",  # canonical, not legacy
        memory_history=history,
    )
    # Planner's choices survive — no inheritance happened.
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert plan.train_cfg["lr"] == 1e-3
    assert plan.model_cfg["kernel_size"] == 2
    out = capsys.readouterr().out
    assert "honored verbatim" in out
    # Log surfaces both the canonical name and the input value.
    assert "independent" in out


def test_shim_legacy_inherit_best_trial_still_works(capsys):
    """The whole point of the shim: live V9 chains passing
    ``inherit_best_trial`` directly to ``_apply_mode_override_chain``
    (bypassing the schema validator) must still trigger inheritance.
    This is the production-path regression guard."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 4}
    history = [_make_trial_record("r1", score=5.0, loss_type="focal", lr=5e-5)]
    _apply_mode_override_chain(
        plan, trial_allowed=True, is_formal_round=True, force_formal_round=True,
        formal_round_strategy="inherit_best_trial",  # legacy literal
        memory_history=history,
    )
    assert plan.loss_cfg["loss_type"] == "focal"
    assert plan.train_cfg["lr"] == 5e-5


# ---------------------------------------------------------------------------
# 6. Zero-output sanity check — REMOVED.
# The legacy `_check_zero_output_collapse` predicate has been replaced by
# the in-process check inside `execute_tools.scoring_utils.score_vector`
# (commits b1+b2) plus the agent-side `_apply_degeneracy_reaction` policy
# helper (commit c2). Coverage now lives in:
#   - tests/unit/execute_tools/test_squid_health_checks.py
#   - tests/unit/agent/tune_ml_hyperparam_agent/test_degeneracy_handling.py
# ---------------------------------------------------------------------------
