"""
Tests for agent/schemas/interpretation.py
"""

import pytest
from pydantic import ValidationError

from agent.schemas.interpretation import (
    InterpretationInput,
    ModelRunSummary,
)

# ---------------------------------------------------------------------------
# ModelRunSummary
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# InterpretationInput
# ---------------------------------------------------------------------------


class TestInterpretationInput:
    def test_valid_with_summaries(self):
        inp = InterpretationInput(
            summaries=[
                ModelRunSummary(
                    model_type="punet",
                    run_name="v1",
                    status="completed",
                    completed_rounds=5,
                )
            ],
        )
        assert inp.storage.backend == "local"

    def test_valid_with_model_types(self):
        inp = InterpretationInput(model_types=["punet", "fcnet"])
        assert inp.model_types == ["punet", "fcnet"]
        assert inp.summaries == []

    def test_valid_with_both(self):
        inp = InterpretationInput(
            summaries=[
                ModelRunSummary(
                    model_type="punet",
                    run_name="v1",
                    status="completed",
                    completed_rounds=5,
                )
            ],
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

    # --- Active-Model policy fields (Commit 6.1) ---


# ---------------------------------------------------------------------------
# InterpretationOutput
# ---------------------------------------------------------------------------
