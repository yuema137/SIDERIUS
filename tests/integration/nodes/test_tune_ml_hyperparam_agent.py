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
from agent.schemas.hyperparam_tuning import HyperparamTuningInput, ExperimentRecord

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
        "multi": 16,
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
    "wavenet": {
        "model_type": "wavenet",
        "segmentation_size": 40000,
        "input_channels": 8,
        "residual_channels": 16,
        "gate_channels": 16,
        "skip_channels": 16,
        "num_blocks": 4,
    },
    "rnn": {
        "model_type": "rnn",
        "segmentation_size": 40000,
        "embedding_dim": 8,
        "hidden_dim": 8,
        "num_layers": 1,
    },
}

LOSS_CONFIGS = {
    "punet":       [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
    "fcnet":       [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}, {"loss_type": "smooth_l1"}],
    "transformer": [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
    "wavenet":     [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
    "rnn":         [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
}

TRAIN_CONFIG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cuda"}

# Two complete configs per model for flexibility testing.
# Config A and Config B differ in ALL dimensions: model hparams, loss, and training hparams.
# segmentation_size=10000 for all to keep inference fast.
FLEX_CONFIGS = {
    "punet": [
        {
            "model_cfg":  {"model_type": "punet", "segmentation_size": 10000, "depth": 2, "multi": 8,  "kernel_size": 7, "embedding_dim": 8},
            "loss_cfg":   {"loss_type": "ce"},
            "train_cfg":  {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
        {
            "model_cfg":  {"model_type": "punet", "segmentation_size": 10000, "depth": 3, "multi": 16, "kernel_size": 9, "embedding_dim": 16},
            "loss_cfg":   {"loss_type": "focal"},
            "train_cfg":  {"lr": 3e-4, "epochs": 1, "batch_size": 256, "device": "cuda"},
        },
    ],
    "fcnet": [
        {
            "model_cfg":  {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [400, 40]},
            "loss_cfg":   {"loss_type": "ce"},
            "train_cfg":  {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
        {
            "model_cfg":  {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [200, 50, 20]},
            "loss_cfg":   {"loss_type": "smooth_l1"},
            "train_cfg":  {"lr": 3e-4, "epochs": 1, "batch_size": 256, "device": "cuda"},
        },
    ],
    "transformer": [
        {
            "model_cfg":  {"model_type": "transformer", "segmentation_size": 4000, "embedding_dim": 16, "nhead": 4, "num_layers": 1, "dim_feedforward": 64},
            "loss_cfg":   {"loss_type": "ce"},
            "train_cfg":  {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
        {
            "model_cfg":  {"model_type": "transformer", "segmentation_size": 4000, "embedding_dim": 32, "nhead": 4, "num_layers": 2, "dim_feedforward": 128},
            "loss_cfg":   {"loss_type": "focal"},
            "train_cfg":  {"lr": 3e-4, "epochs": 1, "batch_size": 256, "device": "cuda"},
        },
    ],
    "wavenet": [
        {
            "model_cfg":  {"model_type": "wavenet", "segmentation_size": 10000, "input_channels": 8,  "residual_channels": 16, "gate_channels": 16, "skip_channels": 16, "num_blocks": 3, "kernel_size": 4},
            "loss_cfg":   {"loss_type": "ce"},
            "train_cfg":  {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
        {
            "model_cfg":  {"model_type": "wavenet", "segmentation_size": 10000, "input_channels": 16, "residual_channels": 32, "gate_channels": 32, "skip_channels": 32, "num_blocks": 5, "kernel_size": 8},
            "loss_cfg":   {"loss_type": "focal_cw"},
            "train_cfg":  {"lr": 3e-4, "epochs": 1, "batch_size": 256, "device": "cuda"},
        },
    ],
    "rnn": [
        {
            "model_cfg":  {"model_type": "rnn", "segmentation_size": 10000, "embedding_dim": 8,  "hidden_dim": 8,  "num_layers": 1},
            "loss_cfg":   {"loss_type": "ce"},
            "train_cfg":  {"lr": 1e-4, "epochs": 1, "batch_size": 512, "device": "cuda"},
        },
        {
            "model_cfg":  {"model_type": "rnn", "segmentation_size": 10000, "embedding_dim": 16, "hidden_dim": 16, "num_layers": 2},
            "loss_cfg":   {"loss_type": "focal"},
            "train_cfg":  {"lr": 3e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
    ],
}


def run_one_loop(provider: str, model_type: str, loss_cfg: dict, workspace: str,
                 model_cfg: dict = None, train_cfg: dict = None):
    """
    Runs one full agent loop iteration:
      plan -> train -> inference -> score -> reflect -> save record

    Input is validated against HyperparamTuningInput.
    Output record is validated against ExperimentRecord.
    """
    run_name = f"real_{provider}_{model_type}_{loss_cfg['loss_type']}"
    exp_id = f"exp_{model_type}_{loss_cfg['loss_type']}_{int(time.time())}"

    model_ids = {
        "gemini": "gemini-3.1-flash-lite-preview",
        "openai": "gpt-4o",
    }

    # --- Validate input against schema ---
    expert_advice = f"Test run: use {model_type} with {loss_cfg['loss_type']} loss. Use minimal epochs."
    HyperparamTuningInput(
        model_type=model_type,
        llm_provider=provider,
        llm_model_id=model_ids[provider],
        expert_advice=expert_advice,
        max_rounds=1,
        storage={"backend": "local", "local": {"workspace": workspace, "run_name": run_name}},
    )

    sandbox = TidmadSandbox(workspace=workspace, run_name=run_name)
    brain = LLMBridge(provider=provider, model_id=model_ids[provider])

    # --- THINK: get plan from LLM ---
    memory_history = sandbox.get_summary()
    decision = brain.plan(
        memory_history=memory_history,
        expert_advice=expert_advice,
        force_model=model_type,
    )
    assert "model_config" in decision or "model_type" in decision, \
        f"LLM plan response missing expected keys: {decision}"

    m_cfg = model_cfg if model_cfg is not None else MODEL_CONFIGS[model_type]
    t_cfg = train_cfg if train_cfg is not None else TRAIN_CONFIG

    params = {
        "exp_id": exp_id,
        "run_name": run_name,
        "model_type": model_type,
        "model_config": m_cfg,
        "train_config": t_cfg,
        "loss_config": loss_cfg,
    }

    # --- ACT: train -> inference -> score ---
    train_result = sandbox.execute_training(
        exp_id=exp_id, run_name=run_name, model_type=model_type,
        m_cfg=m_cfg, t_cfg=t_cfg, l_cfg=loss_cfg,
    )
    assert train_result["status"] == "success", (
        f"Training failed for {model_type}/{loss_cfg['loss_type']}:\n"
        f"{train_result.get('message', '(no message)')}"
    )

    inf_result = sandbox.execute_inference(
        exp_id=exp_id, run_name=run_name, model_type=model_type,
        m_cfg=m_cfg, l_cfg=loss_cfg,
    )
    assert inf_result["status"] == "success", (
        f"Inference failed for {model_type}/{loss_cfg['loss_type']}:\n"
        f"{inf_result.get('message', '(no message)')}"
    )

    score_result = sandbox.execute_scoring(
        exp_id=exp_id, run_name=run_name, model_type=model_type,
        m_cfg=m_cfg, t_cfg=t_cfg, l_cfg=loss_cfg,
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
        "file_index": sandbox.file_index,
        "params": params,
        "results": score_result.get("results", {}),
        "denoising_score": score_result.get("results", {}).get("denoising_score"),
        "memory": {
            "expert_advice_followed": expert_advice,
            "hypothesis": decision.get("hypothesis"),
            "conclusion": reflection.get("conclusion"),
            "discovery": reflection.get("discovery"),
            "memory_update": reflection.get("memory_update"),
        },
    }

    # --- Validate output record against schema ---
    ExperimentRecord(**record)

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

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["wavenet"])
    def test_wavenet_gemini(self, loss_cfg, tmp_path):
        record = run_one_loop("gemini", "wavenet", loss_cfg, str(tmp_path))
        assert record["status"] == "success"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["rnn"])
    def test_rnn_gemini(self, loss_cfg, tmp_path):
        record = run_one_loop("gemini", "rnn", loss_cfg, str(tmp_path))
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["punet"])
    def test_punet_flexibility_gemini(self, cfg, tmp_path):
        record = run_one_loop("gemini", "punet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["fcnet"])
    def test_fcnet_flexibility_gemini(self, cfg, tmp_path):
        record = run_one_loop("gemini", "fcnet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["transformer"])
    def test_transformer_flexibility_gemini(self, cfg, tmp_path):
        record = run_one_loop("gemini", "transformer", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["wavenet"])
    def test_wavenet_flexibility_gemini(self, cfg, tmp_path):
        record = run_one_loop("gemini", "wavenet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["rnn"])
    def test_rnn_flexibility_gemini(self, cfg, tmp_path):
        record = run_one_loop("gemini", "rnn", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
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

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["wavenet"])
    def test_wavenet_openai(self, loss_cfg, tmp_path):
        record = run_one_loop("openai", "wavenet", loss_cfg, str(tmp_path))
        assert record["status"] == "success"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["rnn"])
    def test_rnn_openai(self, loss_cfg, tmp_path):
        record = run_one_loop("openai", "rnn", loss_cfg, str(tmp_path))
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["punet"])
    def test_punet_flexibility_openai(self, cfg, tmp_path):
        record = run_one_loop("openai", "punet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["fcnet"])
    def test_fcnet_flexibility_openai(self, cfg, tmp_path):
        record = run_one_loop("openai", "fcnet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["transformer"])
    def test_transformer_flexibility_openai(self, cfg, tmp_path):
        record = run_one_loop("openai", "transformer", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["wavenet"])
    def test_wavenet_flexibility_openai(self, cfg, tmp_path):
        record = run_one_loop("openai", "wavenet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert record["status"] == "success"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["rnn"])
    def test_rnn_flexibility_openai(self, cfg, tmp_path):
        record = run_one_loop("openai", "rnn", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert record["status"] == "success"
