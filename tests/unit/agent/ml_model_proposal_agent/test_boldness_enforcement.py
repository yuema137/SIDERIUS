"""
Unit tests for boldness enforcement in the causal_reasoning stage retry.

When the causal_reasoning stage produces a FalsifiablePrediction whose boldness
is below policy.minimum_boldness, the pipeline runner must:
  1. Inject a BOLDNESS_TOO_LOW error into accumulated["proposing_stage_errors"].
  2. Re-run the causal_reasoning stage once (one retry, _MAX_REASONING_RETRIES=1).

The proposing stage then sees the error in the accumulated context and the
(hopefully bolder) replacement prediction.

No LLM calls — bridge.generate is mocked throughout.
"""
import json
import pytest
from unittest.mock import MagicMock, call

from agent.schemas.proposal import (
    ProposalInput,
    ProposalOutput,
    ReasoningPipelineConfig,
    ReasoningStage,
    ResearchPolicy,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_model_proposal_agent import MLModelProposalAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_comparison_output():
    return {
        "comparisons": [],
        "proposed_vocab_links": [],
        "proposed_vocab_candidates": [],
        "sota_model_type": "wavenet",
        "sota_score": 5.5,
        "sota_mechanism": "Dilated causal conv.",
    }


def _make_reasoning_output(current: float, predicted: float) -> dict:
    """Build a causal_reasoning output with the given prediction values."""
    return {
        "proposed_change": "Add spectral layer.",
        "causal_hypothesis": "Spectral conv addresses low-freq.",
        "falsifiable_prediction": {
            "metric": "denoising_score",
            "current_value": current,
            "predicted_value": predicted,
            "threshold_for_refutation": min(current, predicted) - 0.1,
            "rationale": "Test prediction.",
        },
        "predicted_failure_modes": ["VRAM overflow."],
        "inherited_components": [],
        "proposed_vocab_candidates": [],
    }


def _make_proposing_output(model_name: str = "spectral_wavenet") -> dict:
    return {
        "model_name": model_name,
        "model_description": "WaveNet + spectral conv.",
        "mathematical_definition": "Dilated conv + FFT layer.",
        "motivation": "Addresses low-freq bottleneck.",
        "expert_advice": {
            "focus_areas": ["low-freq recovery"],
            "constraints": ["VRAM < 10 GB", "params < 50M"],
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


def _make_pipeline_input(tmp_path, policy: ResearchPolicy | None = None) -> ProposalInput:
    return ProposalInput(
        interpretation={
            "model_types": ["wavenet"],
            "total_experiments": 5,
            "best_denoising_score": 5.5,
            "worst_denoising_score": 1.0,
            "key_findings": ["wavenet wins"],
            "bottlenecks": ["low-freq gap"],
            "take_home_message": "Wavenet dominates.",
        },
        existing_model_types=["wavenet"],
        reasoning_pipeline=ReasoningPipelineConfig(
            exploration_mode="exploit",
            stages=[
                ReasoningStage(name="comparison",
                               system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning",
                               system_prompt_key="CAUSAL_REASONING"),
            ],
            policy=policy or ResearchPolicy(),  # default minimum_boldness=0.05
        ),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


def _make_agent(bridge_responses: list) -> tuple[MLModelProposalAgent, MagicMock]:
    mock_bridge = MagicMock()
    mock_bridge.generate.side_effect = bridge_responses
    agent = MLModelProposalAgent(
        provider="gemini", model_id="test",
        bridge_factory=lambda **kw: mock_bridge,
    )
    return agent, mock_bridge


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBoldnessEnforcement:

    def test_boldness_passes_when_above_threshold(self, tmp_path):
        """Bold prediction (boldness > 0.05) — no retry, 3 total LLM calls."""
        # current=5.5, predicted=6.5 → boldness = 1.0/5.5 ≈ 0.18 > 0.05
        agent, mock = _make_agent([
            _make_comparison_output(),
            _make_reasoning_output(current=5.5, predicted=6.5),  # bold
            _make_proposing_output(),
        ])
        inp = _make_pipeline_input(tmp_path)
        output = agent.run(inp)

        assert isinstance(output, ProposalOutput)
        assert mock.generate.call_count == 3  # comparison + reasoning + proposing

    def test_boldness_retry_triggered_when_below_threshold(self, tmp_path):
        """Timid prediction (boldness < 0.05) triggers one causal_reasoning retry.

        current=5.5, predicted=5.75 → boldness = 0.25/5.5 ≈ 0.045 < 0.05.
        The retry returns a bold prediction (predicted=6.5 → boldness ≈ 0.18).
        Total LLM calls: comparison(1) + reasoning_timid(1) + reasoning_retry(1) + proposing(1) = 4.
        """
        agent, mock = _make_agent([
            _make_comparison_output(),
            _make_reasoning_output(current=5.5, predicted=5.75),  # timid: boldness ≈ 0.045
            _make_reasoning_output(current=5.5, predicted=6.5),   # bold on retry
            _make_proposing_output(),
        ])
        inp = _make_pipeline_input(tmp_path)
        output = agent.run(inp)

        assert isinstance(output, ProposalOutput)
        assert mock.generate.call_count == 4  # extra call for reasoning retry

    def test_boldness_error_injected_into_accumulated(self, tmp_path):
        """BOLDNESS_TOO_LOW message appears in the retry call's user prompt."""
        agent, mock = _make_agent([
            _make_comparison_output(),
            _make_reasoning_output(current=5.5, predicted=5.75),  # timid
            _make_reasoning_output(current=5.5, predicted=6.5),   # bold on retry
            _make_proposing_output(),
        ])
        inp = _make_pipeline_input(tmp_path)
        agent.run(inp)

        # Call index 2 is the causal_reasoning retry; its user prompt is call_args[0][1].
        retry_user_prompt = mock.generate.call_args_list[2][0][1]
        retry_context = json.loads(retry_user_prompt.split("\n\n")[0])  # strip vocab block
        errors = retry_context.get("proposing_stage_errors", [])
        assert any("BOLDNESS_TOO_LOW" in e for e in errors), (
            f"BOLDNESS_TOO_LOW not in retry user prompt errors. Got: {errors}"
        )

    def test_boldness_error_carries_current_and_predicted_values(self, tmp_path):
        """The error message includes the actual current and predicted values."""
        agent, mock = _make_agent([
            _make_comparison_output(),
            _make_reasoning_output(current=5.5, predicted=5.75),
            _make_reasoning_output(current=5.5, predicted=6.5),
            _make_proposing_output(),
        ])
        inp = _make_pipeline_input(tmp_path)
        agent.run(inp)

        retry_user_prompt = mock.generate.call_args_list[2][0][1]
        retry_context = json.loads(retry_user_prompt.split("\n\n")[0])
        errors = retry_context.get("proposing_stage_errors", [])
        boldness_error = next(e for e in errors if "BOLDNESS_TOO_LOW" in e)
        assert "5.5" in boldness_error   # current_value
        assert "5.75" in boldness_error  # predicted_value

    def test_tiny_delta_rejected(self, tmp_path):
        """Prediction with a near-zero delta is caught by the boldness check.

        current=5.5, predicted=5.501 → boldness = 0.001/5.5 ≈ 0.000182 < 0.05.
        """
        agent, mock = _make_agent([
            _make_comparison_output(),
            _make_reasoning_output(current=5.5, predicted=5.501),  # near-zero delta
            _make_reasoning_output(current=5.5, predicted=6.5),    # bold on retry
            _make_proposing_output(),
        ])
        inp = _make_pipeline_input(tmp_path)
        agent.run(inp)

        assert mock.generate.call_count == 4  # retry was triggered

    def test_custom_policy_threshold(self, tmp_path):
        """Custom minimum_boldness=0.20 rejects a prediction with boldness=0.18.

        current=5.5, predicted=6.5 → boldness = 1.0/5.5 ≈ 0.18, rejected at 0.20.
        """
        policy = ResearchPolicy(minimum_boldness=0.20)
        agent, mock = _make_agent([
            _make_comparison_output(),
            _make_reasoning_output(current=5.5, predicted=6.5),   # boldness ≈ 0.18 < 0.20
            _make_reasoning_output(current=5.5, predicted=7.5),   # boldness ≈ 0.36 > 0.20
            _make_proposing_output(),
        ])
        inp = _make_pipeline_input(tmp_path, policy=policy)
        agent.run(inp)

        assert mock.generate.call_count == 4  # retry triggered at custom threshold

    def test_boldness_uses_absolute_delta(self, tmp_path):
        """Predictions below the current value are judged by absolute magnitude.

        current=5.5, predicted=4.5 → boldness = abs(4.5-5.5)/5.5 = 1.0/5.5 ≈ 0.18 > 0.05.
        Even though the prediction is pessimistic (lower), boldness passes.
        """
        agent, mock = _make_agent([
            _make_comparison_output(),
            _make_reasoning_output(current=5.5, predicted=4.5),  # negative delta, bold
            _make_proposing_output(),
        ])
        inp = _make_pipeline_input(tmp_path)
        output = agent.run(inp)

        assert isinstance(output, ProposalOutput)
        assert mock.generate.call_count == 3  # no retry needed

    def test_no_retry_when_causal_reasoning_stage_absent(self, tmp_path):
        """If pipeline has no causal_reasoning stage, boldness check skips the retry
        gracefully and proceeds to the proposing stage."""
        agent, mock = _make_agent([
            _make_comparison_output(),  # only comparison stage
            _make_proposing_output(),
        ])
        inp = _make_pipeline_input(tmp_path)
        # Override pipeline to have only comparison stage
        inp.reasoning_pipeline.stages = [
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
        ]
        output = agent.run(inp)

        assert isinstance(output, ProposalOutput)
        assert mock.generate.call_count == 2  # comparison + proposing only

    def test_missing_prediction_skips_boldness_check(self, tmp_path):
        """If causal_reasoning returns no falsifiable_prediction (None), the boldness
        check skips gracefully and the proposing stage runs normally with 3 total calls."""
        reasoning_no_pred = {
            "proposed_change": "Add spectral layer.",
            "causal_hypothesis": "Spectral addresses low-freq.",
            "falsifiable_prediction": None,  # absent — boldness check must skip
            "predicted_failure_modes": ["VRAM overflow."],
            "inherited_components": [],
            "proposed_vocab_candidates": [],
        }
        agent, mock = _make_agent([
            _make_comparison_output(),
            reasoning_no_pred,
            _make_proposing_output(),
        ])
        inp = _make_pipeline_input(tmp_path)
        output = agent.run(inp)

        assert isinstance(output, ProposalOutput)
        assert mock.generate.call_count == 3  # no boldness retry
