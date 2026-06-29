"""
Unit tests for nodes/ml_model_implementor.py

Tests cover:
  TestLLMCallStructure
    - generate_text called once (reasoning)
    - generate called once (code commit)
    - reasoning injected into code commit prompt
    - generate_text called before generate

  TestFileAssembly
    - plugin file is written at correct path
    - test file is written at correct path
    - plugin file contains PLUGIN_MODEL_TYPE constant
    - plugin file contains PLUGIN_CONFIG_CLASS assignment
    - plugin file contains PLUGIN_MODEL_CLASS assignment
    - plugin file contains class definition with correct name
    - test file contains test_forward_shape
    - test file contains test_forward_no_nan
    - test file contains test_config_instantiation

  TestOutputCorrectness
    - output is ImplementorOutput
    - model_type matches input model_name
    - model_file_path is absolute
    - test_file_path is absolute
    - config_fields from LLM response

  TestFilePersistence
    - output record written to workspace
    - output record is valid JSON
    - output record contains model_type

  TestHelpers
    - _class_name converts snake_case to CamelCase correctly
"""

import json
import os
import textwrap
from unittest.mock import MagicMock, call, patch

import pytest

from agent.schemas.implementor import ImplementorInput, ImplementorOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_model_implementor import (
    MLModelImplementor,
    _build_reasoning_prompt,
    _check_config_field_consistency,
    _class_name,
    _smoke_test_plugin,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_REASONING = (
    "The gated_dilated_tcn architecture uses stacked dilated convolutions with "
    "gated activation. We need: nn.Embedding(256, channels) for token embedding, "
    "followed by a series of WaveNet-style blocks with sigmoid*tanh gating. "
    "Shape trace: [B,T] int64 → embed → [B,channels,T] → blocks → [B,256,T]."
)

FAKE_CODE_RESPONSE = {
    "extra_imports": "",
    "config_fields_code": "    channels: int = Field(default=64, ge=8, le=256)\n    depth: int = Field(default=4, ge=1, le=8)",
    "config_fields": {"channels": 64, "depth": 4},
    "init_body": (
        "        self.embedding = nn.Embedding(256, config.channels)\n"
        "        self.conv_out = nn.Conv1d(config.channels, 256, 1)"
    ),
    "forward_body": (
        "        x = self.embedding(x.long()).transpose(1, 2)  # [B, channels, T]\n"
        "        return self.conv_out(x)  # [B, 256, T]"
    ),
}


@pytest.fixture
def storage(tmp_path):
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="unit_test"),
    )


@pytest.fixture
def inp(tmp_path, storage):
    return ImplementorInput(
        model_name="gated_dilated_tcn",
        model_description="A gated dilated TCN for signal denoising.",
        mathematical_definition="y = tanh(W_f * x) * sigmoid(W_g * x) with dilated convolutions.",
        baseline_config={
            "model_config": {"channels": 64, "depth": 4},
            "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 1, "device": "cuda"},
            "loss_config": {"loss_type": "focal", "gamma": 2.0},
        },
        plugin_dir=str(tmp_path / "models"),
        test_dir=str(tmp_path / "tests"),
        storage=storage,
    )


@pytest.fixture
def agent_with_mocks(inp):
    agent = MLModelImplementor.__new__(MLModelImplementor)
    agent.bridge = MagicMock()
    agent._registry = MagicMock()
    agent.bridge.generate_text.return_value = FAKE_REASONING
    agent.bridge.generate.return_value = FAKE_CODE_RESPONSE
    return agent


# ---------------------------------------------------------------------------
# TestHelpers
# ---------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize(
        "snake_case,expected_camel_case",
        [
            pytest.param("tcn", "Tcn", id="single_word"),
            pytest.param("attn_unet", "AttnUnet", id="two_words"),
            pytest.param("gated_dilated_tcn", "GatedDilatedTcn", id="three_words"),
            pytest.param("s4_model", "S4Model", id="single_char_parts"),
        ],
    )
    def test_class_name_snake_to_camel(self, snake_case, expected_camel_case):
        assert _class_name(snake_case) == expected_camel_case


# ---------------------------------------------------------------------------
# TestLLMCallStructure
# ---------------------------------------------------------------------------


class TestLLMCallStructure:
    def test_generate_text_called_once(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        agent_with_mocks.bridge.generate_text.assert_called_once()

    def test_generate_called_once(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        agent_with_mocks.bridge.generate.assert_called_once()

    def test_reasoning_injected_into_code_prompt(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        code_user_prompt = agent_with_mocks.bridge.generate.call_args[0][1]
        assert FAKE_REASONING in code_user_prompt

    def test_generate_text_called_before_generate(self, agent_with_mocks, inp):
        call_order = []
        agent_with_mocks.bridge.generate_text.side_effect = lambda *a, **k: (
            call_order.append("generate_text") or FAKE_REASONING
        )
        agent_with_mocks.bridge.generate.side_effect = lambda *a, **k: (
            call_order.append("generate") or FAKE_CODE_RESPONSE
        )
        agent_with_mocks.run(inp)
        assert call_order == ["generate_text", "generate"]


# ---------------------------------------------------------------------------
# TestFileAssembly
# ---------------------------------------------------------------------------


class TestFileAssembly:
    def test_plugin_file_written(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        assert os.path.exists(os.path.join(inp.plugin_dir, "gated_dilated_tcn.py"))

    def test_test_file_written(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        assert os.path.exists(os.path.join(inp.test_dir, "test_gated_dilated_tcn.py"))

    @pytest.mark.parametrize(
        "dir_attr,filename,expected_substring",
        [
            pytest.param(
                "plugin_dir",
                "gated_dilated_tcn.py",
                'PLUGIN_MODEL_TYPE = "gated_dilated_tcn"',
                id="plugin_model_type_constant",
            ),
            pytest.param(
                "plugin_dir",
                "gated_dilated_tcn.py",
                "PLUGIN_CONFIG_CLASS = GatedDilatedTcnConfig",
                id="plugin_config_class_assignment",
            ),
            pytest.param(
                "plugin_dir",
                "gated_dilated_tcn.py",
                "PLUGIN_MODEL_CLASS = GatedDilatedTcn",
                id="plugin_model_class_assignment",
            ),
            pytest.param(
                "plugin_dir",
                "gated_dilated_tcn.py",
                "class GatedDilatedTcnConfig(BaseModel):",
                id="plugin_config_class_def",
            ),
            pytest.param(
                "plugin_dir",
                "gated_dilated_tcn.py",
                "class GatedDilatedTcn(nn.Module):",
                id="plugin_model_class_def",
            ),
            pytest.param(
                "plugin_dir",
                "gated_dilated_tcn.py",
                "channels",
                id="plugin_has_llm_field_channels",
            ),
            pytest.param(
                "plugin_dir",
                "gated_dilated_tcn.py",
                "depth",
                id="plugin_has_llm_field_depth",
            ),
            pytest.param(
                "test_dir",
                "test_gated_dilated_tcn.py",
                "def test_forward_shape",
                id="test_has_forward_shape",
            ),
            pytest.param(
                "test_dir",
                "test_gated_dilated_tcn.py",
                "def test_forward_no_nan",
                id="test_has_forward_no_nan",
            ),
            pytest.param(
                "test_dir",
                "test_gated_dilated_tcn.py",
                "def test_config_instantiation",
                id="test_has_config_instantiation",
            ),
            pytest.param(
                "test_dir",
                "test_gated_dilated_tcn.py",
                "from gated_dilated_tcn import PLUGIN_MODEL_CLASS, PLUGIN_CONFIG_CLASS",
                id="test_imports_correct_module",
            ),
        ],
    )
    def test_generated_file_contains_token(
        self, agent_with_mocks, inp, dir_attr, filename, expected_substring
    ):
        agent_with_mocks.run(inp)
        content = open(os.path.join(getattr(inp, dir_attr), filename)).read()
        assert expected_substring in content


# ---------------------------------------------------------------------------
# TestOutputCorrectness
# ---------------------------------------------------------------------------


class TestOutputCorrectness:
    def test_model_type_matches_input(self, agent_with_mocks, inp):
        output = agent_with_mocks.run(inp)
        assert output.model_type == "gated_dilated_tcn"

    def test_model_file_path_is_absolute(self, agent_with_mocks, inp):
        output = agent_with_mocks.run(inp)
        assert os.path.isabs(output.model_file_path)

    def test_test_file_path_is_absolute(self, agent_with_mocks, inp):
        output = agent_with_mocks.run(inp)
        assert os.path.isabs(output.test_file_path)

    def test_config_fields_from_llm(self, agent_with_mocks, inp):
        output = agent_with_mocks.run(inp)
        assert output.config_fields == {"channels": 64, "depth": 4}

    def test_model_description_from_input(self, agent_with_mocks, inp):
        output = agent_with_mocks.run(inp)
        assert output.model_description == inp.model_description

    def test_mathematical_definition_from_input(self, agent_with_mocks, inp):
        output = agent_with_mocks.run(inp)
        assert output.mathematical_definition == inp.mathematical_definition


# ---------------------------------------------------------------------------
# TestDescriptionFile
# ---------------------------------------------------------------------------


class TestDescriptionFile:
    def test_description_file_written(self, agent_with_mocks, inp, tmp_path):
        agent_with_mocks.run(inp)
        desc_path = tmp_path / "models" / "gated_dilated_tcn" / "description.md"
        assert desc_path.exists(), "description.md not written"

    @pytest.mark.parametrize(
        "expected_substring",
        [
            pytest.param("GatedDilatedTcn", id="contains_model_class_name"),
            pytest.param("A gated dilated TCN for signal denoising.", id="contains_description"),
            pytest.param("tanh", id="contains_mathematical_definition"),
            pytest.param("[B, T] int64", id="contains_forward_input_contract"),
            pytest.param("[B, 256, T] float32", id="contains_forward_output_contract"),
        ],
    )
    def test_description_file_contains_token(
        self, agent_with_mocks, inp, tmp_path, expected_substring
    ):
        agent_with_mocks.run(inp)
        content = (tmp_path / "models" / "gated_dilated_tcn" / "description.md").read_text()
        assert expected_substring in content

    def test_description_file_path_in_output(self, agent_with_mocks, inp, tmp_path):
        output = agent_with_mocks.run(inp)
        assert os.path.isabs(output.description_file_path)
        assert output.description_file_path.endswith("description.md")
        assert os.path.exists(output.description_file_path)


# ---------------------------------------------------------------------------
# TestFilePersistence
# ---------------------------------------------------------------------------


class TestFilePersistence:
    def test_output_record_written(self, agent_with_mocks, inp, tmp_path):
        agent_with_mocks.run(inp)
        assert (tmp_path / "implementor_unit_test.json").exists()

    def test_output_record_is_valid_json(self, agent_with_mocks, inp, tmp_path):
        agent_with_mocks.run(inp)
        data = json.loads((tmp_path / "implementor_unit_test.json").read_text())
        assert isinstance(data, dict)

    def test_output_record_contains_model_type(self, agent_with_mocks, inp, tmp_path):
        agent_with_mocks.run(inp)
        data = json.loads((tmp_path / "implementor_unit_test.json").read_text())
        assert data["model_type"] == "gated_dilated_tcn"


# ---------------------------------------------------------------------------
# TestConfigFieldConsistency
# ---------------------------------------------------------------------------


class TestConfigFieldConsistency:
    """Tests for _check_config_field_consistency()."""

    def test_all_fields_declared_returns_empty(self):
        code = {
            "config_fields_code": "    channels: int = Field(default=64)",
            "config_fields": {"channels": 64},
            "init_body": "        self.conv = nn.Conv1d(config.channels, 256, 1)",
        }
        assert _check_config_field_consistency(code) == []

    def test_missing_field_returns_name(self):
        code = {
            "config_fields_code": "    channels: int = Field(default=64)",
            "config_fields": {"channels": 64},
            "init_body": "        self.emb = nn.Embedding(256, config.embed_dim)",
        }
        assert _check_config_field_consistency(code) == ["embed_dim"]

    def test_multiple_missing_fields(self):
        code = {
            "config_fields_code": "",
            "config_fields": {},
            "init_body": (
                "        self.emb = nn.Embedding(256, config.embed_dim)\n"
                "        self.layers = nn.ModuleList([nn.Linear(config.hidden_dim, config.hidden_dim)])"
            ),
        }
        missing = _check_config_field_consistency(code)
        assert "embed_dim" in missing
        assert "hidden_dim" in missing

    def test_template_fields_accepted(self):
        """segmentation_size and batch_size are template-provided — should not flag."""
        code = {
            "config_fields_code": "",
            "config_fields": {},
            "init_body": "        self.size = config.segmentation_size",
        }
        assert _check_config_field_consistency(code) == []

    def test_config_fields_dict_sufficient(self):
        """If field is in config_fields dict but not config_fields_code, still OK."""
        code = {
            "config_fields_code": "",
            "config_fields": {"channels": 64},
            "init_body": "        self.conv = nn.Conv1d(config.channels, 256, 1)",
        }
        assert _check_config_field_consistency(code) == []

    def test_empty_init_body_returns_empty(self):
        code = {
            "config_fields_code": "    channels: int = Field(default=64)",
            "config_fields": {},
            "init_body": "",
        }
        assert _check_config_field_consistency(code) == []

    def test_run_raises_on_missing_config_field(self, inp):
        """Integration: run() raises ValueError when LLM omits a config field."""
        bad_code = {
            "extra_imports": "",
            "config_fields_code": "    channels: int = Field(default=64, ge=8)",
            "config_fields": {"channels": 64},
            "init_body": "        self.emb = nn.Embedding(256, config.embed_dim)",
            "forward_body": "        return self.emb(x).transpose(1,2)",
        }
        agent = MLModelImplementor.__new__(MLModelImplementor)
        agent.bridge = MagicMock()
        agent._registry = MagicMock()
        agent.bridge.generate_text.return_value = "reasoning..."
        agent.bridge.generate.return_value = bad_code

        with pytest.raises(ValueError, match="embed_dim"):
            agent.run(inp)


# ---------------------------------------------------------------------------
# TestSmokeTest
# ---------------------------------------------------------------------------


class TestSmokeTest:
    """Tests for _smoke_test_plugin()."""

    VALID_PLUGIN = textwrap.dedent("""\
        import torch
        import torch.nn as nn
        from pydantic import BaseModel, Field

        PLUGIN_MODEL_TYPE = "test_model"

        class TestModelConfig(BaseModel):
            segmentation_size: int = Field(default=40000, ge=1)
            batch_size: int = Field(default=1, ge=1)
            channels: int = Field(default=64, ge=8)

        PLUGIN_CONFIG_CLASS = TestModelConfig

        class TestModel(nn.Module):
            def __init__(self, config: "TestModelConfig"):
                super().__init__()
                self.embedding = nn.Embedding(256, config.channels)
                self.conv_out = nn.Conv1d(config.channels, 256, 1)

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                x = self.embedding(x.long()).transpose(1, 2)
                return self.conv_out(x)

        PLUGIN_MODEL_CLASS = TestModel
    """)

    def test_valid_plugin_returns_none(self):
        assert _smoke_test_plugin(self.VALID_PLUGIN, "test_model") is None

    def test_missing_attribute_returns_error(self):
        # Plugin with no PLUGIN_MODEL_CLASS
        bad = self.VALID_PLUGIN.replace("PLUGIN_MODEL_CLASS = TestModel", "")
        result = _smoke_test_plugin(bad, "test_model")
        assert result is not None
        assert "PLUGIN_MODEL_CLASS" in result

    def test_shape_mismatch_returns_error(self):
        # Make forward return wrong shape [B, 128, T] instead of [B, 256, T]
        bad = self.VALID_PLUGIN.replace(
            "nn.Conv1d(config.channels, 256, 1)",
            "nn.Conv1d(config.channels, 128, 1)",
        )
        result = _smoke_test_plugin(bad, "test_model")
        assert result is not None
        assert "shape mismatch" in result

    def test_runtime_error_returns_error(self):
        # Reference a config field that doesn't exist
        bad = self.VALID_PLUGIN.replace(
            "nn.Embedding(256, config.channels)",
            "nn.Embedding(256, config.embed_dim)",
        )
        result = _smoke_test_plugin(bad, "test_model")
        assert result is not None
        assert "embed_dim" in result

    def test_run_raises_after_retries_exhausted(self, inp):
        """run() raises after MAX_RETRIES when smoke test keeps failing."""
        bad_code = {
            "extra_imports": "",
            "config_fields_code": "    channels: int = Field(default=64, ge=8)",
            "config_fields": {"channels": 64},
            "init_body": (
                "        self.embedding = nn.Embedding(256, config.channels)\n"
                "        self.conv_out = nn.Conv1d(config.channels, 128, 1)"
            ),
            "forward_body": (
                "        x = self.embedding(x.long()).transpose(1, 2)\n"
                "        return self.conv_out(x)"
            ),
        }
        agent = MLModelImplementor.__new__(MLModelImplementor)
        agent.bridge = MagicMock()
        agent._registry = MagicMock()
        agent.bridge.generate_text.return_value = "reasoning..."
        # All attempts return the same bad code
        agent.bridge.generate.return_value = bad_code

        with pytest.raises(ValueError, match="Code generation failed after"):
            agent.run(inp)


# ---------------------------------------------------------------------------
# TestSelfCorrection
# ---------------------------------------------------------------------------


class TestSelfCorrection:
    """Tests for the generate → validate → repair loop."""

    def test_successful_first_attempt_no_repair(self, agent_with_mocks, inp):
        """When first attempt passes, generate is called once (no repair)."""
        agent_with_mocks.run(inp)
        # generate_text once (reasoning) + generate once (code commit)
        assert agent_with_mocks.bridge.generate.call_count == 1

    def test_repair_called_on_first_failure(self, inp):
        """When first attempt fails but repair succeeds, generate is called twice."""
        bad_code = {
            "extra_imports": "",
            "config_fields_code": "    channels: int = Field(default=64, ge=8)",
            "config_fields": {"channels": 64},
            "init_body": "        self.emb = nn.Embedding(256, config.embed_dim)",
            "forward_body": "        return self.emb(x).transpose(1,2)",
        }
        good_code = FAKE_CODE_RESPONSE.copy()

        agent = MLModelImplementor.__new__(MLModelImplementor)
        agent.bridge = MagicMock()
        agent._registry = MagicMock()
        agent.bridge.generate_text.return_value = FAKE_REASONING
        # First call returns bad code, second (repair) returns good code
        agent.bridge.generate.side_effect = [bad_code, good_code]

        output = agent.run(inp)
        assert isinstance(output, ImplementorOutput)
        # generate called twice: initial + 1 repair
        assert agent.bridge.generate.call_count == 2

    def test_repair_prompt_contains_error(self, inp):
        """The repair call receives the validation error in the prompt."""
        bad_code = {
            "extra_imports": "",
            "config_fields_code": "    channels: int = Field(default=64, ge=8)",
            "config_fields": {"channels": 64},
            "init_body": "        self.emb = nn.Embedding(256, config.embed_dim)",
            "forward_body": "        return self.emb(x).transpose(1,2)",
        }
        good_code = FAKE_CODE_RESPONSE.copy()

        agent = MLModelImplementor.__new__(MLModelImplementor)
        agent.bridge = MagicMock()
        agent._registry = MagicMock()
        agent.bridge.generate_text.return_value = FAKE_REASONING
        agent.bridge.generate.side_effect = [bad_code, good_code]

        agent.run(inp)
        # Second generate call is the repair — check its user prompt
        repair_user_prompt = agent.bridge.generate.call_args_list[1][0][1]
        assert "embed_dim" in repair_user_prompt
        assert "Error" in repair_user_prompt

    def test_max_retries_exhausted_raises(self, inp):
        """When all retries fail, ValueError is raised with attempt count."""
        bad_code = {
            "extra_imports": "",
            "config_fields_code": "    channels: int = Field(default=64, ge=8)",
            "config_fields": {"channels": 64},
            "init_body": "        self.emb = nn.Embedding(256, config.embed_dim)",
            "forward_body": "        return self.emb(x).transpose(1,2)",
        }
        agent = MLModelImplementor.__new__(MLModelImplementor)
        agent.bridge = MagicMock()
        agent._registry = MagicMock()
        agent.bridge.generate_text.return_value = FAKE_REASONING
        agent.bridge.generate.return_value = bad_code

        with pytest.raises(ValueError, match="Code generation failed after 3 attempts"):
            agent.run(inp)
        # 1 initial + 2 retries = 3 generate calls
        assert agent.bridge.generate.call_count == 3

    def test_second_retry_succeeds(self, inp):
        """When first repair fails but second repair succeeds."""
        bad_code = {
            "extra_imports": "",
            "config_fields_code": "    channels: int = Field(default=64, ge=8)",
            "config_fields": {"channels": 64},
            "init_body": "        self.emb = nn.Embedding(256, config.embed_dim)",
            "forward_body": "        return self.emb(x).transpose(1,2)",
        }
        good_code = FAKE_CODE_RESPONSE.copy()

        agent = MLModelImplementor.__new__(MLModelImplementor)
        agent.bridge = MagicMock()
        agent._registry = MagicMock()
        agent.bridge.generate_text.return_value = FAKE_REASONING
        # First two fail, third succeeds
        agent.bridge.generate.side_effect = [bad_code, bad_code, good_code]

        output = agent.run(inp)
        assert isinstance(output, ImplementorOutput)
        assert agent.bridge.generate.call_count == 3


# ---------------------------------------------------------------------------
# Expert advice prompt injection tests
# ---------------------------------------------------------------------------


class TestExpertAdviceInPrompt:
    """Verify expert_advice flows into the reasoning prompt."""

    def _make_input(self):
        return ImplementorInput(
            model_name="test_model",
            model_description="A test model.",
            mathematical_definition="Linear → ReLU → Linear",
            baseline_config={"model_config": {"channels": 64}, "train_config": {}},
            storage={"backend": "local", "local": {"workspace": "/tmp/test", "run_name": "r1"}},
        )

    def test_includes_expert_advice_string(self):
        inp = self._make_input()
        inp.expert_advice = "Use grouped convolutions instead of standard conv1d"
        prompt = _build_reasoning_prompt(inp)
        assert "Expert Guidance" in prompt
        assert "grouped convolutions" in prompt

    def test_excludes_expert_when_empty(self):
        inp = self._make_input()
        inp.expert_advice = ""
        prompt = _build_reasoning_prompt(inp)
        assert "Expert Guidance" not in prompt

    def test_includes_structured_expert_advice(self):
        from agent.schemas.hyperparam_tuning import ExpertAdvice

        inp = self._make_input()
        inp.expert_advice = ExpertAdvice(
            focus_areas=["efficient conv layers"],
            constraints=["no external dependencies"],
            known_failures=[],
            suggested_directions=["depthwise separable convolutions"],
            rationale="Reduce parameter count.",
        )
        prompt = _build_reasoning_prompt(inp)
        assert "Expert Guidance" in prompt
        assert "efficient conv layers" in prompt
        assert "depthwise separable" in prompt

    def test_expert_advice_before_human_advice(self):
        inp = self._make_input()
        inp.expert_advice = "Expert guidance here"
        inp.human_advice = "Human guidance here"
        prompt = _build_reasoning_prompt(inp)
        expert_pos = prompt.index("Expert Guidance")
        human_pos = prompt.index("Human Guidance")
        assert expert_pos < human_pos
