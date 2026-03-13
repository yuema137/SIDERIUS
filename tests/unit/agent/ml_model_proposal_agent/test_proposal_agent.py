"""
Tests for nodes/ml_model_proposal_agent.py

LLM calls are mocked — these tests validate:
  - Both LLM calls are made: generate_text (reasoning) then generate (commit)
  - Reasoning text is injected into the commit prompt
  - LLM response is merged correctly into ProposalOutput
  - expert_advice dict is coerced to ExpertAdvice instance
  - Output validates against ProposalOutput schema
  - Output file written to the correct path with correct content
  - Duplicate model_name raises ValueError
  - Empty existing_model_types does not block a valid name
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call

from agent.schemas.proposal import ProposalInput, ProposalOutput
from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_model_proposal_agent import MLModelProposalAgent


# ---------------------------------------------------------------------------
# Fake LLM responses
# ---------------------------------------------------------------------------

FAKE_REASONING = (
    "The bottleneck is the limited receptive field of the current U-Net at the "
    "sequence level. A multi-scale attention mechanism would address this by allowing "
    "the model to attend to both local and global patterns simultaneously..."
)

FAKE_COMMIT_RESPONSE = {
    "model_name": "attn_unet",
    "model_description": "A U-Net variant augmented with multi-head self-attention at the bottleneck.",
    "mathematical_definition": (
        "1. Embedding: nn.Embedding(256, 32) → [B, T, 32], permuted to [B, 32, T]. "
        "2. Encoder: 3 down-blocks, each Conv1d(C, 2C, k=9, stride=2) + GroupNorm + GELU. "
        "3. Bottleneck: MultiheadAttention(embed_dim=256, num_heads=4) over T dimension. "
        "4. Decoder: 3 up-blocks with bilinear upsampling + skip connections from encoder. "
        "5. Head: Conv1d(32, 256, k=1) → [B, 256, T] float32."
    ),
    "motivation": (
        "The take-home message identified that the architecture capacity ceiling prevents "
        "further improvement. Self-attention at the bottleneck addresses the receptive "
        "field bottleneck without significantly increasing parameter count."
    ),
    "expert_advice": {
        "focus_areas": ["tune attention heads before depth", "try focal gamma 2-4"],
        "constraints": ["VRAM < 10 GB", "params < 50M"],
        "known_failures": ["large batch_size with long sequences"],
        "suggested_directions": ["start with depth=2, nhead=4, lr=1e-4"],
        "rationale": "Attention bottleneck is sensitive to learning rate; start conservative.",
    },
    "baseline_config": {
        "model_config": {"depth": 2, "multi": 32, "nhead": 4},
        "train_config": {
            "lr": 1e-4, "epochs": 10, "batch_size": 1,
            "optimizer_type": "adamw", "weight_decay": 1e-5, "device": "cuda",
        },
        "loss_config": {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0, "reduction": "mean"},
    },
}

FAKE_INTERPRETATION = {
    "model_types": ["punet", "fcnet"],
    "model_descriptions": {"punet": "PUNet description...", "fcnet": "FCNet description..."},
    "total_experiments": 20,
    "per_model_best":  {"punet": 1.8, "fcnet": 0.9},
    "per_model_worst": {"punet": 1.2, "fcnet": 0.7},
    "best_denoising_score": 1.8,
    "worst_denoising_score": 0.7,
    "best_config": {"model_config": {"depth": 4}, "train_config": {"lr": 3e-4}},
    "key_findings": ["focal loss consistently outperforms ce"],
    "bottlenecks": ["architecture capacity ceiling at depth=3"],
    "take_home_message": "The current architecture has saturated; a new design is needed.",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    with patch("nodes.ml_model_proposal_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate_text.return_value = FAKE_REASONING
        MockBridge.return_value.generate.return_value = FAKE_COMMIT_RESPONSE
        a = MLModelProposalAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        yield a


def make_input(workspace, run_name="r1", existing_model_types=None, constraints=None):
    return ProposalInput(
        interpretation=FAKE_INTERPRETATION,
        existing_model_types=existing_model_types or [],
        constraints=constraints or [],
        storage={"backend": "local", "local": {"workspace": str(workspace), "run_name": run_name}},
    )


# ---------------------------------------------------------------------------
# LLM call structure
# ---------------------------------------------------------------------------

class TestLLMCallStructure:

    def test_generate_text_called_once(self, agent, tmp_path):
        agent.run(make_input(tmp_path))
        agent.bridge.generate_text.assert_called_once()

    def test_generate_called_once(self, agent, tmp_path):
        agent.run(make_input(tmp_path))
        agent.bridge.generate.assert_called_once()

    def test_reasoning_injected_into_commit_prompt(self, agent, tmp_path):
        agent.run(make_input(tmp_path))
        commit_call_args = agent.bridge.generate.call_args
        user_prompt = commit_call_args[0][1]
        assert FAKE_REASONING in user_prompt

    def test_generate_text_called_before_generate(self, agent, tmp_path):
        call_order = []
        agent.bridge.generate_text.side_effect = lambda *a, **kw: call_order.append("text") or FAKE_REASONING
        agent.bridge.generate.side_effect     = lambda *a, **kw: call_order.append("json") or FAKE_COMMIT_RESPONSE
        agent.run(make_input(tmp_path))
        assert call_order == ["text", "json"]


# ---------------------------------------------------------------------------
# Output correctness
# ---------------------------------------------------------------------------

class TestOutputCorrectness:

    def test_output_is_valid_proposal_output(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert isinstance(output, ProposalOutput)

    def test_model_name_from_llm(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert output.model_name == "attn_unet"

    def test_model_description_from_llm(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "U-Net" in output.model_description

    def test_mathematical_definition_from_llm(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "Embedding" in output.mathematical_definition

    def test_motivation_from_llm(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "take-home message" in output.motivation

    def test_expert_advice_is_expert_advice_instance(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert isinstance(output.expert_advice, ExpertAdvice)

    def test_expert_advice_fields_populated(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "VRAM < 10 GB" in output.expert_advice.constraints
        assert len(output.expert_advice.focus_areas) > 0
        assert len(output.expert_advice.suggested_directions) > 0

    def test_baseline_config_has_required_keys(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "model_config" in output.baseline_config
        assert "train_config" in output.baseline_config
        assert "loss_config"  in output.baseline_config


# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------

class TestFilePersistence:

    def test_output_written_to_file(self, agent, tmp_path):
        agent.run(make_input(tmp_path, run_name="myrun"))
        out_path = tmp_path / "proposal_myrun.json"
        assert out_path.exists()

    def test_output_file_is_valid_json(self, agent, tmp_path):
        agent.run(make_input(tmp_path, run_name="r1"))
        data = json.loads((tmp_path / "proposal_r1.json").read_text())
        assert data["model_name"] == "attn_unet"

    def test_output_file_contains_expert_advice(self, agent, tmp_path):
        agent.run(make_input(tmp_path, run_name="r1"))
        data = json.loads((tmp_path / "proposal_r1.json").read_text())
        assert "expert_advice" in data
        assert "constraints" in data["expert_advice"]


# ---------------------------------------------------------------------------
# Duplicate model name guard
# ---------------------------------------------------------------------------

class TestDuplicateNameGuard:

    def test_duplicate_model_name_raises(self, agent, tmp_path):
        inp = make_input(tmp_path, existing_model_types=["attn_unet", "punet", "fcnet"])
        with pytest.raises(ValueError, match="already exists in existing_model_types"):
            agent.run(inp)

    def test_empty_existing_model_types_does_not_raise(self, agent, tmp_path):
        inp = make_input(tmp_path, existing_model_types=[])
        output = agent.run(inp)
        assert output.model_name == "attn_unet"

    def test_different_existing_types_do_not_raise(self, agent, tmp_path):
        inp = make_input(tmp_path, existing_model_types=["punet", "fcnet", "wavenet"])
        output = agent.run(inp)
        assert output.model_name == "attn_unet"
