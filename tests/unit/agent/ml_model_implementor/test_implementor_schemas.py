"""
Tests for agent/schemas/implementor.py
"""
import pytest
from pydantic import ValidationError

from agent.schemas.implementor import ImplementorInput, ImplementorOutput


class TestImplementorInput:

    def test_valid(self):
        inp = ImplementorInput(
            model_name="attn_unet",
            model_description="Attention U-Net.",
            mathematical_definition="Encoder: 3 down blocks.",
            baseline_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        )
        assert inp.model_name == "attn_unet"
        assert inp.plugin_dir == "agent_generated/models"
        assert inp.test_dir == "agent_generated/tests"
        assert inp.storage.backend == "local"

    def test_custom_plugin_and_test_dirs(self):
        inp = ImplementorInput(
            model_name="attn_unet",
            model_description="x",
            mathematical_definition="x",
            baseline_config={},
            plugin_dir="/custom/models",
            test_dir="/custom/tests",
        )
        assert inp.plugin_dir == "/custom/models"
        assert inp.test_dir == "/custom/tests"

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError) as exc:
            ImplementorInput(
                model_description="x",
                mathematical_definition="x",
                baseline_config={},
            )
        assert "model_name" in str(exc.value)

    def test_missing_mathematical_definition_raises(self):
        with pytest.raises(ValidationError) as exc:
            ImplementorInput(
                model_name="attn_unet",
                model_description="x",
                baseline_config={},
            )
        assert "mathematical_definition" in str(exc.value)

    def test_storage_independent_of_plugin_dir(self):
        # plugin_dir and test_dir are separate from storage.local.workspace
        inp = ImplementorInput(
            model_name="x",
            model_description="x",
            mathematical_definition="x",
            baseline_config={},
            storage={"backend": "local", "local": {"workspace": "/runs", "run_name": "r1"}},
        )
        assert inp.storage.local.workspace == "/runs"
        assert inp.plugin_dir == "agent_generated/models"  # unchanged


class TestImplementorOutput:

    def test_valid(self):
        out = ImplementorOutput(
            model_type="attn_unet",
            model_file_path="/abs/agent_generated/models/attn_unet.py",
            test_file_path="/abs/agent_generated/tests/test_attn_unet.py",
            config_fields={"depth": 2, "num_heads": 4},
        )
        assert out.model_type == "attn_unet"
        assert out.config_fields["depth"] == 2

    def test_missing_model_file_path_raises(self):
        with pytest.raises(ValidationError) as exc:
            ImplementorOutput(
                model_type="attn_unet",
                test_file_path="/abs/test.py",
                config_fields={},
            )
        assert "model_file_path" in str(exc.value)
