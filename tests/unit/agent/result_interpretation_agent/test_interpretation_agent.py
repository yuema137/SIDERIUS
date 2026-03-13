"""
Tests for result_interpretation_agent.py

LLM calls are mocked — these tests validate:
  - Deterministic pre-computation (best score/config extracted correctly)
  - LLM response is merged correctly into InterpretationOutput
  - Output is validated against the schema
  - Output file is written to the correct path
  - Empty records are handled gracefully
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.result_interpretation_agent import ResultInterpretationAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_LLM_RESPONSE = {
    "key_findings": [
        "focal loss with gamma=2 consistently outperforms ce by ~0.05",
        "increasing depth beyond 3 yields diminishing returns",
    ],
    "bottlenecks": [
        "architecture capacity ceiling at depth=3 — score plateaued across 8 experiments",
    ],
    "take_home_message": "The current architecture has saturated; a fundamentally different design is needed.",
}

SUCCESS_RECORD = {
    "exp_id": "punet_v1_001",
    "status": "success",
    "model_type": "punet",
    "timestamp": "2026-01-01 00:00:00",
    "file_index": 6,
    "params": {"model_config": {"depth": 3}, "train_config": {"lr": 1e-4}, "loss_config": {"loss_type": "focal"}},
    "results": {"denoising_score": 1.5, "final_loss": 0.1},
    "denoising_score": 1.5,
}

BETTER_RECORD = {
    "exp_id": "punet_v1_002",
    "status": "success",
    "model_type": "punet",
    "timestamp": "2026-01-01 01:00:00",
    "file_index": 6,
    "params": {"model_config": {"depth": 4}, "train_config": {"lr": 3e-4}, "loss_config": {"loss_type": "focal"}},
    "results": {"denoising_score": 1.8, "final_loss": 0.08},
    "denoising_score": 1.8,
}

OOM_RECORD = {
    "exp_id": "punet_v1_003",
    "status": "skipped_oom_risk",
    "model_type": "punet",
    "timestamp": "2026-01-01 02:00:00",
    "file_index": 6,
    "params": {},
    "results": {},
    "denoising_score": None,
}


@pytest.fixture
def agent():
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.return_value = FAKE_LLM_RESPONSE
        a = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        yield a


def make_input(records, workspace="/tmp/interp_test", run_name="r1"):
    return InterpretationInput.model_validate({
        "summary_records": records,
        "model_type": "punet",
        "storage": {"backend": "local", "local": {"workspace": workspace, "run_name": run_name}},
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResultInterpretationAgentRun:

    def test_best_score_extracted_correctly(self, agent, tmp_path):
        inp = make_input([SUCCESS_RECORD, BETTER_RECORD], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.best_denoising_score == 1.8

    def test_best_config_is_from_best_record(self, agent, tmp_path):
        inp = make_input([SUCCESS_RECORD, BETTER_RECORD], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.best_config["model_config"]["depth"] == 4

    def test_oom_records_excluded_from_best(self, agent, tmp_path):
        inp = make_input([OOM_RECORD], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.best_denoising_score is None
        assert output.best_config is None

    def test_total_experiments_includes_oom(self, agent, tmp_path):
        inp = make_input([SUCCESS_RECORD, OOM_RECORD], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.total_experiments == 2

    def test_llm_findings_merged_into_output(self, agent, tmp_path):
        inp = make_input([SUCCESS_RECORD], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.key_findings == FAKE_LLM_RESPONSE["key_findings"]
        assert output.bottlenecks == FAKE_LLM_RESPONSE["bottlenecks"]
        assert output.take_home_message == FAKE_LLM_RESPONSE["take_home_message"]

    def test_output_written_to_file(self, agent, tmp_path):
        inp = make_input([SUCCESS_RECORD], workspace=str(tmp_path), run_name="myrun")
        agent.run(inp)
        out_path = tmp_path / "interpretation_myrun.json"
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert data["model_type"] == "punet"
        assert data["best_denoising_score"] == 1.5

    def test_empty_records_returns_valid_output(self, agent, tmp_path):
        inp = make_input([], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.total_experiments == 0
        assert output.best_denoising_score is None
        assert isinstance(output.key_findings, list)

    def test_output_is_valid_interpretation_output(self, agent, tmp_path):
        inp = make_input([SUCCESS_RECORD, BETTER_RECORD], workspace=str(tmp_path))
        output = agent.run(inp)
        assert isinstance(output, InterpretationOutput)
        assert output.model_type == "punet"

    def test_model_description_loaded_into_output(self, agent, tmp_path):
        inp = make_input([SUCCESS_RECORD], workspace=str(tmp_path))
        output = agent.run(inp)
        assert isinstance(output.model_description, str)
        assert len(output.model_description) > 100, "description is suspiciously short"
        assert "PUNet" in output.model_description

    def test_unknown_model_type_raises(self, tmp_path):
        inp = make_input([SUCCESS_RECORD], workspace=str(tmp_path))
        inp = inp.model_copy(update={"model_type": "nonexistent_model"})
        agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        with pytest.raises(FileNotFoundError, match="nonexistent_model"):
            agent.run(inp)
