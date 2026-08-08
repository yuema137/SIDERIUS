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

from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.implementor import ImplementorInput
from agent.schemas.proposal import CustomLossSpec, ProposalOutput
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import (
    database_full_spec,
    local_full_spec,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig

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
def valid_expert_advice():
    return ExpertAdvice(
        focus_areas=["depth before width"],
        constraints=["VRAM < 10 GB"],
        known_failures=["depth > 12 causes OOM"],
        suggested_directions=["start with depth=6, lr=1e-4"],
        rationale="Conservative baseline to avoid OOM.",
    )


@pytest.fixture
def proposal_output(valid_expert_advice):
    return ProposalOutput(
        model_name="gated_dilated_tcn",
        model_description="A gated dilated TCN for signal denoising.",
        mathematical_definition="y = tanh(W_f * x) * sigmoid(W_g * x) with dilated convolutions.",
        motivation="Addresses the bottleneck of spatial compression in PUNet.",
        expert_advice=valid_expert_advice,
        baseline_config={
            "model_config": {"channels": 64, "depth": 6, "kernel_size": 3},
            "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 1, "device": "cuda"},
            "loss_config": {"loss_type": "focal", "gamma": 2.0},
        },
    )


# ---------------------------------------------------------------------------
# local_full_spec
# ---------------------------------------------------------------------------


class TestLocalFullSpec:
    def test_baseline_pass_through_and_default_dirs(self, proposal_output, storage):
        """Single multi-assertion baseline: every ProposalOutput field must
        thread through to the matching ImplementorInput field, storage
        round-trips intact, and the plugin_dir / test_dir / loss_dir fall
        back to their ImplementorInput schema defaults. Replaces eight flat
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

        # plugin_dir / test_dir / loss_dir fall back to ImplementorInput schema defaults.
        assert result.plugin_dir == "agent_generated/models"
        assert result.test_dir == "agent_generated/tests"
        assert result.loss_dir == "agent_generated/losses"

    def test_custom_loss_spec_none_forwards_as_none(self, proposal_output, storage):
        """The fixture proposal_output has no custom_loss_spec (defaults to
        None). The protocol must forward None unchanged — this is the
        built-in-loss path."""
        result = local_full_spec(proposal_output, storage)
        assert result.custom_loss_spec is None

    def test_custom_loss_spec_forwards_end_to_end(self, valid_expert_advice, storage):
        """When the proposer emits a CustomLossSpec, the protocol must
        forward it intact to ImplementorInput so the implementor at L4 can
        consume it. The baseline_config must also declare loss_type='custom'
        and the matching loss_name — enforced by the proposal-side
        consistency validator."""
        spec = CustomLossSpec(
            loss_name="snr_weighted_mse",
            description="SNR-weighted MSE for noisy waveform regression.",
            mathematical_definition="L = mean(snr_i * (y - y_hat)^2)",
        )
        proposal = ProposalOutput(
            model_name="m",
            model_description="x",
            mathematical_definition="x",
            motivation="x",
            expert_advice=valid_expert_advice,
            baseline_config={
                "model_config": {},
                "train_config": {},
                "loss_config": {
                    "loss_type": "custom",
                    "loss_name": "snr_weighted_mse",
                },
            },
            custom_loss_spec=spec,
        )
        result = local_full_spec(proposal, storage)
        assert result.custom_loss_spec is not None
        assert result.custom_loss_spec.loss_name == "snr_weighted_mse"
        assert result.custom_loss_spec.description == spec.description
        assert result.custom_loss_spec.mathematical_definition == spec.mathematical_definition


# ---------------------------------------------------------------------------
# database_full_spec
# ---------------------------------------------------------------------------


class TestDatabaseFullSpec:
    def test_raises_not_implemented(self, proposal_output, storage):
        with pytest.raises(NotImplementedError):
            database_full_spec(proposal_output, storage)


# ---------------------------------------------------------------------------
# Output contract transport (V21 PR A3)
# ---------------------------------------------------------------------------
#
# MUTATION TARGET: delete `output_type=output.output_type` from
# `local_full_spec` and `test_declared_output_type_survives_the_hop[regressor]`
# fails. Without that assertion a proposal declaring `regressor` would silently
# yield a classifier plugin — the "produced but not delivered" class that
# repeatedly bit V20. The schema default makes this hop SILENTLY lossy if
# untested, which is exactly why it is tested here rather than inferred.


class TestOutputContractTransport:
    @pytest.mark.parametrize("declared", ["classifier", "regressor"])
    def test_declared_output_type_survives_the_hop(self, valid_expert_advice, storage, declared):
        proposal = ProposalOutput(
            model_name="contract_probe",
            output_type=declared,
            model_description="Probe model for output-contract transport.",
            mathematical_definition="Identity-ish stack; contract under test.",
            motivation="Verify the declared contract reaches the implementor.",
            expert_advice=valid_expert_advice,
            baseline_config={
                "model_config": {"channels": 8},
                "train_config": {"lr": 1e-4, "epochs": 1, "batch_size": 1},
                "loss_config": {"loss_type": "focal"},
            },
        )
        impl_input = local_full_spec(proposal, storage)
        assert impl_input.output_type == declared

    def test_output_type_is_not_inferred_from_loss(self, valid_expert_advice, storage):
        """A regression loss must NOT silently imply a regression contract.

        Inference would re-couple the two design dimensions PR A separates.
        The pair is checked by the shared compatibility rule instead, so an
        inconsistent proposal must travel unchanged and be refused there —
        not be quietly "fixed" in transit.
        """
        proposal = ProposalOutput(
            model_name="mismatch_probe",
            output_type="classifier",
            model_description="Declares classifier but names a regression loss.",
            mathematical_definition="Contract/loss mismatch under test.",
            motivation="Transport must not rewrite the declaration.",
            expert_advice=valid_expert_advice,
            baseline_config={
                "model_config": {"channels": 8},
                "train_config": {"lr": 1e-4, "epochs": 1, "batch_size": 1},
                "loss_config": {"loss_type": "smooth_l1"},
            },
        )
        impl_input = local_full_spec(proposal, storage)
        assert impl_input.output_type == "classifier"
