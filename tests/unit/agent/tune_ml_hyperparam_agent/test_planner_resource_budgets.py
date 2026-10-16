"""Issue735: configuration must not be mislabeled as prior or upcoming evidence.

Preserves the original K.6 cases: no inputs, explicit None, both prior modes,
missing budget on each axis, no estimates, and real prompt ordering. Adds
unknown-mode, evidence-only and full-snapshot Trial witnesses.
"""

import pytest

from agent.prompts import (
    PLANNER_PROMPT,
    RESOURCE_GATE_GUIDANCE_BLOCK,
    _format_active_resource_budgets_block,
    get_planner_user_prompt,
)


def test_trial_role_does_not_invent_data_scope_or_metric_normalization():
    trial = PLANNER_PROMPT.split("### TRIAL vs FORMAL MODE:")[1].split("Trial strategies")[0]
    assert "task/workflow constraints" in trial
    assert "full\n  data or a subset" in trial
    assert "anchor-normalized" not in trial
    assert "sparse sample" not in trial
    assert "GPU MEMORY RULES" not in PLANNER_PROMPT
    assert "Use TIMING CONTROL CONTEXT" in RESOURCE_GATE_GUIDANCE_BLOCK
    assert "An override, inherited" in RESOURCE_GATE_GUIDANCE_BLOCK
    assert "does not identify" in RESOURCE_GATE_GUIDANCE_BLOCK
    assert "If both factors are <= 1: continue" not in RESOURCE_GATE_GUIDANCE_BLOCK
    assert "Lowering batch_size reduces vram_factor" not in RESOURCE_GATE_GUIDANCE_BLOCK


@pytest.mark.parametrize("explicit", [False, True])
def test_no_inputs_emit_no_block(explicit):
    kwargs = (
        dict(
            current_round=1,
            last_mode=None,
            trial_vram_budget_gb=None,
            formal_vram_budget_gb=None,
            trial_time_budget_minutes=None,
            formal_time_budget_minutes=None,
            last_vram_estimate_gb=None,
            last_time_estimate_minutes=None,
            last_batch_size=None,
        )
        if explicit
        else {}
    )
    assert _format_active_resource_budgets_block(**kwargs) == ""


@pytest.mark.parametrize("mode", ["trial", "formal", None, "unrecognized"])
def test_both_budgets_survive_previous_mode_and_unknown_stays_unknown(mode):
    text = _format_active_resource_budgets_block(
        current_round=2,
        last_mode=mode,
        trial_vram_budget_gb=4,
        formal_vram_budget_gb=24,
        trial_time_budget_minutes=10,
        formal_time_budget_minutes=30,
        last_vram_estimate_gb=5.2,
        last_time_estimate_minutes=8.4,
        last_batch_size=4,
    )
    assert "[CONFIGURED RESOURCE BUDGETS — planning round 2]" in text
    assert "Trial: VRAM 4 GB; time 10 min" in text
    assert "Formal: VRAM 24 GB; time 30 min" in text
    prior = mode if mode in ("trial", "formal") else "unknown"
    assert f"[PRIOR ATTEMPT EVIDENCE — mode={prior}]" in text
    assert "VRAM estimate: 5.2 GB" in text
    assert "Time estimate: 8.4 min" in text
    assert "Prior batch_size: 4" in text
    assert "ACTIVE" not in text
    assert "factor" not in text


@pytest.mark.parametrize("axis", ["vram", "time"])
def test_missing_budget_does_not_hide_evidence_or_claim_all_gates_disabled(axis):
    kwargs = {"trial_time_budget_minutes": 20} if axis == "vram" else {"trial_vram_budget_gb": 4}
    text = _format_active_resource_budgets_block(
        **kwargs,
        last_mode="trial",
        last_vram_estimate_gb=5,
        last_time_estimate_minutes=8,
    )
    assert "VRAM estimate: 5 GB" in text
    assert "Time estimate: 8 min" in text
    assert "not supplied" in text
    assert "gate disabled" not in text


def test_first_round_with_only_formal_budget_does_not_assume_trial():
    text = _format_active_resource_budgets_block(current_round=1, formal_time_budget_minutes=30)
    assert "Formal: VRAM not supplied; time 30 min" in text
    assert "PRIOR ATTEMPT EVIDENCE — mode=unknown" in text
    assert "VRAM estimate: not supplied" in text
    assert "Time estimate: not supplied" in text
    assert "Prior batch_size: unknown" in text


def test_evidence_without_budgets_is_still_visible():
    text = _format_active_resource_budgets_block(last_vram_estimate_gb=1e-8, last_batch_size=8)
    assert "VRAM estimate: 1e-08 GB" in text
    assert "Prior batch_size: 8" in text
    assert "not supplied" in text


def test_real_planner_prompt_preserves_both_modes_and_block_order():
    prompt = get_planner_user_prompt(
        memory_history=[],
        current_round=2,
        max_rounds=2,
        trial_time_budget_minutes=10,
        formal_time_budget_minutes=30,
        last_mode="trial",
        last_time_estimate_minutes=2,
        last_batch_size=16,
    )
    assert "Trial: VRAM not supplied; time 10 min" in prompt
    assert "Formal: VRAM not supplied; time 30 min" in prompt
    assert "PRIOR ATTEMPT EVIDENCE — mode=trial" in prompt
    assert "Prior batch_size: 16" in prompt
    assert prompt.index("[CONFIGURED RESOURCE") < prompt.index("[RESOURCE GATE")
    assert prompt.index("[RESOURCE GATE") < prompt.index("### INSTRUCTIONS")


def test_real_planner_without_resource_information_omits_blocks():
    prompt = get_planner_user_prompt(memory_history=[])
    assert "[CONFIGURED RESOURCE" not in prompt
    assert "[PRIOR ATTEMPT EVIDENCE" not in prompt
    assert "[RESOURCE GATE" not in prompt
