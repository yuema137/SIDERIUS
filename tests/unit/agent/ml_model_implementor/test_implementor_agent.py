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
import pytest
from unittest.mock import MagicMock, patch, call

from agent.schemas.implementor import ImplementorInput, ImplementorOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_model_implementor import MLModelImplementor, _class_name


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
            "loss_config":  {"loss_type": "focal", "gamma": 2.0},
        },
        plugin_dir=str(tmp_path / "models"),
        test_dir=str(tmp_path / "tests"),
        storage=storage,
    )


@pytest.fixture
def agent_with_mocks(inp):
    agent = MLModelImplementor.__new__(MLModelImplementor)
    agent.bridge = MagicMock()
    agent.bridge.generate_text.return_value = FAKE_REASONING
    agent.bridge.generate.return_value = FAKE_CODE_RESPONSE
    return agent


# ---------------------------------------------------------------------------
# TestHelpers
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_class_name_single_word(self):
        assert _class_name("tcn") == "Tcn"

    def test_class_name_two_words(self):
        assert _class_name("attn_unet") == "AttnUnet"

    def test_class_name_three_words(self):
        assert _class_name("gated_dilated_tcn") == "GatedDilatedTcn"

    def test_class_name_single_char_parts(self):
        assert _class_name("s4_model") == "S4Model"


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

    def test_plugin_has_model_type_constant(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        content = open(os.path.join(inp.plugin_dir, "gated_dilated_tcn.py")).read()
        assert 'PLUGIN_MODEL_TYPE = "gated_dilated_tcn"' in content

    def test_plugin_has_config_class_assignment(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        content = open(os.path.join(inp.plugin_dir, "gated_dilated_tcn.py")).read()
        assert "PLUGIN_CONFIG_CLASS = GatedDilatedTcnConfig" in content

    def test_plugin_has_model_class_assignment(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        content = open(os.path.join(inp.plugin_dir, "gated_dilated_tcn.py")).read()
        assert "PLUGIN_MODEL_CLASS = GatedDilatedTcn" in content

    def test_plugin_has_correct_class_name(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        content = open(os.path.join(inp.plugin_dir, "gated_dilated_tcn.py")).read()
        assert "class GatedDilatedTcnConfig(BaseModel):" in content
        assert "class GatedDilatedTcn(nn.Module):" in content

    def test_plugin_contains_llm_config_fields(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        content = open(os.path.join(inp.plugin_dir, "gated_dilated_tcn.py")).read()
        assert "channels" in content
        assert "depth" in content

    def test_test_file_has_shape_test(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        content = open(os.path.join(inp.test_dir, "test_gated_dilated_tcn.py")).read()
        assert "def test_forward_shape" in content

    def test_test_file_has_nan_test(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        content = open(os.path.join(inp.test_dir, "test_gated_dilated_tcn.py")).read()
        assert "def test_forward_no_nan" in content

    def test_test_file_has_config_test(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        content = open(os.path.join(inp.test_dir, "test_gated_dilated_tcn.py")).read()
        assert "def test_config_instantiation" in content

    def test_test_file_imports_correct_module(self, agent_with_mocks, inp):
        agent_with_mocks.run(inp)
        content = open(os.path.join(inp.test_dir, "test_gated_dilated_tcn.py")).read()
        assert "from gated_dilated_tcn import PLUGIN_MODEL_CLASS, PLUGIN_CONFIG_CLASS" in content


# ---------------------------------------------------------------------------
# TestOutputCorrectness
# ---------------------------------------------------------------------------

class TestOutputCorrectness:

    def test_output_is_implementor_output(self, agent_with_mocks, inp):
        output = agent_with_mocks.run(inp)
        assert isinstance(output, ImplementorOutput)

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

    def test_description_file_contains_model_name(self, agent_with_mocks, inp, tmp_path):
        agent_with_mocks.run(inp)
        content = (tmp_path / "models" / "gated_dilated_tcn" / "description.md").read_text()
        assert "GatedDilatedTcn" in content

    def test_description_file_contains_description(self, agent_with_mocks, inp, tmp_path):
        agent_with_mocks.run(inp)
        content = (tmp_path / "models" / "gated_dilated_tcn" / "description.md").read_text()
        assert "A gated dilated TCN for signal denoising." in content

    def test_description_file_contains_mathematical_definition(self, agent_with_mocks, inp, tmp_path):
        agent_with_mocks.run(inp)
        content = (tmp_path / "models" / "gated_dilated_tcn" / "description.md").read_text()
        assert "tanh" in content

    def test_description_file_contains_forward_contract(self, agent_with_mocks, inp, tmp_path):
        agent_with_mocks.run(inp)
        content = (tmp_path / "models" / "gated_dilated_tcn" / "description.md").read_text()
        assert "[B, T] int64" in content
        assert "[B, 256, T] float32" in content

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
