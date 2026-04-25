"""Unit tests for the Golden-Paragraph contract re-assertion guard
(WS-B §5.2 / parent §5.3 item 1).

Pins the three citation markers and the preserved guardrails inside the
``mathematical_definition`` field spec of ``PROPOSAL_COMMIT_PROMPT``.
A future prompt refactor that silently drops one of these markers will
flip this test red — this is the single mechanical guard against
Golden-Paragraph drift.

See docs/phase66_ws_b_proposer_hardening.md §3.3 / §5.2.
"""
from __future__ import annotations

import re

import pytest

from nodes.ml_model_proposal_agent import PROPOSAL_COMMIT_PROMPT


# ---------------------------------------------------------------------------
# Extract the mathematical_definition field spec
# ---------------------------------------------------------------------------

def _extract_mathematical_definition_spec() -> str:
    """Pull the string value of the ``mathematical_definition`` field from
    the commit prompt. The field is one JSON-ish line in the template:

        "mathematical_definition": "…long spec string…",
    """
    m = re.search(
        r'"mathematical_definition":\s*"(.+?)"\s*,\s*\n',
        PROPOSAL_COMMIT_PROMPT,
        re.DOTALL,
    )
    assert m is not None, (
        "Commit prompt must contain a mathematical_definition field — "
        "regex to extract it returned no match."
    )
    return m.group(1)


@pytest.fixture(scope="module")
def spec() -> str:
    return _extract_mathematical_definition_spec()


# ---------------------------------------------------------------------------
# Citation 1 — forward contract verbatim
# ---------------------------------------------------------------------------

class TestForwardContractCitation:
    """The field spec must cite the forward I/O contract verbatim —
    ``[B, T] int64`` on the input side and ``[B, 256, T] float32`` on
    the output side. These tokens must not drift (any rename breaks
    the plugin loader's contract guarantee)."""

    def test_input_shape_and_dtype_present(self, spec):
        assert "[B, T] int64" in spec

    def test_output_shape_and_dtype_present(self, spec):
        assert "[B, 256, T] float32" in spec

    def test_per_timestep_semantics_named(self, spec):
        """The forward contract string names 'per-timestep' semantics
        (ADC class indices on input, logits over denoising classes on
        output)."""
        assert "per-timestep" in spec


# ---------------------------------------------------------------------------
# Citation 2 — segmentation semantics
# ---------------------------------------------------------------------------

class TestSegmentationSemanticsCitation:
    """Second Golden-Paragraph citation: the body must be labelled as
    segment-local or segment-cross, and causal-masking must be named as
    a required-or-not decision."""

    def test_segment_local_named(self, spec):
        assert "segment-local" in spec

    def test_segment_cross_named(self, spec):
        assert "segment-cross" in spec

    def test_causal_masking_named(self, spec):
        assert "causal masking" in spec


# ---------------------------------------------------------------------------
# Citation 3 — fixed-dimension clause
# ---------------------------------------------------------------------------

class TestFixedDimensionCitation:
    """Third Golden-Paragraph citation: the 256 denoising bins must be
    called out as contract-fixed (not a tunable hyperparameter)."""

    def test_256_denoising_bins_named(self, spec):
        assert "256 denoising bins" in spec

    def test_contract_fixed_qualifier_present(self, spec):
        assert "contract-fixed" in spec

    def test_contract_fixed_applied_to_256_clause(self, spec):
        """The two tokens must co-occur in the same clause — a future
        rewrite that names '256 denoising bins' somewhere and
        'contract-fixed' somewhere else would defeat the intent."""
        assert re.search(
            r"256 denoising bins[^\"]{0,60}contract-fixed",
            spec,
            re.DOTALL,
        ) is not None, (
            "'256 denoising bins' and 'contract-fixed' must co-occur in "
            "the same clause. Spec:\n" + spec
        )


# ---------------------------------------------------------------------------
# Preserved guardrails from the pre-Golden-Paragraph prompt
# ---------------------------------------------------------------------------

class TestPreservedGuardrails:
    """The WS-B rewrite must preserve the constraints that the pre-WS-B
    prompt already enforced: no concrete layer dimensions in the
    mathematical_definition (those belong in baseline_config)."""

    def test_no_concrete_dims_clause_preserved(self, spec):
        assert "Do NOT include concrete layer dimensions" in spec

    def test_baseline_config_pointer_preserved(self, spec):
        assert "belong in baseline_config" in spec


# ---------------------------------------------------------------------------
# Meta — the field spec itself must exist and be non-trivial
# ---------------------------------------------------------------------------

class TestFieldSpecPresence:

    def test_golden_paragraph_header_literal_present(self, spec):
        """The spec explicitly names 'Golden Paragraph' so the LLM knows
        the three-sentence opening is a contract, not a style request."""
        assert "Golden Paragraph" in spec

    def test_field_spec_is_nontrivial_length(self, spec):
        """Guards against accidental wipe: the Golden-Paragraph spec is
        >=600 chars. A one-liner would indicate a regression."""
        assert len(spec) >= 600, (
            f"mathematical_definition spec shrunk to {len(spec)} chars — "
            f"likely a regression dropped the Golden Paragraph. Spec:\n{spec}"
        )

    def test_commit_prompt_still_carries_io_contract_line(self):
        """Hard-constraint block — separate from the field spec — must
        still carry the I/O contract statement."""
        assert (
            "The forward contract is fixed: input [B, T] int64"
            in PROPOSAL_COMMIT_PROMPT
        )
