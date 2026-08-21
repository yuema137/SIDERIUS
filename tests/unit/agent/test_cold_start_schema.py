"""Cold-start typed-state tests (PR: seedless chain cold start).

Covers the explicit ``cold_start`` field on InterpretationInput /
InterpretationOutput / ProposalInput and the relaxed
``require_at_least_one_model`` validator. No LLM, no GPU.
"""

import pytest

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_evidence import build_proposer_evidence


def _output(**over):
    base = dict(
        model_types=[],
        model_descriptions={},
        total_experiments=0,
        key_findings=[],
        bottlenecks=[],
        take_home_message="x",
    )
    base.update(over)
    return InterpretationOutput(**base)


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

    def test_cold_start_defaults_false_for_seeded_input(self):
        inp = InterpretationInput(summaries=[], model_types=["wavenet"])
        assert inp.cold_start is False


class TestColdStartPropagationFields:
    def test_output_cold_start_defaults_false(self):
        assert _output().cold_start is False

    def test_output_cold_start_roundtrips(self):
        assert _output(cold_start=True).cold_start is True

    def test_proposal_input_cold_start_defaults_false(self):
        assert (
            ProposalInput(interpretation_evidence=build_proposer_evidence({})).cold_start is False
        )

    def test_proposal_input_cold_start_settable(self):
        assert (
            ProposalInput(
                interpretation_evidence=build_proposer_evidence({}),
                cold_start=True,
            ).cold_start
            is True
        )
