"""
Unit tests for agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py

Tests cover:
  local_all_fields
    - Returns a valid ValidatorInput
    - model_type passed through
    - model_file_path passed through
    - test_file_path passed through
    - description_file_path passed through
    - config_fields passed through
    - model_description passed through
    - mathematical_definition passed through
    - storage passed through
    - default llm_provider is gemini
    - custom llm_provider is passed through
    - custom llm_model_id is passed through

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

    def test_returns_validator_input(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert isinstance(result, ValidatorInput)

    def test_model_type_passed_through(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert result.model_type == "gated_tcn"

    def test_model_file_path_passed_through(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert result.model_file_path == implementor_output.model_file_path

    def test_test_file_path_passed_through(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert result.test_file_path == implementor_output.test_file_path

    def test_description_file_path_passed_through(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert result.description_file_path == implementor_output.description_file_path

    def test_config_fields_passed_through(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert result.config_fields == {"depth": 6, "channels": 64, "use_bias": True}

    def test_model_description_passed_through(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert result.model_description == implementor_output.model_description

    def test_mathematical_definition_passed_through(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert result.mathematical_definition == implementor_output.mathematical_definition

    def test_storage_passed_through(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert result.storage.backend == "local"
        assert result.storage.local.workspace == "/tmp/proto_test"
        assert result.storage.local.run_name == "r1"

    def test_default_llm_provider(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage)
        assert result.llm_provider == "gemini"

    def test_custom_llm_provider(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage, llm_provider="openai")
        assert result.llm_provider == "openai"

    def test_custom_llm_model_id(self, implementor_output, storage):
        result = local_all_fields(implementor_output, storage, llm_model_id="gpt-4o")
        assert result.llm_model_id == "gpt-4o"


# ---------------------------------------------------------------------------
# database_all_fields
# ---------------------------------------------------------------------------

class TestDatabaseAllFields:

    def test_raises_not_implemented(self, implementor_output, storage):
        with pytest.raises(NotImplementedError):
            database_all_fields(implementor_output, storage)
