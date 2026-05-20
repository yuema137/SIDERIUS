"""
Unit tests for agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py

Parametrized to collapse one-attribute-per-test pass-through noise into
a single multi-assertion baseline (matching the shape of the other
protocols tests in this folder).

Tests cover:
  local_full_spec
    - Returns a valid ImplementorInput with every ProposalOutput field
      threaded through (model_name, model_description,
      mathematical_definition, baseline_config) plus storage pass-through
    - plugin_dir and test_dir take their ImplementorInput schema defaults

  database_full_spec
    - Raises NotImplementedError
"""
import pytest

from agent.schemas.proposal import ProposalOutput
from agent.schemas.implementor import ImplementorInput
from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import (
    local_full_spec,
    database_full_spec,
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
def proposal_output():
    return ProposalOutput(
        model_name="gated_dilated_tcn",
        model_description="A gated dilated TCN for signal denoising.",
        mathematical_definition="y = tanh(W_f * x) * sigmoid(W_g * x) with dilated convolutions.",
        motivation="Addresses the bottleneck of spatial compression in PUNet.",
        expert_advice=ExpertAdvice(
            focus_areas=["depth before width"],
            constraints=["VRAM < 10 GB"],
            known_failures=["depth > 12 causes OOM"],
            suggested_directions=["start with depth=6, lr=1e-4"],
            rationale="Conservative baseline to avoid OOM.",
        ),
        baseline_config={
            "model_config": {"channels": 64, "depth": 6, "kernel_size": 3},
            "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 1, "device": "cuda"},
            "loss_config":  {"loss_type": "focal", "gamma": 2.0},
        },
    )


# ---------------------------------------------------------------------------
# local_full_spec
# ---------------------------------------------------------------------------

class TestLocalFullSpec:

    def test_baseline_pass_through_and_default_dirs(self, proposal_output, storage):
        """Single multi-assertion baseline: every ProposalOutput field must
        thread through to the matching ImplementorInput field, storage
        round-trips intact, and the plugin_dir / test_dir fall back to
        their ImplementorInput schema defaults. Replaces eight flat
        single-assertion tests (returns_implementor_input,
        model_name_passed_through, model_description_passed_through,
        mathematical_definition_passed_through,
        baseline_config_passed_through, storage_passed_through,
        plugin_dir_is_default, test_dir_is_default)."""
        result = local_full_spec(proposal_output, storage)

        assert isinstance(result, ImplementorInput)

        # Every ProposalOutput field threads through unchanged.
        assert result.model_name == "gated_dilated_tcn"
        assert result.model_description == proposal_output.model_description
        assert result.mathematical_definition == proposal_output.mathematical_definition
        assert result.baseline_config == proposal_output.baseline_config

        # Storage round-trips intact.
        assert result.storage.backend == "local"
        assert result.storage.local.workspace == "/tmp/proto_test"
        assert result.storage.local.run_name == "r1"

        # plugin_dir / test_dir fall back to ImplementorInput schema defaults.
        assert result.plugin_dir == "agent_generated/models"
        assert result.test_dir == "agent_generated/tests"


# ---------------------------------------------------------------------------
# database_full_spec
# ---------------------------------------------------------------------------

class TestDatabaseFullSpec:

    def test_raises_not_implemented(self, proposal_output, storage):
        with pytest.raises(NotImplementedError):
            database_full_spec(proposal_output, storage)
