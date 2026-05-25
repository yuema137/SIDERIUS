"""
Tests for agent/schemas/proposal.py
"""

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExpertAdvice, GateExhaustionInfo
from agent.schemas.proposal import ProposalInput, ProposalOutput


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

    def _second_gate_exhaustion(self):
        return GateExhaustionInfo(
            total_attempts=3,
            vram_gated_attempts=0,
            time_gated_attempts=3,
            other_failure_attempts=0,
            active_mode="trial",
            vram_budget_gb=8.0,
            time_budget_minutes=20.0,
            baseline_vram_estimate_gb=1.2,
            baseline_vram_factor=0.15,
            baseline_time_estimate_minutes=45.0,
            baseline_time_factor=2.25,
            worst_vram_factor=0.2,
            worst_time_factor=3.1,
            summary_message="All 3 attempts exceeded the 20 min time budget.",
        )

    def test_default_empty_when_omitted(self):
        inp = ProposalInput(interpretation={})
        assert inp.recent_gate_exhaustions == []

    def test_accepts_single_entry_list(self, gate_exhaustion):
        inp = ProposalInput(
            interpretation={},
            recent_gate_exhaustions=[gate_exhaustion],
        )
        assert len(inp.recent_gate_exhaustions) == 1
        assert isinstance(inp.recent_gate_exhaustions[0], GateExhaustionInfo)
        assert inp.recent_gate_exhaustions[0].total_attempts == 9

    def test_accepts_multi_entry_list_preserves_order(self, gate_exhaustion):
        older = gate_exhaustion
        newer = self._second_gate_exhaustion()
        inp = ProposalInput(
            interpretation={},
            recent_gate_exhaustions=[older, newer],
        )
        assert len(inp.recent_gate_exhaustions) == 2
        # Oldest-first order preserved — the protocol layer depends on this.
        assert inp.recent_gate_exhaustions[0].vram_gated_attempts == 9
        assert inp.recent_gate_exhaustions[1].time_gated_attempts == 3

    def test_accepts_list_of_dicts_coerced_to_info(self, gate_exhaustion):
        """Pydantic should coerce a list of dicts into GateExhaustionInfo
        objects — mirrors the protocol's output which serialises each entry
        via ``model_dump()`` before handing it to ``ProposalInput``."""
        inp = ProposalInput(
            interpretation={},
            recent_gate_exhaustions=[gate_exhaustion.model_dump()],
        )
        assert isinstance(inp.recent_gate_exhaustions[0], GateExhaustionInfo)
        assert inp.recent_gate_exhaustions[0].summary_message.startswith("All 9 attempts")

    def test_round_trip_preserves_entries(self, gate_exhaustion):
        """JSON round-trip must preserve every entry verbatim — the protocol
        layer serialises ProposalInput across the workflow boundary."""
        inp = ProposalInput(
            interpretation={},
            recent_gate_exhaustions=[gate_exhaustion, self._second_gate_exhaustion()],
        )
        round_tripped = ProposalInput.model_validate_json(inp.model_dump_json())
        assert len(round_tripped.recent_gate_exhaustions) == 2
        assert round_tripped.recent_gate_exhaustions[0].model_dump() == gate_exhaustion.model_dump()
        assert (
            round_tripped.recent_gate_exhaustions[1].model_dump()
            == self._second_gate_exhaustion().model_dump()
        )

    def test_invalid_entry_dict_raises(self):
        """Malformed dicts in the list must fail validation, not silently
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
                recent_gate_exhaustions=[bad_dict],
            )

    def test_rejects_over_ten_entries(self, gate_exhaustion):
        """Schema safety rail: the workflow enforces maxlen=3 via a deque,
        but the schema itself caps the list at 10 entries to guard against
        an unbounded caller. See §14.N.1."""
        with pytest.raises(ValidationError) as exc:
            ProposalInput(
                interpretation={},
                recent_gate_exhaustions=[gate_exhaustion] * 11,
            )
        assert "maximum allowed is 10" in str(exc.value)


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
