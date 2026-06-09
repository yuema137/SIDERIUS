"""Structural regression guards for the proposer prompt files (Commit P-c).

These tests are NOT design validation — that's Checkpoint P's job (offline
human review of rendered prompts). These tests catch *accidental* regressions:
- a deleted MANDATORY block,
- a re-added hardcoded trust hierarchy ("Literature agents:", "Physics agents:",
  "Human directives:"),
- a forgotten "Advice JSON" reference in a mode file,
- a Rule 1 rewrite that drops one of the two valid evidence sources.

Per ``feedback_dont_test_static_analysis``: do NOT add tests here that verify
declarative prose alone (e.g. "the prompt is well-written"). Only add a test
when it catches a *runtime-observable* regression — i.e. something the LLM
would read differently.
"""

from pathlib import Path

import pytest

PROPOSAL_PROMPT_DIR = (
    Path(__file__).resolve().parents[4] / "agent" / "prompt_templates" / "proposal"
)

BASE_FILES = (
    "comparison_stage.md",
    "causal_reasoning_stage.md",
    "proposing_stage.md",
)
MODE_FILES = (
    "comparison_stage_explore.md",
    "comparison_stage_exploit.md",
    "causal_reasoning_stage_explore.md",
    "causal_reasoning_stage_exploit.md",
    "proposing_stage_explore.md",
    "proposing_stage_exploit.md",
)
ALL_PROMPT_FILES = BASE_FILES + MODE_FILES


def _load(name: str) -> str:
    return (PROPOSAL_PROMPT_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Causal-reasoning stage — the MANDATORY synthesis block and Rule 1 rewrite
# are the core P-c design contract. If either disappears, the LLM reverts to
# experiment-only reasoning and the lit-review integration is dead.
# ---------------------------------------------------------------------------


class TestCausalReasoningStage:
    def test_mandatory_multi_source_synthesis_block_present(self):
        """The MANDATORY block telling the LLM how to weight hard_limit /
        strong_prior / soft_prior must exist. Deleting it reverts the
        proposer to its pre-P-c behavior (anchor on experiment history,
        ignore external findings)."""
        text = _load("causal_reasoning_stage.md")
        assert "## MANDATORY — Multi-source synthesis" in text
        # All three trust_level values must be referenced by name — the
        # synthesis rule is generic over trust_level, not over agent names.
        for level in ("hard_limit", "strong_prior", "soft_prior"):
            assert f"`{level}`" in text, f"trust_level {level!r} missing from synthesis block"

    def test_rule_1_is_evidence_backed_two_sources(self):
        """Rule 1 must accept BOTH a ModelComparison and a trust-level-gated
        ExpertContextItem as valid evidence. The pre-P-c form ("must
        reference a specific ModelComparison from Stage 1") is forbidden —
        it blocks literature findings by construction."""
        text = _load("causal_reasoning_stage.md")
        # Header form
        assert "1. **Evidence-backed**" in text
        # Both valid sources mentioned
        assert "ModelComparison" in text
        assert "ExpertContextItem" in text
        # Trust gate on the second source — strong_prior or hard_limit only
        # may motivate a claim; soft_prior is inspirational (see Rule 1 spec)
        assert "`strong_prior`" in text
        assert "`hard_limit`" in text
        # Cite source_ref clause — the citation discipline must survive
        assert "source_ref" in text
        # Pre-P-c regression guard: the old single-source form must be gone.
        assert "must reference\n   a specific ModelComparison from Stage 1." not in text

    def test_rule_5_generic_source_type(self):
        """Rule 5 must reference the generic source_type field (P-b) rather
        than 'past model' only. Otherwise InheritedComponent.source_type =
        external_agent / human becomes orphan vocabulary."""
        text = _load("causal_reasoning_stage.md")
        assert "`source_type`" in text
        # All three source_type values must appear so the LLM knows what's valid
        for st in ("experiment", "external_agent", "human"):
            assert f"`{st}`" in text, f"source_type {st!r} missing from Rule 5"


# ---------------------------------------------------------------------------
# Comparison stage — Rule 4 must allow literature signals as link suggestions
# while preserving "only experiment results confirm" semantics.
# ---------------------------------------------------------------------------


class TestComparisonStage:
    def test_rule_4_allows_external_with_provenance(self):
        """Rule 4 must accept external signals as link suggestions but
        require provenance and forbid promotion on external evidence
        alone. Pre-P-c form ("Do NOT guess from generic ML knowledge")
        is forbidden — it blocked lit-review from influencing
        vocab_links."""
        text = _load("comparison_stage.md")
        # The new form must mention provenance + the "no promotion" guard
        assert "provenance" in text or "Provenance" in text
        assert "Do not promote a link to confirmed status on external evidence alone." in text
        # Pre-P-c phrasing must be gone
        assert "Do NOT guess from generic ML knowledge" not in text


# ---------------------------------------------------------------------------
# Generic-over-trust_level invariant — the hardcoded trust hierarchy must
# NOT appear anywhere in agent/prompt_templates/proposal/. P-b introduced
# trust_level so the proposer reads structured calibration off the card;
# any re-introduction of prose like "Literature agents: ... Physics
# agents: ..." undoes that work.
# ---------------------------------------------------------------------------


class TestNoHardcodedAgentNamesInProposalPrompts:
    @pytest.mark.parametrize("filename", ALL_PROMPT_FILES)
    @pytest.mark.parametrize(
        "forbidden",
        [
            "Literature agents:",
            "Physics agents:",
            "Human directives: always take precedence",
        ],
    )
    def test_forbidden_phrase_absent(self, filename: str, forbidden: str):
        text = _load(filename)
        assert forbidden not in text, (
            f"{filename} contains the pre-P-c hardcoded trust-hierarchy "
            f"phrase {forbidden!r}. Calibration must flow via "
            f"AgentCard.trust_level (P-b) — not via agent-name pattern matching."
        )


# ---------------------------------------------------------------------------
# Mode files — Contract Hierarchy must redirect to the base prompt's
# synthesis rules and must NOT reference the dead "Advice JSON" concept.
# ---------------------------------------------------------------------------


class TestModeFilesRedirectSynthesis:
    @pytest.mark.parametrize("filename", MODE_FILES)
    def test_advice_json_phrase_absent(self, filename: str):
        """'Advice JSON' as the strategic-direction authority was a
        pre-P-c dangling pointer — pipeline mode never rendered any
        such JSON. Replaced with a redirect to the base-prompt synthesis
        rules. The phrase must be gone from every mode file."""
        text = _load(filename)
        assert "Advice JSON" not in text

    @pytest.mark.parametrize("filename", MODE_FILES)
    def test_redirect_to_base_prompt_synthesis_present(self, filename: str):
        """Every mode file's Contract Hierarchy must point at the base
        prompt's synthesis rules so a downstream reader knows where
        the authoritative calibration lives."""
        text = _load(filename)
        assert "base prompt" in text
        assert "Multi-source synthesis" in text
