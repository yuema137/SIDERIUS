"""Unit tests for the B.6a-v4 Integrated Reasoning clause in the staged
pipeline's stage-2 system template ``causal_reasoning_stage.md``.

See ``docs/phase66_ws_b_proposer_hardening.md`` §3.4.5 for the full B.6a-v4
correction plan; this guard is **B.6b-v2** — the rewrite of the original
B.6b guard that asserted against the dormant legacy
``PROPOSAL_REASONING_PROMPT`` string in ``nodes/ml_model_proposal_agent.py``.

History:

- **v1 (B.6a)** asserted a "Physical-rejection acknowledgement" header with
  four dash-bulleted citations against the legacy ``.py`` prompt.
- **Phase A of B.6e** revealed a keyword-gate false-positive
  (``"cap" in "capture"``) and — more importantly — that the ``.py`` prompt
  is dormant: production loads the staged template
  ``causal_reasoning_stage.md`` via ``load_stage_prompt(...)``.
- **v3 (B.6a-v3)** rewrote the clause for "integrated reasoning": science
  and engineering treated as simultaneous constraints.
- **v4 (B.6a-v4)** ported the v3 clause to the live staged template.

This guard (B.6b-v2) asserts the v4 port's invariants against the
``.md`` template, loaded via
``load_prompt("causal_reasoning_stage.md")``. The local variable name
``PROPOSAL_REASONING_PROMPT`` is preserved for continuity with the
pre-v4 test body.
"""

from __future__ import annotations

import re

from agent.prompt_templates.proposal import load_prompt

PROPOSAL_REASONING_PROMPT = load_prompt("causal_reasoning_stage.md")


class TestMandatoryHeaderPresence:
    """The ``## MANDATORY — Integrated reasoning (science + engineering)``
    header must appear verbatim as a top-level Markdown section in the
    staged stage-2 template (B.6a-v4).

    See §3.4.5.6 for the header-form decision (Markdown ``##`` prefix,
    no trailing colon)."""

    def test_mandatory_header_precedes_what_you_produce(self):
        """Placement invariant: the clause must sit BEFORE
        ``## What you produce`` so the cognitive contract on
        ``causal_hypothesis`` is established before the JSON schema that
        defines it (§3.4.5.3)."""
        header_idx = PROPOSAL_REASONING_PROMPT.index(
            "## MANDATORY — Integrated reasoning (science + engineering)"
        )
        produce_idx = PROPOSAL_REASONING_PROMPT.index("## What you produce")
        assert header_idx < produce_idx

    def test_mandatory_header_follows_what_you_receive(self):
        """The clause must appear AFTER ``## What you receive`` so the
        ``[PHYSICAL REJECTION]`` and ``[HARDWARE CONTEXT]`` input blocks
        are already declared before the integrated-reasoning mandate
        lands (§3.4.5.3)."""
        receive_idx = PROPOSAL_REASONING_PROMPT.index("## What you receive")
        header_idx = PROPOSAL_REASONING_PROMPT.index(
            "## MANDATORY — Integrated reasoning (science + engineering)"
        )
        assert receive_idx < header_idx


class TestDesignConstraintTreatment:
    """The load-bearing distinction v3 makes: the previous failure is a
    *design constraint to be solved alongside the scientific bottlenecks*,
    not a historical footnote. This phrase directly addresses the Phase A
    failure mode (LLM pivoted to a different arch class but did not treat
    the rejection as an input to its design)."""

    def test_not_a_historical_footnote(self):
        # The .md wraps "historical" → newline → "footnote" — allow \s+.
        assert re.search(r"not a historical\s+footnote", PROPOSAL_REASONING_PROMPT) is not None


class TestCausalHypothesisIntegrationContract:
    """The ``causal_hypothesis`` must be a *single integrated paragraph*
    that simultaneously names the scientific bottleneck, the physical
    failure (with the three citation requirements from v1 preserved), and
    the integrated synthesis (how the structural choice satisfies both)."""

    def test_causal_hypothesis_named_as_single_integrated_paragraph(self):
        assert "single integrated paragraph" in PROPOSAL_REASONING_PROMPT
        assert "causal_hypothesis" in PROPOSAL_REASONING_PROMPT

    def test_citation_physical_failure_three_requirements(self):
        """Preserved from v1: model_type, dominant OOM layer, overshoot."""
        # Note the backticks around model_type — the .md uses Markdown
        # code-quoting where the legacy .py string did not.
        assert "rejected `model_type`" in PROPOSAL_REASONING_PROMPT
        assert "dominant layer that caused the OOM" in PROPOSAL_REASONING_PROMPT
        assert "overshoot evidence" in PROPOSAL_REASONING_PROMPT
        assert "Effective cap vs Predicted peak" in PROPOSAL_REASONING_PROMPT


class TestClosingConstraintText:
    """The closing paragraph must assert the incompleteness framing (both
    one-sided failures are explicitly disqualified) and close with the
    'cite as design constraint' instruction.

    v3 explicitly disqualifies TWO failure modes:
    (i) scientific-only (ignore rejection),
    (ii) VRAM-only (no science).
    v1 disqualified only the first."""

    def test_both_one_sided_failures_disqualified(self):
        # Tokens may span line breaks — the .md wraps "with" → newline →
        # "no" in the first phrase and "VRAM" → newline → "cap" in the
        # second, so \s+ sits BETWEEN those pairs.
        assert (
            re.search(
                r"only the scientific bottleneck with\s+no mention of the physical rejection",
                PROPOSAL_REASONING_PROMPT,
            )
            is not None
        )
        assert (
            re.search(
                r"only the VRAM\s+cap with no scientific rationale",
                PROPOSAL_REASONING_PROMPT,
            )
            is not None
        )
        assert "incomplete" in PROPOSAL_REASONING_PROMPT


class TestClausePositionInvariant:
    """One regex pinning the whole clause's structural shape in a single
    assertion — header, integration framing, three-bullet citation block,
    closing incompleteness assertion.

    Drift-detector: if any future prompt edit damages the clause's internal
    ordering, this test fails even if targeted tests still pass."""

    def test_clause_structure_intact(self):
        pattern = re.compile(
            r"##\s*MANDATORY — Integrated reasoning \(science \+ engineering\).*?"
            r"You are both a scientist and an engineer\..*?"
            r"two constraint systems.*?"
            r"\(a\) the \*\*scientific goals\*\*.*?"
            r"\(b\) the \*\*physical constraints\*\*.*?"
            r"design constraint to\s+be solved alongside.*?"
            r"  - names the scientific bottleneck.*?"
            r"  - names the physical failure.*?"
            r"  - explains how your new architecture.*?"
            r"scientific\s+improvement.*?"
            r"remaining strictly within.*?"
            r"Cite the previous failure\s+as a design constraint to be solved alongside",
            re.DOTALL,
        )
        assert pattern.search(PROPOSAL_REASONING_PROMPT) is not None
