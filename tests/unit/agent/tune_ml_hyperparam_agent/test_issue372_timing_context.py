"""Issue #372: prompt facts must not invent parameter ownership or strategy."""

from agent.prompts import _format_fixed_params_block, get_planner_user_prompt


def test_partial_lock_does_not_claim_all_portions_and_epochs_are_frozen():
    """A fixed training fraction says nothing about evaluation or an epoch cap."""
    text = _format_fixed_params_block({"trial_portion": 0.37}, max_epochs=7)
    assert "trial_portion    = 0.37" in text
    assert "≤ 7" in text
    assert "since those knobs are frozen" not in text
    assert "Your control surface this run" not in text


def test_direct_call_without_context_does_not_claim_complete_control_knowledge():
    """The bridge can be used alone; absence of constraints is not freedom."""
    text = get_planner_user_prompt(memory_history=[])
    assert "incomplete" in text.lower()
    assert "unknown" in text.lower()


def test_round_counters_do_not_select_a_search_strategy():
    """Moving through rounds must not automatically prescribe data or epochs."""
    for current_round in (1, 4, 8):
        text = get_planner_user_prompt(memory_history=[], current_round=current_round, max_rounds=8)
        assert f"Current round: {current_round} / 8" in text
        assert "Current phase:" not in text
        assert "Increase trial_portion and epochs" not in text
        assert "low trial_portion and low epochs" not in text


def test_override_display_does_not_invent_formal_evaluation_fraction():
    """A Trial override cannot establish the separate Formal policy's value."""
    text = _format_fixed_params_block({"eval_portion": 0.23}, max_epochs=None)
    assert "eval_portion     = 0.23" in text
    assert "formal mode auto-uses 1.0" not in text


def test_execution_sources_and_context_use_the_same_role_bindings(tmp_path):
    """Non-default source values must reach both the renderer and execution."""
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from nodes.ml_hyperparameter_tune_agent.policy import _resolve_sample_set_cfg
    from nodes.ml_hyperparameter_tune_agent.timing_context import build_timing_context
    from tests.helpers.experiment_plans import make_scope_plan

    for owner in ("operator", "agent"):
        inp = HyperparamTuningInput(
            model_type="punet",
            file_index=0,
            llm_provider="openai",
            llm_model_id="test",
            storage=StorageConfig(
                backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="scope")
            ),
            max_rounds=2,
            formal_training_scope_source=owner,
            formal_portion=0.31,
            formal_train_portion=0.47,
            formal_eval_portion=0.29,
            trial_max_epochs=7,
            formal_max_epochs=11,
            validation_max_train_samples=123,
            validation_max_samples=57,
        )
        plan = make_scope_plan(trial_portion=0.61, train_portion=0.73, eval_portion=0.19)
        context = build_timing_context(
            inp,
            trial_allowed=True,
            is_formal_round=False,
            current_round=1,
            trial_winner=None,
            memory_history=[],
            scope_is_partial=False,
        )
        assert [r.epoch_cap for r in context.roles] == [7, 11]
        for role in context.roles:
            actual = _resolve_sample_set_cfg(role.mode, inp, plan)
            described = {
                b.field: getattr(plan, b.source) if b.owner == "resolved_plan" else b.value
                for b in role.workload
            }
            assert actual == described
        assert context.validation_max_train_samples == 123
        assert context.validation_max_samples == 57
        from agent.prompt_templates.tuner.timing_context import render_timing_context

        rendered = render_timing_context(context)
        assert "evaluation scope used for final scoring" in rendered
        assert "also bounds epoch validation" in rendered
        assert context.roles[1].workload[-1].value == 0.29
        training = next(b for b in context.roles[1].workload if b.field == "trial_portion")
        assert training.owner == ("resolved_plan" if owner == "agent" else "run")


def test_native_strategy_context_reaches_final_provider_input():
    """Verify actual bridge delivery, not just direct renderer output."""
    from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
    from tests.helpers.tuner_prompt_fixtures import planner_kwargs

    bridge = BoundaryRecorderBridge()
    bridge.plan(**(planner_kwargs() | {"planner_strategy": "native-timing-v1"}))
    _, _, system, user = bridge.captures[0]
    assert "TIMING CONTROL CONTEXT — incomplete" in user
    assert "PROGRESSIVE RESEARCH STRATEGY" not in system
    assert "double the" not in system
    assert "Default 0.1" not in system
    assert "noise. Do not pivot" not in system
    assert "first consider whether changing batch_size" not in user
    assert "PSD_SEGMENT_LENGTH" not in user
    assert "Lowering batch_size reduces vram_factor" not in user
    assert "EVIDENCE AND CONSTRAINTS" in user


def test_native_recovery_does_not_prescribe_optimizer_or_search_order():
    """Fixed optimizer advice can contradict task constraints after a failure."""
    from agent.prompts import PLANNER_PROMPT

    assert "weight_decay=1e-4" not in PLANNER_PROMPT
    assert "switch from Adam to AdamW" not in PLANNER_PROMPT
    assert "Three or more consecutive" not in PLANNER_PROMPT
    assert "{LOSS_COLLAPSE}" not in PLANNER_PROMPT
    assert "{LOSS_RESET}" not in PLANNER_PROMPT


def test_partial_scope_banner_limits_normalization_to_trial():
    """Agent-owned Formal training must not be described as Trial-normalized."""
    block = _format_fixed_params_block(None, resolved_data_scope=[0, 2])
    assert "partial-scope Trial normalization only" in block
    assert "forced under a partial data_scope" not in block
