"""
Tests for nodes/result_interpretation_agent.py

LLM calls are mocked — these tests validate:
  - Deterministic pre-computation (best/worst scores extracted correctly, per-model and overall)
  - LLM response merged correctly into InterpretationOutput
  - Output validated against schema
  - Output file written to correct path
  - Multiple summary groups handled correctly
  - Empty summaries with model_types handled correctly
  - Unknown model type raises FileNotFoundError
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput, SummaryGroup
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.result_interpretation_agent import ResultInterpretationAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Phase 1 response (per-model summarization)
FAKE_PER_MODEL_RESPONSE = {
    "key_findings": [
        "focal loss with gamma=2 consistently outperforms ce by ~0.05",
        "increasing depth beyond 3 yields diminishing returns",
    ],
    "bottlenecks": [
        "architecture capacity ceiling at depth=3 — score plateaued across 8 experiments",
    ],
    "best_config_analysis": "Depth 4 with focal loss gamma=2 yielded the best result.",
    "score_trend": "Scores improved initially but plateaued after depth=3.",
}

# Phase 2 response (cross-model synthesis)
FAKE_SYNTHESIS_RESPONSE = {
    "key_findings": [
        "punet outperforms fcnet by 0.9 points at best",
        "both models plateau at similar training budgets",
    ],
    "bottlenecks": [
        "all current architectures hit a capacity ceiling",
    ],
    "take_home_message": "The current architecture has saturated; a fundamentally different design is needed.",
}

RECORD_A = {
    "exp_id": "punet_v1_001", "status": "success", "model_type": "punet",
    "timestamp": "2026-01-01 00:00:00", "file_index": 6,
    "params": {"model_config": {"depth": 3}, "train_config": {"lr": 1e-4}, "loss_config": {"loss_type": "focal"}},
    "results": {"denoising_score": 1.5}, "denoising_score": 1.5,
}
RECORD_B = {
    "exp_id": "punet_v1_002", "status": "success", "model_type": "punet",
    "timestamp": "2026-01-01 01:00:00", "file_index": 6,
    "params": {"model_config": {"depth": 4}, "train_config": {"lr": 3e-4}, "loss_config": {"loss_type": "focal"}},
    "results": {"denoising_score": 1.8}, "denoising_score": 1.8,
}
RECORD_OOM = {
    "exp_id": "punet_v1_003", "status": "skipped_oom_risk", "model_type": "punet",
    "timestamp": "2026-01-01 02:00:00", "file_index": 6,
    "params": {}, "results": {}, "denoising_score": None,
}
RECORD_FCNET = {
    "exp_id": "fcnet_v1_001", "status": "success", "model_type": "fcnet",
    "timestamp": "2026-01-01 03:00:00", "file_index": 6,
    "params": {"model_config": {}, "train_config": {}, "loss_config": {}},
    "results": {"denoising_score": 0.9}, "denoising_score": 0.9,
}


@pytest.fixture
def agent():
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        # First call(s) = phase 1 (per-model), last call = phase 2 (synthesis)
        # For single-model tests, only phase 1 is called (synthesis skipped).
        # For multi-model tests, N phase 1 calls + 1 phase 2 call.
        MockBridge.return_value.generate.side_effect = _llm_dispatch
        a = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        yield a


def _llm_dispatch(system_prompt: str, user_prompt: str) -> dict:
    """Route mock LLM calls to the right fake response based on the system prompt."""
    if "ONE model architecture" in system_prompt:
        return FAKE_PER_MODEL_RESPONSE
    else:
        return FAKE_SYNTHESIS_RESPONSE


def make_input(records, model_type="punet", run_name="r1", workspace="/tmp/interp_test"):
    return InterpretationInput(
        summaries=[SummaryGroup(model_type=model_type, run_name=run_name, records=records)],
        storage={"backend": "local", "local": {"workspace": workspace, "run_name": run_name}},
    )


def make_multi_input(groups, workspace="/tmp/interp_test", run_name="r1"):
    return InterpretationInput(
        summaries=[SummaryGroup(**g) for g in groups],
        storage={"backend": "local", "local": {"workspace": workspace, "run_name": run_name}},
    )


# ---------------------------------------------------------------------------
# Single-group tests
# ---------------------------------------------------------------------------

class TestSingleGroup:

    def test_best_score_extracted(self, agent, tmp_path):
        inp = make_input([RECORD_A, RECORD_B], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.best_denoising_score == 1.8

    def test_worst_score_extracted(self, agent, tmp_path):
        inp = make_input([RECORD_A, RECORD_B], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.worst_denoising_score == 1.5

    def test_best_config_from_best_record(self, agent, tmp_path):
        inp = make_input([RECORD_A, RECORD_B], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.best_config["model_config"]["depth"] == 4

    def test_oom_excluded_from_scores(self, agent, tmp_path):
        inp = make_input([RECORD_OOM], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.best_denoising_score is None
        assert output.worst_denoising_score is None

    def test_total_experiments_includes_oom(self, agent, tmp_path):
        inp = make_input([RECORD_A, RECORD_OOM], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.total_experiments == 2

    def test_per_model_scores_populated(self, agent, tmp_path):
        inp = make_input([RECORD_A, RECORD_B], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.per_model_best["punet"] == 1.8
        assert output.per_model_worst["punet"] == 1.5

    def test_llm_findings_merged(self, agent, tmp_path):
        """Single-model: phase 1 findings used directly, synthesis skipped."""
        inp = make_input([RECORD_A], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.key_findings == FAKE_PER_MODEL_RESPONSE["key_findings"]
        assert output.bottlenecks == FAKE_PER_MODEL_RESPONSE["bottlenecks"]
        # take_home_message is constructed from per-model summary in single-model mode
        assert "punet" in output.take_home_message.lower() or "plateau" in output.take_home_message.lower()

    def test_per_model_summaries_populated(self, agent, tmp_path):
        inp = make_input([RECORD_A, RECORD_B], workspace=str(tmp_path))
        output = agent.run(inp)
        assert "punet" in output.per_model_summaries
        assert output.per_model_summaries["punet"]["key_findings"] == FAKE_PER_MODEL_RESPONSE["key_findings"]

    def test_output_written_to_file(self, agent, tmp_path):
        inp = make_input([RECORD_A], workspace=str(tmp_path), run_name="myrun")
        agent.run(inp)
        out_path = tmp_path / "interpretation_myrun.json"
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert "punet" in data["model_types"]
        assert data["best_denoising_score"] == 1.5

    def test_output_is_valid_interpretation_output(self, agent, tmp_path):
        inp = make_input([RECORD_A, RECORD_B], workspace=str(tmp_path))
        output = agent.run(inp)
        assert isinstance(output, InterpretationOutput)
        assert "punet" in output.model_types

    def test_model_description_loaded(self, agent, tmp_path):
        inp = make_input([RECORD_A], workspace=str(tmp_path))
        output = agent.run(inp)
        assert "punet" in output.model_descriptions
        assert len(output.model_descriptions["punet"]) > 100
        assert "PUNet" in output.model_descriptions["punet"]


# ---------------------------------------------------------------------------
# Multi-group tests
# ---------------------------------------------------------------------------

class TestMultiGroup:

    def test_two_models_both_in_output(self, agent, tmp_path):
        inp = make_multi_input([
            {"model_type": "punet", "run_name": "v1", "records": [RECORD_A, RECORD_B]},
            {"model_type": "fcnet", "run_name": "v1", "records": [RECORD_FCNET]},
        ], workspace=str(tmp_path))
        output = agent.run(inp)
        assert "punet" in output.model_types
        assert "fcnet" in output.model_types

    def test_overall_best_is_cross_model_max(self, agent, tmp_path):
        inp = make_multi_input([
            {"model_type": "punet", "run_name": "v1", "records": [RECORD_A, RECORD_B]},
            {"model_type": "fcnet", "run_name": "v1", "records": [RECORD_FCNET]},
        ], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.best_denoising_score == 1.8
        assert output.worst_denoising_score == 0.9

    def test_per_model_scores_independent(self, agent, tmp_path):
        inp = make_multi_input([
            {"model_type": "punet", "run_name": "v1", "records": [RECORD_A, RECORD_B]},
            {"model_type": "fcnet", "run_name": "v1", "records": [RECORD_FCNET]},
        ], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.per_model_best["punet"] == 1.8
        assert output.per_model_best["fcnet"] == 0.9

    def test_total_experiments_across_all_groups(self, agent, tmp_path):
        inp = make_multi_input([
            {"model_type": "punet", "run_name": "v1", "records": [RECORD_A, RECORD_B]},
            {"model_type": "fcnet", "run_name": "v1", "records": [RECORD_FCNET]},
        ], workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.total_experiments == 3

    def test_synthesis_used_for_multi_model(self, agent, tmp_path):
        """Multi-model: phase 2 synthesis call produces the final findings."""
        inp = make_multi_input([
            {"model_type": "punet", "run_name": "v1", "records": [RECORD_A]},
            {"model_type": "fcnet", "run_name": "v1", "records": [RECORD_FCNET]},
        ], workspace=str(tmp_path))
        output = agent.run(inp)
        # Synthesis response should be used for final output
        assert output.key_findings == FAKE_SYNTHESIS_RESPONSE["key_findings"]
        assert output.take_home_message == FAKE_SYNTHESIS_RESPONSE["take_home_message"]

    def test_per_model_summaries_for_all_models(self, agent, tmp_path):
        inp = make_multi_input([
            {"model_type": "punet", "run_name": "v1", "records": [RECORD_A]},
            {"model_type": "fcnet", "run_name": "v1", "records": [RECORD_FCNET]},
        ], workspace=str(tmp_path))
        output = agent.run(inp)
        assert "punet" in output.per_model_summaries
        assert "fcnet" in output.per_model_summaries

    def test_descriptions_loaded_for_all_models(self, agent, tmp_path):
        inp = make_multi_input([
            {"model_type": "punet", "run_name": "v1", "records": [RECORD_A]},
            {"model_type": "fcnet", "run_name": "v1", "records": [RECORD_FCNET]},
        ], workspace=str(tmp_path))
        output = agent.run(inp)
        assert "punet" in output.model_descriptions
        assert "fcnet" in output.model_descriptions


# ---------------------------------------------------------------------------
# model_types only (no summaries)
# ---------------------------------------------------------------------------

class TestModelTypesOnly:

    def test_descriptions_only_no_summaries(self, agent, tmp_path):
        inp = InterpretationInput(
            model_types=["punet"],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert "punet" in output.model_types
        assert "punet" in output.model_descriptions
        assert output.total_experiments == 0
        assert output.best_denoising_score is None


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrorCases:

    def test_unknown_model_type_raises(self, tmp_path):
        inp = InterpretationInput(
            summaries=[SummaryGroup(model_type="nonexistent_model", run_name="v1", records=[])],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        with pytest.raises(FileNotFoundError, match="nonexistent_model"):
            agent.run(inp)

    def test_no_model_provided_raises(self):
        with pytest.raises(Exception, match="At least one model type"):
            InterpretationInput()
