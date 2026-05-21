"""
Real-API integration tests for ml_model_implementor (Node 4).

Exercises the node in isolation with a synthetic ImplementorInput — no GPU,
no real TIDMAD data, and no upstream agent call required.

In addition to schema validation, also verifies that the generated plugin file:
  - is syntactically valid Python
  - loads successfully through ml_models/plugin_loader._load_plugin()
  - exposes PLUGIN_MODEL_TYPE, PLUGIN_CONFIG_CLASS, PLUGIN_MODEL_CLASS

Requires:
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)

Run with:
  uv run pytest -m real_run tests/integration/nodes/test_ml_model_implementor.py -v -s

DO NOT run in CI.
"""

import ast
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.schemas.implementor import ImplementorInput, ImplementorOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from ml_models.plugin_loader import _load_plugin
from nodes.ml_model_implementor import MLModelImplementor

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------


def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set — skipping real API test")


# ---------------------------------------------------------------------------
# Synthetic ImplementorInput
# ---------------------------------------------------------------------------

SYNTHETIC_INPUT = dict(
    model_name="gated_dilated_tcn",
    model_description=(
        "A gated dilated temporal convolutional network for SQUID signal denoising. "
        "Uses stacked residual blocks with exponentially increasing dilation rates to "
        "capture both local and long-range temporal dependencies without the spatial "
        "compression penalty of U-Net-style pooling."
    ),
    mathematical_definition=(
        "Each residual block l computes: output_l = x_l + (tanh(W_f^l * x_l) * sigmoid(W_g^l * x_l)), "
        "where * denotes dilated 1-D convolution with dilation d_l = dilation_base^l. "
        "Data flows: embedding -> input projection -> N gated residual blocks -> output projection. "
        "The final output projection is a pointwise Conv1d mapping to 256 logits per timestep."
    ),
    baseline_config={
        "model_config": {
            "channels": 64,
            "depth": 6,
            "kernel_size": 3,
            "dilation_base": 2,
        },
        "train_config": {
            "lr": 1e-4,
            "epochs": 10,
            "batch_size": 1,
            "optimizer_type": "adamw",
            "weight_decay": 1e-5,
            "device": "cuda",
        },
        "loss_config": {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0},
    },
)


def _make_input(tmp_path) -> ImplementorInput:
    return ImplementorInput(
        **SYNTHETIC_INPUT,
        plugin_dir=str(tmp_path / "models"),
        test_dir=str(tmp_path / "tests"),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="node_test"),
        ),
    )


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def _assert_output(output: ImplementorOutput, tmp_path):
    assert isinstance(output, ImplementorOutput)
    assert output.model_type == "gated_dilated_tcn"

    # Files exist
    assert os.path.exists(output.model_file_path), "Plugin file not found"
    assert os.path.exists(output.test_file_path), "Test file not found"

    # Plugin is syntactically valid Python
    plugin_src = open(output.model_file_path).read()
    try:
        ast.parse(plugin_src)
    except SyntaxError as e:
        pytest.fail(f"Generated plugin has a syntax error: {e}\n\n{plugin_src}")

    # Plugin file contains the required plugin constants
    assert 'PLUGIN_MODEL_TYPE = "gated_dilated_tcn"' in plugin_src
    assert "PLUGIN_CONFIG_CLASS" in plugin_src
    assert "PLUGIN_MODEL_CLASS" in plugin_src

    # Plugin loads successfully through the plugin loader
    plugin = _load_plugin(output.model_file_path)
    assert plugin is not None, "plugin_loader._load_plugin() returned None"
    assert plugin["model_type"] == "gated_dilated_tcn"
    assert plugin["config_class"] is not None
    assert plugin["model_class"] is not None

    # Config can be instantiated with defaults
    config = plugin["config_class"]()
    assert config.segmentation_size > 0
    assert config.batch_size >= 1

    # config_fields is a non-empty dict
    assert isinstance(output.config_fields, dict)
    assert len(output.config_fields) > 0

    # description.md written alongside the plugin
    assert os.path.exists(output.description_file_path), "description.md not found"
    description = open(output.description_file_path).read()
    assert len(description) > 50, "description.md is suspiciously short"
    assert "GatedDilatedTcn" in description
    assert "[B, T] int64" in description  # forward contract present

    # Output record written
    assert (tmp_path / "implementor_node_test.json").exists()
    data = json.loads((tmp_path / "implementor_node_test.json").read_text())
    assert data["model_type"] == "gated_dilated_tcn"

    # Test file has the three required test functions
    test_src = open(output.test_file_path).read()
    assert "def test_forward_shape" in test_src
    assert "def test_forward_no_nan" in test_src
    assert "def test_config_instantiation" in test_src


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMLModelImplementorGemini:
    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_implementation(self, tmp_path):
        agent = MLModelImplementor(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
        output = agent.run(_make_input(tmp_path))

        _assert_output(output, tmp_path)

        plugin_src = open(output.model_file_path).read()
        print(f"\n  model_type    : {output.model_type}")
        print(f"  config_fields : {output.config_fields}")
        print(f"\n=== Generated plugin ===\n{plugin_src}")


class TestMLModelImplementorOpenAI:
    def setup_method(self):
        _skip_if_no_key("openai")

    def test_implementation(self, tmp_path):
        agent = MLModelImplementor(provider="openai", model_id="gpt-5-mini")
        output = agent.run(_make_input(tmp_path))

        _assert_output(output, tmp_path)

        plugin_src = open(output.model_file_path).read()
        print(f"\n  model_type    : {output.model_type}")
        print(f"  config_fields : {output.config_fields}")
        print(f"\n=== Generated plugin ===\n{plugin_src}")
