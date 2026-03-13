"""
Unit tests for agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py

Tests cover:
  local_full_context
    - Returns a valid ProposalInput
    - interpretation is a fully serialised InterpretationOutput dict
    - existing_model_types matches output.model_types
    - all InterpretationOutput fields are present in the interpretation dict
    - storage is passed through correctly
    - works with multiple model types

  database_full_context
    - Raises NotImplementedError (placeholder, not yet implemented)
"""
import pytest

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
    local_full_context,
    database_full_context,
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


def make_interpretation_output(model_types):
    descriptions = {mt: f"{mt} description text" for mt in model_types}
    per_best  = {mt: 1.5 for mt in model_types}
    per_worst = {mt: 0.8 for mt in model_types}
    return InterpretationOutput(
        model_types=model_types,
        model_descriptions=descriptions,
        total_experiments=10,
        per_model_best=per_best,
        per_model_worst=per_worst,
        best_denoising_score=1.5,
        worst_denoising_score=0.8,
        best_config={"model_config": {"depth": 3}},
        key_findings=["focal loss outperforms ce"],
        bottlenecks=["architecture capacity ceiling"],
        take_home_message="A new architecture is needed to break the plateau.",
    )


# ---------------------------------------------------------------------------
# local_full_context
# ---------------------------------------------------------------------------

class TestLocalFullContext:

    def test_returns_proposal_input(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert isinstance(result, ProposalInput)

    def test_existing_model_types_from_output(self, storage):
        output = make_interpretation_output(["punet", "fcnet"])
        result = local_full_context(output, storage)
        assert set(result.existing_model_types) == {"punet", "fcnet"}

    def test_interpretation_is_dict(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert isinstance(result.interpretation, dict)

    def test_interpretation_contains_model_types(self, storage):
        output = make_interpretation_output(["punet", "fcnet"])
        result = local_full_context(output, storage)
        assert result.interpretation["model_types"] == ["punet", "fcnet"]

    def test_interpretation_contains_take_home_message(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.interpretation["take_home_message"] == (
            "A new architecture is needed to break the plateau."
        )

    def test_interpretation_contains_model_descriptions(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert "model_descriptions" in result.interpretation
        assert "punet" in result.interpretation["model_descriptions"]

    def test_interpretation_contains_scores(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.interpretation["best_denoising_score"] == 1.5
        assert result.interpretation["worst_denoising_score"] == 0.8

    def test_interpretation_contains_findings_and_bottlenecks(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.interpretation["key_findings"] == ["focal loss outperforms ce"]
        assert result.interpretation["bottlenecks"] == ["architecture capacity ceiling"]

    def test_storage_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.storage.backend == "local"
        assert result.storage.local.workspace == "/tmp/proto_test"
        assert result.storage.local.run_name == "r1"

    def test_multiple_model_types(self, storage):
        output = make_interpretation_output(["punet", "fcnet", "wavenet"])
        result = local_full_context(output, storage)
        assert len(result.existing_model_types) == 3
        assert set(result.existing_model_types) == {"punet", "fcnet", "wavenet"}


# ---------------------------------------------------------------------------
# database_full_context
# ---------------------------------------------------------------------------

class TestDatabaseFullContext:

    def test_raises_not_implemented(self, storage):
        output = make_interpretation_output(["punet"])
        with pytest.raises(NotImplementedError):
            database_full_context(output, storage)
