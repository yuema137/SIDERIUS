"""
Unit tests for agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py

Parametrized to collapse one-attribute-per-test pass-through noise into
multi-assertion baselines (matching the shape of the other protocols
tests in this folder).

Tests cover:
  local_all_fields
    - Returns a valid ValidatorInput with every ImplementorOutput field
      threaded through (model_type, model_file_path, test_file_path,
      description_file_path, config_fields, model_description,
      mathematical_definition) plus storage pass-through
    - llm_provider defaults to "gemini" and is overridable via kwarg
    - llm_model_id is overridable via kwarg

  database_all_fields
    - Raises NotImplementedError
"""
import pytest

from agent.schemas.implementor import ImplementorOutput
from agent.schemas.validator import ValidatorInput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import (
    local_all_fields,
    database_all_fields,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage():
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="/tmp/proto_test", run_name="r1"),
    )


@pytest.fixture
def implementor_output():
    return ImplementorOutput(
        model_type="gated_tcn",
        model_file_path="/abs/agent_generated/models/gated_tcn.py",
        test_file_path="/abs/agent_generated/tests/test_gated_tcn.py",
        description_file_path="/abs/agent_generated/models/gated_tcn/description.md",
        config_fields={"depth": 6, "channels": 64, "use_bias": True},
        model_description="A gated dilated TCN for signal denoising.",
        mathematical_definition="output_l = x_l + tanh(Wf*x_l) * sigmoid(Wg*x_l)",
    )


# ---------------------------------------------------------------------------
# local_all_fields
# ---------------------------------------------------------------------------

class TestLocalAllFields:

    def test_baseline_all_fields_pass_through(self, implementor_output, storage):
        """Single multi-assertion baseline: every ImplementorOutput field
        must thread through to the matching ValidatorInput field, plus
        storage round-trips intact. Replaces nine flat single-assertion
        tests (returns_validator_input, model_type_passed_through,
        model_file_path_passed_through, test_file_path_passed_through,
        description_file_path_passed_through, config_fields_passed_through,
        model_description_passed_through, mathematical_definition_passed_through,
        storage_passed_through)."""
        result = local_all_fields(implementor_output, storage)

        assert isinstance(result, ValidatorInput)

        # Every ImplementorOutput field threads through unchanged.
        assert result.model_type == "gated_tcn"
        assert result.model_file_path == implementor_output.model_file_path
        assert result.test_file_path == implementor_output.test_file_path
        assert result.description_file_path == implementor_output.description_file_path
        assert result.config_fields == {"depth": 6, "channels": 64, "use_bias": True}
        assert result.model_description == implementor_output.model_description
        assert result.mathematical_definition == implementor_output.mathematical_definition

        # Storage round-trips intact.
        assert result.storage.backend == "local"
        assert result.storage.local.workspace == "/tmp/proto_test"
        assert result.storage.local.run_name == "r1"

    @pytest.mark.parametrize(
        "kwargs, expected_attr, expected_value",
        [
            pytest.param({}, "llm_provider", "gemini",
                         id="default_llm_provider_is_gemini"),
            pytest.param({"llm_provider": "openai"}, "llm_provider", "openai",
                         id="custom_llm_provider"),
            pytest.param({"llm_model_id": "gpt-4o"}, "llm_model_id", "gpt-4o",
                         id="custom_llm_model_id"),
        ],
    )
    def test_llm_kwargs_default_or_override(
        self, implementor_output, storage, kwargs, expected_attr, expected_value,
    ):
        """LLM-knob contract: ``llm_provider`` falls back to "gemini" when
        the caller omits it, and both ``llm_provider`` / ``llm_model_id``
        are overridable via kwargs. One parametrized family with explicit
        case IDs replaces three flat tests."""
        result = local_all_fields(implementor_output, storage, **kwargs)
        assert getattr(result, expected_attr) == expected_value


# ---------------------------------------------------------------------------
# database_all_fields
# ---------------------------------------------------------------------------

class TestDatabaseAllFields:

    def test_raises_not_implemented(self, implementor_output, storage):
        with pytest.raises(NotImplementedError):
            database_all_fields(implementor_output, storage)
