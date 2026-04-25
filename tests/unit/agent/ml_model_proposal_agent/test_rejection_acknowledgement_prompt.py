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

    def test_mandatory_header_present(self):
        assert (
            "## MANDATORY — Integrated reasoning (science + engineering)"
            in PROPOSAL_REASONING_PROMPT
        )

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


class TestTwoConstraintSystemsFraming:
    """The v3 opener must frame two *simultaneous* constraint systems —
    scientific goals (from the DiscoveryMemo) and physical constraints
    (from ``[PHYSICAL REJECTION]`` + ``[HARDWARE CONTEXT]``). This is the
    core cognitive shift over v1 ('acknowledge and pivot') toward v3
    ('solve both jobs at once').

    See §3.4.5.4 for the canonical v3 text."""

    def test_scientist_and_engineer_framing(self):
        assert "You are both a scientist and an engineer" in PROPOSAL_REASONING_PROMPT

    def test_two_constraint_systems_must_be_satisfied_simultaneously(self):
        assert "two constraint systems" in PROPOSAL_REASONING_PROMPT
        assert "simultaneously" in PROPOSAL_REASONING_PROMPT
        assert "not\nsequentially" in PROPOSAL_REASONING_PROMPT

    def test_names_scientific_goals_source(self):
        assert "scientific goals" in PROPOSAL_REASONING_PROMPT
        # The scientific-goals source is the DiscoveryMemo; the staged
        # stage-2 template introduces the DiscoveryMemo in its opening
        # paragraph.
        assert "DiscoveryMemo" in PROPOSAL_REASONING_PROMPT

    def test_names_physical_constraints_sources(self):
        assert "physical constraints" in PROPOSAL_REASONING_PROMPT
        assert "[PHYSICAL REJECTION]" in PROPOSAL_REASONING_PROMPT
        assert "[HARDWARE CONTEXT]" in PROPOSAL_REASONING_PROMPT
        assert "Effective cap" in PROPOSAL_REASONING_PROMPT


class TestDesignConstraintTreatment:
    """The load-bearing distinction v3 makes: the previous failure is a
    *design constraint to be solved alongside the scientific bottlenecks*,
    not a historical footnote. This phrase directly addresses the Phase A
    failure mode (LLM pivoted to a different arch class but did not treat
    the rejection as an input to its design)."""

    def test_treat_failure_as_design_constraint(self):
        assert (
            "design constraint to be solved alongside"
            in PROPOSAL_REASONING_PROMPT
        )

    def test_not_a_historical_footnote(self):
        # The .md wraps "historical" → newline → "footnote" — allow \s+.
        assert re.search(
            r"not a historical\s+footnote", PROPOSAL_REASONING_PROMPT
        ) is not None


class TestCausalHypothesisIntegrationContract:
    """The ``causal_hypothesis`` must be a *single integrated paragraph*
    that simultaneously names the scientific bottleneck, the physical
    failure (with the three citation requirements from v1 preserved), and
    the integrated synthesis (how the structural choice satisfies both)."""

    def test_causal_hypothesis_named_as_single_integrated_paragraph(self):
        assert "single integrated paragraph" in PROPOSAL_REASONING_PROMPT
        assert "causal_hypothesis" in PROPOSAL_REASONING_PROMPT

    def test_citation_scientific_bottleneck(self):
        assert "scientific bottleneck" in PROPOSAL_REASONING_PROMPT
        # The canonical clause scopes the scientific bottleneck to the
        # Stage 1 comparisons (see §3.4.5.4). Uses "from the Stage 1"
        # rather than the legacy "from the memo".
        assert "from the Stage 1" in PROPOSAL_REASONING_PROMPT

    def test_citation_physical_failure_three_requirements(self):
        """Preserved from v1: model_type, dominant OOM layer, overshoot."""
        # Note the backticks around model_type — the .md uses Markdown
        # code-quoting where the legacy .py string did not.
        assert "rejected `model_type`" in PROPOSAL_REASONING_PROMPT
        assert "dominant layer that caused the OOM" in PROPOSAL_REASONING_PROMPT
        assert "overshoot evidence" in PROPOSAL_REASONING_PROMPT
        assert "Effective cap vs Predicted peak" in PROPOSAL_REASONING_PROMPT

    def test_citation_integrated_synthesis(self):
        """The third citation — this is v3's novelty — the architecture
        must do both jobs: achieve scientific improvement AND stay under
        the effective cap that defeated the previous proposal."""
        # Tokens may span a line break in the rendered prompt.
        assert re.search(
            r"scientific\s+improvement", PROPOSAL_REASONING_PROMPT
        ) is not None
        assert "remaining strictly within" in PROPOSAL_REASONING_PROMPT
        assert (
            "defeated the previous proposal"
            in PROPOSAL_REASONING_PROMPT
        )

    def test_three_citation_bullets_appear_in_order(self):
        """The three bullet-prefixed requirements must appear in the order:
        scientific bottleneck → physical failure → integrated synthesis."""
        pattern = re.compile(
            r"  - names the scientific bottleneck.*?"
            r"  - names the physical failure.*?"
            r"  - explains how your new architecture achieves the desired\s+"
            r"scientific\s+improvement",
            re.DOTALL,
        )
        assert pattern.search(PROPOSAL_REASONING_PROMPT) is not None


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
        assert re.search(
            r"only the scientific bottleneck with\s+no mention of the physical rejection",
            PROPOSAL_REASONING_PROMPT,
        ) is not None
        assert re.search(
            r"only the VRAM\s+cap with no scientific rationale",
            PROPOSAL_REASONING_PROMPT,
        ) is not None
        assert "incomplete" in PROPOSAL_REASONING_PROMPT

    def test_closing_cite_as_design_constraint(self):
        """v3 closes with an explicit instruction to cite the previous
        failure as a design constraint to be solved alongside the
        scientific bottlenecks. This sentence is the terminal marker for
        the MANDATORY clause and anchors
        ``test_clause_structure_intact`` below."""
        assert re.search(
            r"Cite the previous failure\s+as a design constraint to be solved alongside",
            PROPOSAL_REASONING_PROMPT,
        ) is not None


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
