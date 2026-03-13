"""
Tests for agent/schemas/validator.py
"""
import pytest
from pydantic import ValidationError

from agent.schemas.validator import ValidatorInput, ValidatorOutput, LLMCodeReview


VALID_INPUT_KWARGS = dict(
    model_type="attn_unet",
    model_file_path="/abs/agent_generated/models/attn_unet.py",
    test_file_path="/abs/agent_generated/tests/test_attn_unet.py",
    description_file_path="/abs/agent_generated/models/attn_unet/description.md",
    config_fields={"depth": 2, "channels": 64},
    model_description="A U-Net variant with multi-head self-attention at the bottleneck.",
    mathematical_definition="1. Embedding: nn.Embedding(256, 32). 2. Encoder: 3 down-blocks.",
)


class TestValidatorInput:

    def test_valid(self):
        inp = ValidatorInput(**VALID_INPUT_KWARGS)
        assert inp.model_type == "attn_unet"
        assert inp.storage.backend == "local"

    def test_description_file_path_present(self):
        inp = ValidatorInput(**VALID_INPUT_KWARGS)
        assert inp.description_file_path.endswith("description.md")

    def test_config_fields_present(self):
        inp = ValidatorInput(**VALID_INPUT_KWARGS)
        assert inp.config_fields == {"depth": 2, "channels": 64}

    def test_model_description_present(self):
        inp = ValidatorInput(**VALID_INPUT_KWARGS)
        assert "U-Net" in inp.model_description

    def test_mathematical_definition_present(self):
        inp = ValidatorInput(**VALID_INPUT_KWARGS)
        assert "Embedding" in inp.mathematical_definition

    def test_default_llm_provider(self):
        inp = ValidatorInput(**VALID_INPUT_KWARGS)
        assert inp.llm_provider == "gemini"

    def test_default_llm_model_id(self):
        inp = ValidatorInput(**VALID_INPUT_KWARGS)
        assert inp.llm_model_id == "gemini-3.1-flash-lite-preview"

    def test_custom_llm_provider(self):
        inp = ValidatorInput(**VALID_INPUT_KWARGS, llm_provider="openai")
        assert inp.llm_provider == "openai"

    def test_missing_model_type_raises(self):
        kwargs = {k: v for k, v in VALID_INPUT_KWARGS.items() if k != "model_type"}
        with pytest.raises(ValidationError) as exc:
            ValidatorInput(**kwargs)
        assert "model_type" in str(exc.value)

    def test_missing_model_file_path_raises(self):
        kwargs = {k: v for k, v in VALID_INPUT_KWARGS.items() if k != "model_file_path"}
        with pytest.raises(ValidationError) as exc:
            ValidatorInput(**kwargs)
        assert "model_file_path" in str(exc.value)

    def test_missing_description_file_path_raises(self):
        kwargs = {k: v for k, v in VALID_INPUT_KWARGS.items() if k != "description_file_path"}
        with pytest.raises(ValidationError) as exc:
            ValidatorInput(**kwargs)
        assert "description_file_path" in str(exc.value)

    def test_missing_config_fields_raises(self):
        kwargs = {k: v for k, v in VALID_INPUT_KWARGS.items() if k != "config_fields"}
        with pytest.raises(ValidationError) as exc:
            ValidatorInput(**kwargs)
        assert "config_fields" in str(exc.value)

    def test_missing_model_description_raises(self):
        kwargs = {k: v for k, v in VALID_INPUT_KWARGS.items() if k != "model_description"}
        with pytest.raises(ValidationError) as exc:
            ValidatorInput(**kwargs)
        assert "model_description" in str(exc.value)

    def test_missing_mathematical_definition_raises(self):
        kwargs = {k: v for k, v in VALID_INPUT_KWARGS.items() if k != "mathematical_definition"}
        with pytest.raises(ValidationError) as exc:
            ValidatorInput(**kwargs)
        assert "mathematical_definition" in str(exc.value)

    def test_storage_custom(self):
        inp = ValidatorInput(
            **VALID_INPUT_KWARGS,
            storage={"backend": "local", "local": {"workspace": "/reports", "run_name": "r1"}},
        )
        assert inp.storage.local.workspace == "/reports"


class TestValidatorOutput:

    def test_valid_passed(self):
        out = ValidatorOutput(
            passed=True,
            model_type="attn_unet",
            plugin_registered=True,
            tests_passed=True,
            description_valid=True,
            config_fields_valid=True,
            instantiation_passed=True,
            gradient_check_passed=True,
            llm_review_passed=True,
        )
        assert out.passed is True
        assert out.error_message is None
        assert out.test_output is None

    def test_valid_passed_with_test_output(self):
        out = ValidatorOutput(
            passed=True,
            model_type="attn_unet",
            plugin_registered=True,
            tests_passed=True,
            description_valid=True,
            config_fields_valid=True,
            instantiation_passed=True,
            gradient_check_passed=True,
            llm_review_passed=True,
            test_output="3 passed in 0.5s",
        )
        assert out.test_output == "3 passed in 0.5s"

    def test_valid_failed_plugin(self):
        out = ValidatorOutput(
            passed=False,
            model_type="attn_unet",
            plugin_registered=False,
            tests_passed=False,
            description_valid=True,
            config_fields_valid=True,
            instantiation_passed=False,
            gradient_check_passed=False,
            llm_review_passed=False,
            error_message="ImportError: cannot import PLUGIN_MODEL_CLASS",
        )
        assert out.passed is False
        assert "ImportError" in out.error_message

    def test_valid_failed_tests(self):
        out = ValidatorOutput(
            passed=False,
            model_type="attn_unet",
            plugin_registered=True,
            tests_passed=False,
            description_valid=True,
            config_fields_valid=True,
            instantiation_passed=True,
            gradient_check_passed=True,
            llm_review_passed=True,
            test_output="FAILED test_forward_shape - AssertionError",
            error_message="1 test failed",
        )
        assert out.tests_passed is False
        assert "FAILED" in out.test_output

    def test_valid_failed_config_fields(self):
        out = ValidatorOutput(
            passed=False,
            model_type="attn_unet",
            plugin_registered=True,
            tests_passed=True,
            description_valid=True,
            config_fields_valid=False,
            instantiation_passed=True,
            gradient_check_passed=True,
            llm_review_passed=True,
            error_message="config field 'kernel_sizes' is List[int], not scalar",
        )
        assert out.config_fields_valid is False

    def test_valid_failed_instantiation(self):
        out = ValidatorOutput(
            passed=False,
            model_type="attn_unet",
            plugin_registered=True,
            tests_passed=True,
            description_valid=True,
            config_fields_valid=True,
            instantiation_passed=False,
            gradient_check_passed=False,
            llm_review_passed=True,
            error_message="Model instantiation failed",
        )
        assert out.instantiation_passed is False
        assert out.gradient_check_passed is False

    def test_valid_failed_gradient(self):
        out = ValidatorOutput(
            passed=False,
            model_type="attn_unet",
            plugin_registered=True,
            tests_passed=True,
            description_valid=True,
            config_fields_valid=True,
            instantiation_passed=True,
            gradient_check_passed=False,
            llm_review_passed=True,
            error_message="Backward pass failed",
        )
        assert out.instantiation_passed is True
        assert out.gradient_check_passed is False

    def test_valid_failed_llm_review(self):
        out = ValidatorOutput(
            passed=False,
            model_type="attn_unet",
            plugin_registered=True,
            tests_passed=True,
            description_valid=True,
            config_fields_valid=True,
            instantiation_passed=True,
            gradient_check_passed=True,
            llm_review_passed=False,
            llm_review_spec_alignment=False,
            llm_review_trainability_concerns=["detached tensor in residual"],
            llm_review_implementation_issues=[],
            llm_review_notes="Implementation does not match spec.",
            error_message="LLM review did not pass",
        )
        assert out.llm_review_passed is False
        assert out.llm_review_spec_alignment is False
        assert len(out.llm_review_trainability_concerns) == 1

    def test_missing_model_type_raises(self):
        with pytest.raises(ValidationError) as exc:
            ValidatorOutput(
                passed=True,
                plugin_registered=True,
                tests_passed=True,
                description_valid=True,
                config_fields_valid=True,
                instantiation_passed=True,
                gradient_check_passed=True,
                llm_review_passed=True,
            )
        assert "model_type" in str(exc.value)

    def test_missing_tests_passed_raises(self):
        with pytest.raises(ValidationError) as exc:
            ValidatorOutput(
                passed=True,
                model_type="attn_unet",
                plugin_registered=True,
                description_valid=True,
                config_fields_valid=True,
                instantiation_passed=True,
                gradient_check_passed=True,
                llm_review_passed=True,
            )
        assert "tests_passed" in str(exc.value)

    def test_missing_instantiation_passed_raises(self):
        with pytest.raises(ValidationError) as exc:
            ValidatorOutput(
                passed=True,
                model_type="attn_unet",
                plugin_registered=True,
                tests_passed=True,
                description_valid=True,
                config_fields_valid=True,
                gradient_check_passed=True,
                llm_review_passed=True,
            )
        assert "instantiation_passed" in str(exc.value)

    def test_missing_gradient_check_passed_raises(self):
        with pytest.raises(ValidationError) as exc:
            ValidatorOutput(
                passed=True,
                model_type="attn_unet",
                plugin_registered=True,
                tests_passed=True,
                description_valid=True,
                config_fields_valid=True,
                instantiation_passed=True,
                llm_review_passed=True,
            )
        assert "gradient_check_passed" in str(exc.value)

    def test_missing_llm_review_passed_raises(self):
        with pytest.raises(ValidationError) as exc:
            ValidatorOutput(
                passed=True,
                model_type="attn_unet",
                plugin_registered=True,
                tests_passed=True,
                description_valid=True,
                config_fields_valid=True,
                instantiation_passed=True,
                gradient_check_passed=True,
            )
        assert "llm_review_passed" in str(exc.value)


class TestLLMCodeReview:

    def test_valid_passed(self):
        review = LLMCodeReview(
            spec_alignment=True,
            trainability_concerns=[],
            implementation_issues=[],
            passed=True,
            notes="Implementation looks correct.",
        )
        assert review.passed is True
        assert review.spec_alignment is True
        assert review.trainability_concerns == []

    def test_valid_failed(self):
        review = LLMCodeReview(
            spec_alignment=False,
            trainability_concerns=["detached tensor"],
            implementation_issues=["wrong shape"],
            passed=False,
            notes="Does not match spec.",
        )
        assert review.passed is False
        assert len(review.trainability_concerns) == 1
        assert len(review.implementation_issues) == 1
