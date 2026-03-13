"""
Unit tests for agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py

Tests cover:
  local_validated_model
    - Returns a valid HyperparamTuningInput
    - model_type passed through from ValidatorOutput
    - storage passed through
    - max_rounds uses caller-supplied value
    - file_index uses caller-supplied value
    - llm_provider uses caller-supplied value
    - llm_model_id uses caller-supplied value
    - expert_advice is empty string (no prior guidance)
    - seed_records is empty list (no prior experiments)
    - Defaults: max_rounds=50, file_index=6, llm_provider="gemini"

  database_validated_model
    - Raises NotImplementedError
"""
import pytest

from agent.schemas.validator import ValidatorOutput
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
    local_validated_model,
    database_validated_model,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage():
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="/tmp/tune_test", run_name="r2"),
    )


@pytest.fixture
def validator_output():
    return ValidatorOutput(
        passed=True,
        model_type="gated_tcn",
        plugin_registered=True,
        tests_passed=True,
        description_valid=True,
        config_fields_valid=True,
        instantiation_passed=True,
        gradient_check_passed=True,
        llm_review_passed=True,
    )


# ---------------------------------------------------------------------------
# local_validated_model
# ---------------------------------------------------------------------------

class TestLocalValidatedModel:

    def test_returns_hyperparam_tuning_input(self, validator_output, storage):
        result = local_validated_model(validator_output, storage)
        assert isinstance(result, HyperparamTuningInput)

    def test_model_type_passed_through(self, validator_output, storage):
        result = local_validated_model(validator_output, storage)
        assert result.model_type == "gated_tcn"

    def test_storage_passed_through(self, validator_output, storage):
        result = local_validated_model(validator_output, storage)
        assert result.storage.local.workspace == "/tmp/tune_test"
        assert result.storage.local.run_name == "r2"

    def test_default_max_rounds(self, validator_output, storage):
        result = local_validated_model(validator_output, storage)
        assert result.max_rounds == 50

    def test_custom_max_rounds(self, validator_output, storage):
        result = local_validated_model(validator_output, storage, max_rounds=10)
        assert result.max_rounds == 10

    def test_default_file_index(self, validator_output, storage):
        result = local_validated_model(validator_output, storage)
        assert result.file_index == 6

    def test_custom_file_index(self, validator_output, storage):
        result = local_validated_model(validator_output, storage, file_index=3)
        assert result.file_index == 3

    def test_default_llm_provider(self, validator_output, storage):
        result = local_validated_model(validator_output, storage)
        assert result.llm_provider == "gemini"

    def test_custom_llm_provider(self, validator_output, storage):
        result = local_validated_model(validator_output, storage, llm_provider="openai")
        assert result.llm_provider == "openai"

    def test_custom_llm_model_id(self, validator_output, storage):
        result = local_validated_model(
            validator_output, storage, llm_model_id="gpt-4o"
        )
        assert result.llm_model_id == "gpt-4o"

    def test_expert_advice_is_empty_string(self, validator_output, storage):
        result = local_validated_model(validator_output, storage)
        assert result.expert_advice == ""

    def test_seed_records_is_empty_list(self, validator_output, storage):
        result = local_validated_model(validator_output, storage)
        assert result.seed_records == []


# ---------------------------------------------------------------------------
# database_validated_model
# ---------------------------------------------------------------------------

class TestDatabaseValidatedModel:

    def test_raises_not_implemented(self, validator_output, storage):
        with pytest.raises(NotImplementedError):
            database_validated_model(validator_output, storage)
