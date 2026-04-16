"""
Unit tests for Phase B Group 4: pipeline runner, model selection, and DI.

Tests:
  - B.10: ModelSelectionStrategy pre-filter
  - B.16a: Exploration mode resolver
  - B.13: Constructor DI (bridge_factory)
  - B.11: Pipeline runner (3-stage pipeline with mocked LLM)
  - B.22: Proposing stage retry on validation failure
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
    "model_knowledge_cache": {
        "punet": {
            "key_findings": ["Skip connections help low-freq"],
            "bottlenecks": ["No temporal context"],
            "score_trend": "Flat after round 3",
            "strategy_assessment": "U-Net family exhausted",
            "_stats": {"best_denoising_score": 1.8},
        },
        "wavenet": {
            "key_findings": ["Wide receptive field via dilation"],
            "bottlenecks": ["Misses very low frequencies"],
            "score_trend": "Steady improvement to round 8",
            "strategy_assessment": "Still room for spectral augmentation",
            "_stats": {"best_denoising_score": 5.5},
        },
        "fcnet": {
            "key_findings": ["Global mixing collapses temporal structure"],
            "bottlenecks": ["No local feature extraction"],
            "score_trend": "Peaked at round 1, flat thereafter",
            "strategy_assessment": "FC architecture unsuitable for this task",
            "_stats": {"best_denoising_score": 0.9},
        },
        "gated_fno": {
            "key_findings": ["Fourier modes capture periodic patterns well"],
            "bottlenecks": ["Gating adds instability at higher modes"],
            "score_trend": "Improving but noisy",
            "strategy_assessment": "Reduce active modes, add residual path",
            "_stats": {"best_denoising_score": 4.2},
        },
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

    def test_non_candidates_included_in_prompt(self, tmp_path):
        """
        When top_n < total models, excluded models must appear in
        accumulated['non_candidates_overview'] with their description and
        cache analysis text, so the Stage 1 LLM can learn from their failures.

        Setup: 4 models, top_n=2 → wavenet (5.5) and gated_fno (4.2) are
        selected; punet (1.8) and fcnet (0.9) are excluded.
        Expected: both excluded models are in non_candidates_overview with
        key_findings, bottlenecks, score_trend, strategy_assessment, and
        description populated from FAKE_INTERPRETATION.
        """
        agent, mock = self._make_agent_with_mock()
        inp = self._make_pipeline_input(tmp_path)
        inp.reasoning_pipeline.model_selection = ModelSelectionStrategy(
            method="top_n", params={"n": 2},
        )

        # Capture the user prompt sent to the Stage 1 LLM call.
        captured_prompts = []
        original_generate = mock.generate.side_effect

        def capture_and_delegate(*args, **kwargs):
            captured_prompts.append(args[1] if len(args) > 1 else kwargs.get("user_prompt", ""))
            result = next(iter(original_generate.__self__._mock_side_effect_iterator
                               if hasattr(original_generate, '__self__') else []))
            return result

        # Simpler: intercept at the accumulated dict level by inspecting the
        # JSON passed as the user prompt to generate().
        call_args_list = []
        responses = [FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT, FAKE_PROPOSING_OUTPUT]
        response_iter = iter(responses)

        def capturing_generate(system_prompt, user_prompt, **kw):
            call_args_list.append(user_prompt)
            return next(response_iter)

        mock.generate.side_effect = capturing_generate

        agent.run(inp)

        # Stage 1 user prompt is call_args_list[0]
        stage1_prompt = call_args_list[0]
        stage1_data = json.loads(stage1_prompt.split("\n\n")[0])  # strip appended blocks

        non_candidates = stage1_data.get("non_candidates_overview", [])
        non_candidate_types = {e["model_type"] for e in non_candidates}

        # The two excluded models are present
        assert "punet" in non_candidate_types, "punet should be in non_candidates_overview"
        assert "fcnet" in non_candidate_types, "fcnet should be in non_candidates_overview"

        # The two selected models are NOT in non_candidates_overview
        assert "wavenet" not in non_candidate_types
        assert "gated_fno" not in non_candidate_types

        # Each excluded model carries its analysis text and description
        for entry in non_candidates:
            assert entry.get("description"), f"{entry['model_type']} missing description"
            assert entry.get("key_findings"), f"{entry['model_type']} missing key_findings"
            assert entry.get("bottlenecks"), f"{entry['model_type']} missing bottlenecks"
            assert entry.get("score_trend"), f"{entry['model_type']} missing score_trend"

    def test_non_candidates_empty_when_all_selected(self, tmp_path):
        """When all models fit within top_n, non_candidates_overview is empty."""
        agent, mock = self._make_agent_with_mock()
        inp = self._make_pipeline_input(tmp_path)
        # top_n=10 with only 4 models → all selected
        inp.reasoning_pipeline.model_selection = ModelSelectionStrategy(
            method="top_n", params={"n": 10},
        )

        call_args_list = []
        responses = iter([FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT, FAKE_PROPOSING_OUTPUT])

        def capturing_generate(system_prompt, user_prompt, **kw):
            call_args_list.append(user_prompt)
            return next(responses)

        mock.generate.side_effect = capturing_generate

        agent.run(inp)

        stage1_data = json.loads(call_args_list[0].split("\n\n")[0])
        assert stage1_data.get("non_candidates_overview") == []


# ---------------------------------------------------------------------------
# B.22 — Proposing stage retry on validation failure
# ---------------------------------------------------------------------------

class TestProposingRetry:
    """
    B.22: when the proposing stage produces invalid output, the pipeline
    retries up to _MAX_PROPOSING_RETRIES times before raising.

    Stages 1+2 (comparison, causal_reasoning) always succeed and are NOT
    re-run on retry — only Stage 3 (proposing) is retried.
    """

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
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
            ),
        )

    def _agent(self, mock_bridge):
        return MLModelProposalAgent(
            provider="gemini", model_id="test",
            bridge_factory=lambda **kw: mock_bridge,
        )

    def test_retry_on_duplicate_model_name(self, tmp_path):
        """First proposing attempt returns an existing model name → retries → succeeds."""
        mock_bridge = MagicMock()
        duplicate_output = dict(FAKE_PROPOSING_OUTPUT, model_name="wavenet")
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            duplicate_output,       # attempt 1: duplicate name (ValueError)
            FAKE_PROPOSING_OUTPUT,  # attempt 2: success
        ]
        output = self._agent(mock_bridge).run(self._make_pipeline_input(tmp_path))

        assert output.model_name == "spectral_wavenet"
        # 2 pipeline stages + 2 proposing attempts
        assert mock_bridge.generate.call_count == 4

    def test_retry_on_validation_error(self, tmp_path):
        """First proposing attempt returns output that fails ProposalOutput validation → retries."""
        mock_bridge = MagicMock()
        # model_name min_length=1 → ValidationError
        invalid_output = {"model_name": ""}
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            invalid_output,         # attempt 1: ValidationError
            FAKE_PROPOSING_OUTPUT,  # attempt 2: success
        ]
        output = self._agent(mock_bridge).run(self._make_pipeline_input(tmp_path))

        assert output.model_name == "spectral_wavenet"
        assert mock_bridge.generate.call_count == 4

    def test_error_injected_into_prompt_on_retry(self, tmp_path):
        """
        The failure message is injected into accumulated['proposing_stage_errors']
        so the LLM sees its own mistake in the retry prompt.
        """
        mock_bridge = MagicMock()
        duplicate_output = dict(FAKE_PROPOSING_OUTPUT, model_name="wavenet")
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            duplicate_output,       # attempt 1: fails
            FAKE_PROPOSING_OUTPUT,  # attempt 2: success
        ]
        self._agent(mock_bridge).run(self._make_pipeline_input(tmp_path))

        # The 4th call (index 3) is the retry proposing attempt.
        retry_user_prompt = mock_bridge.generate.call_args_list[3][0][1]
        retry_data = json.loads(retry_user_prompt.split("\n\n")[0])

        assert "proposing_stage_errors" in retry_data
        errors = retry_data["proposing_stage_errors"]
        assert len(errors) == 1
        assert "wavenet" in errors[0]  # error message mentions the offending name

    def test_stages_1_and_2_not_rerun_on_retry(self, tmp_path):
        """Retry only re-calls Stage 3 — Stages 1 and 2 are called exactly once each."""
        mock_bridge = MagicMock()
        duplicate_output = dict(FAKE_PROPOSING_OUTPUT, model_name="wavenet")
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            duplicate_output,
            FAKE_PROPOSING_OUTPUT,
        ]
        self._agent(mock_bridge).run(self._make_pipeline_input(tmp_path))

        # Total 4 calls: comparison(1) + causal_reasoning(1) + proposing(2)
        assert mock_bridge.generate.call_count == 4

    def test_exhausted_retries_raises(self, tmp_path):
        """All proposing attempts fail → RuntimeError raised after _MAX_PROPOSING_RETRIES+1 attempts."""
        from nodes.ml_model_proposal_agent import _MAX_PROPOSING_RETRIES

        mock_bridge = MagicMock()
        duplicate_output = dict(FAKE_PROPOSING_OUTPUT, model_name="wavenet")
        mock_bridge.generate.side_effect = (
            [FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT]
            + [duplicate_output] * (_MAX_PROPOSING_RETRIES + 1)
        )
        agent = self._agent(mock_bridge)

        with pytest.raises(RuntimeError, match="failed after"):
            agent.run(self._make_pipeline_input(tmp_path))

        # 2 pipeline stage calls + all proposing attempts
        assert mock_bridge.generate.call_count == 2 + (_MAX_PROPOSING_RETRIES + 1)
