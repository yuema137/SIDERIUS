"""
Tier 1 integration test for tune_ml_hyperparam_agent.

Tests HyperparamTuningAgent.run() end-to-end with real LLM API + GPU.
Each test runs 1 round with a given model/loss/train config and verifies
that the output conforms to HyperparamTuningOutput.

Requires:
  - Real TIDMAD data at /home/klz/Data/TIDMAD/
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)
  - GPU (CUDA)

These tests are skipped automatically when API keys are missing.
Run locally with:
  uv run pytest -m real_run tests/integration/nodes/test_tune_ml_hyperparam_agent.py -v -s

DO NOT run these in CI (GitHub Actions or equivalent).
"""
import os
import json
import time
import pytest
from dotenv import load_dotenv

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, HyperparamTuningOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent

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
                 model_cfg: dict = None, train_cfg: dict = None) -> HyperparamTuningOutput:
    """
    Runs HyperparamTuningAgent.run() for 1 round with the given config.

    Uses the standard node contract: HyperparamTuningInput → run() → HyperparamTuningOutput.
    The agent internally handles plan → resource check → train → infer → score → reflect.

    The expert_advice forces the agent to use the exact model/loss/train config provided,
    bypassing LLM-driven config selection.
    """
    run_name = f"real_{provider}_{model_type}_{loss_cfg['loss_type']}_{int(time.time())}"

    model_ids = {
        "gemini": "gemini-3.1-flash-lite-preview",
        "openai": "gpt-5-mini",
    }

    m_cfg = model_cfg if model_cfg is not None else MODEL_CONFIGS[model_type]
    t_cfg = train_cfg if train_cfg is not None else TRAIN_CONFIG

    expert_advice = (
        f"CRITICAL: You MUST use exactly this configuration. "
        f"model_type: {model_type}. "
        f"model_config: {m_cfg}. "
        f"train_config: {t_cfg}. "
        f"loss_config: {loss_cfg}. "
        f"Do NOT deviate from these values."
    )

    agent_input = HyperparamTuningInput(
        model_type=model_type,
        file_index=6,
        max_rounds=1,
        expert_advice=expert_advice,
        llm_provider=provider,
        llm_model_id=model_ids[provider],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name=run_name),
        ),
        progress_bar=False,
    )

    agent = HyperparamTuningAgent()
    output = agent.run(agent_input)

    # --- Validate output against schema ---
    assert isinstance(output, HyperparamTuningOutput)
    HyperparamTuningOutput.model_validate(output.model_dump())

    # --- Verify key fields ---
    assert output.status in ("completed", "partial")
    assert output.run_name == run_name
    assert output.model_type == model_type
    assert len(output.all_records) >= 1

    # --- Verify output file was written ---
    import os
    output_path = os.path.join(workspace, f"run_output_{run_name}.json")
    assert os.path.exists(output_path), f"Output file not found: {output_path}"

    return output


# ==========================================
# Gemini — all model/loss combinations
# ==========================================

class TestRealRunGemini:

    def setup_method(self):
        _skip_if_no_key("gemini")
        _skip_if_no_data()

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["punet"])
    def test_punet_gemini(self, loss_cfg, tmp_path):
        output = run_one_loop("gemini", "punet", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["fcnet"])
    def test_fcnet_gemini(self, loss_cfg, tmp_path):
        output = run_one_loop("gemini", "fcnet", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["transformer"])
    def test_transformer_gemini(self, loss_cfg, tmp_path):
        output = run_one_loop("gemini", "transformer", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["wavenet"])
    def test_wavenet_gemini(self, loss_cfg, tmp_path):
        output = run_one_loop("gemini", "wavenet", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["rnn"])
    def test_rnn_gemini(self, loss_cfg, tmp_path):
        output = run_one_loop("gemini", "rnn", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["punet"])
    def test_punet_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop("gemini", "punet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["fcnet"])
    def test_fcnet_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop("gemini", "fcnet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["transformer"])
    def test_transformer_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop("gemini", "transformer", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["wavenet"])
    def test_wavenet_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop("gemini", "wavenet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["rnn"])
    def test_rnn_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop("gemini", "rnn", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"


# ==========================================
# OpenAI — all model/loss combinations
# ==========================================

class TestRealRunOpenAI:

    def setup_method(self):
        _skip_if_no_key("openai")
        _skip_if_no_data()

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["punet"])
    def test_punet_openai(self, loss_cfg, tmp_path):
        output = run_one_loop("openai", "punet", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["fcnet"])
    def test_fcnet_openai(self, loss_cfg, tmp_path):
        output = run_one_loop("openai", "fcnet", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["transformer"])
    def test_transformer_openai(self, loss_cfg, tmp_path):
        output = run_one_loop("openai", "transformer", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["wavenet"])
    def test_wavenet_openai(self, loss_cfg, tmp_path):
        output = run_one_loop("openai", "wavenet", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["rnn"])
    def test_rnn_openai(self, loss_cfg, tmp_path):
        output = run_one_loop("openai", "rnn", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["punet"])
    def test_punet_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop("openai", "punet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["fcnet"])
    def test_fcnet_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop("openai", "fcnet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["transformer"])
    def test_transformer_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop("openai", "transformer", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["wavenet"])
    def test_wavenet_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop("openai", "wavenet", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["rnn"])
    def test_rnn_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop("openai", "rnn", cfg["loss_cfg"], str(tmp_path),
                              model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"])
        assert output.status == "completed"


# ==========================================
# Trial mode — end-to-end with real LLM + GPU
# ==========================================

ANCHOR_MAP_PATH = os.path.join(DATA_DIR, "segment_anchors.json")


def _skip_if_no_anchor_map():
    if not os.path.exists(ANCHOR_MAP_PATH):
        pytest.skip(f"segment_anchors.json not found at {ANCHOR_MAP_PATH}")


def run_trial_to_formal(provider: str, model_type: str, loss_cfg: dict, workspace: str,
                        model_cfg: dict = None, train_cfg: dict = None,
                        ) -> HyperparamTuningOutput:
    """
    Runs HyperparamTuningAgent.run() for 2 rounds in trial-allowed mode.

    Round 1: LLM decides trial parameters (defaults to trial mode).
    Round 2 (final): forced formal — all 20 files, all segments.

    Expert advice forces the exact model/train/loss config so only the
    trial/formal decision is left to the LLM.
    """
    run_name = f"trial_{provider}_{model_type}_{loss_cfg['loss_type']}_{int(time.time())}"

    model_ids = {
        "gemini": "gemini-3.1-flash-lite-preview",
    }

    m_cfg = model_cfg if model_cfg is not None else MODEL_CONFIGS[model_type]
    t_cfg = train_cfg if train_cfg is not None else TRAIN_CONFIG

    expert_advice = (
        f"CRITICAL: You MUST use exactly this configuration for EVERY round. "
        f"model_type: {model_type}. "
        f"model_config: {m_cfg}. "
        f"train_config: {t_cfg}. "
        f"loss_config: {loss_cfg}. "
        f"Do NOT deviate from these values. "
        f"For trial parameters, you may choose freely."
    )

    agent_input = HyperparamTuningInput(
        model_type=model_type,
        max_rounds=2,
        is_trial=True,
        expert_advice=expert_advice,
        llm_provider=provider,
        llm_model_id=model_ids[provider],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name=run_name),
        ),
        progress_bar=False,
    )

    agent = HyperparamTuningAgent()
    output = agent.run(agent_input)

    # --- Validate output against schema ---
    assert isinstance(output, HyperparamTuningOutput)
    HyperparamTuningOutput.model_validate(output.model_dump())

    # --- Verify key fields ---
    assert output.status in ("completed", "partial")
    assert output.run_name == run_name
    assert output.model_type == model_type

    # --- Verify we got success records ---
    success_records = [r for r in output.all_records if r.status == "success"]
    assert len(success_records) >= 1, "Expected at least 1 successful experiment"

    # --- All records should have file_vector (both trial and formal use score_vector) ---
    for rec in success_records:
        assert rec.file_vector is not None, f"{rec.exp_id} missing file_vector"
        assert len(rec.file_vector) == 20, f"{rec.exp_id} file_vector not length 20"

    # --- If 2 rounds completed, check trial→formal transition ---
    if len(success_records) >= 2:
        last_rec = success_records[-1]
        # Final round should be formal (is_trial=False or absent)
        assert last_rec.is_trial is False, (
            f"Final round should be formal but got is_trial={last_rec.is_trial}"
        )
        # Formal round scores all 20 files — no NaN in file_vector
        import math
        non_nan = [v for v in last_rec.file_vector if not math.isnan(v)]
        assert len(non_nan) == 20, (
            f"Formal round should score all 20 files, got {len(non_nan)} non-NaN"
        )

    # --- Best file vector should be populated ---
    assert output.best_file_vector is not None
    assert len(output.best_file_vector) == 20

    # --- Verify output file was written ---
    output_path = os.path.join(workspace, f"run_output_{run_name}.json")
    assert os.path.exists(output_path), f"Output file not found: {output_path}"

    # --- Verify Phase 4b artifacts: trial_config and sample_set files ---
    configs_dir = os.path.join(workspace, "configs", run_name)
    for rec in success_records:
        exp_id = rec.exp_id
        # trial_config must exist for every round
        tc_path = os.path.join(configs_dir, f"trial_config_{exp_id}.json")
        assert os.path.exists(tc_path), f"trial_config not found: {tc_path}"
        with open(tc_path) as f:
            tc = json.load(f)
        assert "is_trial" in tc and "mode" in tc and "train_portion" in tc

        # train and eval sample_set files must exist
        train_ss = os.path.join(configs_dir, f"train_sample_set_{exp_id}.json")
        eval_ss = os.path.join(configs_dir, f"eval_sample_set_{exp_id}.json")
        assert os.path.exists(train_ss), f"train_sample_set not found: {train_ss}"
        assert os.path.exists(eval_ss), f"eval_sample_set not found: {eval_ss}"

    # --- If formal round completed, verify train/eval separation ---
    if len(success_records) >= 2:
        formal_exp_id = success_records[-1].exp_id
        # Train and eval are independent SampleSets on different physical files.
        with open(os.path.join(configs_dir, f"trial_config_{formal_exp_id}.json")) as f:
            formal_tc = json.load(f)
        assert formal_tc["mode"] == "formal"
        assert formal_tc["eval_portion"] == 1.0, f"Formal eval_portion should be 1.0"
        assert formal_tc["train_portion"] < 1.0, (
            f"Formal train_portion should be < 1.0, got {formal_tc['train_portion']}"
        )

    return output


class TestTrialModeGemini:

    def setup_method(self):
        _skip_if_no_key("gemini")
        _skip_if_no_data()
        _skip_if_no_anchor_map()

    def test_punet_trial_to_formal(self, tmp_path):
        """2-round run: trial (round 1) → formal (round 2, forced by code)."""
        cfg = FLEX_CONFIGS["punet"][0]
        output = run_trial_to_formal(
            "gemini", "punet", cfg["loss_cfg"], str(tmp_path),
            model_cfg=cfg["model_cfg"], train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"
        assert output.completed_rounds == 2
