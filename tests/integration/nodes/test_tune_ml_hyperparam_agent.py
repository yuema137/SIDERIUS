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

import json
import os
import time

import pytest
from dotenv import load_dotenv

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, HyperparamTuningOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent

load_dotenv()

pytestmark = pytest.mark.real_run

try:
    from execute_tools.data_paths import TIDMAD_DATA_DIR

    DATA_DIR = TIDMAD_DATA_DIR
except (FileNotFoundError, ImportError):
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
    "gated_fno": {
        "model_type": "gated_fno",
        "segmentation_size": 10000,
        "width": 16,
        "num_layers": 1,
        "num_gates": 32,
    },
}

LOSS_CONFIGS = {
    "punet": [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
    "fcnet": [
        {"loss_type": "ce"},
        {"loss_type": "focal"},
        {"loss_type": "focal_cw"},
        {"loss_type": "smooth_l1"},
    ],
    "transformer": [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
    "wavenet": [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
    "rnn": [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
    "gated_fno": [{"loss_type": "ce"}, {"loss_type": "focal"}, {"loss_type": "focal_cw"}],
}

TRAIN_CONFIG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cuda"}

# Two complete configs per model for flexibility testing.
# Config A and Config B differ in ALL dimensions: model hparams, loss, and training hparams.
# segmentation_size=10000 for all to keep inference fast.
FLEX_CONFIGS = {
    "punet": [
        {
            "model_cfg": {
                "model_type": "punet",
                "segmentation_size": 10000,
                "depth": 2,
                "multi": 8,
                "kernel_size": 7,
                "embedding_dim": 8,
            },
            "loss_cfg": {"loss_type": "ce"},
            "train_cfg": {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
        {
            "model_cfg": {
                "model_type": "punet",
                "segmentation_size": 10000,
                "depth": 3,
                "multi": 16,
                "kernel_size": 9,
                "embedding_dim": 16,
            },
            "loss_cfg": {"loss_type": "focal"},
            "train_cfg": {"lr": 3e-4, "epochs": 1, "batch_size": 256, "device": "cuda"},
        },
    ],
    "fcnet": [
        {
            "model_cfg": {
                "model_type": "fcnet",
                "segmentation_size": 10000,
                "latent_dims": [400, 40],
            },
            "loss_cfg": {"loss_type": "ce"},
            "train_cfg": {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
        {
            "model_cfg": {
                "model_type": "fcnet",
                "segmentation_size": 10000,
                "latent_dims": [200, 50, 20],
            },
            "loss_cfg": {"loss_type": "smooth_l1"},
            "train_cfg": {"lr": 3e-4, "epochs": 1, "batch_size": 256, "device": "cuda"},
        },
    ],
    "transformer": [
        {
            "model_cfg": {
                "model_type": "transformer",
                "segmentation_size": 4000,
                "embedding_dim": 16,
                "nhead": 4,
                "num_layers": 1,
                "dim_feedforward": 64,
            },
            "loss_cfg": {"loss_type": "ce"},
            "train_cfg": {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
        {
            "model_cfg": {
                "model_type": "transformer",
                "segmentation_size": 4000,
                "embedding_dim": 32,
                "nhead": 4,
                "num_layers": 2,
                "dim_feedforward": 128,
            },
            "loss_cfg": {"loss_type": "focal"},
            "train_cfg": {"lr": 3e-4, "epochs": 1, "batch_size": 256, "device": "cuda"},
        },
    ],
    "wavenet": [
        {
            "model_cfg": {
                "model_type": "wavenet",
                "segmentation_size": 10000,
                "input_channels": 8,
                "residual_channels": 16,
                "gate_channels": 16,
                "skip_channels": 16,
                "num_blocks": 3,
                "kernel_size": 4,
            },
            "loss_cfg": {"loss_type": "ce"},
            "train_cfg": {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
        {
            "model_cfg": {
                "model_type": "wavenet",
                "segmentation_size": 10000,
                "input_channels": 16,
                "residual_channels": 32,
                "gate_channels": 32,
                "skip_channels": 32,
                "num_blocks": 5,
                "kernel_size": 8,
            },
            "loss_cfg": {"loss_type": "focal_cw"},
            "train_cfg": {"lr": 3e-4, "epochs": 1, "batch_size": 256, "device": "cuda"},
        },
    ],
    "rnn": [
        {
            "model_cfg": {
                "model_type": "rnn",
                "segmentation_size": 10000,
                "embedding_dim": 8,
                "hidden_dim": 8,
                "num_layers": 1,
            },
            "loss_cfg": {"loss_type": "ce"},
            "train_cfg": {"lr": 1e-4, "epochs": 1, "batch_size": 512, "device": "cuda"},
        },
        {
            "model_cfg": {
                "model_type": "rnn",
                "segmentation_size": 10000,
                "embedding_dim": 16,
                "hidden_dim": 16,
                "num_layers": 2,
            },
            "loss_cfg": {"loss_type": "focal"},
            "train_cfg": {"lr": 3e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
    ],
    "gated_fno": [
        {
            "model_cfg": {
                "model_type": "gated_fno",
                "segmentation_size": 10000,
                "width": 16,
                "num_layers": 1,
                "num_gates": 32,
            },
            "loss_cfg": {"loss_type": "ce"},
            "train_cfg": {"lr": 1e-4, "epochs": 1, "batch_size": 128, "device": "cuda"},
        },
        {
            "model_cfg": {
                "model_type": "gated_fno",
                "segmentation_size": 10000,
                "width": 32,
                "num_layers": 2,
                "num_gates": 64,
            },
            "loss_cfg": {"loss_type": "focal"},
            "train_cfg": {"lr": 3e-4, "epochs": 1, "batch_size": 256, "device": "cuda"},
        },
    ],
}


def run_one_loop(
    provider: str,
    model_type: str,
    loss_cfg: dict,
    workspace: str,
    model_cfg: dict | None = None,
    train_cfg: dict | None = None,
) -> HyperparamTuningOutput:
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
        output = run_one_loop(
            "gemini",
            "punet",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["fcnet"])
    def test_fcnet_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop(
            "gemini",
            "fcnet",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["transformer"])
    def test_transformer_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop(
            "gemini",
            "transformer",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["wavenet"])
    def test_wavenet_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop(
            "gemini",
            "wavenet",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["rnn"])
    def test_rnn_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop(
            "gemini",
            "rnn",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["gated_fno"])
    def test_gated_fno_gemini(self, loss_cfg, tmp_path):
        output = run_one_loop("gemini", "gated_fno", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["gated_fno"])
    def test_gated_fno_flexibility_gemini(self, cfg, tmp_path):
        output = run_one_loop(
            "gemini",
            "gated_fno",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
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
        output = run_one_loop(
            "openai",
            "punet",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["fcnet"])
    def test_fcnet_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop(
            "openai",
            "fcnet",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["transformer"])
    def test_transformer_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop(
            "openai",
            "transformer",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["wavenet"])
    def test_wavenet_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop(
            "openai",
            "wavenet",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["rnn"])
    def test_rnn_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop(
            "openai",
            "rnn",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"

    @pytest.mark.parametrize("loss_cfg", LOSS_CONFIGS["gated_fno"])
    def test_gated_fno_openai(self, loss_cfg, tmp_path):
        output = run_one_loop("openai", "gated_fno", loss_cfg, str(tmp_path))
        assert output.status == "completed"

    @pytest.mark.parametrize("cfg", FLEX_CONFIGS["gated_fno"])
    def test_gated_fno_flexibility_openai(self, cfg, tmp_path):
        output = run_one_loop(
            "openai",
            "gated_fno",
            cfg["loss_cfg"],
            str(tmp_path),
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        assert output.status == "completed"


# ==========================================
# Trial mode — end-to-end with real LLM + GPU
# ==========================================

ANCHOR_MAP_PATH = os.path.join(DATA_DIR, "segment_anchors.json")


def _skip_if_no_anchor_map():
    if not os.path.exists(ANCHOR_MAP_PATH):
        pytest.skip(f"segment_anchors.json not found at {ANCHOR_MAP_PATH}")


def run_trial_to_formal(
    provider: str,
    model_type: str,
    loss_cfg: dict,
    workspace: str,
    model_cfg: dict | None = None,
    train_cfg: dict | None = None,
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
        for required_key in [
            "is_trial",
            "mode",
            "trial_strategy",
            "trial_portion",
            "train_portion",
            "eval_strategy",
            "eval_portion",
            "train_sampling_seed",
            "eval_sampling_seed",
            "train_base_seed",
        ]:
            assert required_key in tc, f"trial_config missing key: {required_key}"

        # train and eval sample_set files must exist
        train_ss = os.path.join(configs_dir, f"train_sample_set_{exp_id}.json")
        eval_ss = os.path.join(configs_dir, f"eval_sample_set_{exp_id}.json")
        assert os.path.exists(train_ss), f"train_sample_set not found: {train_ss}"
        assert os.path.exists(eval_ss), f"eval_sample_set not found: {eval_ss}"

    # --- If formal round completed, verify train/eval separation ---
    if len(success_records) >= 2:
        formal_exp_id = success_records[-1].exp_id
        with open(os.path.join(configs_dir, f"trial_config_{formal_exp_id}.json")) as f:
            formal_tc = json.load(f)
        assert formal_tc["eval_portion"] == 1.0, "Formal eval_portion should be 1.0"
        assert formal_tc["train_portion"] < 1.0, (
            f"Formal train_portion should be < 1.0, got {formal_tc['train_portion']}"
        )

    return output


class TestTrialModeGemini:
    def setup_method(self):
        _skip_if_no_key("gemini")
        _skip_if_no_data()
        _skip_if_no_anchor_map()

    def test_punet_trial_to_formal(self):
        """2-round run: trial (round 1) → formal (round 2, forced by code).
        Uses persistent directory so results can be inspected after the test."""
        import tempfile

        workspace = os.path.join(
            tempfile.gettempdir(), "siderius_integration_tests", "trial_to_formal"
        )
        os.makedirs(workspace, exist_ok=True)
        cfg = FLEX_CONFIGS["punet"][0]
        output = run_trial_to_formal(
            "gemini",
            "punet",
            cfg["loss_cfg"],
            workspace,
            model_cfg=cfg["model_cfg"],
            train_cfg=cfg["train_cfg"],
        )
        print(f"\n  Results saved to: {workspace}")
        assert output.status == "completed"
        assert output.completed_rounds == 2


# ==========================================
# Dual-mode test (pseudo_full_loop proof-of-concept)
# ==========================================


@pytest.mark.dual_mode
@pytest.mark.parametrize("is_trial", [False, True], ids=["formal", "trial"])
def test_punet_one_round_dual_mode(tmp_path, request, is_trial):
    """
    Dual-mode proof-of-concept: runs the tuner agent for 1 round of punet
    in EITHER pseudo mode (default, recording fakes) or real mode
    (real LLM + real subprocess, requires ``--real-llm`` / ``--real-training``).

    Parametrized over ``is_trial``:
      - ``False`` (formal): scoring goes through ``sandbox.execute_scoring``.
      - ``True`` (trial): scoring goes through ``sandbox.score_vector``,
        backed by ``score_vector.json`` in pseudo mode.

    Same assertions for both modes. Pseudo mode adds extra assertions on
    prompt content and record structure.

    See ``docs/pseudo_test_infra.md`` for the full dual-axis design.
    """
    from tests.conftest import _is_real_training, make_bridge_factory, make_sandbox_factory

    if _is_real_training(request) and is_trial:
        _skip_if_no_anchor_map()

    run_name = f"dual_punet_{'trial' if is_trial else 'formal'}_{int(time.time())}"
    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)

    agent_input = HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=1,
        expert_advice=(
            "CRITICAL: You MUST use exactly this configuration. "
            "model_type: punet. "
            f"model_config: {MODEL_CONFIGS['punet']}. "
            f"train_config: {TRAIN_CONFIG}. "
            "loss_config: {'loss_type': 'focal', 'alpha': 0.5, 'gamma': 2.0}. "
            "Do NOT deviate from these values."
        ),
        llm_provider="gemini",
        llm_model_id="gemini-3.1-flash-lite-preview",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name=run_name),
        ),
        progress_bar=False,
        is_trial=is_trial,
    )

    from agent.llm_bridge import LLMBridge
    from core.sandbox_executor import TidmadSandbox
    from tests.conftest import _is_real_llm, _is_real_training
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge
    from tests.helpers.recording_sandbox import RecordingSandbox

    # Each axis is switched independently.
    bridge = sandbox = None
    if _is_real_llm(request):
        _skip_if_no_key("gemini")
        bridge_factory = LLMBridge
    else:
        bridge = RecordingLLMBridge.for_agent("ml_hyperparameter_tune_agent")

        def bridge_factory(**kw):
            return bridge

    if _is_real_training(request):
        _skip_if_no_data()
        if is_trial:
            _skip_if_no_anchor_map()
        sandbox_factory = TidmadSandbox
    else:
        sandbox = RecordingSandbox.for_model("punet", base_dir=workspace, run_name=run_name)

        def sandbox_factory(**kw):
            return sandbox

    agent = HyperparamTuningAgent(bridge_factory=bridge_factory, sandbox_factory=sandbox_factory)

    output = agent.run(agent_input)

    # --- Assertions that hold in BOTH modes ---
    assert isinstance(output, HyperparamTuningOutput)
    HyperparamTuningOutput.model_validate(output.model_dump())
    assert output.status in ("completed", "partial")
    assert output.run_name == run_name
    assert output.model_type == "punet"
    assert len(output.all_records) >= 1

    # --- Pseudo-LLM assertions (orchestration wiring) ---
    if bridge is not None:
        # 1. First LLM call is the planner (plan method)
        planner_call = bridge.calls[0]
        assert planner_call[0] == "plan", (
            f"First LLM call should be 'plan' (planner), got {planner_call[0]!r}"
        )

        # 2. The reflector was called and received scoring results
        reflect_calls = [c for c in bridge.calls if c[0] == "reflect"]
        assert len(reflect_calls) >= 1, "Reflector should have been called"
        reflect_results = reflect_calls[0][3]
        assert "denoising_score" in reflect_results
        assert "file_vector" in reflect_results

        # 3. Call sequence sanity: plan → … → reflect
        bridge_methods = [c[0] for c in bridge.calls]
        assert bridge_methods[0] == "plan"
        assert "reflect" in bridge_methods

    # --- Pseudo-sandbox assertions (record structure) ---
    if sandbox is not None:
        assert len(sandbox.saved_records) >= 1, (
            "At least one record should have been saved via sandbox.save_record()"
        )
        record = sandbox.saved_records[0]
        assert record["status"] == "success"
        assert record["model_type"] == "punet"
        assert record["denoising_score"] is not None
        assert record["file_vector"] is not None
        assert len(record["file_vector"]) == 20
        assert record["final_loss"] is not None
        assert record["model_params"] is not None
        sandbox_methods = [c[0] for c in sandbox.calls]
        assert "execute_training" in sandbox_methods
        assert "save_record" in sandbox_methods


# ---------------------------------------------------------------------------
# F.8 — Wavenet dual-mode test
# ---------------------------------------------------------------------------

# Canned wavenet LLM plan — must validate against ExperimentPlan + WavenetConfig.
# device="cpu" so the resource check does not require a GPU in pseudo mode.
_WAVENET_CANNED_PLAN = {
    "model_type": "wavenet",
    "hypothesis": "Default wavenet baseline with focal loss should leverage dilated causal conv for high-frequency denoising.",
    "reasoning": "First round, no prior records. Use wavenet defaults: residual_channels=16, num_blocks=3, focal loss. Established SOTA pattern for 1D signal denoising.",
    "model_config": {
        "model_type": "wavenet",
        "segmentation_size": 10000,
        "input_channels": 8,
        "residual_channels": 16,
        "gate_channels": 16,
        "skip_channels": 16,
        "num_blocks": 3,
        "kernel_size": 4,
        "embedding_dim": 8,
    },
    "train_config": {
        "lr": 0.0001,
        "epochs": 5,
        "batch_size": 1,
        "optimizer_type": "adamw",
        "weight_decay": 0.00001,
        "device": "cpu",
    },
    "loss_config": {
        "loss_type": "focal",
        "alpha": 0.5,
        "gamma": 2.0,
        "reduction": "mean",
        "use_class_weights": False,
    },
    "is_trial": False,
    "trial_strategy": "snapshot",
    "trial_portion": 0.05,
    "target_files": [],
    "train_portion": 0.1,
    "eval_strategy": "snapshot",
    "eval_portion": 0.05,
    "train_validation_align": True,
}

_WAVENET_CANNED_REFLECT = {
    "conclusion": "Strong. wavenet achieved denoising_score=5.576, substantially above the punet baseline (~1.57). High-frequency files (10-19) score 7-9; low-frequency files (0-4) score near 0.1 — low-frequency blindness is the dominant bottleneck.",
    "key_factor": "Dilated causal convolution with gated activation provides exponential receptive field growth, enabling strong high-frequency recovery. The low-freq gap suggests the receptive field cannot capture the lowest frequency bands.",
    "discovery": "Wavenet's dilated causal conv excels at high-freq (files 10-19: 7-9) but is near-blind at low-freq (files 0-4: 0.1). This is a structural gap, not a hyperparameter issue.",
    "memory_update": "Next round, investigate spectral or multi-rate processing to address low-frequency blindness. Keep dilated_causal_conv as the backbone — it is clearly the driver of the strong high-freq performance.",
}


@pytest.mark.dual_mode
def test_wavenet_one_round_dual_mode(tmp_path, request, monkeypatch):
    """F.8 — Dual-mode test for wavenet (formal mode only).

    Pseudo mode (default): uses a wavenet-specific canned plan and wavenet
    train/score outputs from tests/pseudo_data/train_outputs/wavenet/.
    Real mode (--real-api-call): runs against the real Gemini API + GPU.

    Validates that the tuner orchestration works correctly for wavenet:
    canned plan, training, scoring, reflection, and record persistence.
    """
    from agent.llm_bridge import LLMBridge
    from core.sandbox_executor import TidmadSandbox
    from tests.conftest import _is_real_llm, _is_real_training
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge
    from tests.helpers.recording_sandbox import RecordingSandbox

    run_name = f"dual_wavenet_formal_{int(time.time())}"
    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)

    agent_input = HyperparamTuningInput(
        model_type="wavenet",
        file_index=6,
        max_rounds=1,
        expert_advice=(
            "CRITICAL: You MUST use exactly this configuration. "
            "model_type: wavenet. "
            f"model_config: {MODEL_CONFIGS['wavenet']}. "
            f"train_config: {TRAIN_CONFIG}. "
            "loss_config: {'loss_type': 'focal', 'alpha': 0.5, 'gamma': 2.0}. "
            "Do NOT deviate from these values."
        ),
        llm_provider="gemini",
        llm_model_id="gemini-3.1-flash-lite-preview",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name=run_name),
        ),
        progress_bar=False,
        is_trial=False,
    )

    # Each axis switched independently.
    bridge = sandbox = None
    if _is_real_llm(request):
        _skip_if_no_key("gemini")
        bridge_factory = LLMBridge
    else:
        # Wavenet plan is model-specific — inline construction, not for_agent.
        bridge = RecordingLLMBridge(
            responses={
                "generate": _WAVENET_CANNED_PLAN,
                "reflect": _WAVENET_CANNED_REFLECT,
            }
        )

        def bridge_factory(**kw):
            return bridge

    if _is_real_training(request):
        _skip_if_no_data()
        sandbox_factory = TidmadSandbox
    else:
        sandbox = RecordingSandbox.for_model("wavenet", base_dir=workspace, run_name=run_name)

        def sandbox_factory(**kw):
            return sandbox

    agent = HyperparamTuningAgent(bridge_factory=bridge_factory, sandbox_factory=sandbox_factory)
    output = agent.run(agent_input)

    # --- Assertions that hold in BOTH modes ---
    assert isinstance(output, HyperparamTuningOutput)
    HyperparamTuningOutput.model_validate(output.model_dump())
    assert output.status in ("completed", "partial")
    assert output.run_name == run_name
    assert output.model_type == "wavenet"
    assert len(output.all_records) >= 1

    # --- Pseudo-LLM assertions ---
    if bridge is not None:
        planner_call = bridge.calls[0]
        assert planner_call[0] == "plan", (
            f"First LLM call should be 'plan', got {planner_call[0]!r}"
        )
        bridge_methods = [c[0] for c in bridge.calls]
        assert "reflect" in bridge_methods

    # --- Pseudo-sandbox assertions ---
    if sandbox is not None:
        assert len(sandbox.saved_records) >= 1
        record = sandbox.saved_records[0]
        assert record["status"] == "success"
        assert record["model_type"] == "wavenet"
        assert record["denoising_score"] == pytest.approx(5.576, abs=0.01)
        assert record["file_vector"] is not None
        assert len(record["file_vector"]) == 20
        assert record["file_vector"][0] < 1.0, "Low-freq (file 0) should be weak"
        assert record["file_vector"][19] > 7.0, "High-freq (file 19) should be strong"
        sandbox_methods = [c[0] for c in sandbox.calls]
        assert "execute_training" in sandbox_methods
        assert "save_record" in sandbox_methods
        print(
            f"\n  [wavenet pseudo] score={record['denoising_score']:.4f} "
            f"file_vec[0]={record['file_vector'][0]:.2f} "
            f"file_vec[19]={record['file_vector'][19]:.2f}"
        )
