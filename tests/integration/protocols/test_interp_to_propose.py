"""
Tier 2 integration test: result_interpretation_agent → ml_model_proposal_agent.

Exercises the full edge:
  1. Run result_interpretation_agent with synthetic summaries (real API)
  2. Apply protocol local_full_context to produce ProposalInput
  3. Run ml_model_proposal_agent (real API — two LLM calls: reasoning + commit)
  4. Validate ProposalOutput

No GPU or real TIDMAD data required — both nodes are LLM-only.

Requires:
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)

Run with:
  uv run pytest -m real_run tests/integration/protocols/test_interp_to_propose.py -v -s

DO NOT run in CI.
"""
import os
import re
import pytest
from dotenv import load_dotenv

from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from agent.schemas.proposal import (
    ProposalOutput, ReasoningPipelineConfig, ReasoningStage,
)
from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.result_interpretation_agent import ResultInterpretationAgent
from nodes.ml_model_proposal_agent import MLModelProposalAgent

# Reuse the synthetic summaries defined in the node integration test
from tests.integration.nodes.test_result_interpretation_agent import (
    PUNET_SUMMARY, FCNET_SUMMARY,
    _SEED_WAVENET, _SEED_PUNET, _PREVIOUS_PROPOSAL_REFUTED,
)

load_dotenv()

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------

def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set — skipping real API test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_interpretation(provider: str, model_id: str, tmp_path) -> "InterpretationOutput":
    """Run the interpretation agent over punet + fcnet synthetic summaries."""
    inp = InterpretationInput(
        summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "interp_to_propose"},
        },
    )
    return ResultInterpretationAgent(provider=provider, model_id=model_id).run(inp)


def _assert_proposal_output(output: ProposalOutput, existing_types: list):
    assert isinstance(output, ProposalOutput)

    # model_name: non-empty, snake_case, not reusing an existing type
    assert len(output.model_name) > 0
    assert re.match(r'^[a-z][a-z0-9_]*$', output.model_name), (
        f"model_name '{output.model_name}' is not snake_case"
    )
    assert output.model_name not in existing_types, (
        f"model_name '{output.model_name}' reuses an existing model type"
    )

    # Substantive text fields
    assert len(output.model_description) > 20
    assert len(output.mathematical_definition) > 50
    assert len(output.motivation) > 20

    # expert_advice is a valid ExpertAdvice instance with non-empty guidance
    assert isinstance(output.expert_advice, ExpertAdvice)
    assert len(output.expert_advice.constraints) > 0, "expert_advice.constraints is empty"
    assert len(output.expert_advice.focus_areas) > 0, "expert_advice.focus_areas is empty"
    assert len(output.expert_advice.suggested_directions) > 0, (
        "expert_advice.suggested_directions is empty"
    )

    # baseline_config has all required keys
    assert "model_config" in output.baseline_config
    assert "train_config" in output.baseline_config
    assert "loss_config"  in output.baseline_config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInterpToProposalGemini:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_interp_to_proposal_full_chain(self, tmp_path):
        """
        Full edge: interpretation agent → local_full_context protocol → proposal agent.
        """
        provider  = "gemini"
        model_id  = "gemini-3.1-flash-lite-preview"
        storage   = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="interp_to_propose"),
        )

        # Step 1: run interpretation agent (real API)
        interp_output = _run_interpretation(provider, model_id, tmp_path)
        assert len(interp_output.key_findings) > 0
        assert len(interp_output.take_home_message) > 10

        # Step 2: apply protocol
        proposal_input = local_full_context(interp_output, storage)
        assert set(proposal_input.existing_model_types) == {"punet", "fcnet"}
        assert "take_home_message" in proposal_input.interpretation

        # Step 3: run proposal agent (real API — two LLM calls)
        output = MLModelProposalAgent(provider=provider, model_id=model_id).run(proposal_input)

        # Step 4: validate
        _assert_proposal_output(output, existing_types=["punet", "fcnet"])
        assert (tmp_path / "proposal_interp_to_propose.json").exists()

        print(f"\n  take_home_message : {interp_output.take_home_message}")
        print(f"  proposed model    : {output.model_name}")
        print(f"  motivation        : {output.motivation[:200]}...")
        print(f"  math_definition   : {output.mathematical_definition[:300]}...")
        print(f"  constraints       : {output.expert_advice.constraints}")


class TestInterpToProposalOpenAI:

    def setup_method(self):
        _skip_if_no_key("openai")

    def test_interp_to_proposal_full_chain(self, tmp_path):
        """
        Full edge via OpenAI: interpretation agent → local_full_context → proposal agent.
        """
        provider  = "openai"
        model_id  = "gpt-4o-mini"
        storage   = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="interp_to_propose"),
        )

        interp_output = _run_interpretation(provider, model_id, tmp_path)
        assert len(interp_output.take_home_message) > 10

        proposal_input = local_full_context(interp_output, storage)
        output = MLModelProposalAgent(provider=provider, model_id=model_id).run(proposal_input)

        _assert_proposal_output(output, existing_types=["punet", "fcnet"])
        assert (tmp_path / "proposal_interp_to_propose.json").exists()

        print(f"\n  proposed model : {output.model_name}")
        print(f"  motivation     : {output.motivation[:200]}...")


# ---------------------------------------------------------------------------
# F.5 — Dual-mode Tier 2 test: discoveries reach the proposer prompt
# ---------------------------------------------------------------------------

# Default pipeline config matching the workflow (2 stages + final proposing call)
_PIPELINE_CFG = ReasoningPipelineConfig(stages=[
    ReasoningStage(name="comparison",      system_prompt_key="COMPARATIVE_ANALYSIS"),
    ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
])


@pytest.mark.dual_mode
def test_interp_to_propose_feedback_loop(tmp_path, request):
    """F.5 — Tier 2 dual-mode test: a REFUTED discovery from interpretation
    reaches the proposer's LLM prompt end-to-end.

    Chain:
      ResultInterpretationAgent.run(input with previous_proposal)
        → local_full_context (protocol) → ProposalInput with vocab containing discovery
          → MLModelProposalAgent.run() → proposer prompt contains 'REFUTED'

    Pseudo mode (default): both agents use RecordingLLMBridge. No API calls.
    Real mode (--real-api-call): uses real Gemini API. Skips if key not set.
    """
    is_real = request.config.getoption("--real-api-call")

    if is_real:
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY not set")

    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="feedback_chain"),
    )

    # Proposed model summary with a bad score → triggers REFUTED outcome
    proposed_summary = ModelRunSummary(
        model_type="attn_wavenet",
        run_name="adaptive_v1",
        status="completed",
        completed_rounds=3,
        best_denoising_score=-1.509,
        worst_denoising_score=-2.509,
        best_config={"model_config": {"attn_heads": 4},
                     "train_config": {"lr": 1e-4},
                     "loss_config": {"loss_type": "focal"}},
        round_scores=[-2.509, -2.0, -1.509],
        round_conclusions=["unstable", "partial recovery", "best achieved"],
        model_description="Wavenet with multi-head self-attention at the bottleneck.",
    )

    interp_inp = InterpretationInput(
        summaries=[_SEED_WAVENET, _SEED_PUNET, proposed_summary],
        previous_proposal=_PREVIOUS_PROPOSAL_REFUTED,
        runtime_vocab=[],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "feedback_chain"},
        },
    )

    if is_real:
        interp_agent  = ResultInterpretationAgent(provider="gemini",
                                                   model_id="gemini-3.1-flash-lite-preview")
        propose_agent = MLModelProposalAgent(provider="gemini",
                                             model_id="gemini-3.1-flash-lite-preview")
    else:
        from tests.helpers.recording_llm_bridge import RecordingLLMBridge
        interp_bridge  = RecordingLLMBridge.for_agent("result_interpretation_agent")
        propose_bridge = RecordingLLMBridge.for_agent("ml_model_proposal_agent")
        interp_agent  = ResultInterpretationAgent(bridge_factory=lambda **kw: interp_bridge)
        propose_agent = MLModelProposalAgent(bridge_factory=lambda **kw: propose_bridge)

    # Step 1: run interpretation — produces REFUTED discovery in runtime_vocab
    interp_output = interp_agent.run(interp_inp)
    assert interp_output.prediction_evaluation is not None
    assert interp_output.prediction_evaluation["outcome"] == "refuted"
    assert len(interp_output.runtime_vocab) >= 1

    # Step 2: apply protocol — runtime_vocab (with discovery) flows to vocab_seed
    proposal_input = local_full_context(
        interp_output, storage, reasoning_pipeline=_PIPELINE_CFG,
    )
    assert proposal_input.vocab_seed, "vocab_seed is empty — discovery not passed to proposer"

    # Confirm discovery is in vocab_seed
    discovery_in_seed = any(
        (v.get("kind") if isinstance(v, dict) else v.kind) == "discovery"
        for v in proposal_input.vocab_seed
    )
    assert discovery_in_seed, "No discovery entry in proposal_input.vocab_seed"

    # Step 3: run proposal agent
    propose_output = propose_agent.run(proposal_input)
    assert isinstance(propose_output, ProposalOutput)

    # Step 4 (pseudo mode only): assert "REFUTED" appears in a generate() user prompt
    if not is_real:
        generate_calls = [(call[1], call[2]) for call in propose_bridge.calls
                          if call[0] == "generate"]
        user_prompts = [user for _, user in generate_calls]
        discovery_prompt = next((p for p in user_prompts if "Discoveries" in p), None)
        assert discovery_prompt is not None, (
            "No generate() call contained 'Discoveries' — "
            "vocab discovery not rendered in proposer prompt"
        )
        assert "REFUTED" in discovery_prompt, (
            "REFUTED discovery text not present in proposer prompt — "
            "feedback loop broken end-to-end"
        )
        print(f"\n  [pseudo] REFUTED discovery confirmed in proposer prompt ✓")
        print(f"  [pseudo] vocab_seed entries: {len(proposal_input.vocab_seed)}")
        print(f"  [pseudo] proposed model: {propose_output.model_name}")
