"""
Phase K (K.7.6) — proposer prompt: [PRIOR ITERATION GATE EXHAUSTION] block.

Covers the helper that renders the §10.13.5 block from a populated
``GateExhaustionInfo`` and the two injection points that splice it into
the proposer's user/system prompts:

  * Helper truth-table: None → "" (no empty section), populated → block
    contains every documented field + the verdict text.
  * Legacy mode: ``_build_reasoning_prompt`` includes the block when
    ``inp.prior_iteration_gate_exhaustion`` is set; omits it when None.
  * Pipeline mode: ``template_vars`` carries the rendered block under
    ``prior_iteration_gate_exhaustion_block``; the proposing-stage
    template substitutes the placeholder so the LLM sees the block in
    its system prompt; placeholder is also collapsed (empty string) when
    the field is None.

See docs/resource_estimator_implement.md §10.13.5.
"""
import pytest
from unittest.mock import MagicMock

from agent.prompt_templates.proposal import load_stage_prompt
from agent.schemas.hyperparam_tuning import GateExhaustionInfo
from agent.schemas.proposal import (
    ProposalInput,
    ReasoningPipelineConfig,
    ReasoningStage,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_model_proposal_agent import (
    MLModelProposalAgent,
    _build_reasoning_prompt,
    _format_prior_iteration_gate_exhaustion_block,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _gate_exhaustion(**overrides) -> GateExhaustionInfo:
    """Concise factory for a fully-populated GateExhaustionInfo."""
    base = dict(
        total_attempts=9,
        vram_gated_attempts=7,
        time_gated_attempts=2,
        other_failure_attempts=0,
        active_mode="trial",
        vram_budget_gb=4.0,
        time_budget_minutes=20.0,
        baseline_vram_estimate_gb=6.4,
        baseline_vram_factor=1.6,
        baseline_time_estimate_minutes=8.0,
        baseline_time_factor=0.4,
        worst_vram_factor=2.0,
        worst_time_factor=0.6,
        summary_message="All 9 attempts were rejected by the resource gate.",
    )
    base.update(overrides)
    return GateExhaustionInfo(**base)


def _minimal_interp() -> dict:
    return {
        "model_types": ["wavenet"],
        "total_experiments": 5,
        "best_denoising_score": 5.5,
        "worst_denoising_score": 1.0,
        "key_findings": [],
        "bottlenecks": [],
        "take_home_message": "wavenet dominates",
    }


def _proposal_input(tmp_path, gate_info=None) -> ProposalInput:
    return ProposalInput(
        interpretation=_minimal_interp(),
        existing_model_types=["wavenet"],
        recent_gate_exhaustions=[gate_info] if gate_info is not None else [],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


def _pipeline_input(tmp_path, gate_info=None) -> ProposalInput:
    return ProposalInput(
        interpretation=_minimal_interp(),
        existing_model_types=["wavenet"],
        recent_gate_exhaustions=[gate_info] if gate_info is not None else [],
        reasoning_pipeline=ReasoningPipelineConfig(
            exploration_mode="exploit",
            stages=[
                ReasoningStage(name="comparison",
                               system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning",
                               system_prompt_key="CAUSAL_REASONING"),
            ],
        ),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


# ---------------------------------------------------------------------------
# Helper truth-table
# ---------------------------------------------------------------------------

class TestFormatPriorIterationGateExhaustionBlock:

    def test_none_returns_empty_string(self):
        """No prior gate-exhaustion → empty string so callers can splice
        unconditionally without producing a stray header."""
        assert _format_prior_iteration_gate_exhaustion_block(None) == ""

    def test_header_present_when_populated(self):
        block = _format_prior_iteration_gate_exhaustion_block(_gate_exhaustion())
        assert "[PRIOR ITERATION GATE EXHAUSTION]" in block

    def test_summary_message_rendered(self):
        info = _gate_exhaustion(
            summary_message="All 9 attempts hit the VRAM gate.",
        )
        block = _format_prior_iteration_gate_exhaustion_block(info)
        assert "All 9 attempts hit the VRAM gate." in block

    def test_active_mode_rendered(self):
        block = _format_prior_iteration_gate_exhaustion_block(
            _gate_exhaustion(active_mode="formal")
        )
        assert "Mode active:       formal" in block

    def test_budgets_rendered_with_units(self):
        block = _format_prior_iteration_gate_exhaustion_block(
            _gate_exhaustion(vram_budget_gb=8.0, time_budget_minutes=240.0)
        )
        assert "VRAM budget:       8.0 GB" in block
        assert "Time budget:       240.0 min" in block

    def test_baseline_factors_use_two_decimals_and_x_suffix(self):
        block = _format_prior_iteration_gate_exhaustion_block(
            _gate_exhaustion(baseline_vram_factor=1.6, baseline_time_factor=0.4)
        )
        # Two-decimal × suffix matches the K.6 [ACTIVE RESOURCE BUDGETS] style
        assert "VRAM 1.60×" in block
        assert "Time 0.40×" in block

    def test_worst_factors_rendered(self):
        block = _format_prior_iteration_gate_exhaustion_block(
            _gate_exhaustion(worst_vram_factor=2.5, worst_time_factor=1.1)
        )
        assert "VRAM 2.50×" in block
        assert "Time 1.10×" in block

    def test_attempt_counts_rendered(self):
        info = _gate_exhaustion(
            total_attempts=12,
            vram_gated_attempts=8,
            time_gated_attempts=3,
            other_failure_attempts=1,
        )
        block = _format_prior_iteration_gate_exhaustion_block(info)
        assert "12 total" in block
        assert "8 VRAM-gated" in block
        assert "3 time-gated" in block
        assert "1 other failures" in block

    def test_verdict_text_present(self):
        """The fixed verdict paragraph is the load-bearing instruction —
        spot-check the phrases that tell the LLM what lever to pull."""
        block = _format_prior_iteration_gate_exhaustion_block(_gate_exhaustion())
        assert "propose an architecture that fits the budgets" in block
        assert "Reduce parameter count and/or layer" in block

    def test_disabled_axis_factors_render_as_na(self):
        """When an axis was disabled (budget None) or no record carried
        the estimate, factor fields are None and must render as ``n/a``
        rather than crashing or showing ``None``."""
        info = _gate_exhaustion(
            vram_budget_gb=None,
            baseline_vram_factor=None,
            worst_vram_factor=None,
        )
        block = _format_prior_iteration_gate_exhaustion_block(info)
        assert "VRAM budget:       n/a" in block
        assert "VRAM n/a" in block
        # Time axis is untouched and still renders normally
        assert "Time 0.40×" in block

    def test_both_budgets_none_yields_na(self):
        """Edge case: caller never supplied budgets — shouldn't crash."""
        info = _gate_exhaustion(
            vram_budget_gb=None,
            time_budget_minutes=None,
            baseline_vram_factor=None,
            baseline_time_factor=None,
            worst_vram_factor=None,
            worst_time_factor=None,
        )
        block = _format_prior_iteration_gate_exhaustion_block(info)
        assert "VRAM budget:       n/a" in block
        assert "Time budget:       n/a" in block
        # Counts still render numerically — they don't depend on budgets
        assert "9 total" in block


# ---------------------------------------------------------------------------
# Legacy mode — _build_reasoning_prompt
# ---------------------------------------------------------------------------

class TestLegacyReasoningPromptInjection:

    def test_block_absent_when_field_is_none(self, tmp_path):
        """Default ProposalInput → field is None → header must not appear
        anywhere in the legacy reasoning prompt."""
        inp = _proposal_input(tmp_path, gate_info=None)
        prompt = _build_reasoning_prompt(inp)
        assert "[PRIOR ITERATION GATE EXHAUSTION]" not in prompt

    def test_block_present_when_field_is_set(self, tmp_path):
        inp = _proposal_input(
            tmp_path,
            gate_info=_gate_exhaustion(
                summary_message="All attempts blew the VRAM ceiling.",
            ),
        )
        prompt = _build_reasoning_prompt(inp)
        assert "[PRIOR ITERATION GATE EXHAUSTION]" in prompt
        assert "All attempts blew the VRAM ceiling." in prompt

    def test_block_carries_resource_accounting(self, tmp_path):
        """End-to-end: every field the §10.13.5 template references must
        reach the legacy reasoning prompt verbatim."""
        inp = _proposal_input(
            tmp_path,
            gate_info=_gate_exhaustion(
                active_mode="trial",
                vram_budget_gb=4.0,
                time_budget_minutes=20.0,
                baseline_vram_factor=1.6,
                worst_vram_factor=2.0,
            ),
        )
        prompt = _build_reasoning_prompt(inp)
        assert "Mode active:       trial" in prompt
        assert "VRAM budget:       4.0 GB" in prompt
        assert "Time budget:       20.0 min" in prompt
        assert "VRAM 1.60×" in prompt
        assert "VRAM 2.00×" in prompt


# ---------------------------------------------------------------------------
# Pipeline mode — proposing-stage template substitution
# ---------------------------------------------------------------------------

class TestPipelineProposingStageInjection:
    """The proposing-stage template (.md file) carries a
    ``{prior_iteration_gate_exhaustion_block}`` placeholder; the pipeline
    populates ``template_vars`` from the input field; ``load_stage_prompt``
    substitutes the placeholder. This test loads the template directly via
    ``load_stage_prompt`` to verify the round-trip without standing up the
    whole 3-stage pipeline."""

    def test_template_carries_placeholder(self):
        """Sanity: the .md file must contain the placeholder, otherwise
        the template_vars substitution is a no-op."""
        # Load with empty vars to expose the raw placeholder.
        prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode="exploit",
            template_vars=None,
        )
        assert "{prior_iteration_gate_exhaustion_block}" in prompt

    def test_placeholder_substitutes_to_block_when_set(self):
        block = _format_prior_iteration_gate_exhaustion_block(_gate_exhaustion())
        prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode="exploit",
            template_vars={
                "prior_iteration_gate_exhaustion_block": block,
                # Other proposing-stage placeholders need values too so the
                # final prompt has no stray ``{...}`` markers.
                "known_constraints_block": "",
                "existing_model_types": "wavenet",
            },
        )
        assert "{prior_iteration_gate_exhaustion_block}" not in prompt
        assert "[PRIOR ITERATION GATE EXHAUSTION]" in prompt
        assert "All 9 attempts were rejected by the resource gate." in prompt

    def test_placeholder_collapses_to_empty_when_field_is_none(self):
        """Field None → helper returns "" → placeholder substitutes to
        empty so the rendered prompt does not contain the header at all."""
        block = _format_prior_iteration_gate_exhaustion_block(None)
        assert block == ""
        prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode="exploit",
            template_vars={
                "prior_iteration_gate_exhaustion_block": block,
                "known_constraints_block": "",
                "existing_model_types": "wavenet",
            },
        )
        assert "{prior_iteration_gate_exhaustion_block}" not in prompt
        assert "[PRIOR ITERATION GATE EXHAUSTION]" not in prompt


class TestPipelineTemplateVarsCarryBlock:
    """Belt-and-braces: hook into ``_run_pipeline`` via a fake bridge and
    assert the rendered system prompt actually reaches the LLM with the
    block when the input field is set, and without it when None.

    Inspecting ``self.bridge.generate.call_args_list`` is the cleanest way
    to see the substituted system prompt, since the proposing call sits
    behind the comparison + reasoning calls."""

    _FAKE_COMPARISON = {
        "comparisons": [],
        "proposed_vocab_links": [],
        "proposed_vocab_candidates": [],
        "sota_model_type": "wavenet",
        "sota_score": 5.5,
        "sota_mechanism": "x",
    }
    _FAKE_REASONING = {
        "proposed_change": "x",
        "causal_hypothesis": "x",
        "falsifiable_prediction": {
            "metric": "denoising_score",
            "current_value": 5.5,
            "predicted_value": 6.5,
            "threshold_for_refutation": 5.0,
            "rationale": "x",
        },
        "predicted_failure_modes": [],
        "inherited_components": [],
        "proposed_vocab_candidates": [],
    }
    _FAKE_PROPOSING = {
        "model_name": "spectral_wavenet",
        "model_description": "x",
        "mathematical_definition": "x",
        "motivation": "x",
        "expert_advice": {
            "focus_areas": [], "constraints": ["VRAM<10", "params<50M"],
            "known_failures": [], "suggested_directions": [], "rationale": "x",
        },
        "baseline_config": {
            "model_config": {}, "train_config": {}, "loss_config": {},
        },
        "memo_consistency_notes": [],
    }

    def _agent(self):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            self._FAKE_COMPARISON,
            self._FAKE_REASONING,
            self._FAKE_PROPOSING,
        ]
        agent = MLModelProposalAgent(
            provider="gemini", model_id="test",
            bridge_factory=lambda **kw: bridge,
        )
        return agent, bridge

    def _proposing_system_prompt(self, bridge) -> str:
        """The proposing call is the 3rd ``bridge.generate`` invocation;
        the system prompt is the first positional arg."""
        return bridge.generate.call_args_list[2][0][0]

    def test_proposing_system_prompt_contains_block_when_set(self, tmp_path):
        agent, bridge = self._agent()
        inp = _pipeline_input(
            tmp_path,
            gate_info=_gate_exhaustion(
                summary_message="All attempts hit the VRAM gate.",
            ),
        )
        agent.run(inp)
        system_prompt = self._proposing_system_prompt(bridge)
        assert "[PRIOR ITERATION GATE EXHAUSTION]" in system_prompt
        assert "All attempts hit the VRAM gate." in system_prompt

    def test_proposing_system_prompt_omits_block_when_field_none(self, tmp_path):
        agent, bridge = self._agent()
        inp = _pipeline_input(tmp_path, gate_info=None)
        agent.run(inp)
        system_prompt = self._proposing_system_prompt(bridge)
        assert "[PRIOR ITERATION GATE EXHAUSTION]" not in system_prompt
        # And no stray placeholder text either
        assert "{prior_iteration_gate_exhaustion_block}" not in system_prompt


class TestDebugDumpProposingPrompt:
    """Phase K.8 instrumentation: when
    ``ProposalInput.debug_dump_proposing_prompt_path`` is set, the
    pipeline's proposing-stage system prompt is written to that path
    so smoke runs can audit it. None (default) → no file written."""

    def _agent(self):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            TestPipelineTemplateVarsCarryBlock._FAKE_COMPARISON,
            TestPipelineTemplateVarsCarryBlock._FAKE_REASONING,
            TestPipelineTemplateVarsCarryBlock._FAKE_PROPOSING,
        ]
        agent = MLModelProposalAgent(
            provider="gemini", model_id="test",
            bridge_factory=lambda **kw: bridge,
        )
        return agent, bridge

    def test_dump_path_set_writes_rendered_prompt(self, tmp_path):
        agent, _ = self._agent()
        dump_path = tmp_path / "debug" / "iter002_proposing.md"
        inp = _pipeline_input(
            tmp_path,
            gate_info=_gate_exhaustion(
                summary_message="All attempts hit the VRAM gate.",
            ),
        )
        inp.debug_dump_proposing_prompt_path = str(dump_path)
        agent.run(inp)
        assert dump_path.exists(), "dump file should be created"
        contents = dump_path.read_text()
        # The dumped file IS the rendered proposing-stage system prompt.
        assert "[PRIOR ITERATION GATE EXHAUSTION]" in contents
        assert "All attempts hit the VRAM gate." in contents

    def test_dump_path_none_writes_nothing(self, tmp_path):
        agent, _ = self._agent()
        inp = _pipeline_input(tmp_path, gate_info=None)
        # Field defaults to None — no dump file should appear under tmp_path.
        agent.run(inp)
        # Nothing under tmp_path/debug/ should exist.
        debug_dir = tmp_path / "debug"
        assert not debug_dir.exists(), (
            "no debug dir should be created when path is None"
        )
