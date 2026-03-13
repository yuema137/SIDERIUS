"""
Tier 1 integration test for ml_code_validator_agent (Node 5).

Exercises the node in isolation with synthetic plugin files written to a
temporary directory. Now includes LLM code review (check 7), so a valid
API key is required.

Tests verify that the real subprocess pytest runner, the real importlib plugin
loader, the real filesystem checks, the in-process instantiation + gradient
checks, and the LLM code review all work end-to-end.

Run with:
  uv run pytest -m real_run tests/integration/nodes/test_ml_code_validator_agent.py -v -s

DO NOT run in CI.
"""
import json
import os
import textwrap
import pytest
from dotenv import load_dotenv

load_dotenv()

from agent.schemas.validator import ValidatorInput, ValidatorOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_code_validator_agent import MLCodeValidatorAgent


pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------

def _skip_if_no_key(provider: str = "gemini"):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set — skipping real API test")


# ---------------------------------------------------------------------------
# Synthetic plugin files
# ---------------------------------------------------------------------------

VALID_PLUGIN_SRC = textwrap.dedent("""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel, Field

    PLUGIN_MODEL_TYPE = "integration_test_model"

    class IntegrationTestModelConfig(BaseModel):
        depth: int = Field(default=2, ge=1)
        channels: int = Field(default=32, ge=1)
        use_bias: bool = Field(default=True)
        lr: float = Field(default=1e-3, gt=0.0)

    class IntegrationTestModel(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.emb = nn.Embedding(256, config.channels)
            self.proj = nn.Conv1d(config.channels, 256, kernel_size=1)

        def forward(self, x):
            # x: [B, T] int64 -> [B, 256, T] float32
            out = self.emb(x).permute(0, 2, 1)  # [B, channels, T]
            return self.proj(out)                 # [B, 256, T]

    PLUGIN_CONFIG_CLASS = IntegrationTestModelConfig
    PLUGIN_MODEL_CLASS  = IntegrationTestModel
""")

VALID_TEST_SRC = textwrap.dedent("""\
    import torch
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import importlib.util
    import pathlib

    def _load():
        path = str(pathlib.Path(__file__).parent / "integration_test_model.py")
        spec = importlib.util.spec_from_file_location("_plugin", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_config_instantiation():
        mod = _load()
        cfg = mod.PLUGIN_CONFIG_CLASS()
        assert cfg.depth >= 1
        assert cfg.channels >= 1

    def test_forward_shape():
        mod = _load()
        cfg = mod.PLUGIN_CONFIG_CLASS()
        model = mod.PLUGIN_MODEL_CLASS(cfg)
        model.eval()
        x = torch.randint(0, 256, (2, 64))
        with torch.no_grad():
            out = model(x)
        assert out.shape == (2, 256, 64)

    def test_forward_no_nan():
        mod = _load()
        cfg = mod.PLUGIN_CONFIG_CLASS()
        model = mod.PLUGIN_MODEL_CLASS(cfg)
        model.eval()
        x = torch.randint(0, 256, (1, 32))
        with torch.no_grad():
            out = model(x)
        assert not torch.isnan(out).any()
""")

VALID_DESCRIPTION = (
    "# Integration Test Model\n\n"
    "A minimal model used for integration testing of ml_code_validator_agent.\n"
    "It consists of a learned embedding layer followed by a pointwise projection.\n"
    "Input: [B, T] int64 token indices. Output: [B, 256, T] float32 logits.\n"
)

VALID_CONFIG_FIELDS = {"depth": 2, "channels": 32, "use_bias": True, "lr": 1e-3}

MODEL_DESCRIPTION = (
    "A minimal integration test model with an embedding layer and pointwise convolution. "
    "Takes integer token indices and projects them to 256-dimensional logits per timestep."
)

MATHEMATICAL_DEFINITION = (
    "1. Embedding: x -> nn.Embedding(256, channels)(x) -> [B, T, channels]. "
    "2. Transpose: [B, T, channels] -> [B, channels, T]. "
    "3. Projection: nn.Conv1d(channels, 256, kernel_size=1) -> [B, 256, T]."
)


def _write_valid_files(tmp_path):
    """Write a complete valid plugin + test + description to tmp_path."""
    plugin_path = tmp_path / "integration_test_model.py"
    plugin_path.write_text(VALID_PLUGIN_SRC)

    test_path = tmp_path / "test_integration_test_model.py"
    test_path.write_text(VALID_TEST_SRC)

    desc_dir = tmp_path / "integration_test_model"
    desc_dir.mkdir()
    desc_path = desc_dir / "description.md"
    desc_path.write_text(VALID_DESCRIPTION)

    return str(plugin_path), str(test_path), str(desc_path)


def _make_input(tmp_path, **overrides) -> ValidatorInput:
    plugin_path, test_path, desc_path = _write_valid_files(tmp_path)
    defaults = dict(
        model_type="integration_test_model",
        model_file_path=plugin_path,
        test_file_path=test_path,
        description_file_path=desc_path,
        config_fields=VALID_CONFIG_FIELDS,
        model_description=MODEL_DESCRIPTION,
        mathematical_definition=MATHEMATICAL_DEFINITION,
        llm_provider="gemini",
        llm_model_id="gemini-3.1-flash-lite-preview",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="node_test"),
        ),
    )
    defaults.update(overrides)
    return ValidatorInput(**defaults)


# ---------------------------------------------------------------------------
# All-pass case
# ---------------------------------------------------------------------------

class TestMLCodeValidatorAgentAllPass:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_passed_is_true(self, tmp_path):
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(_make_input(tmp_path))
        assert out.passed is True

    def test_all_individual_checks_true(self, tmp_path):
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(_make_input(tmp_path))
        assert out.plugin_registered is True
        assert out.tests_passed is True
        assert out.description_valid is True
        assert out.config_fields_valid is True
        assert out.instantiation_passed is True
        assert out.gradient_check_passed is True
        assert out.llm_review_passed is True

    def test_output_is_validator_output(self, tmp_path):
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(_make_input(tmp_path))
        assert isinstance(out, ValidatorOutput)

    def test_model_type_set(self, tmp_path):
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(_make_input(tmp_path))
        assert out.model_type == "integration_test_model"

    def test_error_message_is_none(self, tmp_path):
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(_make_input(tmp_path))
        assert out.error_message is None

    def test_test_output_captured(self, tmp_path):
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(_make_input(tmp_path))
        assert out.test_output is not None
        assert "passed" in out.test_output

    def test_llm_review_spec_alignment(self, tmp_path):
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(_make_input(tmp_path))
        assert out.llm_review_spec_alignment is True

    def test_output_file_written(self, tmp_path):
        MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(_make_input(tmp_path))
        assert (tmp_path / "validation_node_test.json").exists()

    def test_output_file_content(self, tmp_path):
        MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(_make_input(tmp_path))
        data = json.loads((tmp_path / "validation_node_test.json").read_text())
        assert data["passed"] is True
        assert data["model_type"] == "integration_test_model"
        assert data["instantiation_passed"] is True
        assert data["gradient_check_passed"] is True
        assert data["llm_review_passed"] is True


# ---------------------------------------------------------------------------
# Plugin load failure
# ---------------------------------------------------------------------------

class TestMLCodeValidatorAgentPluginFailure:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_broken_import_sets_plugin_registered_false(self, tmp_path):
        plugin_path = tmp_path / "broken.py"
        plugin_path.write_text("import nonexistent_library_xyz\n")
        inp = _make_input(tmp_path, model_file_path=str(plugin_path))
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert out.plugin_registered is False
        assert out.passed is False

    def test_missing_attribute_sets_plugin_registered_false(self, tmp_path):
        plugin_path = tmp_path / "incomplete.py"
        plugin_path.write_text("PLUGIN_MODEL_TYPE = 'test'\n")
        inp = _make_input(tmp_path, model_file_path=str(plugin_path))
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert out.plugin_registered is False

    def test_error_message_present_on_plugin_failure(self, tmp_path):
        plugin_path = tmp_path / "broken.py"
        plugin_path.write_text("import nonexistent_library_xyz\n")
        inp = _make_input(tmp_path, model_file_path=str(plugin_path))
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert out.error_message is not None


# ---------------------------------------------------------------------------
# Test suite failure
# ---------------------------------------------------------------------------

class TestMLCodeValidatorAgentTestFailure:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_failing_pytest_sets_tests_passed_false(self, tmp_path):
        test_path = tmp_path / "test_fail.py"
        test_path.write_text("def test_always_fails(): assert False\n")
        inp = _make_input(tmp_path, test_file_path=str(test_path))
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert out.tests_passed is False
        assert out.passed is False

    def test_failing_test_output_captured(self, tmp_path):
        test_path = tmp_path / "test_fail.py"
        test_path.write_text("def test_always_fails(): assert False\n")
        inp = _make_input(tmp_path, test_file_path=str(test_path))
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert out.test_output is not None
        assert "FAILED" in out.test_output or "failed" in out.test_output


# ---------------------------------------------------------------------------
# Description failure
# ---------------------------------------------------------------------------

class TestMLCodeValidatorAgentDescriptionFailure:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_missing_description_sets_description_valid_false(self, tmp_path):
        inp = _make_input(
            tmp_path,
            description_file_path=str(tmp_path / "nonexistent.md"),
        )
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert out.description_valid is False
        assert out.passed is False

    def test_too_short_description_sets_description_valid_false(self, tmp_path):
        short_desc = tmp_path / "short.md"
        short_desc.write_text("Too short.")
        inp = _make_input(tmp_path, description_file_path=str(short_desc))
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert out.description_valid is False


# ---------------------------------------------------------------------------
# Config fields failure
# ---------------------------------------------------------------------------

class TestMLCodeValidatorAgentConfigFailure:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_list_config_field_sets_config_fields_valid_false(self, tmp_path):
        inp = _make_input(tmp_path, config_fields={"depth": 2, "kernel_sizes": [3, 5, 7]})
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert out.config_fields_valid is False
        assert out.passed is False

    def test_dict_config_field_sets_config_fields_valid_false(self, tmp_path):
        inp = _make_input(tmp_path, config_fields={"nested": {"a": 1}})
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert out.config_fields_valid is False
