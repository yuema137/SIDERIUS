"""
Real-API integration tests for result_interpretation_agent.

Requires:
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)
  - No GPU or real TIDMAD data needed — interpretation is LLM-only

Run with:
  uv run pytest -m real_run tests/integration/agent/test_interpretation_real.py -v

DO NOT run in CI.
"""
import os
import pytest
from dotenv import load_dotenv

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput, SummaryGroup
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
# Synthetic records that look like a real tuning run
# ---------------------------------------------------------------------------

PUNET_RECORDS = [
    {
        "exp_id": "punet_v1_001",
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-01-01 00:00:00",
        "file_index": 6,
        "params": {
            "model_config": {"depth": 2, "multi": 16},
            "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 128},
            "loss_config":  {"loss_type": "ce"},
        },
        "results": {"denoising_score": 1.2, "final_loss": 0.45},
        "denoising_score": 1.2,
        "memory": {
            "hypothesis": "Baseline CE loss with shallow arch",
            "conclusion": "CE loss achieves acceptable baseline but limited ceiling",
            "discovery": "Shallow arch insufficient for complex signal patterns",
            "memory_update": "Try focal loss and deeper architecture",
        },
    },
    {
        "exp_id": "punet_v1_002",
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-01-01 01:00:00",
        "file_index": 6,
        "params": {
            "model_config": {"depth": 3, "multi": 16},
            "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 128},
            "loss_config":  {"loss_type": "focal", "gamma": 2.0},
        },
        "results": {"denoising_score": 1.55, "final_loss": 0.38},
        "denoising_score": 1.55,
        "memory": {
            "hypothesis": "Focal loss with gamma=2 should improve class imbalance handling",
            "conclusion": "Focal loss provides +0.35 improvement over CE — significant gain",
            "discovery": "Class imbalance is a key bottleneck; focal loss addresses it",
            "memory_update": "Focal with gamma=2 is strong baseline — explore deeper arch",
        },
    },
    {
        "exp_id": "punet_v1_003",
        "status": "skipped_oom_risk",
        "model_type": "punet",
        "timestamp": "2026-01-01 02:00:00",
        "file_index": 6,
        "params": {
            "model_config": {"depth": 5, "multi": 32},
            "train_config": {"lr": 1e-4, "epochs": 20, "batch_size": 256},
            "loss_config":  {"loss_type": "focal"},
        },
        "results": {},
        "denoising_score": None,
        "memory": {
            "hypothesis": "Deeper architecture with larger capacity",
            "conclusion": "Skipped: estimated VRAM exceeds 80% safety limit",
            "discovery": "depth=5 multi=32 is too large for available GPU",
            "memory_update": "Reduce depth to 4 or multi to 16 to stay within VRAM budget",
        },
    },
    {
        "exp_id": "punet_v1_004",
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-01-01 03:00:00",
        "file_index": 6,
        "params": {
            "model_config": {"depth": 4, "multi": 16},
            "train_config": {"lr": 3e-4, "epochs": 15, "batch_size": 128},
            "loss_config":  {"loss_type": "focal", "gamma": 2.0},
        },
        "results": {"denoising_score": 1.57, "final_loss": 0.36},
        "denoising_score": 1.57,
        "memory": {
            "hypothesis": "Deeper arch (depth=4) with same focal loss should improve further",
            "conclusion": "Marginal gain (+0.02) over depth=3 — architecture plateau emerging",
            "discovery": "Diminishing returns from depth after depth=3 with this U-Net design",
            "memory_update": "Architecture appears saturated — new design may be needed",
        },
    },
    {
        "exp_id": "punet_v1_005",
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-01-01 04:00:00",
        "file_index": 6,
        "params": {
            "model_config": {"depth": 4, "multi": 24},
            "train_config": {"lr": 1e-4, "epochs": 20, "batch_size": 64},
            "loss_config":  {"loss_type": "focal_cw"},
        },
        "results": {"denoising_score": 1.56, "final_loss": 0.37},
        "denoising_score": 1.56,
        "memory": {
            "hypothesis": "Class-weighted focal loss should further address imbalance",
            "conclusion": "focal_cw slightly worse than focal with gamma=2 — not beneficial here",
            "discovery": "Standard focal gamma=2 is better than class-weighted variant for this data",
            "memory_update": "Stick with focal gamma=2; architecture capacity is the real bottleneck",
        },
    },
]

FCNET_RECORDS = [
    {
        "exp_id": "fcnet_v1_001",
        "status": "success",
        "model_type": "fcnet",
        "timestamp": "2026-01-01 00:00:00",
        "file_index": 6,
        "params": {
            "model_config": {"latent_dims": [400, 40]},
            "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 128},
            "loss_config":  {"loss_type": "ce"},
        },
        "results": {"denoising_score": 0.85},
        "denoising_score": 0.85,
        "memory": {
            "hypothesis": "Baseline FCNet with CE loss",
            "conclusion": "FCNet lags behind PUNet — likely insufficient temporal modelling",
            "discovery": "Fully connected arch struggles with long-range temporal dependencies",
            "memory_update": "FCNet architecture is fundamentally limited for this task",
        },
    },
    {
        "exp_id": "fcnet_v1_002",
        "status": "success",
        "model_type": "fcnet",
        "timestamp": "2026-01-01 01:00:00",
        "file_index": 6,
        "params": {
            "model_config": {"latent_dims": [800, 200, 40]},
            "train_config": {"lr": 3e-4, "epochs": 15, "batch_size": 64},
            "loss_config":  {"loss_type": "focal", "gamma": 2.0},
        },
        "results": {"denoising_score": 0.9},
        "denoising_score": 0.9,
        "memory": {
            "hypothesis": "Wider/deeper FCNet with focal loss",
            "conclusion": "Marginal improvement — still well below PUNet",
            "discovery": "Capacity increases yield diminishing returns for FCNet",
            "memory_update": "FCNet has hit its ceiling; architecture change needed",
        },
    },
]


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _make_single_model_input(tmp_path) -> InterpretationInput:
    """Single summary group — one model, one run."""
    return InterpretationInput(
        summaries=[SummaryGroup(model_type="punet", run_name="v1", records=PUNET_RECORDS)],
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "real_api_test"},
        },
    )


def _make_multi_model_input(tmp_path) -> InterpretationInput:
    """Two summary groups — punet and fcnet compared together."""
    return InterpretationInput(
        summaries=[
            SummaryGroup(model_type="punet",  run_name="v1", records=PUNET_RECORDS),
            SummaryGroup(model_type="fcnet",  run_name="v1", records=FCNET_RECORDS),
        ],
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
    assert output.total_experiments == len(PUNET_RECORDS)
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
    assert output.total_experiments == len(PUNET_RECORDS) + len(FCNET_RECORDS)
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
