"""
Tests for agent/schemas/proposal.py
"""
import pytest
from pydantic import ValidationError

from agent.schemas.proposal import ProposalInput, ProposalOutput
from agent.schemas.hyperparam_tuning import ExpertAdvice


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
