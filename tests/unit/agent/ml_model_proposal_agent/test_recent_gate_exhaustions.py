"""
Phase N (§14.N.3-N.4) — proposer prompt: [RECENT GATE EXHAUSTIONS] block.

Aggregate-window successor to the K.7.6 singular block. Covers the helper
that renders the §14.N.3 block from a (possibly empty) list of up to
``GateExhaustionInfo`` entries, plus the two injection points that splice
the rendered block into the proposer's user/system prompts:

  * Helper truth-table: [] → "" (no empty section). 1/2/3-entry lists →
    block with header-arithmetic, per-entry ``iter N-k`` labels, rules
    between entries, and the "switch family" closing guidance.
  * Legacy mode: ``_build_reasoning_prompt`` includes the block when
    ``inp.recent_gate_exhaustions`` is non-empty; omits it when empty.
  * Pipeline mode: ``template_vars`` carries the rendered block under
    ``recent_gate_exhaustions_block``; the proposing-stage template
    substitutes the placeholder so the LLM sees the block in its system
    prompt; placeholder is collapsed to "" when the list is empty.

Field numeric-to-string rendering (``n/a`` for disabled axes, factor
two-decimal ``×`` suffix, etc.) is inherited from the K.7.6 helper and
not re-tested here — see §14.N.4.
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
    _format_recent_gate_exhaustions_block,
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


def _proposal_input(tmp_path, gate_infos=None) -> ProposalInput:
    return ProposalInput(
        interpretation=_minimal_interp(),
        existing_model_types=["wavenet"],
        recent_gate_exhaustions=list(gate_infos) if gate_infos else [],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


def _pipeline_input(tmp_path, gate_infos=None) -> ProposalInput:
    return ProposalInput(
        interpretation=_minimal_interp(),
        existing_model_types=["wavenet"],
        recent_gate_exhaustions=list(gate_infos) if gate_infos else [],
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
# Helper truth-table — §14.N.4: 0 / 1 / 2 / 3 entries
# ---------------------------------------------------------------------------

class TestFormatRecentGateExhaustionsBlock:

    def test_empty_list_returns_empty_string(self):
        """No gate-exhaustions → empty string so callers can splice
        unconditionally without producing a stray header."""
        assert _format_recent_gate_exhaustions_block([]) == ""

    def test_single_entry_header_is_singular(self):
        """1 entry → header reads '(last 1 iteration)', singular."""
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()])
        assert "[RECENT GATE EXHAUSTIONS (last 1 iteration)]" in block

    def test_single_entry_labelled_most_recent(self):
        """The newest entry is always tagged ``iter N-1 (most recent)``."""
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()])
        assert "iter N-1 (most recent):" in block

    def test_single_entry_has_no_rule_separator(self):
        """One entry → nothing to separate, so no horizontal rule."""
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()])
        assert "-" * 68 not in block

    def test_single_entry_carries_summary_message(self):
        info = _gate_exhaustion(summary_message="VRAM gate exhausted.")
        block = _format_recent_gate_exhaustions_block([info])
        assert "VRAM gate exhausted." in block

    def test_two_entries_header_is_plural(self):
        block = _format_recent_gate_exhaustions_block(
            [_gate_exhaustion(), _gate_exhaustion()]
        )
        assert "[RECENT GATE EXHAUSTIONS (last 2 iterations)]" in block

    def test_two_entries_labels_oldest_first(self):
        """For 2 entries: oldest → ``iter N-2``, newest → ``iter N-1``."""
        block = _format_recent_gate_exhaustions_block(
            [_gate_exhaustion(), _gate_exhaustion()]
        )
        assert "iter N-2:" in block
        assert "iter N-1 (most recent):" in block
        assert block.index("iter N-2:") < block.index("iter N-1 (most recent):")

    def test_two_entries_separated_by_one_rule(self):
        """Adjacent entries split by a 68-dash rule — 2 entries → 1 rule."""
        block = _format_recent_gate_exhaustions_block(
            [_gate_exhaustion(), _gate_exhaustion()]
        )
        assert block.count("-" * 68) == 1

    def test_two_entries_preserve_distinct_summaries(self):
        """Each entry's summary_message reaches the rendered block verbatim,
        oldest first."""
        older = _gate_exhaustion(summary_message="OLDER: VRAM gate hit.")
        newer = _gate_exhaustion(summary_message="NEWER: time gate hit.")
        block = _format_recent_gate_exhaustions_block([older, newer])
        assert "OLDER: VRAM gate hit." in block
        assert "NEWER: time gate hit." in block
        assert (
            block.index("OLDER: VRAM gate hit.")
            < block.index("NEWER: time gate hit.")
        )

    def test_three_entries_header_mentions_three(self):
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()] * 3)
        assert "[RECENT GATE EXHAUSTIONS (last 3 iterations)]" in block

    def test_three_entries_all_labels_present_in_order(self):
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()] * 3)
        assert "iter N-3:" in block
        assert "iter N-2:" in block
        assert "iter N-1 (most recent):" in block
        assert (
            block.index("iter N-3:")
            < block.index("iter N-2:")
            < block.index("iter N-1 (most recent):")
        )

    def test_three_entries_separated_by_two_rules(self):
        """N entries → (N-1) rules. 3 entries → 2 rules."""
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()] * 3)
        assert block.count("-" * 68) == 2

    def test_closing_guidance_present(self):
        """§14.N.3 load-bearing nudge: when the same family recurs, switch
        family rather than shrink. Spot-check the phrases that carry that."""
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()] * 2)
        assert "same architecture family or scale" in block
        assert "different family" in block


# ---------------------------------------------------------------------------
# Legacy mode — _build_reasoning_prompt
# ---------------------------------------------------------------------------

class TestLegacyReasoningPromptInjection:

    def test_block_absent_when_list_empty(self, tmp_path):
        """Default ProposalInput → empty list → header must not appear in
        the legacy reasoning prompt."""
        inp = _proposal_input(tmp_path, gate_infos=[])
        prompt = _build_reasoning_prompt(inp)
        assert "[RECENT GATE EXHAUSTIONS" not in prompt

    def test_block_present_when_list_populated(self, tmp_path):
        inp = _proposal_input(
            tmp_path,
            gate_infos=[
                _gate_exhaustion(summary_message="All attempts blew the VRAM ceiling.")
            ],
        )
        prompt = _build_reasoning_prompt(inp)
        assert "[RECENT GATE EXHAUSTIONS (last 1 iteration)]" in prompt
        assert "All attempts blew the VRAM ceiling." in prompt

    def test_block_carries_resource_accounting(self, tmp_path):
        """Every field the §14.N.3 template references must reach the
        legacy reasoning prompt verbatim."""
        inp = _proposal_input(
            tmp_path,
            gate_infos=[
                _gate_exhaustion(
                    active_mode="trial",
                    vram_budget_gb=4.0,
                    time_budget_minutes=20.0,
                    baseline_vram_factor=1.6,
                    worst_vram_factor=2.0,
                )
            ],
        )
        prompt = _build_reasoning_prompt(inp)
        assert "Mode active:       trial" in prompt
        assert "VRAM budget:       4.0 GB" in prompt
        assert "Time budget:       20.0 min" in prompt
        assert "VRAM 1.60×" in prompt
        assert "VRAM 2.00×" in prompt

    def test_multi_entry_ordering_preserved_in_legacy_prompt(self, tmp_path):
        """Two entries → both summary_messages reach the prompt, oldest
        first."""
        older = _gate_exhaustion(summary_message="OLD: VRAM gate hit.")
        newer = _gate_exhaustion(summary_message="NEW: time gate hit.")
        inp = _proposal_input(tmp_path, gate_infos=[older, newer])
        prompt = _build_reasoning_prompt(inp)
        assert "OLD: VRAM gate hit." in prompt
        assert "NEW: time gate hit." in prompt
        assert prompt.index("OLD:") < prompt.index("NEW:")


# ---------------------------------------------------------------------------
# Pipeline mode — proposing-stage template substitution
# ---------------------------------------------------------------------------

class TestPipelineProposingStageInjection:
    """The proposing-stage template (.md file) carries a
    ``{recent_gate_exhaustions_block}`` placeholder; the pipeline populates
    ``template_vars`` from the input list; ``load_stage_prompt`` substitutes
    the placeholder. This test loads the template directly via
    ``load_stage_prompt`` to verify the round-trip without standing up the
    whole 3-stage pipeline."""

    def test_template_carries_placeholder(self):
        """Sanity: the .md file must contain the placeholder, otherwise the
        template_vars substitution is a no-op."""
        prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode="exploit",
            template_vars=None,
        )
        assert "{recent_gate_exhaustions_block}" in prompt

    def test_placeholder_substitutes_to_block_when_populated(self):
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()])
        prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode="exploit",
            template_vars={
                "recent_gate_exhaustions_block": block,
                # Other proposing-stage placeholders need values too so the
                # final prompt has no stray ``{...}`` markers.
                "known_constraints_block": "",
                "existing_model_types": "wavenet",
            },
        )
        assert "{recent_gate_exhaustions_block}" not in prompt
        assert "[RECENT GATE EXHAUSTIONS" in prompt
        assert "All 9 attempts were rejected by the resource gate." in prompt

    def test_placeholder_collapses_to_empty_when_list_empty(self):
        """Empty list → helper returns "" → placeholder substitutes to
        empty so the rendered prompt does not contain the header at all."""
        block = _format_recent_gate_exhaustions_block([])
        assert block == ""
        prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode="exploit",
            template_vars={
                "recent_gate_exhaustions_block": block,
                "known_constraints_block": "",
                "existing_model_types": "wavenet",
            },
        )
        assert "{recent_gate_exhaustions_block}" not in prompt
        assert "[RECENT GATE EXHAUSTIONS" not in prompt


class TestPipelineTemplateVarsCarryBlock:
    """Belt-and-braces: hook into ``_run_pipeline`` via a fake bridge and
    assert the rendered system prompt actually reaches the LLM with the
    block when the input list is populated, and without it when empty.

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

    def test_proposing_system_prompt_contains_block_when_populated(self, tmp_path):
        agent, bridge = self._agent()
        inp = _pipeline_input(
            tmp_path,
            gate_infos=[
                _gate_exhaustion(summary_message="All attempts hit the VRAM gate.")
            ],
        )
        agent.run(inp)
        system_prompt = self._proposing_system_prompt(bridge)
        assert "[RECENT GATE EXHAUSTIONS" in system_prompt
        assert "All attempts hit the VRAM gate." in system_prompt

    def test_proposing_system_prompt_omits_block_when_list_empty(self, tmp_path):
        agent, bridge = self._agent()
        inp = _pipeline_input(tmp_path, gate_infos=[])
        agent.run(inp)
        system_prompt = self._proposing_system_prompt(bridge)
        assert "[RECENT GATE EXHAUSTIONS" not in system_prompt
        # No stray placeholder either
        assert "{recent_gate_exhaustions_block}" not in system_prompt

    def test_proposing_system_prompt_preserves_three_entry_order(self, tmp_path):
        """Three entries → all reach the system prompt oldest-first, with
        the pluralised header."""
        agent, bridge = self._agent()
        older = _gate_exhaustion(summary_message="OLD: VRAM hit.")
        middle = _gate_exhaustion(summary_message="MID: time hit.")
        newer = _gate_exhaustion(summary_message="NEW: both hit.")
        inp = _pipeline_input(tmp_path, gate_infos=[older, middle, newer])
        agent.run(inp)
        system_prompt = self._proposing_system_prompt(bridge)
        assert "[RECENT GATE EXHAUSTIONS (last 3 iterations)]" in system_prompt
        assert system_prompt.index("OLD:") < system_prompt.index("MID:")
        assert system_prompt.index("MID:") < system_prompt.index("NEW:")


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
            gate_infos=[
                _gate_exhaustion(summary_message="All attempts hit the VRAM gate.")
            ],
        )
        inp.debug_dump_proposing_prompt_path = str(dump_path)
        agent.run(inp)
        assert dump_path.exists(), "dump file should be created"
        contents = dump_path.read_text()
        assert "[RECENT GATE EXHAUSTIONS" in contents
        assert "All attempts hit the VRAM gate." in contents

    def test_dump_path_none_writes_nothing(self, tmp_path):
        agent, _ = self._agent()
        inp = _pipeline_input(tmp_path, gate_infos=[])
        agent.run(inp)
        debug_dir = tmp_path / "debug"
        assert not debug_dir.exists(), (
            "no debug dir should be created when path is None"
        )
