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
    _resume_progress,
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
        "is_trial": time_mode == "trial",
        "health_gate_results": [
            {
                "gate_name": gate_name,
                "execution_status": "passed",
                "check_passed": True,
                "would_invalidate_under_production_policy": False,
                "resolved_action": "continue",
            }
            for gate_name in (
                "output_diversity_blocking",
                "output_std_blocking",
                "amplitude_collapse_blocking",
            )
        ],
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


def test_full_clone_formal_oom_retry_preserves_planner_recovery_fields(capsys):
    """A formal OOM retry must not reapply the batch/model that just OOMed."""
    plan = _make_plan()
    plan.model_cfg = {"model_type": "wavenet", "num_blocks": 8}
    plan.train_cfg = {"lr": 1e-4, "epochs": 1, "batch_size": 8}
    plan.loss_cfg = {"loss_type": "focal"}
    winner = _make_trial_record(
        "trial_best",
        score=1.0,
        model_config={"model_type": "wavenet", "num_blocks": 10},
        loss_type="focal_cw",
        lr=3e-4,
        epochs=1,
        batch_size=16,
    )
    oom = {
        "exp_id": "formal_oom",
        "status": "error_training_oom",
        "memory": {"round_index": 10},
    }

    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
        formal_round_strategy="full_clone",
        memory_history=[winner, oom],
    )

    assert plan.model_cfg["num_blocks"] == 8
    assert plan.train_cfg["batch_size"] == 8
    assert plan.train_cfg["lr"] == 3e-4
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert "[FORMAL RECOVERY]" in capsys.readouterr().out


def test_resume_progress_ignores_baseline_timestamp_suffix():
    """Baseline experiment IDs must not inflate the tuner attempt counter."""
    history = [
        {
            "exp_id": "baseline_wavenet_1784177030",
            "status": "failed_mode_collapse",
            "memory": {},
        },
        {
            "exp_id": "wavenet_diagnostic_baseline_pre_v17_004",
            "status": "failed_mode_collapse",
            "memory": {"round_index": 1},
        },
        {
            "exp_id": "wavenet_diagnostic_baseline_pre_v17_005",
            "status": "success",
            "memory": {"round_index": 2},
        },
    ]

    assert _resume_progress(
        history,
        model_type="wavenet",
        run_name="diagnostic_baseline_pre_v17",
    ) == (2, 5)


def test_strategy_accepts_canonical_full_clone():
    inp = _make_input(formal_round_strategy="full_clone")
    assert inp.formal_round_strategy == "full_clone"


def test_strategy_accepts_canonical_independent():
    inp = _make_input(formal_round_strategy="independent")
    assert inp.formal_round_strategy == "independent"


def test_strategy_legacy_inherit_best_trial_aliases_to_full_clone():
    """Backward-compat: live V9 chains and pre-2026-05-02
    ``advice/workflow/*.json`` configs still pass ``inherit_best_trial``.
    The schema validator must canonicalise it to ``full_clone`` so
    downstream code only handles canonical names."""
    inp = _make_input(formal_round_strategy="inherit_best_trial")
    assert inp.formal_round_strategy == "full_clone"


def test_strategy_legacy_llm_propose_aliases_to_independent():
    """Same backward-compat contract for the second legacy literal."""
    inp = _make_input(formal_round_strategy="llm_propose")
    assert inp.formal_round_strategy == "independent"


def test_strategy_hybrid_params_validates():
    """Phase 2 of refactor_formal_round_strategy.md adds ``hybrid_params``
    as a valid canonical strategy alongside ``full_clone`` and
    ``independent``. This is the inverse of the Phase 1 regression guard
    (``test_strategy_hybrid_params_rejected_in_phase_1``) — Phase 2 lands
    the registry handler so the schema can now accept it."""
    inp = _make_input(formal_round_strategy="hybrid_params")
    assert inp.formal_round_strategy == "hybrid_params"


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
    winner_model = {
        "segmentation_size": 1000,
        "kernel_size": 3,
        "use_same_padding": True,
        "num_blocks": 4,
    }
    history = [
        _make_trial_record("r1", score=5.15, loss_type="focal", lr=1e-4),
        _make_trial_record(
            "r2",
            score=5.45,
            loss_type="focal",
            lr=5e-5,
            epochs=1,
            batch_size=1,
            model_config=winner_model,
        ),  # winner
        _make_trial_record("r3", score=None, loss_type="ce", lr=5e-5, status="error_inference"),
    ]
    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
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
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
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
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
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
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
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
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=False,
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
        plan,
        trial_allowed=True,
        is_formal_round=False,
        force_formal_round=True,
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
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
        # memory_history omitted on purpose
    )
    assert plan.is_trial is False
    # No winner → loss/lr untouched
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert plan.train_cfg["lr"] == 1e-3


def test_inheritance_logs_winner_identity(capsys):
    """The success-path log lines must surface enough context that an
    operator can audit the inheritance after the fact.

    Phase 2 audit-log contract (refactor_formal_round_strategy.md §3):
    a ``[STRATEGY]`` line names the canonical strategy + alias
    provenance (when applicable), and a ``[FORMAL OVERRIDE]`` line
    names the winner exp_id, score, and the comma-list of inherited
    fields. The actual hyperparameter values aren't echoed in the log
    anymore — those live in the round's record. The winner's exp_id
    + score is enough to look the rest up."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 1}
    history = [
        _make_trial_record("r2", score=5.4523, loss_type="focal", lr=5e-5, epochs=2, batch_size=8)
    ]
    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
        memory_history=history,
    )
    out = capsys.readouterr().out
    # [STRATEGY] line — canonical name, no alias (caller passed default).
    assert "[STRATEGY] formal_round_strategy=full_clone" in out
    assert "alias_of" not in out
    # [FORMAL OVERRIDE] line — winner identity + score + inherited fields.
    assert "[FORMAL OVERRIDE]" in out
    assert "winner='r2'" in out
    assert "score=5.4523" in out
    # full_clone with all 5 fields available → all 5 listed in inherited=...
    assert "inherited=model_cfg,loss_cfg,lr,epochs,batch_size" in out


def test_strategy_llm_propose_keeps_planner_choices(capsys):
    """The escape hatch: with strategy='llm_propose' (legacy alias of
    canonical 'independent'), the planner's model_config, loss_config,
    and train_config survive verbatim even when a perfectly good trial
    winner exists. ``is_trial`` is still flipped to False because the
    formal-round mode flip is independent of the inheritance policy.

    Phase 2 log contract: the ``[STRATEGY]`` line surfaces both the
    canonical name and the legacy alias the caller passed
    (``alias_of:llm_propose``). ``[FORMAL OVERRIDE]`` shows
    ``inherited=(none)`` because ``independent`` is a no-op handler."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw", "experimental_flag": True}
    plan.train_cfg = {"lr": 1e-3, "epochs": 4, "batch_size": 16}
    plan.model_cfg = {"kernel_size": 2, "use_same_padding": False}  # planner's choice
    history = [
        _make_trial_record("r2", score=5.45, loss_type="focal", lr=5e-5, epochs=1, batch_size=1)
    ]
    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
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
    assert "[STRATEGY] formal_round_strategy=independent (alias_of:llm_propose)" in out
    assert "[FORMAL OVERRIDE] strategy=independent" in out
    assert "winner='r2'" in out
    assert "inherited=(none)" in out


def test_strategy_llm_propose_no_warning_without_winner(capsys):
    """With strategy='llm_propose', missing trial winner is not a
    warning condition — the policy explicitly disclaims inheritance."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3, "epochs": 1}
    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
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
    history = [
        _make_trial_record(
            "r1",
            score=5.45,
            loss_type="focal",
            lr=5e-5,
            epochs=2,
            batch_size=8,
            model_config={"kernel_size": 3, "use_same_padding": True, "num_blocks": 4},
        )
    ]
    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
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
    and emit the Phase 2 ``[FORMAL OVERRIDE] strategy=independent ...
    inherited=(none)`` line. No ``alias_of`` annotation since the caller
    passed the canonical name directly."""
    plan = _make_plan(is_trial=True)
    plan.loss_cfg = {"loss_type": "focal_cw"}
    plan.train_cfg = {"lr": 1e-3}
    plan.model_cfg = {"kernel_size": 2}
    history = [_make_trial_record("r1", score=5.45)]
    _apply_mode_override_chain(
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
        formal_round_strategy="independent",  # canonical, not legacy
        memory_history=history,
    )
    # Planner's choices survive — no inheritance happened.
    assert plan.loss_cfg["loss_type"] == "focal_cw"
    assert plan.train_cfg["lr"] == 1e-3
    assert plan.model_cfg["kernel_size"] == 2
    out = capsys.readouterr().out
    assert "[STRATEGY] formal_round_strategy=independent" in out
    assert "alias_of" not in out  # caller passed canonical, not legacy
    assert "[FORMAL OVERRIDE] strategy=independent" in out
    assert "inherited=(none)" in out


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
        plan,
        trial_allowed=True,
        is_formal_round=True,
        force_formal_round=True,
        formal_round_strategy="inherit_best_trial",  # legacy literal
        memory_history=history,
    )
    assert plan.loss_cfg["loss_type"] == "focal"
    assert plan.train_cfg["lr"] == 5e-5


# ---------------------------------------------------------------------------
# 5c. Phase 2 — strategy registry tests
# ---------------------------------------------------------------------------
# Phase 2 of refactor_formal_round_strategy.md replaces the if/elif chain
# inside ``_apply_mode_override_chain`` with a registry dispatch keyed by
# the canonical strategy name, and adds ``hybrid_params`` as the third
# canonical strategy. Section 5 (above) already exercises ``full_clone``
# (default) and the legacy ``llm_propose`` alias paths; this section adds
# the registry-shape pin, the ``hybrid_params`` cases, and the
# alias-resolution log assertion called for in §7.2 of the design doc.


import inspect
from typing import get_type_hints

from nodes.ml_hyperparameter_tune_agent import (
    _FORMAL_STRATEGY_REGISTRY,
    _strategy_full_clone,
    _strategy_hybrid_params,
    _strategy_independent,
)


class TestFullCloneStrategy:
    """``full_clone`` is the production default. Sections 5 (above) and 5b
    cover most paths with the default; these are the explicit
    canonical-name re-statements per §7.2."""

    def test_inherits_all_five_fields_from_winner(self):
        plan = _make_plan(is_trial=True)
        plan.loss_cfg = {"loss_type": "focal_cw"}
        plan.train_cfg = {"lr": 1e-3, "epochs": 4, "batch_size": 16}
        plan.model_cfg = {"kernel_size": 2}
        winner_model = {
            "segmentation_size": 1000,
            "kernel_size": 3,
            "use_same_padding": True,
            "num_blocks": 4,
        }
        history = [
            _make_trial_record(
                "r1",
                score=5.45,
                loss_type="focal",
                lr=5e-5,
                epochs=2,
                batch_size=8,
                model_config=winner_model,
            )
        ]
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="full_clone",
            memory_history=history,
        )
        assert plan.loss_cfg["loss_type"] == "focal"
        assert plan.train_cfg["lr"] == 5e-5
        assert plan.train_cfg["epochs"] == 2
        assert plan.train_cfg["batch_size"] == 8
        assert plan.model_cfg == winner_model

    def test_falls_back_to_planner_when_no_winner(self, capsys):
        plan = _make_plan(is_trial=True)
        plan.loss_cfg = {"loss_type": "focal_cw"}
        plan.train_cfg = {"lr": 1e-3, "epochs": 1}
        plan.model_cfg = {"kernel_size": 2}
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="full_clone",
            memory_history=[],
        )
        # Planner's plan unchanged.
        assert plan.loss_cfg["loss_type"] == "focal_cw"
        assert plan.train_cfg["lr"] == 1e-3
        assert plan.model_cfg["kernel_size"] == 2
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "no successful trial" in out.lower()


class TestHybridParamsStrategy:
    """The Phase 2 newcomer: lock loss + lr from the trial winner, leave
    everything else (model_cfg, epochs, batch_size) to the planner. See
    §2 of refactor_formal_round_strategy.md."""

    def test_inherits_only_loss_cfg_and_lr(self):
        plan = _make_plan(is_trial=True)
        plan.loss_cfg = {"loss_type": "focal_cw"}
        plan.train_cfg = {"lr": 1e-3, "epochs": 4, "batch_size": 16}
        plan.model_cfg = {"kernel_size": 5, "num_blocks": 8}  # planner's pick
        history = [
            _make_trial_record(
                "r1",
                score=5.45,
                loss_type="focal",
                lr=5e-5,
                epochs=2,
                batch_size=8,
                model_config={"kernel_size": 3, "num_blocks": 4},
            )
        ]
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="hybrid_params",
            memory_history=history,
        )
        # Inherited: loss + lr.
        assert plan.loss_cfg["loss_type"] == "focal"
        assert plan.train_cfg["lr"] == 5e-5
        # Survived from planner: model_cfg, epochs, batch_size.
        assert plan.model_cfg == {"kernel_size": 5, "num_blocks": 8}
        assert plan.train_cfg["epochs"] == 4
        assert plan.train_cfg["batch_size"] == 16

    def test_does_not_touch_model_cfg(self):
        """Pin: hybrid_params must NOT clone model_cfg even when the
        winner's record has a perfectly good one. The whole point of
        ``hybrid_params`` is to let the planner scale capacity."""
        plan = _make_plan(is_trial=True)
        plan.model_cfg = {"untouched": True}
        history = [
            _make_trial_record(
                "r1",
                score=5.45,
                model_config={"would_be_inherited_in_full_clone": True},
            )
        ]
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="hybrid_params",
            memory_history=history,
        )
        assert plan.model_cfg == {"untouched": True}

    def test_falls_back_to_planner_when_no_winner(self, capsys):
        """Same fallback contract as full_clone: no winner → planner's
        plan unchanged, WARNING logged. Score gate may still flag the
        round as unreliable downstream."""
        plan = _make_plan(is_trial=True)
        plan.loss_cfg = {"loss_type": "focal_cw"}
        plan.train_cfg = {"lr": 1e-3, "epochs": 1}
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="hybrid_params",
            memory_history=[],
        )
        assert plan.loss_cfg["loss_type"] == "focal_cw"
        assert plan.train_cfg["lr"] == 1e-3
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "no successful trial" in out.lower()

    def test_log_lists_inherited_fields(self, capsys):
        """The audit log must show ``inherited=loss_cfg,lr`` (in this
        exact order) so a post-mortem reader can grep the strategy
        without re-deriving from diffs."""
        plan = _make_plan(is_trial=True)
        history = [_make_trial_record("r1", score=5.4500)]
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="hybrid_params",
            memory_history=history,
        )
        out = capsys.readouterr().out
        assert "[STRATEGY] formal_round_strategy=hybrid_params" in out
        assert "[FORMAL OVERRIDE] strategy=hybrid_params" in out
        assert "winner='r1'" in out
        assert "inherited=loss_cfg,lr" in out


class TestIndependentStrategy:
    """``independent`` ignores any winner that may exist. Sections 5 and
    5b above exercise this through the legacy alias and the canonical
    name; these are the explicit per-§7.2 statements."""

    def test_planner_choices_survive_verbatim(self):
        plan = _make_plan(is_trial=True)
        plan.loss_cfg = {"loss_type": "focal_cw"}
        plan.train_cfg = {"lr": 1e-3, "epochs": 4, "batch_size": 16}
        plan.model_cfg = {"kernel_size": 2}
        history = [
            _make_trial_record(
                "r1",
                score=5.45,
                loss_type="focal",
                lr=5e-5,
                epochs=1,
                batch_size=1,
                model_config={"kernel_size": 3},
            )
        ]
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="independent",
            memory_history=history,
        )
        assert plan.loss_cfg["loss_type"] == "focal_cw"
        assert plan.train_cfg["lr"] == 1e-3
        assert plan.train_cfg["epochs"] == 4
        assert plan.train_cfg["batch_size"] == 16
        assert plan.model_cfg["kernel_size"] == 2

    def test_no_winner_no_warning(self, capsys):
        """Pin: ``independent`` shouldn't emit a WARNING about a missing
        winner — the policy explicitly disclaims inheritance, so the
        warning would be noise. Uniform `[FORMAL OVERRIDE]` line still
        surfaces so the audit trail is consistent."""
        plan = _make_plan(is_trial=True)
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="independent",
            memory_history=[],
        )
        out = capsys.readouterr().out
        assert "WARNING" not in out
        assert "no successful trial" not in out.lower()
        assert "[FORMAL OVERRIDE] strategy=independent" in out
        assert "winner=none" in out
        assert "inherited=(none)" in out


class TestAliasResolution:
    """Backward-compat path: the schema validator canonicalises legacy
    literals before they reach ``_apply_mode_override_chain``, but
    ``_canonical_strategy`` inside the function provides a defensive
    second pass for unit tests / ad-hoc constructions that bypass the
    schema. These tests pin the second-pass behavior so a refactor
    can't silently drop alias support."""

    def test_inherit_best_trial_behaves_as_full_clone(self):
        plan = _make_plan(is_trial=True)
        plan.loss_cfg = {"loss_type": "focal_cw"}
        plan.train_cfg = {"lr": 1e-3, "epochs": 4, "batch_size": 16}
        plan.model_cfg = {"kernel_size": 2}
        history = [
            _make_trial_record(
                "r1",
                score=5.45,
                loss_type="focal",
                lr=5e-5,
                epochs=2,
                batch_size=8,
                model_config={"kernel_size": 3, "num_blocks": 4},
            )
        ]
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="inherit_best_trial",  # legacy
            memory_history=history,
        )
        # Same outcome as full_clone — all 5 fields inherited.
        assert plan.loss_cfg["loss_type"] == "focal"
        assert plan.train_cfg["lr"] == 5e-5
        assert plan.train_cfg["epochs"] == 2
        assert plan.train_cfg["batch_size"] == 8
        assert plan.model_cfg["kernel_size"] == 3

    def test_llm_propose_behaves_as_independent(self):
        plan = _make_plan(is_trial=True)
        plan.loss_cfg = {"loss_type": "focal_cw"}
        plan.train_cfg = {"lr": 1e-3}
        plan.model_cfg = {"kernel_size": 2}
        history = [_make_trial_record("r1", score=5.45)]
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="llm_propose",  # legacy
            memory_history=history,
        )
        # Same outcome as independent — planner's plan untouched.
        assert plan.loss_cfg["loss_type"] == "focal_cw"
        assert plan.train_cfg["lr"] == 1e-3
        assert plan.model_cfg["kernel_size"] == 2

    def test_alias_log_line_emitted(self, capsys):
        """The ``[STRATEGY]`` line must surface ``alias_of:<legacy>``
        when the input differed from the canonical name. This is the
        single most useful audit-trail field — a reader scanning
        workflow_log.txt can see at a glance which configs came from
        legacy paths and need migration."""
        plan = _make_plan(is_trial=True)
        history = [_make_trial_record("r1", score=5.45)]
        _apply_mode_override_chain(
            plan,
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="inherit_best_trial",
            memory_history=history,
        )
        out = capsys.readouterr().out
        assert "[STRATEGY] formal_round_strategy=full_clone" in out
        assert "(alias_of:inherit_best_trial)" in out


class TestRegistryShape:
    """Pin the registry's structural invariants so a future strategy
    addition can't silently drift the contract."""

    def test_registry_has_three_canonical_strategies(self):
        assert set(_FORMAL_STRATEGY_REGISTRY.keys()) == {
            "full_clone",
            "hybrid_params",
            "independent",
        }

    def test_all_strategies_uniform_signature(self):
        """Every handler must accept ``(plan, winner)`` and return a
        list-like sequence of strings (the inherited field names).
        Catches future drift if someone adds a 4th handler with a
        different signature."""
        for name, handler in _FORMAL_STRATEGY_REGISTRY.items():
            sig = inspect.signature(handler)
            params = list(sig.parameters.values())
            assert len(params) == 2, (
                f"Handler {name!r} must accept exactly 2 args; got {len(params)}"
            )
            # Smoke-call each handler with a minimal valid winner record
            # to confirm the contract holds in practice (signature alone
            # doesn't rule out a handler that crashes on every input).
            plan = _make_plan(is_trial=True)
            winner = _make_trial_record("smoke", score=5.0)
            inherited = handler(plan, winner)
            assert isinstance(inherited, list), (
                f"Handler {name!r} returned {type(inherited).__name__}, expected list[str]"
            )
            for field in inherited:
                assert isinstance(field, str), (
                    f"Handler {name!r} returned non-string in inherited list: {field!r}"
                )

    def test_registry_directly_exposes_handler_callables(self):
        """Sanity: the three module-level handler symbols are the same
        objects as the registry values, so test fixtures can poke them
        directly without going through the dispatch wrapper."""
        assert _FORMAL_STRATEGY_REGISTRY["full_clone"] is _strategy_full_clone
        assert _FORMAL_STRATEGY_REGISTRY["hybrid_params"] is _strategy_hybrid_params
        assert _FORMAL_STRATEGY_REGISTRY["independent"] is _strategy_independent


# ---------------------------------------------------------------------------
# 6. Zero-output sanity check — REMOVED.
# The legacy `_check_zero_output_collapse` predicate has been replaced by
# the in-process check inside `execute_tools.scoring_utils.score_vector`
# (commits b1+b2) plus the agent-side `_apply_degeneracy_reaction` policy
# helper (commit c2). Coverage now lives in:
#   - tests/unit/execute_tools/health_checks/test_output_diversity_check.py
#   - tests/unit/execute_tools/health_checks/test_amplitude_collapse_check.py
#   - tests/unit/execute_tools/health_checks/test_runner.py
#   - tests/unit/agent/tune_ml_hyperparam_agent/test_gate_integration.py
#   - tests/unit/agent/tune_ml_hyperparam_agent/test_degeneracy_handling.py
# ---------------------------------------------------------------------------
