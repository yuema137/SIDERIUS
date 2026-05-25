"""
Tier 2 integration test: tune_ml_hyperparam_agent → result_interpretation_agent.

Exercises the full edge:
  1. Run HyperparamTuningAgent.run() for 1 round (real LLM + GPU)
  2. Apply protocol local_all_records to convert output → InterpretationInput
     (HyperparamTuningOutput → ModelRunSummary, raw records discarded)
  3. Run ResultInterpretationAgent and validate InterpretationOutput

Requires:
  - Real TIDMAD data at /home/klz/Data/TIDMAD/
  - GEMINI_API_KEY set in the environment (or .env file)
  - CUDA GPU

Run with:
  uv run pytest -m real_run tests/integration/protocols/test_tune_to_interpret.py -v -s

DO NOT run in CI.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationOutput, ModelRunSummary
from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import local_all_records
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.result_interpretation_agent import ResultInterpretationAgent

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

pytestmark = pytest.mark.real_run

try:
    from execute_tools.data_paths import TIDMAD_DATA_DIR

    DATA_DIR = TIDMAD_DATA_DIR
except (FileNotFoundError, ImportError):
    DATA_DIR = "/home/klz/Data/TIDMAD/"


def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set")


def _skip_if_no_data():
    if not os.path.isdir(DATA_DIR):
        pytest.skip(f"Real data not found at {DATA_DIR}")


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


class TestTuneToInterpret:
    def setup_method(self):
        _skip_if_no_key("gemini")
        _skip_if_no_data()

    def test_punet_tuning_feeds_into_interpretation(self, tmp_path):
        """
        Run one real punet tuning round, apply the protocol, then interpret.
        Validates the full tune → interpret edge using the node contract.
        """
        # --- Step 1: run tuning agent for 1 round ---
        tune_input = HyperparamTuningInput(
            model_type="punet",
            file_index=6,
            max_rounds=1,
            expert_advice="Test run. Use minimal epochs.",
            llm_provider="gemini",
            llm_model_id="gemini-3.1-flash-lite-preview",
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(
                    workspace=str(tmp_path / "tuning"),
                    run_name="tune_test",
                ),
            ),
        )

        tune_output = HyperparamTuningAgent().run(tune_input)
        assert isinstance(tune_output, HyperparamTuningOutput)
        assert tune_output.status in ("completed", "partial")
        assert tune_output.best_denoising_score is not None

        print(f"\n  Tuning score: {tune_output.best_denoising_score}")

        # --- Step 2: apply protocol (converts to ModelRunSummary) ---
        interp_storage = StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=str(tmp_path / "interp"),
                run_name="interp_test",
            ),
        )
        interp_input = local_all_records(tune_output, interp_storage)

        # Verify protocol produced ModelRunSummary, not raw records
        assert len(interp_input.summaries) == 1
        summary = interp_input.summaries[0]
        assert isinstance(summary, ModelRunSummary)
        assert summary.model_type == "punet"
        assert summary.best_denoising_score == tune_output.best_denoising_score
        assert len(summary.round_scores) >= 1
        assert len(summary.round_conclusions) >= 1

        # --- Step 3: run interpretation agent ---
        interp_agent = ResultInterpretationAgent(
            provider="gemini",
            model_id="gemini-3.1-flash-lite-preview",
        )
        output = interp_agent.run(interp_input)

        # --- Step 4: validate output ---
        assert isinstance(output, InterpretationOutput)
        assert "punet" in output.model_types
        assert "punet" in output.model_descriptions
        assert output.total_experiments == tune_output.completed_rounds
        assert output.best_denoising_score == tune_output.best_denoising_score
        assert output.per_model_best["punet"] == tune_output.best_denoising_score
        assert len(output.key_findings) > 0
        assert len(output.take_home_message) > 10

        # Per-model summary from phase 1 should be present
        assert "punet" in output.model_knowledge_cache

        out_file = tmp_path / "interp" / "interpretation_interp_test.json"
        assert out_file.exists()

        print(f"  Key findings : {output.key_findings}")
        print(f"  Take-home    : {output.take_home_message}")
