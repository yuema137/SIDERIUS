"""
Real-API integration tests for result_interpretation_agent.

Requires:
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)
  - No GPU or real TIDMAD data needed — interpretation is LLM-only

Run with:
  uv run pytest -m real_run tests/integration/nodes/test_result_interpretation_agent.py -v

DO NOT run in CI.
"""
import os
import pytest
from dotenv import load_dotenv

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput, ModelRunSummary
from nodes.result_interpretation_agent import ResultInterpretationAgent

load_dotenv()

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set — skipping real API test")


# ---------------------------------------------------------------------------
# Synthetic summaries (derived from 5-round punet and 2-round fcnet runs)
# ---------------------------------------------------------------------------

PUNET_SUMMARY = ModelRunSummary(
    model_type="punet",
    run_name="v1",
    status="completed",
    completed_rounds=4,   # 4 success, 1 OOM-skipped
    best_denoising_score=1.57,
    worst_denoising_score=1.2,
    best_config={
        "model_config": {"depth": 4, "multi": 16},
        "train_config": {"lr": 3e-4, "epochs": 15, "batch_size": 128},
        "loss_config":  {"loss_type": "focal", "gamma": 2.0},
    },
    round_scores=[1.2, 1.55, None, 1.57, 1.56],
    round_conclusions=[
        "CE loss achieves acceptable baseline but limited ceiling",
        "Focal loss provides +0.35 improvement over CE — significant gain",
        "Skipped: estimated VRAM exceeds 80% safety limit",
        "Marginal gain (+0.02) over depth=3 — architecture plateau emerging",
        "focal_cw slightly worse than focal with gamma=2 — not beneficial here",
    ],
)

FCNET_SUMMARY = ModelRunSummary(
    model_type="fcnet",
    run_name="v1",
    status="completed",
    completed_rounds=2,
    best_denoising_score=0.9,
    worst_denoising_score=0.85,
    best_config={
        "model_config": {"latent_dims": [800, 200, 40]},
        "train_config": {"lr": 3e-4, "epochs": 15, "batch_size": 64},
        "loss_config":  {"loss_type": "focal", "gamma": 2.0},
    },
    round_scores=[0.85, 0.9],
    round_conclusions=[
        "FCNet lags behind PUNet — likely insufficient temporal modelling",
        "Marginal improvement — still well below PUNet",
    ],
)


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _make_single_model_input(tmp_path) -> InterpretationInput:
    """Single summary — one model, one run."""
    return InterpretationInput(
        summaries=[PUNET_SUMMARY],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "real_api_test"},
        },
    )


def _make_multi_model_input(tmp_path) -> InterpretationInput:
    """Two summaries — punet and fcnet compared together."""
    return InterpretationInput(
        summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "real_api_multimodel"},
        },
    )


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

def _assert_single_model_output(output: InterpretationOutput):
    assert isinstance(output, InterpretationOutput)
    assert "punet" in output.model_types
    assert "punet" in output.model_descriptions
    assert len(output.model_descriptions["punet"]) > 100, "model description suspiciously short"
    assert output.total_experiments == PUNET_SUMMARY.completed_rounds
    assert output.best_denoising_score == 1.57
    assert output.worst_denoising_score == 1.2
    assert output.per_model_best["punet"] == 1.57
    assert output.per_model_worst["punet"] == 1.2
    assert output.best_config is not None
    assert len(output.key_findings) > 0, "LLM produced no key_findings"
    assert len(output.bottlenecks) > 0, "LLM produced no bottlenecks"
    assert len(output.take_home_message) > 10, "take_home_message is suspiciously short"
    for f in output.key_findings:
        assert isinstance(f, str) and len(f) > 0
    for b in output.bottlenecks:
        assert isinstance(b, str) and len(b) > 0


def _assert_multi_model_output(output: InterpretationOutput):
    assert isinstance(output, InterpretationOutput)
    assert "punet" in output.model_types
    assert "fcnet" in output.model_types
    assert "punet" in output.model_descriptions
    assert "fcnet" in output.model_descriptions
    assert output.total_experiments == (
        PUNET_SUMMARY.completed_rounds + FCNET_SUMMARY.completed_rounds
    )
    assert output.best_denoising_score == 1.57   # cross-model max
    assert output.worst_denoising_score == 0.85  # cross-model min
    assert output.per_model_best["punet"] == 1.57
    assert output.per_model_best["fcnet"] == 0.9
    assert output.per_model_worst["punet"] == 1.2
    assert output.per_model_worst["fcnet"] == 0.85
    assert len(output.key_findings) > 0
    assert len(output.bottlenecks) > 0
    assert len(output.take_home_message) > 10


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInterpretationRealGemini:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_single_model(self, tmp_path):
        agent = ResultInterpretationAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
        output = agent.run(_make_single_model_input(tmp_path))
        _assert_single_model_output(output)
        assert (tmp_path / "interpretation_real_api_test.json").exists()

    def test_multi_model(self, tmp_path):
        agent = ResultInterpretationAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
        output = agent.run(_make_multi_model_input(tmp_path))
        _assert_multi_model_output(output)
        assert (tmp_path / "interpretation_real_api_multimodel.json").exists()


class TestInterpretationRealOpenAI:

    def setup_method(self):
        _skip_if_no_key("openai")

    def test_single_model(self, tmp_path):
        agent = ResultInterpretationAgent(provider="openai", model_id="gpt-4o-mini")
        output = agent.run(_make_single_model_input(tmp_path))
        _assert_single_model_output(output)
        assert (tmp_path / "interpretation_real_api_test.json").exists()

    def test_multi_model(self, tmp_path):
        agent = ResultInterpretationAgent(provider="openai", model_id="gpt-4o-mini")
        output = agent.run(_make_multi_model_input(tmp_path))
        _assert_multi_model_output(output)
        assert (tmp_path / "interpretation_real_api_multimodel.json").exists()


# ---------------------------------------------------------------------------
# F.3 — Dual-mode feedback loop test
# ---------------------------------------------------------------------------

# Seed summaries shared across both scenarios.
_SEED_WAVENET = ModelRunSummary(
    model_type="wavenet",
    run_name="adaptive_v1",
    status="completed",
    completed_rounds=3,
    best_denoising_score=5.576,
    worst_denoising_score=5.52,
    best_config={"model_config": {"num_layers": 6}, "train_config": {"lr": 1e-4},
                 "loss_config": {"loss_type": "focal"}},
    round_scores=[5.52, 5.55, 5.576],
    round_conclusions=["stable baseline", "minor improvement", "converged"],
)

_SEED_PUNET = ModelRunSummary(
    model_type="punet",
    run_name="adaptive_v1",
    status="completed",
    completed_rounds=2,
    best_denoising_score=1.29,
    worst_denoising_score=1.20,
    best_config={"model_config": {"depth": 3}, "train_config": {"lr": 1e-4},
                 "loss_config": {"loss_type": "focal"}},
    round_scores=[1.20, 1.29],
    round_conclusions=["baseline established", "marginal improvement"],
)

# The previous proposal that the interpretation agent will evaluate.
# model_name="attn_wavenet" must match a model_type in summaries.
_PREVIOUS_PROPOSAL_REFUTED = {
    "model_name": "attn_wavenet",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.576,
        "predicted_value": 6.5,
        "threshold_for_refutation": 5.8,
        "rationale": "Multi-head attention should capture global context.",
    },
    "inherited_components": [
        {"component": "dilated_causal_conv", "from_model_type": "wavenet",
         "contribution_evidence": "Core mechanism of wavenet's 5.576 score."},
    ],
    "proposed_vocab_links": [],
    "proposed_discoveries": [],
}

_PREVIOUS_PROPOSAL_CONFIRMED = {
    "model_name": "attn_wavenet",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.576,
        "predicted_value": 5.65,
        "threshold_for_refutation": 5.58,
        "rationale": "Targeted attention at the bottleneck should push score past SOTA.",
    },
    "inherited_components": [
        {"component": "dilated_causal_conv", "from_model_type": "wavenet",
         "contribution_evidence": "Core mechanism of wavenet's 5.576 score."},
    ],
    "proposed_vocab_links": [],
    "proposed_discoveries": [],
}


@pytest.mark.dual_mode
@pytest.mark.parametrize("scenario,actual_score,prev_proposal,expected_outcome", [
    ("refuted",   -1.509, _PREVIOUS_PROPOSAL_REFUTED,   "refuted"),
    ("confirmed",  5.68,  _PREVIOUS_PROPOSAL_CONFIRMED, "confirmed"),
])
def test_interpretation_feedback_loop(
    scenario, actual_score, prev_proposal, expected_outcome,
    tmp_path, request,
):
    """F.3 — Dual-mode test for the vocabulary feedback loop.

    Pseudo mode (default): RecordingLLMBridge returns canned per-model
    summaries and synthesis. Prediction evaluation is deterministic —
    the outcome is driven entirely by actual_score vs predicted_value.
    Asserts that discoveries are generated and appear in runtime_vocab.

    Real mode (--real-api-call): runs against the real Gemini API. Skips
    if GEMINI_API_KEY is not set.
    """
    from tests.conftest import make_bridge_factory

    # Proposed model summary with the actual score for this scenario
    proposed_summary = ModelRunSummary(
        model_type="attn_wavenet",
        run_name="adaptive_v1",
        status="completed",
        completed_rounds=3,
        best_denoising_score=actual_score,
        worst_denoising_score=actual_score - 1.0,
        best_config={"model_config": {"attn_heads": 4},
                     "train_config": {"lr": 1e-4},
                     "loss_config": {"loss_type": "focal"}},
        round_scores=[actual_score - 1.0, actual_score - 0.5, actual_score],
        round_conclusions=["unstable", "partial recovery", "best achieved"],
        model_description="Wavenet with multi-head self-attention at the bottleneck.",
    )

    inp = InterpretationInput(
        summaries=[_SEED_WAVENET, _SEED_PUNET, proposed_summary],
        previous_proposal=prev_proposal,
        runtime_vocab=[],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "test"},
        },
    )

    bridge_factory = make_bridge_factory(request, "result_interpretation_agent")
    agent = ResultInterpretationAgent(bridge_factory=bridge_factory)

    output = agent.run(inp)

    # --- Core feedback loop assertions (both modes) ---

    # Prediction was evaluated (not skipped)
    assert output.prediction_evaluation is not None, \
        "prediction_evaluation is None — feedback loop did not run"

    # Bug 1 regression: actual_value must not be None
    assert output.prediction_evaluation["actual_value"] is not None, \
        "actual_value is None — metric alias not resolved (Bug 1 regression)"

    # Outcome matches expectation
    assert output.prediction_evaluation["outcome"] == expected_outcome, (
        f"Expected outcome={expected_outcome!r}, "
        f"got {output.prediction_evaluation['outcome']!r}"
    )

    # At least one discovery was generated
    assert len(output.new_discoveries) >= 1, \
        "No discoveries generated — generate_discoveries() returned empty"

    # Discovery description contains the outcome label (CONFIRMED / REFUTED)
    first_discovery_desc = output.new_discoveries[0].description
    assert expected_outcome.upper() in first_discovery_desc, (
        f"Expected '{expected_outcome.upper()}' in first discovery, "
        f"got: {first_discovery_desc!r}"
    )

    # Bug 2 regression: discovery must appear in runtime_vocab
    discovery_entries = [v for v in output.runtime_vocab if v.kind == "discovery"]
    assert len(discovery_entries) >= 1, \
        "No discovery in runtime_vocab — feedback loop broken (Bug 2 regression)"

    # Storage: output file written
    assert (tmp_path / "interpretation_test.json").exists(), \
        "Output file not written — persistence step failed"

    print(f"\n  [{scenario}] outcome={output.prediction_evaluation['outcome']!r} "
          f"actual={output.prediction_evaluation['actual_value']:.3f} "
          f"discoveries={len(output.new_discoveries)}")
