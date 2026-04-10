"""
Unit tests for Phase B Group 4: pipeline runner, model selection, and DI.

Tests:
  - B.10: ModelSelectionStrategy pre-filter
  - B.16a: Exploration mode resolver
  - B.13: Constructor DI (bridge_factory)
  - B.11: Pipeline runner (3-stage pipeline with mocked LLM)
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from agent.schemas.proposal import (
    ProposalInput,
    ProposalOutput,
    ReasoningPipelineConfig,
    ReasoningStage,
    ModelSelectionStrategy,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.proposal_helpers import select_candidate_models, resolve_exploration_mode
from nodes.ml_model_proposal_agent import MLModelProposalAgent


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

FAKE_INTERPRETATION = {
    "model_types": ["punet", "wavenet", "fcnet", "gated_fno"],
    "total_experiments": 20,
    "per_model_best": {"punet": 1.8, "wavenet": 5.5, "fcnet": 0.9, "gated_fno": 4.2},
    "per_model_worst": {"punet": 1.2, "wavenet": 3.1, "fcnet": 0.7, "gated_fno": 2.0},
    "best_denoising_score": 5.5,
    "worst_denoising_score": 0.7,
    "key_findings": ["wavenet dominates"],
    "bottlenecks": ["low-freq gap"],
    "take_home_message": "Wavenet wins but lacks low-freq coverage.",
    "model_descriptions": {
        "punet": "U-Net with positional encoding",
        "wavenet": "Dilated causal convolutions with gating and dilated_causal_conv",
        "fcnet": "Fully connected autoencoder",
        "gated_fno": "Fourier neural operator with gating",
    },
}


# ---------------------------------------------------------------------------
# B.10 — Model selection pre-filter
# ---------------------------------------------------------------------------

class TestModelSelection:

    def test_top_n_default(self):
        strategy = ModelSelectionStrategy()  # default: top_n, n=10
        result = select_candidate_models(FAKE_INTERPRETATION, strategy)
        # All 4 models fit in top 10
        assert len(result) == 4
        # Sorted by score descending
        assert result[0]["model_type"] == "wavenet"
        assert result[0]["best_score"] == 5.5

    def test_top_n_limited(self):
        strategy = ModelSelectionStrategy(method="top_n", params={"n": 2})
        result = select_candidate_models(FAKE_INTERPRETATION, strategy)
        assert len(result) == 2
        assert result[0]["model_type"] == "wavenet"
        assert result[1]["model_type"] == "gated_fno"

    def test_all(self):
        strategy = ModelSelectionStrategy(method="all")
        result = select_candidate_models(FAKE_INTERPRETATION, strategy)
        assert len(result) == 4

    def test_human_specified(self):
        strategy = ModelSelectionStrategy(
            method="human_specified",
            params={"models": ["wavenet", "gated_fno"]},
        )
        result = select_candidate_models(FAKE_INTERPRETATION, strategy)
        types = {m["model_type"] for m in result}
        assert types == {"wavenet", "gated_fno"}

    def test_feature_match(self):
        strategy = ModelSelectionStrategy(
            method="feature_match",
            params={"feature": "dilated_causal_conv"},
        )
        result = select_candidate_models(FAKE_INTERPRETATION, strategy)
        # Only wavenet's description contains "dilated_causal_conv"
        assert len(result) == 1
        assert result[0]["model_type"] == "wavenet"

    def test_source_field_seed_vs_proposed(self):
        strategy = ModelSelectionStrategy(method="all")
        result = select_candidate_models(FAKE_INTERPRETATION, strategy)
        sources = {m["model_type"]: m["source"] for m in result}
        assert sources["wavenet"] == "seed"
        assert sources["punet"] == "seed"
        # gated_fno is also built-in
        assert sources["gated_fno"] == "seed"

    def test_empty_interpretation(self):
        strategy = ModelSelectionStrategy()
        result = select_candidate_models({"model_types": []}, strategy)
        assert result == []


# ---------------------------------------------------------------------------
# B.16a — Exploration mode resolver
# ---------------------------------------------------------------------------

class TestExplorationModeResolver:

    def test_explicit_explore(self):
        pipeline = ReasoningPipelineConfig(exploration_mode="explore")
        assert resolve_exploration_mode(FAKE_INTERPRETATION, pipeline) == "explore"

    def test_explicit_exploit(self):
        pipeline = ReasoningPipelineConfig(exploration_mode="exploit")
        assert resolve_exploration_mode(FAKE_INTERPRETATION, pipeline) == "exploit"

    def test_auto_few_models_explore(self):
        """Only built-in models → explore mode."""
        pipeline = ReasoningPipelineConfig(exploration_mode="auto")
        interp = {"model_types": ["punet", "wavenet"]}
        assert resolve_exploration_mode(interp, pipeline) == "explore"

    def test_auto_many_agent_proposed_exploit(self):
        """5+ agent-proposed models → exploit mode."""
        pipeline = ReasoningPipelineConfig(exploration_mode="auto")
        interp = {"model_types": [
            "punet", "wavenet",  # built-in
            "model_a", "model_b", "model_c", "model_d", "model_e",  # agent-proposed
        ]}
        assert resolve_exploration_mode(interp, pipeline) == "exploit"


# ---------------------------------------------------------------------------
# B.13 — Constructor DI
# ---------------------------------------------------------------------------

class TestConstructorDI:

    def test_default_factory_uses_real_bridge(self):
        """Without bridge_factory, the agent constructs a real LLMBridge."""
        with patch("nodes.ml_model_proposal_agent.LLMBridge") as MockBridge:
            agent = MLModelProposalAgent(provider="gemini", model_id="test")
            MockBridge.assert_called_once()

    def test_custom_factory(self):
        """With bridge_factory, the agent uses the provided factory."""
        fake_bridge = MagicMock()
        factory = MagicMock(return_value=fake_bridge)
        agent = MLModelProposalAgent(
            provider="gemini", model_id="test", bridge_factory=factory,
        )
        factory.assert_called_once()
        assert agent.bridge is fake_bridge


# ---------------------------------------------------------------------------
# B.11 — Pipeline runner (with mocked LLM)
# ---------------------------------------------------------------------------

FAKE_COMPARISON_OUTPUT = {
    "comparisons": [
        {
            "model_type": "wavenet",
            "source": "seed",
            "best_score": 5.5,
            "key_mechanism": "Dilated causal conv gives wide receptive field.",
            "strengths": ["Strong on high-freq files"],
            "weaknesses": ["Weak on low-freq files"],
            "lesson_for_next_proposal": "Keep dilation, add spectral processing.",
        }
    ],
    "proposed_vocab_links": [],
    "proposed_vocab_candidates": [],
    "sota_model_type": "wavenet",
    "sota_score": 5.5,
    "sota_mechanism": "Dilated causal conv.",
}

FAKE_REASONING_OUTPUT = {
    "proposed_change": "Add spectral_conv after the dilated conv stack.",
    "causal_hypothesis": "WaveNet bottleneck is low-freq. Spectral conv addresses this.",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.5,
        "predicted_value": 6.5,
        "threshold_for_refutation": 5.0,
        "rationale": "Spectral processing should lift low-freq.",
    },
    "predicted_failure_modes": ["FNO layer may exceed VRAM."],
    "inherited_components": [],
}

FAKE_PROPOSING_OUTPUT = {
    "model_name": "spectral_wavenet",
    "model_description": "WaveNet with spectral conv layer.",
    "mathematical_definition": "Dilated conv stack + FFT spectral layer.",
    "motivation": "Addresses low-freq bottleneck per DiscoveryMemo.",
    "expert_advice": {
        "focus_areas": ["low-freq recovery"],
        "constraints": ["VRAM < 10 GB"],
        "known_failures": [],
        "suggested_directions": ["start with depth=2"],
        "rationale": "Conservative baseline.",
    },
    "baseline_config": {
        "model_config": {"depth": 2},
        "train_config": {"lr": 1e-4, "epochs": 5},
        "loss_config": {"loss_type": "focal"},
    },
    "memo_consistency_notes": [],
}


class TestPipelineRunner:

    def _make_pipeline_input(self, tmp_path):
        return ProposalInput(
            interpretation=FAKE_INTERPRETATION,
            existing_model_types=["punet", "wavenet", "fcnet", "gated_fno"],
            reasoning_pipeline=ReasoningPipelineConfig(
                stages=[
                    ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                    ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
                ],
            ),
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(
                    workspace=str(tmp_path), run_name="test",
                ),
            ),
        )

    def _make_agent_with_mock(self):
        mock_bridge = MagicMock()
        # Stage 1 (comparison) → JSON
        # Stage 2 (causal_reasoning) → JSON
        # Stage 3 (proposing) → JSON
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            FAKE_PROPOSING_OUTPUT,
        ]
        agent = MLModelProposalAgent(
            provider="gemini", model_id="test",
            bridge_factory=lambda **kw: mock_bridge,
        )
        return agent, mock_bridge

    def test_pipeline_produces_valid_output(self, tmp_path):
        agent, mock = self._make_agent_with_mock()
        inp = self._make_pipeline_input(tmp_path)
        output = agent.run(inp)

        assert isinstance(output, ProposalOutput)
        assert output.model_name == "spectral_wavenet"
        assert output.memo_consistency_notes == []

    def test_pipeline_calls_bridge_3_times(self, tmp_path):
        agent, mock = self._make_agent_with_mock()
        inp = self._make_pipeline_input(tmp_path)
        agent.run(inp)

        # 3 calls: comparison, causal_reasoning, proposing
        assert mock.generate.call_count == 3

    def test_disabled_stage_skipped(self, tmp_path):
        agent, mock = self._make_agent_with_mock()
        # Only 2 generate calls needed now (causal_reasoning disabled)
        mock.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_PROPOSING_OUTPUT,
        ]
        inp = self._make_pipeline_input(tmp_path)
        inp.reasoning_pipeline.stages[1].enabled = False
        output = agent.run(inp)

        assert mock.generate.call_count == 2
        assert output.model_name == "spectral_wavenet"

    def test_legacy_mode_when_no_stages(self, tmp_path):
        """Empty stages → legacy 2-call mode."""
        mock_bridge = MagicMock()
        mock_bridge.generate_text.return_value = "Some reasoning text."
        mock_bridge.generate.return_value = FAKE_PROPOSING_OUTPUT
        agent = MLModelProposalAgent(
            provider="gemini", model_id="test",
            bridge_factory=lambda **kw: mock_bridge,
        )
        inp = ProposalInput(
            interpretation=FAKE_INTERPRETATION,
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(
                    workspace=str(tmp_path), run_name="test",
                ),
            ),
        )
        output = agent.run(inp)

        # Legacy: generate_text (reasoning) + generate (commit) = 2 calls
        assert mock_bridge.generate_text.call_count == 1
        assert mock_bridge.generate.call_count == 1
        assert output.model_name == "spectral_wavenet"

    def test_output_file_written(self, tmp_path):
        agent, mock = self._make_agent_with_mock()
        inp = self._make_pipeline_input(tmp_path)
        agent.run(inp)

        import os
        out_path = os.path.join(str(tmp_path), "proposal_test.json")
        assert os.path.exists(out_path)
        with open(out_path) as f:
            data = json.load(f)
        assert data["model_name"] == "spectral_wavenet"
