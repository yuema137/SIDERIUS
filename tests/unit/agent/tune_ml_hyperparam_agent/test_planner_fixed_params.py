"""
Tests for the SYSTEM-FIXED PARAMETERS block injected into the planner prompt.

Validates:
  _format_fixed_params_block:
    - Returns empty string when both plan_overrides and max_epochs are unset
    - Renders only requested keys when partial overrides supplied
    - Renders generic fallback for unknown keys
    - max_epochs cap line appears when set
    - All four canonical keys + cap render together (workflow default scenario)

  get_planner_user_prompt integration:
    - Block absent from output when no overrides are passed (no regression)
    - Block present and references the SYSTEM-FIXED PARAMETERS heading when set
    - Override values appear verbatim in the rendered prompt
"""
from agent.prompts import _format_fixed_params_block, get_planner_user_prompt


# ---- _format_fixed_params_block ----

def test_empty_when_no_overrides_and_no_cap():
    assert _format_fixed_params_block(None, None) == ""
    assert _format_fixed_params_block({}, None) == ""


def test_only_max_epochs_renders_cap_only():
    block = _format_fixed_params_block(None, max_epochs=1)
    assert "SYSTEM-FIXED PARAMETERS" in block
    assert "epochs (cap)" in block
    assert "≤ 1" in block
    # No rendered-value line for the override keys (the NOTE prose may still
    # reference them — only the "key  = value" lines should be absent).
    assert "trial_portion    =" not in block
    assert "train_portion    =" not in block


def test_partial_overrides_render_only_supplied_keys():
    block = _format_fixed_params_block({"trial_portion": 0.1}, max_epochs=None)
    assert "trial_portion    = 0.1" in block
    assert "train_portion" not in block
    assert "eval_portion" not in block
    assert "is_trial" not in block
    assert "epochs (cap)" not in block


def test_unknown_override_key_renders_generically():
    block = _format_fixed_params_block({"some_new_field": "abc"}, None)
    assert "some_new_field" in block
    assert "abc" in block


def test_workflow_default_overrides_render_all_lines():
    overrides = {
        "is_trial": True,
        "trial_portion": 0.1,
        "train_portion": 1.0,
        "eval_portion": 0.1,
    }
    block = _format_fixed_params_block(overrides, max_epochs=1)
    # All canonical keys present
    assert "is_trial         = True" in block
    assert "trial_portion    = 0.1" in block
    assert "train_portion    = 1.0" in block
    assert "eval_portion     = 0.1" in block
    assert "epochs (cap)     ≤ 1" in block
    # Annotations present
    assert "final round auto-flips to formal" in block
    assert "formal mode auto-uses 1.0" in block
    # Control surface guidance present
    assert "Your control surface this run" in block
    # NOTE about contradicting prose present
    assert "phase-progression" in block


# ---- get_planner_user_prompt integration ----

def test_planner_prompt_omits_block_when_no_overrides():
    prompt = get_planner_user_prompt(memory_history=[])
    assert "SYSTEM-FIXED PARAMETERS" not in prompt


def test_planner_prompt_includes_block_when_overrides_set():
    overrides = {
        "is_trial": True,
        "trial_portion": 0.1,
        "train_portion": 1.0,
        "eval_portion": 0.1,
    }
    prompt = get_planner_user_prompt(
        memory_history=[],
        plan_overrides=overrides,
        max_epochs=1,
    )
    # Block heading appears
    assert "SYSTEM-FIXED PARAMETERS" in prompt
    # Values appear verbatim
    assert "trial_portion    = 0.1" in prompt
    assert "train_portion    = 1.0" in prompt
    # Block precedes the Human Expert Advice section
    assert prompt.index("SYSTEM-FIXED PARAMETERS") < prompt.index("Human Expert Advice")


def test_planner_prompt_block_with_only_max_epochs():
    prompt = get_planner_user_prompt(memory_history=[], max_epochs=1)
    assert "SYSTEM-FIXED PARAMETERS" in prompt
    assert "epochs (cap)     ≤ 1" in prompt
