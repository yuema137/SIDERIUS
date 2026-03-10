"""
Real-run integration tests for the full agent research loop.

Requires:
  - Real TIDMAD data at /home/klz/Data/TIDMAD/
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)

These tests are skipped automatically when API keys are missing.
Run locally with:
  uv run pytest -m real_run -v

DO NOT run these in CI (GitHub Actions or equivalent).
"""
import os
import time
import pytest
from dotenv import load_dotenv

from core.sandbox_executor import TidmadSandbox
from agent.llm_bridge import LLMBridge

load_dotenv()

pytestmark = pytest.mark.real_run

DATA_DIR = "/home/klz/Data/TIDMAD/"

# ==========================================
# Shared skip guards
# ==========================================

def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set — skipping real run test")


def _skip_if_no_data():
    if not os.path.isdir(DATA_DIR):
        pytest.skip(f"Real data not found at {DATA_DIR}")


# ==========================================
# Helpers
# ==========================================

# Small model configs: segmentation_size matches real data format (40000),
# but architectures are intentionally minimal so training/inference are fast.
MODEL_CONFIGS = {
    "punet": {
        "model_type": "punet",
        "segmentation_size": 40000,
        "depth": 2,
        "multi": 8,
        "kernel_size": 7,
        "embedding_dim": 8,
    },
    "fcnet": {
        "model_type": "fcnet",
        "segmentation_size": 40000,
        "latent_dims": [400, 40],
    },
    "transformer": {
        "model_type": "transformer",
        "segmentation_size": 10000,
        "embedding_dim": 16,
        "nhead": 4,
        "num_layers": 1,
        "dim_feedforward": 64,
    },
}

LOSS_CONFIGS = {
    "punet":       [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
    "fcnet":       [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}, {"loss_type": "smooth_l1"}],
    "transformer": [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
}

TRAIN_CONFIG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cuda"}


def run_one_loop(provider: str, model_type: str, loss_cfg: dict, workspace: str):
    """
    Runs one full agent loop iteration:
      plan -> train -> inference -> score -> reflect -> save record
    """
    run_name = f"real_{provider}_{model_type}_{loss_cfg['loss_type']}"
    exp_id = f"exp_{model_type}_{loss_cfg['loss_type']}_{int(time.time())}"

    model_ids = {
        "gemini": "gemini-3.1-flash-lite-preview",
        "openai": "gpt-4o",
    }
    sandbox = TidmadSandbox(workspace=workspace, run_name=run_name)
    brain = LLMBridge(provider=provider, model_id=model_ids[provider])

    # --- THINK: get plan from LLM ---
    memory_history = sandbox.get_summary()
    decision = brain.plan(
        memory_history=memory_history,
        expert_advice=f"Test run: use {model_type} with {loss_cfg['loss_type']} loss. Use minimal epochs.",
        force_model=model_type,
    )
    assert "model_config" in decision or "model_type" in decision, \
        f"LLM plan response missing expected keys: {decision}"

    params = {
        "exp_id": exp_id,
        "run_name": run_name,
        "model_type": model_type,
        "model_config": MODEL_CONFIGS[model_type],
        "train_config": TRAIN_CONFIG,
        "loss_config": loss_cfg,
    }

    # --- ACT: train -> inference -> score ---
    train_result = sandbox.execute_training(
        exp_id=exp_id, run_name=run_name, model_type=model_type,
        m_cfg=MODEL_CONFIGS[model_type], t_cfg=TRAIN_CONFIG, l_cfg=loss_cfg,
    )
    assert train_result["status"] == "success", (
        f"Training failed for {model_type}/{loss_cfg['loss_type']}:\n"
        f"{train_result.get('message', '(no message)')}"
    )

    inf_result = sandbox.execute_inference(
        exp_id=exp_id, run_name=run_name, model_type=model_type,
        m_cfg=MODEL_CONFIGS[model_type], l_cfg=loss_cfg,
    )
    assert inf_result["status"] == "success", (
        f"Inference failed for {model_type}/{loss_cfg['loss_type']}:\n"
        f"{inf_result.get('message', '(no message)')}"
    )

    score_result = sandbox.execute_scoring(
        exp_id=exp_id, run_name=run_name, model_type=model_type,
        m_cfg=MODEL_CONFIGS[model_type], t_cfg=TRAIN_CONFIG, l_cfg=loss_cfg,
    )
    assert score_result["status"] == "success", (
        f"Scoring failed for {model_type}/{loss_cfg['loss_type']}:\n"
        f"{score_result.get('message', '(no message)')}"
    )
    assert "denoising_score" in score_result["results"] or "results" in score_result

    # --- REFLECT ---
    reflection = brain.reflect(
        exp_id=exp_id,
        hypothesis=decision.get("hypothesis", "Test run"),
        actual_results=score_result["results"],
    )
    assert "conclusion" in reflection, f"Reflection missing 'conclusion': {reflection}"
    assert "discovery" in reflection, f"Reflection missing 'discovery': {reflection}"

    # --- COMMIT ---
    record = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "params": params,
        "results": score_result.get("results", {}),
        "denoising_score": score_result.get("results", {}).get("denoising_score"),
        "memory": {
            "hypothesis": decision.get("hypothesis"),
            "conclusion": reflection.get("conclusion"),
            "discovery": reflection.get("discovery"),
            "memory_update": reflection.get("memory_update"),
        },
    }
    sandbox.save_record(record)

    # --- Verify summary was written ---
    summary = sandbox.get_summary()
    assert any(r["exp_id"] == exp_id for r in summary), \
        "Record was not found in summary after save"

    return record


# ==========================================
# Gemini — all model/loss combinations
# ==========================================

class TestRealRunGemini:

    def setup_method(self):
        _skip_if_no_key("gemini")
        _skip_if_no_data()

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["punet"])
    def test_punet_gemini(self, loss_cfg, tmp_path):
        record = run_one_loop("gemini", "punet", loss_cfg, str(tmp_path))
        assert record["status"] == "success"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["fcnet"])
    def test_fcnet_gemini(self, loss_cfg, tmp_path):
        record = run_one_loop("gemini", "fcnet", loss_cfg, str(tmp_path))
        assert record["status"] == "success"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["transformer"])
    def test_transformer_gemini(self, loss_cfg, tmp_path):
        record = run_one_loop("gemini", "transformer", loss_cfg, str(tmp_path))
        assert record["status"] == "success"


# ==========================================
# OpenAI — all model/loss combinations
# ==========================================

class TestRealRunOpenAI:

    def setup_method(self):
        _skip_if_no_key("openai")
        _skip_if_no_data()

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["punet"])
    def test_punet_openai(self, loss_cfg, tmp_path):
        record = run_one_loop("openai", "punet", loss_cfg, str(tmp_path))
        assert record["status"] == "success"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["fcnet"])
    def test_fcnet_openai(self, loss_cfg, tmp_path):
        record = run_one_loop("openai", "fcnet", loss_cfg, str(tmp_path))
        assert record["status"] == "success"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["transformer"])
    def test_transformer_openai(self, loss_cfg, tmp_path):
        record = run_one_loop("openai", "transformer", loss_cfg, str(tmp_path))
        assert record["status"] == "success"
