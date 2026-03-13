"""
Tier 2 integration test: result_interpretation_agent → ml_model_proposal_agent.

Exercises the full edge:
  1. Run result_interpretation_agent with synthetic records (real API)
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

from agent.schemas.interpretation import InterpretationInput, SummaryGroup
from agent.schemas.proposal import ProposalOutput
from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.result_interpretation_agent import ResultInterpretationAgent
from nodes.ml_model_proposal_agent import MLModelProposalAgent

# Reuse the synthetic records defined in the node integration test
from tests.integration.nodes.test_result_interpretation_agent import PUNET_RECORDS, FCNET_RECORDS

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
    """Run the interpretation agent over punet + fcnet synthetic records."""
    inp = InterpretationInput(
        summaries=[
            SummaryGroup(model_type="punet", run_name="v1", records=PUNET_RECORDS),
            SummaryGroup(model_type="fcnet", run_name="v1", records=FCNET_RECORDS),
        ],
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
