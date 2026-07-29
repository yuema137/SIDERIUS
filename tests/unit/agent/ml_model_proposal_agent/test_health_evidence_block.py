"""Flag ON ⇒ the proposer renders exact structured HealthGate evidence.

CB4-b suite (``pr3_healthgate_feedback.md`` §3.7; CB4 spec §6-§11).
Uses the SAME strong two-model fixture as the parity golden, so every
value asserted here is the real ``InterpretationOutput.model_dump``
serialization shape.
"""

import pytest

from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _build_reasoning_prompt,
    _format_healthgate_evidence_block,
    _format_recent_gate_exhaustions_block,
)
from tests.unit.agent.ml_model_proposal_agent._health_feedback_fixtures import (
    SIG_A,
    SIG_B,
    gate_exhaustion,
    strong_proposal_input,
    structured_interpretation_output,
)

WS = "/tmp/cb4_golden_ws"


def _prompt_on():
    return _build_reasoning_prompt(
        strong_proposal_input(WS, enable_structured_health_feedback=True)
    )


class TestFlagOnBlock:
    def test_block_appears_with_exact_values(self):
        prompt = _prompt_on()
        assert "[HEALTHGATE EVIDENCE]" in prompt
        # Exact per-model counts (this iteration).
        assert "Round validity (this iteration): 0 valid, 1 invalid, 1 unknown" in prompt
        assert "Round validity (this iteration): 1 valid, 2 invalid, 0 unknown" in prompt
        # Current-iteration fingerprints with human-readable explanations.
        assert f"- {SIG_A} — output collapsed to a single int8 value" in prompt
        assert f"- {SIG_B} — output std collapsed below 1 mV" in prompt

    def test_retained_window_count_not_lifetime(self):
        """model_a's history has buckets iter-3(x2) + iter-5(x1): the block
        must show the retained-window sum 3 with the exact iteration tags —
        the buckets ARE the retained window (post-retention storage)."""
        prompt = _prompt_on()
        assert f"- {SIG_A}: 3 occurrence(s) across iteration(s) 3, 5" in prompt
        assert f"- {SIG_B}: 1 occurrence(s) across iteration(s) 5" in prompt

    def test_representative_metrics_labelled(self):
        prompt = _prompt_on()
        assert "Representative observation: n_unique_int8_values=1" in prompt
        assert "Representative observation: output_std_mv=0.0431" in prompt

    def test_bounded_source_identity_surfaced(self):
        prompt = _prompt_on()
        assert (
            "Source experiments (recent, bounded): model_a_iter_003_002, "
            "model_a_iter_003_004, model_a_iter_005_001"
        ) in prompt

    def test_closing_instruction_present_and_bounded(self):
        prompt = _prompt_on()
        assert "Rules for using this evidence:" in prompt
        assert "concrete mechanism expected to break it" in prompt
        assert "not merely the explanation text" in prompt
        assert "invalid round is a failure, not a success" in prompt
        block = _format_healthgate_evidence_block(
            structured_interpretation_output().model_dump(mode="json")
        )
        assert len(block.splitlines()) < 45  # bounded, not a second system prompt

    def test_rendered_after_and_separate_from_gate_exhaustions(self):
        prompt = _prompt_on()
        exhaustion_pos = prompt.find("[RECENT GATE EXHAUSTIONS")
        health_pos = prompt.find("[HEALTHGATE EVIDENCE]")
        assert 0 <= exhaustion_pos < health_pos
        assert "distinct from the resource-gate report" in prompt


class TestModelAttribution:
    def test_no_cross_model_contamination(self):
        """Adversarial two-model check: each model's section carries ONLY
        its own signatures, counts, tags, and source ids."""
        block = _format_healthgate_evidence_block(
            structured_interpretation_output().model_dump(mode="json")
        )
        a_section = block.split("### model_a")[1].split("### model_b")[0]
        b_section = block.split("### model_b")[1]
        assert SIG_A in a_section and SIG_B not in a_section
        assert SIG_B in b_section and SIG_A not in b_section
        assert "model_b_iter" not in a_section
        assert "model_a_iter" not in b_section
        assert "0.0431" not in a_section
        # No global unlabelled fingerprint list: every signature line sits
        # under a "### {model}" heading.
        preamble = block.split("### model_a")[0]
        assert SIG_A not in preamble and SIG_B not in preamble


class TestLegacyEmptyPartial:
    def test_legacy_dict_renders_nothing(self):
        legacy = {"model_types": ["wavenet"], "total_experiments": 3}
        assert _format_healthgate_evidence_block(legacy) == ""

    def test_empty_evidence_renders_no_header(self):
        interp = structured_interpretation_output().model_dump(mode="json")
        interp["per_model_round_health_counts"] = {}
        interp["per_model_collapse_fingerprints"] = {}
        interp["collapse_fingerprint_history"] = {}
        assert _format_healthgate_evidence_block(interp) == ""

    def test_counts_without_fingerprints_render_counts_only(self):
        """Validity counts but no deterministic fingerprint: render only
        what is supported — never invent a fingerprint."""
        interp = structured_interpretation_output().model_dump(mode="json")
        interp["per_model_collapse_fingerprints"] = {}
        interp["collapse_fingerprint_history"] = {}
        block = _format_healthgate_evidence_block(interp)
        assert "Round validity (this iteration)" in block
        assert "collapse fingerprints" not in block
        assert "Retained history" not in block

    def test_malformed_history_entry_fails_diagnostically(self):
        interp = structured_interpretation_output().model_dump(mode="json")
        interp["collapse_fingerprint_history"]["model_a"] = [{"not_signature": True}]
        with pytest.raises(ValueError, match="model 'model_a'"):
            _format_healthgate_evidence_block(interp)


class TestGateExhaustionUnchanged:
    def test_exhaustion_block_byte_identical_before_and_after_cb4(self):
        """§14.N regression: the exhaustion renderer's output on the same
        fixture is identical whether or not the health flag is on, and the
        exact block string appears verbatim inside the flag-ON prompt."""
        block = _format_recent_gate_exhaustions_block([gate_exhaustion()])
        assert block in _prompt_on()
        prompt_off = _build_reasoning_prompt(strong_proposal_input(WS))
        assert block in prompt_off
