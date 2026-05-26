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
# Golden-Paragraph required tokens (citations 1-3 + guardrails + header)
# ---------------------------------------------------------------------------


class TestGoldenParagraphRequiredTokens:
    """Consolidated single-token presence assertions on the
    mathematical_definition spec.

    Covers all three Golden-Paragraph citation groups (forward contract,
    segmentation semantics, fixed-dimension clause), the preserved
    guardrails carried over from the pre-WS-B prompt, and the explicit
    'Golden Paragraph' header. Each case is one ``assert <token> in spec``
    — these tokens must not drift; any rename breaks the plugin loader's
    contract guarantee or defeats the WS-B intent.
    """

    @pytest.mark.parametrize(
        "expected_token",
        [
            pytest.param("[B, T] int64", id="forward_input_shape_dtype"),
            pytest.param("[B, 256, T] float32", id="forward_output_shape_dtype"),
            pytest.param("per-timestep", id="per_timestep_semantics"),
            pytest.param("segment-local", id="segment_local_named"),
            pytest.param("segment-cross", id="segment_cross_named"),
            pytest.param("causal masking", id="causal_masking_named"),
            pytest.param("256 denoising bins", id="256_denoising_bins_named"),
            pytest.param("contract-fixed", id="contract_fixed_qualifier"),
            pytest.param(
                "Do NOT include concrete layer dimensions",
                id="no_concrete_dims_clause_preserved",
            ),
            pytest.param("belong in baseline_config", id="baseline_config_pointer_preserved"),
            pytest.param("Golden Paragraph", id="golden_paragraph_header_literal"),
        ],
    )
    def test_required_token_in_spec(self, spec, expected_token):
        assert expected_token in spec


# ---------------------------------------------------------------------------
# Citation 3 — fixed-dimension co-occurrence (regex, not single-token)
# ---------------------------------------------------------------------------


class TestFixedDimensionCitation:
    """Third Golden-Paragraph citation: the 256 denoising bins must be
    called out as contract-fixed (not a tunable hyperparameter)."""

    def test_contract_fixed_applied_to_256_clause(self, spec):
        """The two tokens must co-occur in the same clause — a future
        rewrite that names '256 denoising bins' somewhere and
        'contract-fixed' somewhere else would defeat the intent."""
        assert (
            re.search(
                r"256 denoising bins[^\"]{0,60}contract-fixed",
                spec,
                re.DOTALL,
            )
            is not None
        ), (
            "'256 denoising bins' and 'contract-fixed' must co-occur in "
            "the same clause. Spec:\n" + spec
        )


# ---------------------------------------------------------------------------
# Meta — the field spec itself must exist and be non-trivial
# ---------------------------------------------------------------------------


class TestFieldSpecPresence:
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
        assert "The forward contract is fixed: input [B, T] int64" in PROPOSAL_COMMIT_PROMPT
