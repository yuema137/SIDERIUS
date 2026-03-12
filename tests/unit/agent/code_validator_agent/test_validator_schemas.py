"""
Tests for agent/schemas/validator.py
"""
import pytest
from pydantic import ValidationError

from agent.schemas.validator import ValidatorInput, ValidatorOutput


class TestValidatorInput:

    def test_valid(self):
        inp = ValidatorInput(
            model_type="attn_unet",
            model_file_path="/abs/agent_generated/models/attn_unet.py",
            test_file_path="/abs/agent_generated/tests/test_attn_unet.py",
        )
        assert inp.model_type == "attn_unet"
        assert inp.storage.backend == "local"

    def test_missing_model_type_raises(self):
        with pytest.raises(ValidationError) as exc:
            ValidatorInput(
                model_file_path="/abs/model.py",
                test_file_path="/abs/test.py",
            )
        assert "model_type" in str(exc.value)

    def test_missing_model_file_path_raises(self):
        with pytest.raises(ValidationError) as exc:
            ValidatorInput(
                model_type="attn_unet",
                test_file_path="/abs/test.py",
            )
        assert "model_file_path" in str(exc.value)

    def test_storage_custom(self):
        inp = ValidatorInput(
            model_type="attn_unet",
            model_file_path="/abs/model.py",
            test_file_path="/abs/test.py",
            storage={"backend": "local", "local": {"workspace": "/reports", "run_name": "r1"}},
        )
        assert inp.storage.local.workspace == "/reports"


class TestValidatorOutput:

    def test_valid_passed(self):
        out = ValidatorOutput(
            passed=True,
            model_type="attn_unet",
            plugin_registered=True,
        )
        assert out.passed is True
        assert out.error_message is None

    def test_valid_failed_with_error(self):
        out = ValidatorOutput(
            passed=False,
            model_type="attn_unet",
            plugin_registered=False,
            error_message="AssertionError: expected shape (2, 256, 40000) got (2, 40000, 256)",
        )
        assert out.passed is False
        assert "AssertionError" in out.error_message

    def test_plugin_registered_false_with_passed_true(self):
        # Schema does not enforce consistency between passed and plugin_registered —
        # that is runtime logic in the validator node itself
        out = ValidatorOutput(passed=True, model_type="x", plugin_registered=False)
        assert out.passed is True

    def test_missing_model_type_raises(self):
        with pytest.raises(ValidationError) as exc:
            ValidatorOutput(passed=True, plugin_registered=True)
        assert "model_type" in str(exc.value)
