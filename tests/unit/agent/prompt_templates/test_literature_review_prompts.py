"""
Unit tests for ``agent/prompt_templates/literature_review`` — the paper
compression prompt renderer. No I/O, no LLM, no network.

Covers Commit 3 of docs/commit_plan_ml_literature_review.md:
  - render_paper_extract_prompt determinism + content (snapshot-style asserts)
  - raw-text truncation at MAX_RAW_TEXT_CHARS
  - task-description injection (default + custom)
  - the "validation half" of the Commit 4 fallback: a valid dict from a mocked
    bridge.generate() parses into PaperExtract; a malformed payload raises.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agent.prompt_templates.literature_review import (
    MAX_RAW_TEXT_CHARS,
    SIDERIUS_TASK,
    render_paper_extract_prompt,
    render_search_decision_prompt,
    render_synthesis_prompt,
)
from agent.schemas.literature_review import (
    ConfidenceBand,
    ConfidenceRubric,
    PaperExtract,
    SynthesisConfig,
)

# The seven locked PaperExtract keys. Kept inline (not derived from the schema)
# so the test fails loudly if either the schema or the prompt drifts away from
# the agreed contract.
_EXPECTED_KEYS = (
    "title",
    "authors",
    "year",
    "core_idea",
    "architecture_details",
    "key_results",
    "relevance_to_task",
)


class TestRenderStructure:
    def test_returns_two_strings(self):
        system, user = render_paper_extract_prompt("some paper text")
        assert isinstance(system, str)
        assert isinstance(user, str)
        assert system and user

    def test_deterministic(self):
        a = render_paper_extract_prompt("identical input")
        b = render_paper_extract_prompt("identical input")
        assert a == b

    def test_system_prompt_lists_all_seven_keys(self):
        system, _ = render_paper_extract_prompt("text")
        for key in _EXPECTED_KEYS:
            assert key in system, f"system prompt missing key {key!r}"

    def test_system_prompt_has_anti_noise_and_math_rules(self):
        system, _ = render_paper_extract_prompt("text")
        # (cid:NN) glyph artifacts (F3) must be called out.
        assert "(cid:" in system
        # Math-in-prose / no-LaTeX instruction (F3).
        assert "LaTeX" in system
        # Despacing tolerance (run-together words).
        assert "missing spaces" in system

    def test_system_prompt_has_checkpoint_b_revision_instructions(self):
        # Checkpoint B revision: regime on every number + per-model mechanism
        # for benchmark papers.
        system, _ = render_paper_extract_prompt("text")
        assert "the training regime to EVERY performance number" in system
        assert "concrete mechanism" in system

    def test_system_prompt_has_generic_freq_split_rule(self):
        system, _ = render_paper_extract_prompt("text")
        # Generic, paper-conditional phrasing — keys off "if the paper reports".
        assert "frequency-split" in system
        assert "full-spectrum" in system
        # Must NOT name a specific paper (that would hallucinate for non-TIDMAD
        # papers compressed by the same prompt).
        assert "TIDMAD" not in system


class TestTaskInjection:
    def test_default_task_injected_and_placeholder_gone(self):
        system, _ = render_paper_extract_prompt("text")
        assert SIDERIUS_TASK in system
        assert "{TASK_DESCRIPTION}" not in system

    def test_custom_task_overrides_default(self):
        custom = "denoise audio recordings of whale song"
        system, _ = render_paper_extract_prompt("text", task_description=custom)
        assert custom in system
        assert SIDERIUS_TASK not in system
        assert "{TASK_DESCRIPTION}" not in system


class TestRawTextAndTruncation:
    def test_short_text_passed_verbatim(self):
        _, user = render_paper_extract_prompt("hello world body")
        assert "hello world body" in user
        assert "[...TRUNCATED...]" not in user

    def test_text_under_cap_not_truncated(self):
        body = "a" * (MAX_RAW_TEXT_CHARS - 10)
        _, user = render_paper_extract_prompt(body)
        assert "[...TRUNCATED...]" not in user
        assert body in user

    def test_text_over_cap_is_truncated(self):
        # 'Z' is absent from the user-prompt template + truncation marker, so
        # counting it isolates surviving body chars.
        body = "Z" * MAX_RAW_TEXT_CHARS + "UNIQUE_TAIL_SENTINEL"
        _, user = render_paper_extract_prompt(body)
        assert "[...TRUNCATED...]" in user
        # The portion past the cap must be dropped.
        assert "UNIQUE_TAIL_SENTINEL" not in user
        # Exactly MAX_RAW_TEXT_CHARS of the body survive (the marker is extra).
        assert user.count("Z") == MAX_RAW_TEXT_CHARS

    def test_text_at_cap_boundary_not_truncated(self):
        body = "b" * MAX_RAW_TEXT_CHARS
        _, user = render_paper_extract_prompt(body)
        assert "[...TRUNCATED...]" not in user


class TestPaperExtractValidationHalf:
    """The validation half of Commit 4's malformed-JSON fallback test.

    Commit 3 has no node yet, so we assert the contract directly: what
    ``bridge.generate()`` returns (a parsed dict) round-trips through
    ``PaperExtract.model_validate``; a structurally-invalid payload raises.
    A MagicMock stands in for the bridge so no API call happens.
    """

    def test_valid_generate_dict_parses(self):
        valid = {
            "title": "TIDMAD",
            "authors": "A. Author, B. Author",
            "year": "2024",
            "core_idea": "A time-series dataset and denoising benchmark.",
            "architecture_details": "WaveNet: dilated causal convs, full-spectrum.",
            "key_results": "WaveNet 4.99/5.16 under full-spectrum training.",
            "relevance_to_task": "Only full-spectrum baseline; directly comparable.",
        }
        bridge = MagicMock()
        bridge.generate.return_value = valid

        system, user = render_paper_extract_prompt("paper text")
        raw = bridge.generate(system, user)
        bridge.generate.assert_called_once_with(system, user)

        extract = PaperExtract.model_validate(raw)
        for key in _EXPECTED_KEYS:
            assert getattr(extract, key) == valid[key]

    def test_partial_dict_uses_empty_string_defaults(self):
        # The prompt tells the LLM to omit-or-empty unknown fields; a partial
        # dict must still validate, with "" defaults for the rest.
        extract = PaperExtract.model_validate({"title": "Only a title"})
        assert extract.title == "Only a title"
        assert extract.architecture_details == ""
        assert extract.relevance_to_task == ""

    def test_malformed_payload_raises(self):
        # A wrong-typed field (list where str is required) must raise rather
        # than silently coerce.
        bridge = MagicMock()
        bridge.generate.return_value = {"title": ["not", "a", "string"]}
        raw = bridge.generate(*render_paper_extract_prompt("text"))
        with pytest.raises(ValidationError):
            PaperExtract.model_validate(raw)

    def test_non_dict_payload_raises(self):
        with pytest.raises(ValidationError):
            PaperExtract.model_validate(["not", "a", "dict"])


class TestSynthesisPrompt:
    def _render(self):
        return render_synthesis_prompt(
            key_findings=["high-frequency band overfits"],
            bottlenecks=["loss saturates after ~5 epochs"],
            take_home_message="need more temporal depth",
            papers=[{"paper_id": "arxiv:1", "title": "P", "year": 2023, "summary": "s"}],
        )

    def test_returns_two_strings(self):
        system, user = self._render()
        assert isinstance(system, str) and isinstance(user, str)
        assert system and user

    def test_system_prompt_content_asserts(self):
        system, _ = self._render()
        # (a) bottleneck-grounding instruction
        assert "bottleneck" in system
        # (d) omission / transfer rule present (default _render = moderate tolerance)
        assert "no plausible mechanism transfer exists" in system
        # (e) cite_id-matching instruction
        assert "cite_id" in system and "paper_id" in system
        # task-description injection
        assert SIDERIUS_TASK in system
        assert "{TASK_DESCRIPTION}" not in system

    def test_user_prompt_fronts_bottlenecks(self):
        _, user = self._render()
        assert "PRIMARY" in user
        assert "loss saturates after ~5 epochs" in user  # bottleneck present
        assert "arxiv:1" in user  # paper id available for cite_id matching

    def test_separate_keys_instruction_locked(self):
        # Locks the Step-1 fix: gpt-4o-mini collapsed cite_id/confidence into the
        # content prose. The prompt must demand three separate keys AND show the
        # exact example shape. Guards against a future edit re-collapsing them.
        system, _ = self._render()
        assert "THREE SEPARATE keys" in system
        assert '"cite_id": "arxiv:2406.04378"' in system  # example: cite_id as its own key
        assert (
            '"confidence":' in system
        )  # example: confidence as its own key (value is rubric-driven)

    def test_full_spectrum_guard_locked(self):
        # Checkpoint C Fix B: the synthesis must NOT recommend frequency-split
        # techniques (it did on the first run). Lock the guard.
        system, _ = self._render()
        assert (
            "recommend frequency-split" in system
        )  # the "Do NOT ... recommend frequency-split" guard
        assert "CAUTIONARY" in system
        assert "full-spectrum" in system

    def test_confidence_rubric_injected(self):
        # Default rubric's bands + omit threshold are rendered into the prompt.
        system, _ = self._render()
        assert "{CONFIDENCE_RUBRIC}" not in system  # placeholder filled
        assert "0.80-1.00" in system
        assert "0.40-0.59" in system
        assert "below 0.40: omit" in system
        # band criteria text present
        assert "abstract-only evidence" in system

    def test_confidence_rubric_custom_override(self):
        custom = ConfidenceRubric(
            bands=[ConfidenceBand(lower=0.90, upper=1.00, criteria="ONLY-IF-REPLICATED-ON-SQUID")],
            omit_below=0.90,
        )
        system, _ = render_synthesis_prompt(
            key_findings=["x"],
            bottlenecks=["y"],
            take_home_message="z",
            papers=[{"paper_id": "arxiv:1", "title": "P", "year": 2023, "summary": "s"}],
            confidence_rubric=custom,
        )
        assert "ONLY-IF-REPLICATED-ON-SQUID" in system  # custom band wins
        assert "0.90-1.00" in system
        assert "below 0.90: omit" in system
        assert "abstract-only evidence" not in system  # default band gone

    def test_md_template_has_no_confidence_numbers(self):
        # Invariant 2 (Scoring & rubric design): the .md carries the placeholder,
        # never numeric bands. All band numbers must come from the rubric at
        # render time, not the template.
        from pathlib import Path

        import agent.prompt_templates.literature_review as mod

        raw = Path(mod.__file__).with_name("synthesis_system.md").read_text()
        assert "{CONFIDENCE_RUBRIC}" in raw
        for n in ("0.40", "0.59", "0.60", "0.79", "0.80", "1.00", "0.5", "0.65", "0.7"):
            assert n not in raw, f"confidence number {n!r} leaked into the .md template"

    def test_md_template_has_content_format_placeholder(self):
        # findings_verbosity content blocks live in the render module, not the
        # .md template; the .md carries only the placeholder so future verbosity
        # levels need no template rewrite.
        from pathlib import Path

        import agent.prompt_templates.literature_review as mod

        raw = Path(mod.__file__).with_name("synthesis_system.md").read_text()
        assert "{CONTENT_FORMAT_BLOCK}" in raw
        # The content-format example/rules must NOT be in the raw .md
        # (they belong in _SYNTHESIS_CONTENT_FORMAT_V1 / _V0 in __init__.py).
        assert "**Implication:**" not in raw
        assert "every item MUST" not in raw

    def test_findings_verbosity_default_is_v1(self):
        # Default findings_verbosity=1 → V1 three-part block injected; the
        # placeholder is filled and the structured headings appear in the
        # rendered system prompt.
        system, _ = self._render()  # no findings_verbosity arg → default
        assert "{CONTENT_FORMAT_BLOCK}" not in system
        assert "**Implication:**" in system
        assert "**Mechanism:**" in system
        assert "**Adaptation:**" in system
        # word budgets (the load-bearing constraint at v=1)
        assert "≤ 40 words" in system  # Implication
        assert "≤ 80 words" in system  # Mechanism (raised from 60 per user)
        assert "≤ 50 words" in system  # Adaptation

    def test_findings_verbosity_0_uses_v0_format(self):
        # Explicit findings_verbosity=0 → backward-compat single-paragraph block;
        # V1 structural headings must NOT appear, and V0's existing rules must.
        system, _ = render_synthesis_prompt(
            key_findings=["x"],
            bottlenecks=["y"],
            take_home_message="z",
            papers=[{"paper_id": "arxiv:1", "title": "P", "year": 2023, "summary": "s"}],
            findings_verbosity=0,
        )
        assert "{CONTENT_FORMAT_BLOCK}" not in system
        assert "**Implication:**" not in system
        assert "**Mechanism:**" not in system
        assert "**Adaptation:**" not in system
        # V0 rules present (the existing single-paragraph format)
        assert "every item MUST" in system
        assert "End with a one-line rationale" in system

    def test_omission_rule_strict_block(self):
        system, _ = render_synthesis_prompt(
            key_findings=["x"],
            bottlenecks=["y"],
            take_home_message="z",
            papers=[{"paper_id": "arxiv:1", "title": "P", "year": 2023, "summary": "s"}],
            synthesis_config=SynthesisConfig(transfer_tolerance="strict"),
        )
        assert "{OMISSION_RULE}" not in system  # placeholder filled
        assert "Cross-domain papers with fundamental domain differences" in system
        # moderate/liberal phrasings must NOT leak in
        assert "more valuable than no finding at all" not in system

    def test_omission_rule_moderate_block(self):
        system, _ = render_synthesis_prompt(
            key_findings=["x"],
            bottlenecks=["y"],
            take_home_message="z",
            papers=[{"paper_id": "arxiv:1", "title": "P", "year": 2023, "summary": "s"}],
            synthesis_config=SynthesisConfig(transfer_tolerance="moderate"),
        )
        assert "{OMISSION_RULE}" not in system
        assert "A finding with a clear caveat is more valuable than no finding" in system
        assert "no plausible mechanism transfer exists whatsoever" in system

    def test_omission_rule_liberal_block(self):
        system, _ = render_synthesis_prompt(
            key_findings=["x"],
            bottlenecks=["y"],
            take_home_message="z",
            papers=[{"paper_id": "arxiv:1", "title": "P", "year": 2023, "summary": "s"}],
            synthesis_config=SynthesisConfig(transfer_tolerance="liberal"),
        )
        assert "{OMISSION_RULE}" not in system
        assert "potentially relevant technique" in system
        assert "Let the proposer decide relevance" in system

    def test_omission_rule_default_is_moderate(self):
        # No synthesis_config arg → SynthesisConfig() → moderate block.
        system, _ = self._render()
        assert "A finding with a clear caveat is more valuable than no finding" in system

    def test_md_template_has_omission_placeholder(self):
        from pathlib import Path

        import agent.prompt_templates.literature_review as mod

        raw = Path(mod.__file__).with_name("synthesis_system.md").read_text()
        assert "{OMISSION_RULE}" in raw
        # the tolerance-specific phrasings live in __init__.py, not the .md
        assert "more valuable than no finding" not in raw
        assert "Cross-domain papers with fundamental domain differences" not in raw


class TestSearchDecisionPrompt:
    def _render(self):
        return render_search_decision_prompt(
            key_findings=["file 17 is the top Impact_Score lever"],
            bottlenecks=["under-recovery of the late-file cluster (file 17)"],
            take_home_message="target file 17 recovery",
            explored_models=["spectral_gated_pyramid", "wavenet"],
            papers_seen=[],
            escalation_allowed=True,
        )

    def test_jargon_translation_section_locked(self):
        # Checkpoint C Fix A: queries were polluted with internal jargon
        # ("file 17", "Impact_Score") → 0 S2 hits. Lock the translation guidance.
        system, _ = self._render()
        assert "Translating the experiment state into a query" in system
        assert "NEVER put an internal identifier" in system
        # representative internal terms the section must teach translating away
        assert "Impact_Score" in system
        assert "trial_portion" in system
        # tightened rule: the literal word "file" is banned from queries
        assert 'the literal word "file"' in system

    def test_full_spectrum_preference_present(self):
        system, _ = self._render()
        assert "full-spectrum" in system.lower() or "FULL-SPECTRUM" in system
        assert "frequency-split" in system

    def test_query_form_keyword_guideline_present(self):
        # Fix C (a): keyword-phrase guideline + bad/good example pair.
        system, _ = self._render()
        assert "Query form" in system
        assert "short keyword phrase" in system
        assert "adaptive loss weighting for hard samples" in system  # BAD example (line-1 portion)
        assert "hard sample reweighting loss" in system  # GOOD example

    def test_mandatory_escalation_assessment_block_present(self):
        # Diagnostic finding (2026-05-27): the search-decision LLM never evaluated
        # retrieved papers for escalation — it defaulted to SEARCH every round and
        # its reasoning referenced no retrieved paper. This block forces a
        # pre-decision escalate-vs-search assessment. Pure addition: Fix A/B/C
        # (jargon translation, freq-split guard, keyword-phrase form) are untouched.
        system, _ = self._render()
        assert "Mandatory assessment before deciding" in system
        assert "scan the papers already" in system
        assert "choose ESCALATE for that paper" in system
        assert "defaulting to SEARCH" in system

    def test_no_prior_results_no_feedback_block(self):
        _, user = self._render()  # papers_seen=[] and prior_search_results defaults None
        assert "Queries already tried this run" not in user

    def test_zero_hit_prior_injects_annotation_and_nudge(self):
        # Fix C (b): a 0-hit prior query gets the fixed "too specific" annotation
        # AND triggers the broaden nudge; a hit query shows only its count.
        _, user = render_search_decision_prompt(
            key_findings=["k"],
            bottlenecks=["b"],
            take_home_message="t",
            explored_models=["wavenet"],
            papers_seen=[],
            escalation_allowed=True,
            prior_search_results=[("narrow query alpha", 0), ("spectral gating denoising", 7)],
        )
        assert "Queries already tried this run" in user
        assert '"narrow query alpha" → 0 hits' in user
        assert "(too specific — try broader terms for the same concept)" in user
        assert '"spectral gating denoising" → 7 hits' in user
        assert "do NOT repeat a 0-hit query" in user

    def test_all_hits_prior_no_nudge(self):
        _, user = render_search_decision_prompt(
            key_findings=["k"],
            bottlenecks=["b"],
            take_home_message="t",
            explored_models=["wavenet"],
            papers_seen=[],
            escalation_allowed=True,
            prior_search_results=[("spectral gating denoising", 5)],
        )
        assert '"spectral gating denoising" → 5 hits' in user
        assert "too specific" not in user  # no 0-hit annotation
        assert "do NOT repeat a 0-hit query" not in user  # no broaden nudge
