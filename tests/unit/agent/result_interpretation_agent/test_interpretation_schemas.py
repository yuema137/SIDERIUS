"""
Tests for agent/schemas/interpretation.py
"""
import pytest
from pydantic import ValidationError

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput


class TestInterpretationInput:

    def test_valid(self):
        inp = InterpretationInput(summary_records=[{"exp_id": "x"}], model_type="punet")
        assert inp.model_type == "punet"
        assert inp.max_records == 50
        assert inp.storage.backend == "local"

    def test_missing_model_type_raises(self):
        with pytest.raises(ValidationError) as exc:
            InterpretationInput(summary_records=[])
        assert "model_type" in str(exc.value)

    def test_zero_max_records_raises(self):
        with pytest.raises(ValidationError) as exc:
            InterpretationInput(summary_records=[], model_type="punet", max_records=0)
        assert "max_records" in str(exc.value)

    def test_storage_custom(self):
        inp = InterpretationInput(
            summary_records=[],
            model_type="fcnet",
            storage={"backend": "local", "local": {"workspace": "/runs", "run_name": "exp1"}},
        )
        assert inp.storage.local.workspace == "/runs"
        assert inp.storage.local.run_name == "exp1"

    def test_storage_default(self):
        inp = InterpretationInput(summary_records=[], model_type="punet")
        assert inp.storage.local.workspace == "./siderius_workspace"


class TestInterpretationOutput:

    def test_valid_full(self):
        out = InterpretationOutput(
            model_type="punet",
            model_description="# PUNet\nA 1D U-Net with positional encoding.",
            total_experiments=10,
            best_denoising_score=1.5,
            best_config={"model_config": {}},
            key_findings=["focal loss outperforms ce"],
            bottlenecks=["architecture plateau at depth=3"],
            take_home_message="Need a new architecture.",
        )
        assert out.total_experiments == 10
        assert len(out.key_findings) == 1
        assert "PUNet" in out.model_description

    def test_valid_minimal(self):
        out = InterpretationOutput(
            model_type="punet",
            model_description="# PUNet\nA 1D U-Net with positional encoding.",
            total_experiments=0,
            key_findings=[],
            bottlenecks=[],
            take_home_message="No data yet.",
        )
        assert out.best_denoising_score is None
        assert out.best_config is None

    def test_missing_take_home_message_raises(self):
        with pytest.raises(ValidationError) as exc:
            InterpretationOutput(
                model_type="punet",
                total_experiments=5,
                key_findings=[],
                bottlenecks=[],
            )
        assert "take_home_message" in str(exc.value)
