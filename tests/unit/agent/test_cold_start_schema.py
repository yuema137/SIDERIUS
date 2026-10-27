"""Cold-start typed-state tests (PR: seedless chain cold start).

Covers the explicit ``cold_start`` field on InterpretationInput /
InterpretationOutput / ProposalInput and the relaxed
``require_at_least_one_model`` validator. No LLM, no GPU.
"""

import pytest

from agent.schemas.interpretation import InterpretationInput


class TestInterpretationInputColdStart:
    def test_empty_summaries_with_cold_start_is_valid(self):
        inp = InterpretationInput(summaries=[], cold_start=True)
        assert inp.cold_start is True

    def test_empty_summaries_without_cold_start_still_rejected(self):
        # Backward-compat: an accidental empty input is still an error.
        with pytest.raises(ValueError, match="At least one model type"):
            InterpretationInput(summaries=[])

    def test_empty_model_types_list_still_rejected_even_in_cold_start(self):
        with pytest.raises(ValueError, match="cannot be an empty list"):
            InterpretationInput(summaries=[], model_types=[], cold_start=True)
