"""
Tests for agent/schemas/proposal.py
"""
import pytest
from pydantic import ValidationError

from agent.schemas.proposal import ProposalInput, ProposalOutput
from agent.schemas.hyperparam_tuning import ExpertAdvice, GateExhaustionInfo


class TestProposalInput:

    def test_valid_minimal(self):
        inp = ProposalInput(interpretation={"take_home_message": "need new arch"})
        assert inp.existing_model_types == []
        assert inp.constraints == []
        assert inp.storage.backend == "local"

    def test_valid_with_all_fields(self):
        inp = ProposalInput(
            interpretation={"take_home_message": "need new arch"},
            existing_model_types=["punet", "fcnet"],
            constraints=["VRAM < 10 GB"],
        )
        assert "punet" in inp.existing_model_types
        assert "VRAM < 10 GB" in inp.constraints

    def test_missing_interpretation_raises(self):
        with pytest.raises(ValidationError) as exc:
            ProposalInput()
        assert "interpretation" in str(exc.value)

    def test_storage_custom(self):
        inp = ProposalInput(
            interpretation={},
            storage={"backend": "local", "local": {"workspace": "/runs", "run_name": "r1"}},
        )
        assert inp.storage.local.run_name == "r1"

    def test_human_advice_defaults_to_none(self):
        inp = ProposalInput(interpretation={})
        assert inp.human_advice is None

    def test_human_advice_accepts_plain_string(self):
        inp = ProposalInput(
            interpretation={},
            human_advice="Focus on reducing parameter count.",
        )
        assert inp.human_advice == "Focus on reducing parameter count."

    def test_human_advice_accepts_structured_expert_advice(self):
        adv = ExpertAdvice(
            focus_areas=["depth over width"],
            constraints=["VRAM < 8 GB"],
            known_failures=["large kernel_size"],
            suggested_directions=["try dilation_base=3"],
            rationale="prior runs show width saturation",
        )
        inp = ProposalInput(interpretation={}, human_advice=adv)
        assert isinstance(inp.human_advice, ExpertAdvice)
        assert inp.human_advice.rationale == "prior runs show width saturation"

    def test_human_advice_accepts_expert_advice_as_dict(self):
        adv_dict = {
            "focus_areas": ["depth over width"],
            "constraints": [],
            "known_failures": [],
            "suggested_directions": [],
            "rationale": "test",
        }
        inp = ProposalInput(interpretation={}, human_advice=adv_dict)
        assert isinstance(inp.human_advice, ExpertAdvice)


class TestProposalInputGateExhaustion:
    """K.7.2 — ProposalInput.prior_iteration_gate_exhaustion field.

    See docs/resource_estimator_implement.md §10.13.2. The field is
    populated by the interp→propose protocol when the previous
    iteration's tuner exited under gate exhaustion; the proposer
    prompt then renders a [PRIOR ITERATION GATE EXHAUSTION] block
    (K.7.6).
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

    def test_default_none_when_omitted(self):
        inp = ProposalInput(interpretation={})
        assert inp.prior_iteration_gate_exhaustion is None

    def test_accepts_populated_info_object(self, gate_exhaustion):
        inp = ProposalInput(
            interpretation={},
            prior_iteration_gate_exhaustion=gate_exhaustion,
        )
        assert isinstance(inp.prior_iteration_gate_exhaustion, GateExhaustionInfo)
        assert inp.prior_iteration_gate_exhaustion.total_attempts == 9
        assert inp.prior_iteration_gate_exhaustion.active_mode == "trial"
        assert inp.prior_iteration_gate_exhaustion.worst_vram_factor == 2.0

    def test_accepts_populated_info_as_dict(self, gate_exhaustion):
        """Pydantic should coerce a dict into GateExhaustionInfo, mirroring
        the existing dict-coercion pattern for ExpertAdvice."""
        inp = ProposalInput(
            interpretation={},
            prior_iteration_gate_exhaustion=gate_exhaustion.model_dump(),
        )
        assert isinstance(inp.prior_iteration_gate_exhaustion, GateExhaustionInfo)
        assert inp.prior_iteration_gate_exhaustion.summary_message.startswith(
            "All 9 attempts"
        )

    def test_round_trip_preserves_gate_exhaustion(self, gate_exhaustion):
        """JSON round-trip must preserve the field — the protocol layer
        serialises ProposalInput across the workflow boundary."""
        inp = ProposalInput(
            interpretation={},
            prior_iteration_gate_exhaustion=gate_exhaustion,
        )
        round_tripped = ProposalInput.model_validate_json(inp.model_dump_json())
        assert round_tripped.prior_iteration_gate_exhaustion is not None
        assert (
            round_tripped.prior_iteration_gate_exhaustion.model_dump()
            == gate_exhaustion.model_dump()
        )

    def test_invalid_active_mode_in_dict_raises(self):
        """Passing a malformed dict should fail validation, not silently
        coerce — guards against the protocol layer dropping garbage in."""
        bad_dict = {
            "total_attempts": 1,
            "vram_gated_attempts": 1,
            "time_gated_attempts": 0,
            "other_failure_attempts": 0,
            "active_mode": "smoke",
            "summary_message": "x",
        }
        with pytest.raises(ValidationError):
            ProposalInput(
                interpretation={},
                prior_iteration_gate_exhaustion=bad_dict,
            )


class TestProposalOutput:

    @pytest.fixture
    def valid_expert_advice(self):
        return ExpertAdvice(
            focus_areas=["start with depth=2"],
            constraints=["VRAM < 8 GB"],
            known_failures=["large batch_size"],
            suggested_directions=["try focal gamma=2"],
            rationale="architecture plateau detected",
        )

    def test_valid(self, valid_expert_advice):
        out = ProposalOutput(
            model_name="attn_unet",
            model_description="Attention-based U-Net variant.",
            mathematical_definition="Encoder: 3 down blocks. Attention gate at bottleneck.",
            motivation="Addresses the plateau by adding attention.",
            expert_advice=valid_expert_advice,
            baseline_config={
                "model_config": {"depth": 2},
                "train_config": {"lr": 1e-4, "epochs": 10},
                "loss_config": {"loss_type": "focal"},
            },
        )
        assert out.model_name == "attn_unet"
        assert isinstance(out.expert_advice, ExpertAdvice)

    def test_expert_advice_as_dict(self, valid_expert_advice):
        out = ProposalOutput(
            model_name="attn_unet",
            model_description="x",
            mathematical_definition="x",
            motivation="x",
            expert_advice=valid_expert_advice.model_dump(),
            baseline_config={},
        )
        assert isinstance(out.expert_advice, ExpertAdvice)

    def test_missing_model_name_raises(self, valid_expert_advice):
        with pytest.raises(ValidationError) as exc:
            ProposalOutput(
                model_description="x",
                mathematical_definition="x",
                motivation="x",
                expert_advice=valid_expert_advice,
                baseline_config={},
            )
        assert "model_name" in str(exc.value)

    def test_missing_mathematical_definition_raises(self, valid_expert_advice):
        with pytest.raises(ValidationError) as exc:
            ProposalOutput(
                model_name="attn_unet",
                model_description="x",
                motivation="x",
                expert_advice=valid_expert_advice,
                baseline_config={},
            )
        assert "mathematical_definition" in str(exc.value)
