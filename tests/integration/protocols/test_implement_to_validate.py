"""
Tier 2 integration test: ml_model_implementor -> ml_code_validator_agent.

Exercises the full edge:
  1. Run ml_model_implementor with a synthetic ImplementorInput (real LLM API)
  2. Apply protocol local_all_fields to produce ValidatorInput
  3. Run ml_code_validator_agent (LLM code review included)
  4. Validate ValidatorOutput: passed=True, all checks green

No GPU or real TIDMAD data required.

Requires:
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)

Run with:
  uv run pytest -m real_run tests/integration/protocols/test_implement_to_validate.py -v -s

DO NOT run in CI.
"""

import json
import os

import pytest
from dotenv import load_dotenv

from agent.schemas.implementor import ImplementorInput, ImplementorOutput
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import ValidatorOutput
from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_model_implementor import MLModelImplementor

load_dotenv()

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------


def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set — skipping real API test")


# ---------------------------------------------------------------------------
# Synthetic implementor input
# ---------------------------------------------------------------------------

SYNTHETIC_IMPLEMENTOR_INPUT = dict(
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


def _make_implementor_input(provider: str, tmp_path) -> ImplementorInput:
    return ImplementorInput(
        **SYNTHETIC_IMPLEMENTOR_INPUT,
        plugin_dir=str(tmp_path / "models"),
        test_dir=str(tmp_path / "tests"),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="impl_to_valid"),
        ),
    )


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def _assert_validator_output(out: ValidatorOutput, model_type: str, tmp_path):
    assert isinstance(out, ValidatorOutput)
    assert out.model_type == model_type

    assert out.plugin_registered is True, (
        f"Plugin failed to load. error_message: {out.error_message}"
    )
    assert out.description_valid is True, (
        f"description.md invalid. error_message: {out.error_message}"
    )
    assert out.config_fields_valid is True, (
        f"Config fields invalid. error_message: {out.error_message}"
    )
    assert out.tests_passed is True, f"Pytest tests failed.\n\ntest_output:\n{out.test_output}"
    assert out.instantiation_passed is True, (
        f"In-process instantiation failed. error_message: {out.error_message}"
    )
    assert out.gradient_check_passed is True, (
        f"Gradient check failed. error_message: {out.error_message}"
    )
    assert out.llm_review_passed is True, f"LLM review failed. notes: {out.llm_review_notes}"
    assert out.llm_review_spec_alignment is True, (
        f"LLM found spec misalignment. notes: {out.llm_review_notes}"
    )
    assert out.passed is True, f"Validation did not pass. error_message: {out.error_message}"
    assert out.error_message is None

    # Output record written
    assert (tmp_path / "validation_impl_to_valid.json").exists()
    data = json.loads((tmp_path / "validation_impl_to_valid.json").read_text())
    assert data["passed"] is True
    assert data["model_type"] == model_type


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImplementToValidateGemini:
    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_implement_to_validate_full_chain(self, tmp_path):
        """
        Full edge: implementor -> local_all_fields protocol -> validator.
        """
        provider = "gemini"
        model_id = "gemini-3.1-flash-lite-preview"
        storage = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="impl_to_valid"),
        )

        # Step 1: run implementor (real LLM)
        impl_input = _make_implementor_input(provider, tmp_path)
        impl_output = MLModelImplementor(provider=provider, model_id=model_id).run(impl_input)
        assert isinstance(impl_output, ImplementorOutput)
        assert impl_output.model_type == "gated_dilated_tcn"

        # Step 2: apply protocol
        val_input = local_all_fields(impl_output, storage)
        assert val_input.model_type == impl_output.model_type
        assert val_input.model_file_path == impl_output.model_file_path
        assert val_input.description_file_path == impl_output.description_file_path
        assert val_input.config_fields == impl_output.config_fields
        assert val_input.model_description == impl_output.model_description
        assert val_input.mathematical_definition == impl_output.mathematical_definition

        # Step 3: run validator (with LLM review)
        val_output = MLCodeValidatorAgent(
            provider="gemini", model_id="gemini-3.1-flash-lite-preview"
        ).run(val_input)

        # Step 4: validate
        _assert_validator_output(val_output, "gated_dilated_tcn", tmp_path)

        print(f"\n  model_type    : {val_output.model_type}")
        print(f"  passed        : {val_output.passed}")
        print(f"  config_fields : {val_input.config_fields}")
        print(f"  llm_review    : {val_output.llm_review_notes}")
        print(f"\n=== pytest output ===\n{val_output.test_output}")


class TestImplementToValidateOpenAI:
    def setup_method(self):
        _skip_if_no_key("openai")

    def test_implement_to_validate_full_chain(self, tmp_path):
        """
        Full edge via OpenAI: implementor -> local_all_fields protocol -> validator.
        """
        provider = "openai"
        model_id = "gpt-5-mini"
        storage = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="impl_to_valid"),
        )

        # Step 1: run implementor
        impl_input = _make_implementor_input(provider, tmp_path)
        impl_output = MLModelImplementor(provider=provider, model_id=model_id).run(impl_input)
        assert isinstance(impl_output, ImplementorOutput)

        # Step 2: apply protocol
        val_input = local_all_fields(impl_output, storage)

        # Step 3: run validator
        val_output = MLCodeValidatorAgent(provider="openai", model_id="gpt-5-mini").run(val_input)

        # Step 4: validate
        _assert_validator_output(val_output, impl_output.model_type, tmp_path)

        print(f"\n  model_type    : {val_output.model_type}")
        print(f"  passed        : {val_output.passed}")
        print(f"  llm_review    : {val_output.llm_review_notes}")
        print(f"\n=== pytest output ===\n{val_output.test_output}")
