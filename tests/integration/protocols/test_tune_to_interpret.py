"""
End-to-end integration test: tune_ml_hyperparam_agent → result_interpretation_agent.

Exercises the full edge:
  1. Run a real training loop (one record) via tune_ml_hyperparam_agent
  2. Apply the protocol local_all_records to produce InterpretationInput
  3. Run result_interpretation_agent and validate InterpretationOutput

This is a Tier 2 protocol test — it verifies that the protocol correctly
connects the two nodes, not just that each node works in isolation.

Requires:
  - Real TIDMAD data at /home/klz/Data/TIDMAD/
  - GEMINI_API_KEY set in the environment (or .env file)
  - CUDA GPU

Run with:
  uv run pytest -m real_run tests/integration/protocols/test_tune_to_interpret.py -v -s

DO NOT run in CI.
"""
import os
import pytest
from dotenv import load_dotenv

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput, ExperimentRecord
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import local_all_records
from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.integration.nodes.test_tune_ml_hyperparam_agent import run_one_loop, _skip_if_no_data

load_dotenv()

pytestmark = pytest.mark.real_run

DATA_DIR = "/home/klz/Data/TIDMAD/"


def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set")


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

class TestTuneToInterpret:

    def setup_method(self):
        _skip_if_no_key("gemini")
        _skip_if_no_data()

    def test_fcnet_record_feeds_into_interpretation(self, tmp_path):
        """
        Run one real fcnet training loop, then interpret the resulting record.
        Validates the full tune → interpret edge.
        """
        # --- Step 1: run one tuning loop (same config as cfg0 in test_real_run) ---
        model_cfg  = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [400, 40]}
        train_cfg  = {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"}
        loss_cfg   = {"loss_type": "ce"}

        record = run_one_loop(
            provider="gemini",
            model_type="fcnet",
            loss_cfg=loss_cfg,
            workspace=str(tmp_path),
            model_cfg=model_cfg,
            train_cfg=train_cfg,
        )
        assert record["status"] == "success"
        assert record["denoising_score"] is not None

        # --- Step 2: apply the protocol to produce InterpretationInput ---
        tuning_output = HyperparamTuningOutput(
            run_name="tune_to_interpret",
            model_type="fcnet",
            file_index=6,
            status="completed",
            completed_rounds=1,
            total_attempts=1,
            all_records=[ExperimentRecord.model_validate(record)],
            started_at="2026-01-01T00:00:00",
            finished_at="2026-01-01T01:00:00",
        )
        storage = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="tune_to_interpret"),
        )
        inp = local_all_records(tuning_output, storage)

        agent = ResultInterpretationAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
        output = agent.run(inp)

        # --- Step 3: validate the output ---
        assert "fcnet" in output.model_types
        assert "fcnet" in output.model_descriptions
        assert output.total_experiments == 1
        assert output.best_denoising_score == record["denoising_score"]
        assert output.worst_denoising_score == record["denoising_score"]
        assert output.per_model_best["fcnet"] == record["denoising_score"]
        assert output.per_model_worst["fcnet"] == record["denoising_score"]
        assert output.best_config is not None
        assert len(output.key_findings) > 0
        assert len(output.bottlenecks) > 0
        assert len(output.take_home_message) > 10

        out_file = tmp_path / "interpretation_tune_to_interpret.json"
        assert out_file.exists()

        print(f"\n  denoising_score : {record['denoising_score']}")
        print(f"  key_findings    : {output.key_findings}")
        print(f"  take_home       : {output.take_home_message}")
