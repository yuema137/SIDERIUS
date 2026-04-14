"""
Real-API integration tests for ml_model_proposal_agent (Node 3).

Exercises the node in isolation with a synthetic ProposalInput — no GPU,
no real TIDMAD data, and no upstream agent call required.

Requires:
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)

Run with:
  uv run pytest -m real_run tests/integration/nodes/test_ml_model_proposal_agent.py -v -s

DO NOT run in CI.
"""
import os
import re
import json
import pytest
from dotenv import load_dotenv

from agent.schemas.proposal import ProposalInput, ProposalOutput
from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_model_proposal_agent import MLModelProposalAgent

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
# Synthetic ProposalInput
# ---------------------------------------------------------------------------

SYNTHETIC_INTERPRETATION = {
    "model_types": ["punet", "fcnet"],
    "model_descriptions": {
        "punet": (
            "PUNet is a U-Net variant for 1-D signal denoising. It applies strided "
            "convolutions to downsample the signal into hierarchical feature maps, "
            "then recovers the original resolution via transposed convolutions with "
            "skip connections. It excels at local pattern recognition but struggles "
            "with long-range temporal dependencies."
        ),
        "fcnet": (
            "FCNet is a fully-connected architecture that treats each timestep "
            "independently. It has low capacity for temporal modelling and consistently "
            "underperforms PUNet on this task."
        ),
    },
    "total_experiments": 7,
    "best_denoising_score": 1.57,
    "worst_denoising_score": 0.85,
    "per_model_best":  {"punet": 1.57, "fcnet": 0.90},
    "per_model_worst": {"punet": 1.20, "fcnet": 0.85},
    "best_config": {
        "model_config": {"depth": 4, "multi": 16},
        "train_config": {"lr": 3e-4, "epochs": 15, "batch_size": 128},
        "loss_config":  {"loss_type": "focal", "gamma": 2.0},
    },
    "key_findings": [
        "Focal loss with gamma=2 outperforms CE by +0.35 on punet.",
        "FCNet is fundamentally limited for this task — architecture change needed.",
        "PUNet depth saturates at depth=4; further depth yields no improvement.",
    ],
    "bottlenecks": [
        "PUNet bottleneck layer compresses all temporal context into a fixed-size vector, "
        "losing long-range structure.",
        "Strided pooling discards positional detail that is hard to recover in the decoder.",
    ],
    "take_home_message": (
        "The current PUNet architecture has reached a saturation point. A new design "
        "that models long-range temporal dependencies without aggressive spatial compression "
        "is needed to break the performance ceiling."
    ),
}


def _make_input(tmp_path) -> ProposalInput:
    return ProposalInput(
        interpretation=SYNTHETIC_INTERPRETATION,
        existing_model_types=["punet", "fcnet"],
        constraints=["VRAM < 10 GB", "params < 100M"],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="node_test"),
        ),
    )


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

def _assert_output(output: ProposalOutput):
    assert isinstance(output, ProposalOutput)

    # model_name: snake_case, not reusing an existing type
    assert len(output.model_name) > 0
    assert re.match(r'^[a-z][a-z0-9_]*$', output.model_name), (
        f"model_name '{output.model_name}' is not snake_case"
    )
    assert output.model_name not in ["punet", "fcnet"], (
        f"model_name '{output.model_name}' reuses an existing model type"
    )

    # Substantive text fields
    assert len(output.model_description) > 20
    assert len(output.mathematical_definition) > 50
    assert len(output.motivation) > 20

    # mathematical_definition should not contain concrete shapes (channel counts etc.)
    # — this is a heuristic check to catch regressions in prompt quality
    assert "Conv1d(1," not in output.mathematical_definition, (
        "mathematical_definition contains concrete layer shapes — should be abstract"
    )

    # expert_advice
    assert isinstance(output.expert_advice, ExpertAdvice)
    assert len(output.expert_advice.constraints) > 0
    assert len(output.expert_advice.focus_areas) > 0
    assert len(output.expert_advice.suggested_directions) > 0

    # baseline_config
    assert "model_config" in output.baseline_config
    assert "train_config" in output.baseline_config
    assert "loss_config"  in output.baseline_config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMLModelProposalAgentGemini:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_proposal(self, tmp_path):
        agent = MLModelProposalAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
        output = agent.run(_make_input(tmp_path))

        _assert_output(output)
        assert (tmp_path / "proposal_node_test.json").exists()

        # Spot-check the persisted file is valid JSON
        with open(tmp_path / "proposal_node_test.json") as f:
            data = json.load(f)
        assert data["model_name"] == output.model_name

        print(f"\n  proposed model   : {output.model_name}")
        print(f"  motivation       : {output.motivation[:200]}...")
        print(f"  math_definition  : {output.mathematical_definition[:300]}...")
        print(f"  constraints      : {output.expert_advice.constraints}")
        print(f"  baseline_config  : {output.baseline_config}")


class TestMLModelProposalAgentOpenAI:

    def setup_method(self):
        _skip_if_no_key("openai")

    def test_proposal(self, tmp_path):
        agent = MLModelProposalAgent(provider="openai", model_id="gpt-4o-mini")
        output = agent.run(_make_input(tmp_path))

        _assert_output(output)
        assert (tmp_path / "proposal_node_test.json").exists()

        print(f"\n  proposed model  : {output.model_name}")
        print(f"  motivation      : {output.motivation[:200]}...")


# ==========================================
# Dual-mode test — 3-stage pipeline (B.21)
# ==========================================

@pytest.mark.dual_mode
def test_proposal_pipeline_dual_mode(tmp_path, request):
    """
    Dual-mode test for the 3-stage reasoning pipeline.

    Pseudo mode (default): RecordingLLMBridge returns predefined responses
    for comparison, causal_reasoning, and proposing stages. Asserts on
    call count, prompt content, and output structure. No API calls.

    Real mode (--real-api-call): real LLMBridge makes real API calls.
    Same assertions on output structure.
    """
    from agent.schemas.proposal import ReasoningPipelineConfig, ReasoningStage

    # Pipeline input with 2 reasoning stages
    pipeline = ReasoningPipelineConfig(
        stages=[
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ],
    )
    inp = ProposalInput(
        interpretation=SYNTHETIC_INTERPRETATION,
        existing_model_types=["punet", "wavenet", "fcnet"],
        constraints=["VRAM < 10 GB", "params < 50M"],
        reasoning_pipeline=pipeline,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=str(tmp_path),
                run_name="pipeline_test",
            ),
        ),
    )

    from tests.conftest import _is_real_llm
    from agent.llm_bridge import LLMBridge
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    if _is_real_llm(request):
        bridge = None
        bridge_factory = LLMBridge
    else:
        bridge = RecordingLLMBridge.for_agent("ml_model_proposal_agent")
        bridge_factory = lambda **kw: bridge

    agent = MLModelProposalAgent(provider="gemini", model_id="gemini-3.1-pro-preview",
                                  bridge_factory=bridge_factory)

    output = agent.run(inp)

    # --- Assertions that hold in BOTH modes ---
    assert isinstance(output, ProposalOutput)
    ProposalOutput.model_validate(output.model_dump())
    assert output.model_name  # non-empty
    assert output.model_name not in inp.existing_model_types
    assert output.model_description
    assert output.mathematical_definition
    assert output.motivation
    assert output.expert_advice.constraints  # at least one constraint
    assert output.baseline_config

    # Output file should be written
    out_path = tmp_path / "proposal_pipeline_test.json"
    assert out_path.exists()

    # --- Pseudo-LLM assertions (orchestration wiring) ---
    if bridge is not None:
        # 3 generate() calls: comparison, causal_reasoning, proposing
        gen_calls = [c for c in bridge.calls if c[0] == "generate"]
        assert len(gen_calls) == 3, (
            f"Expected 3 generate() calls (comparison + reasoning + proposing), "
            f"got {len(gen_calls)}"
        )

        # First call should contain vocabulary/comparison context
        first_prompt = gen_calls[0][2]  # user_prompt
        assert "candidates" in first_prompt.lower() or "model_type" in first_prompt.lower()

        # Output should match the canned proposing response
        assert output.model_name == "spectral_dilated_net"
        assert "dilated" in output.mathematical_definition.lower()
        assert output.memo_consistency_notes == []

        print(f"\n  [pseudo] 3-stage pipeline completed successfully")
        print(f"  [pseudo] {len(bridge.calls)} total bridge calls")
        print(f"  [pseudo] proposed: {output.model_name}")
