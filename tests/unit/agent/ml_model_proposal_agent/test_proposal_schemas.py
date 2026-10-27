"""
Tests for agent/schemas/proposal.py
"""

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExpertAdvice, GateExhaustionInfo
from agent.schemas.proposal import CustomLossSpec, ProposalInput, ProposalOutput
from agent.schemas.proposer_evidence import build_proposer_evidence


class TestProposalInputRecentGateExhaustions:
    """Phase N (§14.N.1) — ProposalInput.recent_gate_exhaustions field.

    Replaces the K.7.2 singular ``prior_iteration_gate_exhaustion`` field
    with a bounded list (oldest-first). Populated by the interp→propose
    protocol from the workflow's bounded FIFO of recent tuner outputs;
    consumed by the proposer prompt as the [RECENT GATE EXHAUSTIONS]
    block.

    See docs/resource_estimator_implement.md §14.N + §10.13.
    """

    @pytest.fixture
    def gate_exhaustion(self):
        return GateExhaustionInfo(
            total_attempts=9,
            vram_gated_attempts=9,
            time_gated_attempts=0,
            other_failure_attempts=0,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
            baseline_vram_estimate_gb=6.4,
            baseline_vram_factor=1.6,
            baseline_time_estimate_minutes=8.0,
            baseline_time_factor=0.4,
            worst_vram_factor=2.0,
            worst_time_factor=0.6,
            summary_message=(
                "All 9 attempts were rejected by the pre-flight VRAM gate. "
                "The baseline already estimated 6.4 GB vs the 4.0 GB trial "
                "budget (factor 1.6×); the tuner's mutations went up to "
                "8.1 GB (factor 2.0×)."
            ),
        )

    def test_rejects_over_ten_entries(self, gate_exhaustion):
        """Schema safety rail: the workflow enforces maxlen=3 via a deque,
        but the schema itself caps the list at 10 entries to guard against
        an unbounded caller. See §14.N.1."""
        with pytest.raises(ValidationError) as exc:
            ProposalInput(
                interpretation_evidence=build_proposer_evidence({}),
                recent_gate_exhaustions=[gate_exhaustion] * 11,
            )
        assert "maximum allowed is 10" in str(exc.value)


# ==========================================
# L3 — CustomLossSpec + ProposalOutput.custom_loss_spec consistency
# ==========================================
#
# Verifies the schema-only loss-spec channel added by L3. See
# ``docs/design/enable_loss_inventory.md`` § Commit L3.


class TestProposalOutputCustomLossSpec:
    """End-to-end consistency between ProposalOutput.custom_loss_spec and
    ``baseline_config['loss_config']``."""

    @pytest.fixture
    def valid_expert_advice(self):
        return ExpertAdvice(
            focus_areas=["x"],
            constraints=["x"],
            known_failures=["x"],
            suggested_directions=["x"],
            rationale="x",
        )

    @pytest.fixture
    def custom_spec(self):
        return CustomLossSpec(
            loss_name="snr_weighted_mse",
            description="SNR-weighted MSE for noisy waveform regression.",
            mathematical_definition="L = mean(snr_i * (y - y_hat)^2)",
        )

    def test_none_is_back_compat(self, valid_expert_advice):
        """custom_loss_spec defaults to None — every pre-L3 ProposalOutput
        round-trip remains valid without modification."""
        out = ProposalOutput(
            model_name="m",
            model_description="x",
            mathematical_definition="x",
            motivation="x",
            expert_advice=valid_expert_advice,
            baseline_config={
                "model_config": {},
                "train_config": {},
                "loss_config": {"loss_type": "focal", "gamma": 2.0},
            },
        )
        assert out.custom_loss_spec is None

    def test_valid_custom_round_trip(self, valid_expert_advice, custom_spec):
        out = ProposalOutput(
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
            custom_loss_spec=custom_spec,
        )
        assert out.custom_loss_spec is not None
        assert out.custom_loss_spec.loss_name == "snr_weighted_mse"

    def test_spec_set_but_loss_type_not_custom_raises(self, valid_expert_advice, custom_spec):
        with pytest.raises(ValidationError, match="must be 'custom'"):
            ProposalOutput(
                model_name="m",
                model_description="x",
                mathematical_definition="x",
                motivation="x",
                expert_advice=valid_expert_advice,
                baseline_config={
                    "loss_config": {
                        "loss_type": "focal",
                        "loss_name": "snr_weighted_mse",
                    },
                },
                custom_loss_spec=custom_spec,
            )

    def test_spec_set_but_loss_name_mismatch_raises(self, valid_expert_advice, custom_spec):
        with pytest.raises(ValidationError, match="does not match"):
            ProposalOutput(
                model_name="m",
                model_description="x",
                mathematical_definition="x",
                motivation="x",
                expert_advice=valid_expert_advice,
                baseline_config={
                    "loss_config": {
                        "loss_type": "custom",
                        "loss_name": "different_loss",
                    },
                },
                custom_loss_spec=custom_spec,
            )

    def test_spec_set_but_no_loss_config_raises(self, valid_expert_advice, custom_spec):
        with pytest.raises(ValidationError, match="missing"):
            ProposalOutput(
                model_name="m",
                model_description="x",
                mathematical_definition="x",
                motivation="x",
                expert_advice=valid_expert_advice,
                baseline_config={"model_config": {}, "train_config": {}},
                custom_loss_spec=custom_spec,
            )

    def test_spec_none_with_custom_loss_type_does_not_raise(self, valid_expert_advice):
        """Asymmetry: the validator only fires when custom_loss_spec is set.
        A ProposalOutput with loss_type='custom' but no custom_loss_spec is
        accepted at the schema layer — this is the 'reuse an existing
        registered loss' path (no new generation needed). The implementor
        node at L4 will look up the registered plugin by loss_name and skip
        the LLM call. The schema is intentionally permissive here so the
        reuse path is open."""
        out = ProposalOutput(
            model_name="m",
            model_description="x",
            mathematical_definition="x",
            motivation="x",
            expert_advice=valid_expert_advice,
            baseline_config={
                "loss_config": {
                    "loss_type": "custom",
                    "loss_name": "previously_registered_loss",
                },
            },
        )
        assert out.custom_loss_spec is None
