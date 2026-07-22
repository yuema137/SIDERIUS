"""Cold-start prompt behavior + interpretation node cold branch. No LLM, no GPU.

Asserts the cold-start banner states 'no prior experimental evidence', frames
registries as available options, never claims false history, and is empty (so
seeded prompts stay byte-identical) when cold_start is False. Also asserts the
interpretation node's cold branch is deterministic and makes no LLM call.
"""

from unittest.mock import MagicMock

from agent.schemas.interpretation import InterpretationInput
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import _render_cold_start_block
from nodes.result_interpretation_agent.result_interpretation_agent import (
    ResultInterpretationAgent,
)

# Phrases that would falsely imply prior experiments occurred.
_FORBIDDEN = ["no valid candidate", "previous best", "prior collapse", "previous failed"]


class TestColdStartBlock:
    def test_empty_when_not_cold_start(self):
        # Seeded backward-compat: zero injection into the proposer prompt.
        assert _render_cold_start_block(False) == ""

    def test_states_no_prior_evidence_when_cold(self):
        b = _render_cold_start_block(True).lower()
        assert "cold start" in b
        assert "no prior experimental" in b

    def test_registries_framed_as_options_not_results(self):
        b = _render_cold_start_block(True).lower()
        assert "available options" in b
        assert "not past results" in b

    def test_no_false_history_claims(self):
        b = _render_cold_start_block(True).lower()
        for phrase in _FORBIDDEN:
            assert phrase not in b


class TestInterpretationColdBranch:
    def _agent(self):
        bridge = MagicMock()
        bridge.generate.side_effect = AssertionError("LLM must not be called on cold start")
        bridge.generate_text.side_effect = AssertionError("LLM must not be called on cold start")
        agent = ResultInterpretationAgent(bridge_factory=lambda **kw: bridge)
        return agent, bridge

    def test_cold_start_returns_deterministic_output_no_llm(self):
        agent, bridge = self._agent()
        out = agent.run(InterpretationInput(summaries=[], cold_start=True))
        assert out.cold_start is True
        assert out.model_types == []
        assert out.total_experiments == 0
        assert out.best_denoising_score is None
        bridge.generate.assert_not_called()
        bridge.generate_text.assert_not_called()

    def test_cold_start_message_states_no_evidence(self):
        agent, _ = self._agent()
        out = agent.run(InterpretationInput(summaries=[], cold_start=True))
        thm = out.take_home_message.lower()
        assert "cold start" in thm
        assert "no prior experimental evidence" in thm
        for phrase in ["previous best", "no valid candidate"]:
            assert phrase not in thm
