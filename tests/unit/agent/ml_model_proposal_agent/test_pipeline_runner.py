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
from unittest.mock import MagicMock, patch

import pytest

from agent.schemas.proposal import (
    ModelSelectionStrategy,
    ProposalInput,
    ProposalOutput,
    ReasoningPipelineConfig,
    ReasoningStage,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.proposal_helpers import resolve_exploration_mode, select_candidate_models

from ._prompt_utils import extract_accumulated_json

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
        strategy = ModelSelectionStrategy()  # default: top_n, n=5
        result = select_candidate_models(FAKE_INTERPRETATION, strategy)
        # All 4 models fit in top 5
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

    def test_score_table_passthrough(self):
        # Phase 5 B: candidate summary exposes "score_table" (raw serialized
        # ScoreComparisonTable dict) instead of the old "file_vector" key.
        interp = {
            "model_types": ["punet"],
            "per_model_best": {"punet": 1.8},
            "per_model_worst": {"punet": 1.2},
            "per_model_score_tables": {
                "punet": {
                    "rows": [{"model": 0.5}] * 20,
                    "aggregate": {"num_sampled_files": 20},
                    "rendered_markdown": "| test |",
                }
            },
        }
        result = select_candidate_models(interp, ModelSelectionStrategy(method="all"))
        assert len(result) == 1
        summary = result[0]
        # New key is the raw dict — untouched passthrough.
        assert summary["score_table"] == interp["per_model_score_tables"]["punet"]
        # Old key must be gone — guards against silent dual-write drift.
        assert "file_vector" not in summary

    def test_score_table_none_when_missing(self):
        # Models without a score_table (e.g. fully failed runs) carry None,
        # not a synthesized empty list — consumers must handle None explicitly.
        interp = {
            "model_types": ["punet"],
            "per_model_best": {"punet": None},
        }
        result = select_candidate_models(interp, ModelSelectionStrategy(method="all"))
        assert result[0]["score_table"] is None


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
        interp = {
            "model_types": [
                "punet",
                "wavenet",  # built-in
                "model_a",
                "model_b",
                "model_c",
                "model_d",
                "model_e",  # agent-proposed
            ]
        }
        assert resolve_exploration_mode(interp, pipeline) == "exploit"


# ---------------------------------------------------------------------------
# B.13 — Constructor DI
# ---------------------------------------------------------------------------


class TestConstructorDI:
    def test_default_factory_uses_real_bridge(self):
        """Without bridge_factory, the agent constructs a real LLMBridge."""
        with patch("nodes.ml_model_proposal_agent.LLMBridge") as MockBridge:
            MLModelProposalAgent(provider="gemini", model_id="test")
            MockBridge.assert_called_once()

    def test_custom_factory(self):
        """With bridge_factory, the agent uses the provided factory."""
        fake_bridge = MagicMock()
        factory = MagicMock(return_value=fake_bridge)
        agent = MLModelProposalAgent(
            provider="gemini",
            model_id="test",
            bridge_factory=factory,
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
                    workspace=str(tmp_path),
                    run_name="test",
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
            provider="gemini",
            model_id="test",
            bridge_factory=lambda **kw: mock_bridge,
        )
        return agent, mock_bridge

    def test_pipeline_produces_valid_output(self, tmp_path):
        agent, _mock = self._make_agent_with_mock()
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
            provider="gemini",
            model_id="test",
            bridge_factory=lambda **kw: mock_bridge,
        )
        inp = ProposalInput(
            interpretation=FAKE_INTERPRETATION,
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(
                    workspace=str(tmp_path),
                    run_name="test",
                ),
            ),
        )
        output = agent.run(inp)

        # Legacy: generate_text (reasoning) + generate (commit) = 2 calls
        assert mock_bridge.generate_text.call_count == 1
        assert mock_bridge.generate.call_count == 1
        assert output.model_name == "spectral_wavenet"

    def test_output_file_written(self, tmp_path):
        agent, _mock = self._make_agent_with_mock()
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
            method="top_n",
            params={"n": 2},
        )

        # Capture the user prompt sent to the Stage 1 LLM call.
        captured_prompts = []
        original_generate = mock.generate.side_effect

        def capture_and_delegate(*args, **kwargs):
            captured_prompts.append(args[1] if len(args) > 1 else kwargs.get("user_prompt", ""))
            result = next(
                iter(
                    original_generate.__self__._mock_side_effect_iterator
                    if hasattr(original_generate, "__self__")
                    else []
                )
            )
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
        stage1_data = extract_accumulated_json(stage1_prompt)

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
            method="top_n",
            params={"n": 10},
        )

        call_args_list = []
        responses = iter([FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT, FAKE_PROPOSING_OUTPUT])

        def capturing_generate(system_prompt, user_prompt, **kw):
            call_args_list.append(user_prompt)
            return next(responses)

        mock.generate.side_effect = capturing_generate

        agent.run(inp)

        stage1_data = extract_accumulated_json(call_args_list[0])
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
            provider="gemini",
            model_id="test",
            bridge_factory=lambda **kw: mock_bridge,
        )

    def test_retry_on_duplicate_model_name(self, tmp_path):
        """First proposing attempt returns an existing model name → retries → succeeds."""
        mock_bridge = MagicMock()
        duplicate_output = dict(FAKE_PROPOSING_OUTPUT, model_name="wavenet")
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            duplicate_output,  # attempt 1: duplicate name (ValueError)
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
            invalid_output,  # attempt 1: ValidationError
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
            duplicate_output,  # attempt 1: fails
            FAKE_PROPOSING_OUTPUT,  # attempt 2: success
        ]
        self._agent(mock_bridge).run(self._make_pipeline_input(tmp_path))

        # The 4th call (index 3) is the retry proposing attempt.
        retry_user_prompt = mock_bridge.generate.call_args_list[3][0][1]
        retry_data = extract_accumulated_json(retry_user_prompt)

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
        mock_bridge.generate.side_effect = [FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT] + [
            duplicate_output
        ] * (_MAX_PROPOSING_RETRIES + 1)
        agent = self._agent(mock_bridge)

        with pytest.raises(RuntimeError, match="failed after"):
            agent.run(self._make_pipeline_input(tmp_path))

        # 2 pipeline stage calls + all proposing attempts
        assert mock_bridge.generate.call_count == 2 + (_MAX_PROPOSING_RETRIES + 1)


# ---------------------------------------------------------------------------
# Phase A.4 — segmentation_size validator integration with the retry loop
# ---------------------------------------------------------------------------


class TestSegmentationSizeRetryIntegration:
    """
    A.4: end-to-end check that the A.1 ProposalOutput.segmentation_size validator
    fires inside the proposer's existing retry loop, surfaces the divisor-list
    error to the next attempt via ``proposing_stage_errors``, and lets a
    self-corrected response succeed.

    See docs/improving_validation_awareness.md Phase A.4.
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
            provider="gemini",
            model_id="test",
            bridge_factory=lambda **kw: mock_bridge,
        )

    @staticmethod
    def _with_seg(size):
        out = json.loads(json.dumps(FAKE_PROPOSING_OUTPUT))
        out["baseline_config"]["model_config"]["segmentation_size"] = size
        return out

    def test_invalid_segmentation_size_triggers_retry_then_succeeds(self, tmp_path):
        """16384 is the exact value the production runs failed on. 16000 is the
        nearest valid divisor of 10_000_000 and is mentioned in the recovery hint."""
        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            self._with_seg(16384),  # attempt 1: invalid (power of 2, not a divisor)
            self._with_seg(16000),  # attempt 2: valid divisor
        ]
        output = self._agent(mock_bridge).run(self._make_pipeline_input(tmp_path))

        assert output.baseline_config["model_config"]["segmentation_size"] == 16000
        # comparison(1) + causal_reasoning(1) + proposing(2)
        assert mock_bridge.generate.call_count == 4

    def test_validator_error_visible_in_retry_prompt(self, tmp_path):
        """The retry's user prompt must include the validator's error in
        ``proposing_stage_errors`` so the LLM can self-correct against the
        divisor list."""
        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [
            FAKE_COMPARISON_OUTPUT,
            FAKE_REASONING_OUTPUT,
            self._with_seg(16384),
            self._with_seg(16000),
        ]
        self._agent(mock_bridge).run(self._make_pipeline_input(tmp_path))

        # Call index 3 = retry proposing attempt
        retry_user_prompt = mock_bridge.generate.call_args_list[3][0][1]
        retry_data = extract_accumulated_json(retry_user_prompt)

        assert "proposing_stage_errors" in retry_data
        errors = retry_data["proposing_stage_errors"]
        assert len(errors) == 1
        # Error message names the offending field and the diagnostic
        err = errors[0]
        assert "segmentation_size" in err
        assert "16384" in err

    def test_all_invalid_segmentation_sizes_exhausts_retries(self, tmp_path):
        """If the LLM never corrects, the retry loop exhausts cleanly and raises."""
        from nodes.ml_model_proposal_agent import _MAX_PROPOSING_RETRIES

        mock_bridge = MagicMock()
        mock_bridge.generate.side_effect = [FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT] + [
            self._with_seg(16384)
        ] * (_MAX_PROPOSING_RETRIES + 1)
        with pytest.raises(RuntimeError, match="failed after"):
            self._agent(mock_bridge).run(self._make_pipeline_input(tmp_path))

        assert mock_bridge.generate.call_count == 2 + (_MAX_PROPOSING_RETRIES + 1)


# ---------------------------------------------------------------------------
# Phase 5 C — proposer prompt rendering (native markdown + clean JSON)
#
# These four classes pin down the three new helpers introduced in
# ``nodes.proposal_helpers`` and the stage-user-prompt assembler in
# ``nodes.ml_model_proposal_agent._render_stage_user_prompt``. The split is:
#
#   * TestScoreSummaryLine       — non-candidate one-liners
#   * TestCandidateMarkdownBlock — top-level per-candidate markdown region
#   * TestStripHeavyFieldsForJson — heavy-field removal for the JSON region
#   * TestStageUserPrompt        — end-to-end markdown + JSON layout
#
# See docs/aggregated_score_table_awareness.md §"Sub-commit C detailed plan".
# ---------------------------------------------------------------------------


class TestScoreSummaryLine:
    """``build_score_summary_line`` produces the compact one-liner used in
    ``non_candidates_overview[i]["score_summary"]``. It mirrors the below-
    baseline guard in ``render_comparison_table`` so non-candidate models
    never quote a sign-flipped ``% of ceiling``."""

    def test_normal_recovery_formatting(self):
        from nodes.proposal_helpers import build_score_summary_line

        table = {
            "aggregate": {
                "model_scalar": 5.5763,
                "raw_baseline_scalar": -2.771,
                "percent_of_ceiling_log": 0.823,
                "num_sampled_files": 20,
            }
        }
        line = build_score_summary_line(table)
        assert line == "log_scalar=5.58, recovery=82.3% on 20 files"

    def test_below_baseline_honest_line(self):
        from nodes.proposal_helpers import build_score_summary_line

        # model_scalar (-7.5) < raw_baseline_scalar (-2.771) — the percent-of-
        # ceiling scalar is mathematically useless (and can even be positive
        # from a double negative) so we must not surface it.
        table = {
            "aggregate": {
                "model_scalar": -7.5,
                "raw_baseline_scalar": -2.771,
                "percent_of_ceiling_log": 2.3,
                "num_sampled_files": 17,
            }
        }
        line = build_score_summary_line(table)
        assert line == "log_scalar=-7.50, below raw baseline on 17 files"

    def test_missing_recovery_falls_back_to_no_percent(self):
        from nodes.proposal_helpers import build_score_summary_line

        # No percent_of_ceiling_log but model is above baseline — drop the
        # recovery clause rather than lie.
        table = {
            "aggregate": {
                "model_scalar": 3.2,
                "raw_baseline_scalar": 1.0,
                "percent_of_ceiling_log": None,
                "num_sampled_files": 20,
            }
        }
        line = build_score_summary_line(table)
        assert line == "log_scalar=3.20 on 20 files"

    def test_none_table_returns_none(self):
        from nodes.proposal_helpers import build_score_summary_line

        assert build_score_summary_line(None) is None

    def test_missing_aggregate_returns_none(self):
        from nodes.proposal_helpers import build_score_summary_line

        assert build_score_summary_line({"rows": []}) is None

    def test_missing_model_scalar_returns_none(self):
        from nodes.proposal_helpers import build_score_summary_line

        assert build_score_summary_line({"aggregate": {"num_sampled_files": 20}}) is None

    def test_missing_num_sampled_files_returns_none(self):
        from nodes.proposal_helpers import build_score_summary_line

        assert build_score_summary_line({"aggregate": {"model_scalar": 1.0}}) is None


class TestCandidateMarkdownBlock:
    """``build_candidate_markdown_block`` is the top-level native-markdown
    region that lifts the heavy rendered tables + source code out of the
    JSON-escaped candidate dicts."""

    def test_renders_heading_per_candidate(self):
        from nodes.proposal_helpers import build_candidate_markdown_block

        candidates = [
            {
                "model_type": "wavenet",
                "score_table": {"rendered_markdown": "| wavenet-table |"},
                "source_code": "class WaveNet: pass",
            },
            {
                "model_type": "punet",
                "score_table": {"rendered_markdown": "| punet-table |"},
                "source_code": "class PUNet: pass",
            },
        ]
        block = build_candidate_markdown_block(candidates)
        assert "## Candidate Models — detailed view" in block
        assert "### Candidate: wavenet" in block
        assert "### Candidate: punet" in block
        assert "| wavenet-table |" in block
        assert "| punet-table |" in block
        # Source code rendered inside a python fence.
        assert "```python\nclass WaveNet: pass\n```" in block
        assert "```python\nclass PUNet: pass\n```" in block

    def test_empty_candidates_returns_empty_string(self):
        from nodes.proposal_helpers import build_candidate_markdown_block

        assert build_candidate_markdown_block([]) == ""

    def test_missing_score_table_falls_back(self):
        from nodes.proposal_helpers import build_candidate_markdown_block

        candidates = [{"model_type": "mystery", "source_code": "pass"}]
        block = build_candidate_markdown_block(candidates)
        assert "_Score table unavailable._" in block
        assert "pass" in block  # source still rendered

    def test_missing_source_code_falls_back(self):
        from nodes.proposal_helpers import build_candidate_markdown_block

        candidates = [{"model_type": "mystery", "score_table": {"rendered_markdown": "| t |"}}]
        block = build_candidate_markdown_block(candidates)
        assert "_Source code unavailable._" in block
        assert "| t |" in block  # table still rendered

    def test_separator_between_candidates(self):
        from nodes.proposal_helpers import build_candidate_markdown_block

        candidates = [
            {"model_type": "a", "score_table": {"rendered_markdown": "A"}, "source_code": "a"},
            {"model_type": "b", "score_table": {"rendered_markdown": "B"}, "source_code": "b"},
        ]
        block = build_candidate_markdown_block(candidates)
        # One `---` separator per candidate keeps the LLM from merging sections.
        assert block.count("\n---\n") == 2


class TestStripHeavyFieldsForJson:
    """``strip_heavy_fields_for_json`` mirrors the candidate-markdown lift:
    heavy fields are removed from the JSON region because they are already
    present in the top-level markdown block."""

    def test_drops_score_table_and_source_code(self):
        from nodes.proposal_helpers import strip_heavy_fields_for_json

        candidates = [
            {
                "model_type": "wavenet",
                "best_score": 5.5,
                "model_params": 120_000,
                "description": "dilated causal conv",
                "score_table": {"rendered_markdown": "| t |"},
                "source_code": "class W: pass",
                "source_code_lines": 1,
            }
        ]
        stripped = strip_heavy_fields_for_json(candidates)
        assert stripped[0] == {
            "model_type": "wavenet",
            "best_score": 5.5,
            "model_params": 120_000,
            "description": "dilated causal conv",
        }

    def test_preserves_other_fields(self):
        from nodes.proposal_helpers import strip_heavy_fields_for_json

        # Arbitrary scalar/list fields (the pipeline may add new ones) must
        # survive — the helper is a targeted subtraction, not a whitelist.
        candidates = [
            {
                "model_type": "x",
                "training_segments": 200,
                "worst_score": 0.1,
                "source": "seed",
                "score_table": {"rendered_markdown": "| t |"},
            }
        ]
        stripped = strip_heavy_fields_for_json(candidates)
        assert stripped[0]["training_segments"] == 200
        assert stripped[0]["worst_score"] == 0.1
        assert stripped[0]["source"] == "seed"
        assert "score_table" not in stripped[0]

    def test_does_not_mutate_input(self):
        from nodes.proposal_helpers import strip_heavy_fields_for_json

        candidates = [
            {
                "model_type": "x",
                "score_table": {"rendered_markdown": "| t |"},
                "source_code": "pass",
                "source_code_lines": 1,
            }
        ]
        strip_heavy_fields_for_json(candidates)
        # Original dict untouched — downstream consumers (e.g. the markdown
        # block builder) still see the heavy fields.
        assert "score_table" in candidates[0]
        assert "source_code" in candidates[0]
        assert "source_code_lines" in candidates[0]

    def test_empty_list_returns_empty_list(self):
        from nodes.proposal_helpers import strip_heavy_fields_for_json

        assert strip_heavy_fields_for_json([]) == []


class TestStageUserPrompt:
    """End-to-end: ``_render_stage_user_prompt`` wires the markdown block +
    JSON region together and drops the redundant ``per_model_score_tables``
    key from ``interpretation_summary`` before dumping."""

    def test_markdown_block_first_then_json_region(self):
        from nodes.ml_model_proposal_agent import _render_stage_user_prompt

        accumulated = {
            "candidates": [
                {
                    "model_type": "wavenet",
                    "best_score": 5.5,
                    "score_table": {"rendered_markdown": "| wavenet-rendered |"},
                    "source_code": "class W: pass",
                }
            ],
            "non_candidates_overview": [],
            "interpretation_summary": {"take_home_message": "hi"},
        }
        prompt = _render_stage_user_prompt(accumulated)
        # Markdown block comes first (LLMs anchor on leading content).
        md_idx = prompt.index("## Candidate Models — detailed view")
        json_idx = prompt.index("## Accumulated context")
        assert md_idx < json_idx

    def test_json_region_strips_heavy_candidate_fields(self):
        from nodes.ml_model_proposal_agent import _render_stage_user_prompt

        accumulated = {
            "candidates": [
                {
                    "model_type": "wavenet",
                    "best_score": 5.5,
                    "score_table": {"rendered_markdown": "| wavenet-rendered |"},
                    "source_code": "class W: pass",
                    "source_code_lines": 1,
                }
            ],
            "non_candidates_overview": [],
            "interpretation_summary": {},
        }
        prompt = _render_stage_user_prompt(accumulated)
        payload = extract_accumulated_json(prompt)
        assert payload["candidates"][0]["best_score"] == 5.5
        assert "score_table" not in payload["candidates"][0]
        assert "source_code" not in payload["candidates"][0]
        assert "source_code_lines" not in payload["candidates"][0]
        # But the rendered markdown still survives in the top-level block.
        assert "| wavenet-rendered |" in prompt

    def test_drops_per_model_score_tables_from_interpretation_summary(self):
        from nodes.ml_model_proposal_agent import _render_stage_user_prompt

        accumulated = {
            "candidates": [],
            "non_candidates_overview": [],
            "interpretation_summary": {
                "take_home_message": "stay the course",
                "per_model_score_tables": {"wavenet": {"rendered_markdown": "| t |"}},
            },
        }
        prompt = _render_stage_user_prompt(accumulated)
        payload = extract_accumulated_json(prompt)
        assert "take_home_message" in payload["interpretation_summary"]
        # per_model_score_tables is redundant with the top-level markdown +
        # non-candidate score_summary lines, and is a heavy field — drop it.
        assert "per_model_score_tables" not in payload["interpretation_summary"]

    def test_no_candidates_emits_json_only(self):
        from nodes.ml_model_proposal_agent import _render_stage_user_prompt

        accumulated = {
            "candidates": [],
            "non_candidates_overview": [
                {"model_type": "x", "score_summary": "log_scalar=1.0, recovery=10.0% on 20 files"}
            ],
            "interpretation_summary": {},
        }
        prompt = _render_stage_user_prompt(accumulated)
        # Empty candidates → no top-level markdown heading at all.
        assert "## Candidate Models — detailed view" not in prompt
        assert prompt.startswith("## Accumulated context")
        # Non-candidate summary line passes through untouched.
        assert "recovery=10.0%" in prompt


# ---------------------------------------------------------------------------
# Phase 5 D — proposer render adversarial edges
#
# Covers the gap between the happy-path Sub-commit C tests and the
# ``tests/unit/execute_tools/test_score_table_adversarial.py`` probes (the
# latter target ``ScoreComparisonTable`` + ``render_comparison_table``, not
# the proposer-side render helpers). These pin down:
#
#   * ``build_score_summary_line``: priority ordering of the below-baseline
#     guard, boundary recovery values, non-dict/empty-dict robustness.
#   * ``build_candidate_markdown_block``: empty string vs missing field
#     semantics for ``rendered_markdown`` and ``source_code``, missing
#     ``model_type`` fallback, non-dict ``score_table`` robustness.
# ---------------------------------------------------------------------------


class TestProposerRenderAdversarial:
    """Adversarial probes for the three new proposer-side render helpers
    introduced in Sub-commit C. Complements the happy-path classes above."""

    def test_below_baseline_takes_priority_over_recovery(self):
        """If ``model_scalar < raw_baseline_scalar`` the honest one-liner must
        win even when ``percent_of_ceiling_log`` is populated. This mirrors
        the render_comparison_table below-baseline relabel guard — a double-
        negative log ratio can flip ``percent_of_ceiling_log`` back to a
        positive number, which is exactly why the guard is priority-ordered.
        """
        from nodes.proposal_helpers import build_score_summary_line

        table = {
            "aggregate": {
                "model_scalar": -7.5,
                "raw_baseline_scalar": -2.771,
                # Non-None — would mis-render as "recovery=270.4%" if the
                # below-baseline branch didn't take priority.
                "percent_of_ceiling_log": 2.704,
                "num_sampled_files": 20,
            }
        }
        line = build_score_summary_line(table)
        assert line == "log_scalar=-7.50, below raw baseline on 20 files"
        # Must NOT leak a misleading recovery percentage.
        assert "recovery" not in line
        assert "%" not in line

    def test_recovery_zero_renders_percent_not_missing_clause(self):
        """``recovery=0.0`` is a real datum (ties raw baseline exactly).
        It must render as ``recovery=0.0%``, not drop into the
        no-recovery fallback branch reserved for ``recovery is None``.
        """
        from nodes.proposal_helpers import build_score_summary_line

        table = {
            "aggregate": {
                "model_scalar": 1.0,
                "raw_baseline_scalar": 1.0,  # exactly tied — strict "<" stays on normal branch
                "percent_of_ceiling_log": 0.0,
                "num_sampled_files": 20,
            }
        }
        line = build_score_summary_line(table)
        assert line == "log_scalar=1.00, recovery=0.0% on 20 files"

    def test_non_dict_score_table_returns_none(self):
        """LLM-side or cache-round-trip corruption could replace the
        score_table with a bare string (e.g. ``"N/A"``). The helper must
        not crash."""
        from nodes.proposal_helpers import build_score_summary_line

        assert build_score_summary_line("N/A") is None
        assert build_score_summary_line([]) is None
        assert build_score_summary_line(42) is None

    def test_empty_rendered_markdown_string_falls_back(self):
        """Explicitly-empty ``rendered_markdown=""`` (falsy) must fall back
        to the ``_Score table unavailable._`` sentinel — not emit a blank
        region that the LLM would silently ignore."""
        from nodes.proposal_helpers import build_candidate_markdown_block

        candidates = [
            {
                "model_type": "a",
                "score_table": {"rendered_markdown": ""},
                "source_code": "pass",
            }
        ]
        block = build_candidate_markdown_block(candidates)
        assert "_Score table unavailable._" in block

    def test_empty_source_code_string_falls_back(self):
        """Same contract on the source-code side: empty string → sentinel
        rather than an empty python fence."""
        from nodes.proposal_helpers import build_candidate_markdown_block

        candidates = [
            {
                "model_type": "a",
                "score_table": {"rendered_markdown": "| t |"},
                "source_code": "",
            }
        ]
        block = build_candidate_markdown_block(candidates)
        assert "_Source code unavailable._" in block
        # And the empty python fence MUST NOT leak through.
        assert "```python\n\n```" not in block

    def test_missing_model_type_renders_unknown_placeholder(self):
        """If ``model_type`` is missing we fall back to ``<unknown>`` —
        should never crash the whole render, but should be visible enough
        that a reader notices the upstream data defect."""
        from nodes.proposal_helpers import build_candidate_markdown_block

        candidates = [
            {
                "score_table": {"rendered_markdown": "| t |"},
                "source_code": "pass",
            }
        ]
        block = build_candidate_markdown_block(candidates)
        assert "### Candidate: <unknown>" in block

    def test_non_dict_score_table_on_candidate_falls_back(self):
        """``score_table`` replaced by a non-dict (string, None, list) must
        not crash the markdown block — ``isinstance(table, dict)`` guard
        should catch it and produce the sentinel."""
        from nodes.proposal_helpers import build_candidate_markdown_block

        for bad_table in (None, "N/A", [], 42):
            candidates = [
                {
                    "model_type": "a",
                    "score_table": bad_table,
                    "source_code": "pass",
                }
            ]
            block = build_candidate_markdown_block(candidates)
            assert "_Score table unavailable._" in block, f"bad_table={bad_table!r}"


# ---------------------------------------------------------------------------
# Phase 5 D — genericity tests (directive #5 from the "Hardened genericity
# directives" audit in docs/aggregated_score_table_awareness.md).
#
# The litmus scan is the key check: after assembling a full stage user
# prompt with ONLY a synthetic model_type, the resulting string must not
# contain any of the SIDERIUS baseline model names. A hit would mean the
# LLM receives a contradictory signal — the dynamic table says
# ``mystery_model_x`` while some hidden string hardcodes ``wavenet``.
#
# Scope is strictly the proposer-side code we own in Sub-commit C
# (``build_candidate_markdown_block`` + ``_render_stage_user_prompt``).
# Stage-template few-shot examples that hardcode baseline names are a
# known gap tracked separately; see the "Hardened genericity directives"
# subsection for rationale.
# ---------------------------------------------------------------------------


class TestProposerGenericity:
    """Synthetic-model-name tests to prove no name-dependent branches
    remain in the code paths Sub-commit C introduced."""

    _BASELINE_NAMES = ("wavenet", "punet", "fcnet")

    def test_candidate_markdown_with_unseen_model_name(self):
        """A never-before-seen model_type must flow through
        ``build_candidate_markdown_block`` unchanged — heading, rendered
        table, and source code all carry the synthetic name."""
        from nodes.proposal_helpers import build_candidate_markdown_block

        candidates = [
            {
                "model_type": "mystery_model_x",
                "score_table": {"rendered_markdown": "| mystery_model_x row |"},
                "source_code": "class MysteryModelX: pass",
            }
        ]
        block = build_candidate_markdown_block(candidates)
        assert "### Candidate: mystery_model_x" in block
        assert "| mystery_model_x row |" in block
        assert "class MysteryModelX: pass" in block
        # No baseline-model leakage — directive #1 (No-Names rule).
        for name in self._BASELINE_NAMES:
            assert name not in block, (
                f"Baseline name '{name}' leaked into a mystery_model_x-only block"
            )

    def test_score_summary_indifferent_to_model_name(self):
        """``build_score_summary_line`` is keyed on aggregate scalars, not
        on the model name — it has no access to ``model_type`` at all.
        This test pins the contract down: identical aggregates produce
        identical summaries regardless of which model they describe."""
        from nodes.proposal_helpers import build_score_summary_line

        agg = {
            "model_scalar": 5.5763,
            "raw_baseline_scalar": -2.771,
            "percent_of_ceiling_log": 0.823,
            "num_sampled_files": 20,
        }
        line = build_score_summary_line({"aggregate": agg})
        # No model name appears in the summary — by design, the caller
        # inserts the name at the non_candidates_overview level.
        for name in (*self._BASELINE_NAMES, "mystery_model_x"):
            assert name not in line

    def test_render_stage_user_prompt_with_mystery_model(self):
        """The full ``_render_stage_user_prompt`` assembly with only
        ``mystery_model_x`` as the candidate must not leak any baseline
        model name — the litmus scan for directive #5."""
        from nodes.ml_model_proposal_agent import _render_stage_user_prompt

        accumulated = {
            "candidates": [
                {
                    "model_type": "mystery_model_x",
                    "best_score": 4.2,
                    "worst_score": 2.1,
                    "description": "A generic test architecture",
                    "model_params": 123_456,
                    "training_segments": 200,
                    "source": "proposed",
                    "score_table": {
                        "rendered_markdown": "| mystery_model_x row |",
                        "aggregate": {
                            "model_scalar": 4.2,
                            "raw_baseline_scalar": -2.771,
                            "percent_of_ceiling_log": 0.63,
                            "num_sampled_files": 20,
                        },
                    },
                    "source_code": "class MysteryModelX: pass",
                    "source_code_lines": 1,
                }
            ],
            "non_candidates_overview": [],
            "interpretation_summary": {
                "take_home_message": "Explore novel architectures.",
                "model_types": ["mystery_model_x"],
            },
            "existing_model_types": ["mystery_model_x"],
            "previous_failures": [],
        }
        prompt = _render_stage_user_prompt(accumulated)

        # Synthetic name flows through verbatim — every expected anchor.
        assert "### Candidate: mystery_model_x" in prompt
        assert "| mystery_model_x row |" in prompt
        assert "class MysteryModelX: pass" in prompt
        # The cleaned JSON region must still carry the scalar metadata.
        payload = extract_accumulated_json(prompt)
        assert payload["candidates"][0]["model_type"] == "mystery_model_x"
        assert payload["candidates"][0]["best_score"] == 4.2
        # Heavy fields stripped from JSON (they live in the markdown block).
        assert "score_table" not in payload["candidates"][0]
        assert "source_code" not in payload["candidates"][0]

        # Litmus substring scan — directive #5's hard requirement: ZERO
        # baseline-model-name hits when the candidate list is synthetic.
        for name in self._BASELINE_NAMES:
            assert name not in prompt, (
                f"Contradictory signal: '{name}' leaked into a mystery_model_x-only "
                "assembled stage prompt. Trace the source (proposal_helpers, "
                "_render_stage_user_prompt, or accumulated payload) and genericize "
                "before closing Sub-commit D."
            )

    def test_empty_candidate_list_prompt_has_no_leakage(self):
        """Regression guard: even with an empty candidate list, the fall-
        through path (JSON region only) must not contain baseline names."""
        from nodes.ml_model_proposal_agent import _render_stage_user_prompt

        accumulated = {
            "candidates": [],
            "non_candidates_overview": [
                {
                    "model_type": "mystery_model_x",
                    "score_summary": "log_scalar=1.00, recovery=10.0% on 20 files",
                }
            ],
            "interpretation_summary": {},
            "existing_model_types": [],
            "previous_failures": [],
        }
        prompt = _render_stage_user_prompt(accumulated)
        for name in self._BASELINE_NAMES:
            assert name not in prompt, (
                f"Baseline name '{name}' leaked into JSON-only fall-through prompt"
            )


# ---------------------------------------------------------------------------
# Phase 5 E — stage-prompt size budget
#
# Regression guard for the token-budget steer: the n=5 default must comfortably
# fit inside gpt-4o-mini's 128k context window, even with full per-candidate
# rendered_markdown score tables + ~30-line source-code fences. We use a char-
# count heuristic (~4 chars/token) because tiktoken is not installed.
# ---------------------------------------------------------------------------


class TestStagePromptSizeBudget:
    """Assert the assembled stage user prompt stays well under context limits."""

    _TABLE_ROWS = 20  # matches ScoreComparisonTable's 20-row cap

    def _rendered_markdown(self, model_type: str) -> str:
        header = (
            "| file | raw_baseline | ground_truth | model |\n"
            "|------|--------------|--------------|-------|\n"
        )
        rows = "\n".join(
            f"| seg_{i:03d}_{model_type} | 1.00 | 5.50 | 4.20 |" for i in range(self._TABLE_ROWS)
        )
        return header + rows

    def _source_code(self, model_type: str) -> str:
        # ~30 lines of representative plugin source with realistic width.
        lines = [
            f"# {model_type} plugin — representative source for budget test",
            "import torch",
            "import torch.nn as nn",
            "",
            f"class {model_type.title().replace('_', '')}Config:",
            "    depth: int = 4",
            "    width: int = 128",
            "    dropout: float = 0.1",
            "    activation: str = 'gelu'",
            "",
            f"class {model_type.title().replace('_', '')}Model(nn.Module):",
            "    def __init__(self, cfg):",
            "        super().__init__()",
            "        self.embed = nn.Embedding(256, cfg.width)",
            "        self.blocks = nn.ModuleList([",
            "            nn.Sequential(",
            "                nn.Conv1d(cfg.width, cfg.width, 3, padding=1),",
            "                nn.GELU(),",
            "                nn.Dropout(cfg.dropout),",
            "            ) for _ in range(cfg.depth)",
            "        ])",
            "        self.head = nn.Conv1d(cfg.width, 256, 1)",
            "",
            "    def forward(self, x):",
            "        h = self.embed(x).transpose(1, 2)",
            "        for block in self.blocks:",
            "            h = block(h) + h",
            "        return self.head(h)",
            "",
            "PLUGIN_MODEL_TYPE = 'placeholder'",
            f"PLUGIN_CONFIG_CLASS = {model_type.title().replace('_', '')}Config",
            f"PLUGIN_MODEL_CLASS = {model_type.title().replace('_', '')}Model",
        ]
        return "\n".join(lines)

    def _candidate(self, model_type: str, best_score: float) -> dict:
        return {
            "model_type": model_type,
            "description": f"{model_type} — auto-synthesized candidate for budget test.",
            "best_score": best_score,
            "model_params": 12_345_678,
            "source": "agent_generated",
            "source_code": self._source_code(model_type),
            "score_table": {
                "model_type": model_type,
                "rendered_markdown": self._rendered_markdown(model_type),
                "rows": [],  # scalar rows elided; stripped from JSON region anyway
                "aggregate": {"log_scalar": 1.23, "recovery": 0.42},
            },
        }

    def _build_accumulated(self, n_candidates: int) -> dict:
        candidates = [
            self._candidate(f"candidate_model_{i:02d}", best_score=5.5 - 0.1 * i)
            for i in range(n_candidates)
        ]
        non_candidates = [
            {
                "model_type": f"tail_model_{i:02d}",
                "score_summary": (
                    f"log_scalar=0.50, recovery=15.0% on 20 files (below raw_baseline on {i} files)"
                ),
            }
            for i in range(5)
        ]
        return {
            "candidates": candidates,
            "non_candidates_overview": non_candidates,
            "interpretation_summary": {
                "take_home_message": "Budget test synthetic summary.",
                "key_findings": ["finding " + str(i) for i in range(8)],
                "bottlenecks": ["bottleneck " + str(i) for i in range(6)],
            },
            "existing_model_types": [f"candidate_model_{i:02d}" for i in range(n_candidates)],
            "previous_failures": [],
        }

    def test_five_candidate_prompt_fits_budget(self, capsys):
        """Baseline: n=5 worst-case prompt stays comfortably inside 128k context.

        Reports actual char count so future changes to prompt shape stay
        observable. Budget: 200_000 chars (~50k tokens at 4 chars/token) —
        well under gpt-4o-mini's 128_000-token context window.
        """
        from nodes.ml_model_proposal_agent import _render_stage_user_prompt

        accumulated = self._build_accumulated(n_candidates=5)
        prompt = _render_stage_user_prompt(accumulated)

        n_chars = len(prompt)
        estimated_tokens = n_chars // 4
        # Emit so future regressions are observable in pytest -s output.
        print(
            f"\n[budget] n=5 stage prompt: {n_chars} chars "
            f"(~{estimated_tokens} tokens at 4 chars/token)"
        )

        assert n_chars < 200_000, (
            f"n=5 stage prompt is {n_chars} chars (~{estimated_tokens} tokens). "
            f"Budget is 200_000 chars — investigate before enlarging the prompt."
        )
        # Sanity: the markdown block and JSON region must both be present.
        assert "## Candidate Models — detailed view" in prompt
        assert "## Accumulated context" in prompt

    def test_budget_scales_sublinearly_with_n(self):
        """Smoke-check: doubling n (5→10) must not blow past a 2x bound.

        Guards against accidental quadratic growth (e.g. if every candidate
        started embedding all other candidates' tables).
        """
        from nodes.ml_model_proposal_agent import _render_stage_user_prompt

        small = _render_stage_user_prompt(self._build_accumulated(5))
        large = _render_stage_user_prompt(self._build_accumulated(10))

        # 10 candidates should be roughly ~2x of 5. Allow a generous 2.5x
        # ceiling to cover constant overhead + JSON expansion.
        assert len(large) < len(small) * 2.5, (
            f"Stage prompt scales super-linearly: "
            f"5-candidate={len(small)} chars, 10-candidate={len(large)} chars "
            f"(ratio={len(large) / len(small):.2f}x)."
        )
