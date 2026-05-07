"""
Tests for agent/schemas/interpretation.py
"""
import pytest
from pydantic import ValidationError

from agent.schemas.interpretation import (
    InterpretationInput, InterpretationOutput, ModelRunSummary,
)


# ---------------------------------------------------------------------------
# ModelRunSummary
# ---------------------------------------------------------------------------

class TestModelRunSummary:

    def test_valid(self):
        s = ModelRunSummary(
            model_type="punet", run_name="v1", status="completed",
            completed_rounds=10, best_denoising_score=1.5,
            worst_denoising_score=0.3, best_config={"model_config": {}},
            round_scores=[0.3, 0.8, 1.2, 1.5],
            round_conclusions=["Bad", "Better", "Good", "Best"],
        )
        assert s.model_type == "punet"
        assert s.completed_rounds == 10
        assert len(s.round_scores) == 4

    def test_minimal(self):
        s = ModelRunSummary(
            model_type="fcnet", run_name="v1", status="completed",
            completed_rounds=0,
        )
        assert s.round_scores == []
        assert s.best_denoising_score is None


# ---------------------------------------------------------------------------
# InterpretationInput
# ---------------------------------------------------------------------------

class TestInterpretationInput:

    def test_valid_with_summaries(self):
        inp = InterpretationInput(
            summaries=[ModelRunSummary(
                model_type="punet", run_name="v1", status="completed",
                completed_rounds=5,
            )],
        )
        assert inp.storage.backend == "local"

    def test_valid_with_model_types(self):
        inp = InterpretationInput(model_types=["punet", "fcnet"])
        assert inp.model_types == ["punet", "fcnet"]
        assert inp.summaries == []

    def test_valid_with_both(self):
        inp = InterpretationInput(
            summaries=[ModelRunSummary(
                model_type="punet", run_name="v1", status="completed",
                completed_rounds=5,
            )],
            model_types=["fcnet"],
        )
        assert len(inp.summaries) == 1
        assert "fcnet" in inp.model_types

    def test_no_model_raises(self):
        with pytest.raises(ValidationError, match="At least one model type"):
            InterpretationInput()

    def test_empty_model_types_raises(self):
        with pytest.raises(ValidationError, match="model_types cannot be an empty list"):
            InterpretationInput(model_types=[])

    def test_storage_custom(self):
        inp = InterpretationInput(
            model_types=["punet"],
            storage={"backend": "local", "local": {"workspace": "/runs", "run_name": "exp1"}},
        )
        assert inp.storage.local.workspace == "/runs"

    def test_storage_default(self):
        inp = InterpretationInput(model_types=["punet"])
        assert inp.storage.local.workspace == "./siderius_workspace"

    # --- Active-Model policy fields (Commit 6.1) ---

    def test_active_model_defaults(self):
        """Defaults match the design doc: K=3, N=2, Δ=0.05."""
        inp = InterpretationInput(model_types=["punet"])
        assert inp.active_model_top_k == 3
        assert inp.active_model_last_n == 2
        assert inp.active_model_score_delta == 0.05

    def test_active_model_custom(self):
        """Custom K/N/Δ propagate through validation."""
        inp = InterpretationInput(
            model_types=["punet"],
            active_model_top_k=5,
            active_model_last_n=1,
            active_model_score_delta=0.1,
        )
        assert inp.active_model_top_k == 5
        assert inp.active_model_last_n == 1
        assert inp.active_model_score_delta == 0.1

    def test_active_model_zero_allowed(self):
        """K=0, N=0, Δ=0 are valid (disable Top-K / Last-N pathway, max sensitivity)."""
        inp = InterpretationInput(
            model_types=["punet"],
            active_model_top_k=0,
            active_model_last_n=0,
            active_model_score_delta=0.0,
        )
        assert inp.active_model_top_k == 0
        assert inp.active_model_last_n == 0
        assert inp.active_model_score_delta == 0.0

    def test_active_model_negative_top_k_rejected(self):
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            InterpretationInput(model_types=["punet"], active_model_top_k=-1)

    def test_active_model_negative_last_n_rejected(self):
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            InterpretationInput(model_types=["punet"], active_model_last_n=-1)

    def test_active_model_negative_delta_rejected(self):
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            InterpretationInput(model_types=["punet"], active_model_score_delta=-0.01)


# ---------------------------------------------------------------------------
# InterpretationOutput
# ---------------------------------------------------------------------------

class TestInterpretationOutput:

    def test_valid_full(self):
        out = InterpretationOutput(
            model_types=["punet"],
            model_descriptions={"punet": "# PUNet\nA 1D U-Net with positional encoding."},
            total_experiments=10,
            per_model_best={"punet": 1.5},
            per_model_worst={"punet": 0.3},
            best_denoising_score=1.5,
            worst_denoising_score=0.3,
            best_config={"model_config": {}},
            key_findings=["focal loss outperforms ce"],
            bottlenecks=["architecture plateau at depth=3"],
            take_home_message="Need a new architecture.",
        )
        assert out.total_experiments == 10
        assert out.per_model_best["punet"] == 1.5
        assert out.worst_denoising_score == 0.3

    def test_valid_multi_model(self):
        out = InterpretationOutput(
            model_types=["punet", "fcnet"],
            model_descriptions={
                "punet": "# PUNet",
                "fcnet": "# FCNet",
            },
            total_experiments=20,
            per_model_best={"punet": 1.5, "fcnet": 0.8},
            per_model_worst={"punet": 0.3, "fcnet": 0.1},
            best_denoising_score=1.5,
            worst_denoising_score=0.1,
            key_findings=["punet outperforms fcnet"],
            bottlenecks=["both architectures plateau"],
            take_home_message="Need a fundamentally new approach.",
        )
        assert len(out.model_types) == 2
        assert out.per_model_best["fcnet"] == 0.8

    def test_valid_no_experiments(self):
        out = InterpretationOutput(
            model_types=["punet"],
            model_descriptions={"punet": "# PUNet"},
            total_experiments=0,
            key_findings=[],
            bottlenecks=[],
            take_home_message="No data yet.",
        )
        assert out.best_denoising_score is None
        assert out.best_config is None
        assert out.per_model_best == {}

    def test_missing_take_home_message_raises(self):
        with pytest.raises(ValidationError) as exc:
            InterpretationOutput(
                model_types=["punet"],
                model_descriptions={"punet": "# PUNet"},
                total_experiments=0,
                key_findings=[],
                bottlenecks=[],
            )
        assert "take_home_message" in str(exc.value)
