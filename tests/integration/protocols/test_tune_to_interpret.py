"""
End-to-end integration test: tune_ml_hyperparam_agent → result_interpretation_agent.

Runs a real training loop (one record), feeds the output directly into the
interpretation agent, and validates the full InterpretationOutput.

Requires:
  - Real TIDMAD data at /home/klz/Data/TIDMAD/
  - GEMINI_API_KEY set in the environment (or .env file)
  - CUDA GPU

Run with:
  uv run pytest -m real_run tests/integration/agent/test_tune_to_interpret.py -v -s

DO NOT run in CI.
"""
import os
import pytest
from dotenv import load_dotenv

from agent.schemas.interpretation import InterpretationInput, SummaryGroup
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

        # --- Step 2: feed the record into the interpretation agent ---
        inp = InterpretationInput(
            summaries=[SummaryGroup(model_type="fcnet", run_name="tune_to_interpret", records=[record])],
            storage={
                "backend": "local",
                "local": {"workspace": str(tmp_path), "run_name": "tune_to_interpret"},
            },
        )

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
