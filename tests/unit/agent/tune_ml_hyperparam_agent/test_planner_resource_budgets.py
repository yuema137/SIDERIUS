"""
Phase K (K.6) — planner-prompt resource blocks.

Covers two helpers in ``agent/prompts.py``:

  * ``_format_active_resource_budgets_block`` — per-round dynamic block that
    renders the budgets, the most recent prior estimate, the resulting
    factor, and the current batch_size. Edge cases: budget None, estimate
    None, both None.
  * ``RESOURCE_GATE_GUIDANCE_BLOCK`` — static guidance text appended near
    the [ACTIVE RESOURCE BUDGETS] block. Verbatim text from
    docs/resource_estimator_implement.md §10.3.

Plus integration: ``get_planner_user_prompt`` injects both blocks together
when budgets/estimates are present, and omits both when neither is set.
The PLANNER_PROMPT system text no longer carries the abstract
"GPU MEMORY RULES" section (replaced by §10.11's two new blocks).

See docs/resource_estimator_implement.md §10.3 / §10.11.
"""

from agent.prompts import (
    PLANNER_PROMPT,
    RESOURCE_GATE_GUIDANCE_BLOCK,
    _format_active_resource_budgets_block,
    get_planner_user_prompt,
)

# ---------------------------------------------------------------------------
# PLANNER_PROMPT — the abstract GPU MEMORY RULES section is gone (K.6 §10.11)
# ---------------------------------------------------------------------------


class TestPlannerSystemPromptCleanup:
    def test_gpu_memory_rules_section_removed(self):
        """K.6: the abstract 'GPU MEMORY RULES' header was replaced by the
        per-round numeric block + static guidance. Confirm it no longer
        appears in the system prompt so the LLM is not told two stories."""
        assert "GPU MEMORY RULES" not in PLANNER_PROMPT


# ---------------------------------------------------------------------------
# RESOURCE_GATE_GUIDANCE_BLOCK — static text, verbatim from §10.3
# ---------------------------------------------------------------------------


class TestStaticGuidanceBlock:
    def test_header_present(self):
        assert "[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]" in RESOURCE_GATE_GUIDANCE_BLOCK

    def test_lever_decision_tree_phrases_present(self):
        """Spot-check the load-bearing phrases. Don't assert the whole
        body byte-for-byte (formatting drift would create noisy diffs);
        instead assert the decision-tree language survives."""
        text = RESOURCE_GATE_GUIDANCE_BLOCK
        assert "If both factors are <= 1: continue" in text
        assert "Lowering batch_size reduces vram_factor" in text
        assert "Raising batch_size does the opposite" in text
        assert "reduce model depth/width" in text
        assert "do NOT change segmentation_size" in text
        assert "frequency-resolution physics" in text


# ---------------------------------------------------------------------------
# _format_active_resource_budgets_block — empty when nothing to show
# ---------------------------------------------------------------------------


class TestActiveBudgetsBlockEmpty:
    def test_empty_when_no_budgets_and_no_estimates(self):
        out = _format_active_resource_budgets_block()
        assert out == ""

    def test_empty_when_all_args_explicit_none(self):
        out = _format_active_resource_budgets_block(
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
        assert out == ""


# ---------------------------------------------------------------------------
# _format_active_resource_budgets_block — full render with both axes
# ---------------------------------------------------------------------------


class TestActiveBudgetsBlockFull:
    def test_trial_mode_full_render_matches_spec_example(self):
        """Mirror the §10.3 example: round 3, trial mode, VRAM over budget,
        Time under budget, batch_size 4."""
        out = _format_active_resource_budgets_block(
            current_round=3,
            last_mode="trial",
            trial_vram_budget_gb=4.0,
            formal_vram_budget_gb=8.0,
            trial_time_budget_minutes=20.0,
            formal_time_budget_minutes=240.0,
            last_vram_estimate_gb=5.20,
            last_time_estimate_minutes=8.40,
            last_batch_size=4,
        )
        assert "[ACTIVE RESOURCE BUDGETS — round 3, mode=trial]" in out
        assert "estimate 5.20 GB" in out
        assert "budget 4.00 GB" in out
        assert "factor 1.30" in out
        assert "(over)" in out
        assert "estimate 8.40 min" in out
        assert "budget 20.0 min" in out
        assert "factor 0.42" in out
        assert "(under)" in out
        assert "Current batch_size: 4" in out

    def test_formal_mode_picks_formal_budgets(self):
        """When last_mode is 'formal', the active-mode budgets must come
        from the formal_* fields, not trial_*."""
        out = _format_active_resource_budgets_block(
            current_round=12,
            last_mode="formal",
            trial_vram_budget_gb=4.0,
            formal_vram_budget_gb=24.0,
            trial_time_budget_minutes=20.0,
            formal_time_budget_minutes=240.0,
            last_vram_estimate_gb=18.0,
            last_time_estimate_minutes=120.0,
            last_batch_size=8,
        )
        assert "mode=formal" in out
        # Active budget on each axis must be the formal one
        assert "budget 24.00 GB" in out
        assert "budget 240.0 min" in out
        # Trial budget values must NOT appear in either axis line
        assert "budget 4.00 GB" not in out
        assert "budget 20.0 min" not in out


# ---------------------------------------------------------------------------
# _format_active_resource_budgets_block — disabled-axis handling
# ---------------------------------------------------------------------------


class TestActiveBudgetsBlockDisabledAxis:
    def test_vram_budget_none_renders_disabled_line_no_factor(self):
        """When the active-mode VRAM budget is None, the VRAM line says
        '(no budget — gate disabled)' and no factor is shown for that
        axis. The Time line still renders normally."""
        out = _format_active_resource_budgets_block(
            current_round=2,
            last_mode="trial",
            trial_vram_budget_gb=None,
            formal_vram_budget_gb=None,
            trial_time_budget_minutes=20.0,
            formal_time_budget_minutes=240.0,
            last_vram_estimate_gb=5.0,  # ignored — no budget to compare against
            last_time_estimate_minutes=8.0,
            last_batch_size=4,
        )
        assert "VRAM:  (no budget — gate disabled)" in out
        # No VRAM factor line for the disabled axis
        assert "VRAM" in out
        # Time line still renders with factor
        assert "estimate 8.00 min" in out
        assert "factor 0.40" in out

    def test_time_budget_none_renders_disabled_line_no_factor(self):
        out = _format_active_resource_budgets_block(
            current_round=2,
            last_mode="trial",
            trial_vram_budget_gb=4.0,
            formal_vram_budget_gb=8.0,
            trial_time_budget_minutes=None,
            formal_time_budget_minutes=None,
            last_vram_estimate_gb=2.0,
            last_time_estimate_minutes=8.0,
            last_batch_size=4,
        )
        assert "Time:  (no budget — gate disabled)" in out
        assert "estimate 2.00 GB" in out
        assert "factor 0.50" in out


# ---------------------------------------------------------------------------
# _format_active_resource_budgets_block — no prior estimate handling
# ---------------------------------------------------------------------------


class TestActiveBudgetsBlockNoPriorEstimate:
    def test_round_1_no_prior_estimate_renders_budget_only(self):
        """Round 1 before any pre-flight has run: budgets are known, but
        last_*_estimate / last_batch_size / last_mode are all None.
        Block must render budgets + '(no prior estimate)' lines and not
        crash on factor division."""
        out = _format_active_resource_budgets_block(
            current_round=1,
            last_mode=None,
            trial_vram_budget_gb=4.0,
            formal_vram_budget_gb=8.0,
            trial_time_budget_minutes=20.0,
            formal_time_budget_minutes=240.0,
            last_vram_estimate_gb=None,
            last_time_estimate_minutes=None,
            last_batch_size=None,
        )
        # Falls back to trial mode for the active-mode label
        assert "round 1, mode=trial" in out
        assert "(no prior estimate)" in out
        assert "budget 4.00 GB" in out
        assert "budget 20.0 min" in out
        assert "Current batch_size: (not yet set)" in out
        # No factor lines when there's no estimate to compare
        assert "factor" not in out


# ---------------------------------------------------------------------------
# get_planner_user_prompt integration
# ---------------------------------------------------------------------------


class TestPlannerPromptIntegration:
    def test_blocks_absent_when_no_budgets_or_estimates(self):
        """No regression on existing callers — the prompt does NOT include
        the [ACTIVE RESOURCE BUDGETS] block when no resource kwargs are
        supplied, and the static guidance is also absent (it's only
        rendered alongside the dynamic block)."""
        prompt = get_planner_user_prompt(memory_history=[])
        assert "[ACTIVE RESOURCE BUDGETS" not in prompt
        assert "[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]" not in prompt

    def test_both_blocks_rendered_when_budgets_set(self):
        prompt = get_planner_user_prompt(
            memory_history=[],
            current_round=2,
            max_rounds=10,
            trial_vram_budget_gb=4.0,
            trial_time_budget_minutes=20.0,
            last_vram_estimate_gb=5.20,
            last_time_estimate_minutes=8.40,
            last_batch_size=4,
            last_mode="trial",
        )
        # Dynamic block
        assert "[ACTIVE RESOURCE BUDGETS — round 2, mode=trial]" in prompt
        assert "estimate 5.20 GB" in prompt
        assert "Current batch_size: 4" in prompt
        # Static guidance follows
        assert "[RESOURCE GATE — RESOLVING OVER-BUDGET CONFIGS]" in prompt
        assert "Lowering batch_size reduces vram_factor" in prompt
        # Order: dynamic block precedes static guidance
        assert prompt.index("[ACTIVE RESOURCE BUDGETS") < prompt.index("[RESOURCE GATE")

    def test_rendered_before_instructions(self):
        """Both K.6 blocks must appear in the user prompt before the final
        ### INSTRUCTIONS section so the LLM reads them with the rest of
        the per-round context."""
        prompt = get_planner_user_prompt(
            memory_history=[],
            current_round=1,
            max_rounds=10,
            trial_vram_budget_gb=4.0,
            trial_time_budget_minutes=20.0,
        )
        assert prompt.index("[ACTIVE RESOURCE BUDGETS") < prompt.index("### INSTRUCTIONS")
        assert prompt.index("[RESOURCE GATE") < prompt.index("### INSTRUCTIONS")
