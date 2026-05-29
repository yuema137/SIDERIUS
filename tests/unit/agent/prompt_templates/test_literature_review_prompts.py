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
    render_review_report,
    render_search_decision_prompt,
    render_synthesis_prompt,
)
from agent.schemas.literature_review import (
    ConfidenceBand,
    ConfidenceRubric,
    LiteratureReviewOutput,
    PaperExtract,
    PaperSource,
    RetrievedPaper,
    SynthesisConfig,
)
from agent.schemas.proposal import AgentCard, ExpertContextItem

# The nine LLM-emitted PaperExtract keys (the 10th field, `extraction_method`,
# is set node-side, not by the LLM, so it is NOT in this contract). Kept inline
# (not derived from the schema) so the test fails loudly if either the schema or
# the prompt drifts away from the agreed contract.
_EXPECTED_KEYS = (
    "title",
    "authors",
    "year",
    "core_idea",
    "architecture_details",
    "key_results",
    "relevance_to_task",
    # Commit 2c additions (F3 conditionally superseded; see §5a):
    "key_equations_md",
    "pseudocode_md",
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

    def test_system_prompt_lists_all_nine_keys(self):
        # 7 original keys + 2 new (`key_equations_md`, `pseudocode_md`); the 10th
        # `PaperExtract` field (`extraction_method`) is set node-side, NOT
        # emitted by the LLM, so it does NOT appear as a contract key. (The word
        # "extraction_method" can legitimately appear elsewhere in the prompt —
        # e.g., the pdfplumber block's downstream-consumer note — so we don't
        # assert its absence; the .md contract intro pins "EXACTLY these nine".)
        system, _ = render_paper_extract_prompt("text")
        for key in _EXPECTED_KEYS:
            assert key in system, f"system prompt missing key {key!r}"
        assert "nine string keys and no others" in system

    def test_system_prompt_has_anti_noise_and_math_rules(self):
        # Default extraction_method='pdfplumber_llm' selects the degraded-PDF
        # instruction block, which contains these rules verbatim. The other
        # tier (arxiv_source) has a different block — see
        # TestExtractionInstructions below.
        system, _ = render_paper_extract_prompt("text")
        # (cid:NN) glyph artifacts (F3) must be called out.
        assert "(cid:" in system
        # Math-in-prose / approximate-LaTeX instruction (F3, Tier-2 path).
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


class TestExtractionInstructions:
    """`render_paper_extract_prompt(extraction_method=...)` injects one of three
    per-tier instruction blocks at the `{EXTRACTION_INSTRUCTIONS}` placeholder.
    Each block's distinctive guidance must appear (and the wrong-tier guidance
    must NOT appear)."""

    def test_arxiv_source_block_injected(self):
        system, _ = render_paper_extract_prompt("clean tex", extraction_method="arxiv_source")
        assert "{EXTRACTION_INSTRUCTIONS}" not in system  # placeholder filled
        assert "clean LaTeX / Markdown extracted from the arXiv source" in system
        assert "DIRECTLY into `key_equations_md`" in system
        # arxiv source is clean — pdfplumber's (cid:NN) artifact rule must NOT leak.
        assert "(cid:" not in system

    def test_pdfplumber_block_injected_and_is_default(self):
        # Explicit and default both select the degraded-PDF block.
        for kwargs in ({}, {"extraction_method": "pdfplumber_llm"}):
            system, _ = render_paper_extract_prompt("degraded text", **kwargs)
            assert "(cid:" in system  # F3 degraded-PDF artifact rule
            assert "approximate LaTeX form" in system  # Tier-2 best-effort note
            assert 'extraction_method="pdfplumber_llm"' in system  # downstream trust signal

    def test_abstract_only_block_injected(self):
        system, _ = render_paper_extract_prompt("abstract", extraction_method="abstract_only")
        assert "only the paper's abstract" in system.lower()
        # Abstracts have no equations / pseudocode — block tells the LLM to leave both empty.
        assert 'Leave `key_equations_md` and `pseudocode_md` as `""`' in system
        # No degraded-PDF / arxiv-source content should leak.
        assert "(cid:" not in system
        assert "arXiv source" not in system

    def test_md_template_has_extraction_placeholder(self):
        # Per-tier guidance lives in __init__.py blocks; the .md template
        # carries only the placeholder so a future extraction tier just needs a
        # new block, not a template rewrite.
        from pathlib import Path

        import agent.prompt_templates.literature_review as mod

        raw = Path(mod.__file__).with_name("paper_extract_system.md").read_text()
        assert "{EXTRACTION_INSTRUCTIONS}" in raw
        # tier-specific fingerprints must NOT be in the raw .md
        assert "arXiv source" not in raw
        assert "(cid:" not in raw


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
            # Commit 2c fields the LLM emits (extraction_method is set node-side).
            "key_equations_md": "$$s = -\\log\\|x - \\hat x\\|^2$$",
            "pseudocode_md": "```python\nfor x in batch:\n    pass\n```",
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


# ---------------------------------------------------------------------------
# render_review_report — pure Markdown view of a LiteratureReviewOutput.
# Pure function: same input → same output. No LLM, no I/O.
# ---------------------------------------------------------------------------


def _agent_card() -> AgentCard:
    """Minimal AgentCard fixture — required by LiteratureReviewOutput's parent."""
    return AgentCard(
        agent_name="ml_literature_review",
        role="Surveys recent literature and emits findings.",
        expertise_domain="ML denoising / signal modelling literature.",
        coverage="arXiv + S2 search, last 24 months.",
        limitations="LLM-mediated extraction; equation fidelity tier-dependent.",
        trust_guidance="Treat as promising priors; cross-check with experiments.",
    )


def _arxiv_extract(
    title: str = "Mamba",
    authors: str = "Albert Gu, Tri Dao",
    year: str = "2023",
    *,
    key_equations_md: str = "$$h_t = \\bar{A} h_{t-1} + \\bar{B} x_t$$",
    pseudocode_md: str = "```python\nfor t in range(L):\n    h = A @ h + B @ x[t]\n```",
) -> PaperExtract:
    """Tier-1 PaperExtract — clean LaTeX source, all fields populated."""
    return PaperExtract(
        title=title,
        authors=authors,
        year=year,
        core_idea="Selective SSM with hardware-aware scan.",
        architecture_details="Mamba block: linear projections, 1-D conv, selective SSM.",
        key_results="Matches Pythia-2.8B perplexity at 1.4B params.",
        relevance_to_task="Linear-time scan for long 1-D sequences — directly relevant.",
        key_equations_md=key_equations_md,
        pseudocode_md=pseudocode_md,
        extraction_method="arxiv_source",
    )


def _pdfplumber_extract() -> PaperExtract:
    """Tier-2 PaperExtract — degraded PDF, equations marked best-effort."""
    return PaperExtract(
        title="SNRAware",
        authors="A. Researcher, B. Coauthor",
        year="2025",
        core_idea="SNR-aware loss reweighting for MRI denoising.",
        architecture_details="U-Net denoiser; SNR-gated patch reweighting.",
        key_results="1.4 dB PSNR over baseline U-Net on fastMRI knee.",
        relevance_to_task="Loss-layer engineering is domain-portable to 1-D signals.",
        key_equations_md="$$\\mathcal{L}_{SNR} = \\sum_i w(SNR_i) \\| \\hat{y}_i - y_i \\|^2$$",
        pseudocode_md="```python\nfor patch in batch:\n    snr = estimate_snr(patch)\n```",
        extraction_method="pdfplumber_llm",
    )


def _retrieved_paper(
    paper_id: str = "arxiv:2312.00752",
    source_type: str = "arxiv",
    identifier: str = "2312.00752",
    *,
    extract: PaperExtract | None = None,
    s2_metadata: dict | None = None,
    verbosity_achieved: int = 1,
    error: str | None = None,
) -> RetrievedPaper:
    if s2_metadata is None and extract is not None:
        # Mirror what the resolver actually returns: S2 also carries the title
        # so the title-lookup fallback chain is exercised.
        s2_metadata = {
            "title": extract.title,
            "year": int(extract.year) if extract.year.isdigit() else None,
            "paperId": "abc123",
        }
    return RetrievedPaper(
        paper_id=paper_id,
        source=PaperSource(source_type=source_type, identifier=identifier, verbosity=1),
        s2_metadata=s2_metadata,
        extract=extract,
        verbosity_achieved=verbosity_achieved,  # type: ignore[arg-type]
        error=error,
    )


def _output(
    *,
    retrieved_papers: list[RetrievedPaper] | None = None,
    findings: list[ExpertContextItem] | None = None,
    run_name: str = "test_run",
    search_rounds_used: int = 0,
) -> LiteratureReviewOutput:
    return LiteratureReviewOutput(
        agent_card=_agent_card(),
        findings=findings or [],
        retrieved_papers=retrieved_papers or [],
        search_rounds_used=search_rounds_used,
        run_name=run_name,
        started_at="2026-05-29T14:21:18+00:00",
        finished_at="2026-05-29T14:32:01+00:00",
    )


def _finding(
    cite_id: str = "arxiv:2312.00752",
    confidence: float | None = 0.85,
    content: str = (
        "**Implication.** Replace FCNet attention with a Mamba block.\n\n"
        "**Mechanism.** Selective SSM with linear scan.\n\n"
        "**Adaptation.** Drop in Mamba-1.4B; train full-spectrum.\n\n"
        "*(rationale: deep-read; on-domain; mechanism implementable.)*"
    ),
) -> ExpertContextItem:
    return ExpertContextItem(
        source="ml_literature_review",
        kind="literature",
        content=content,
        cite_id=cite_id,
        confidence=confidence,
    )


class TestRenderReviewReportSummary:
    """Top-of-report metadata banner — run name, timestamps, counts, tier
    breakdown, rubric footnote."""

    def test_run_name_and_timestamps_in_banner(self):
        report = render_review_report(_output(run_name="squid_v1"))
        assert "# Literature Review Report — squid_v1" in report
        assert "`squid_v1`" in report
        assert "`2026-05-29T14:21:18+00:00`" in report  # started_at
        assert "`2026-05-29T14:32:01+00:00`" in report  # finished_at

    def test_paper_and_finding_counts_in_banner(self):
        papers = [_retrieved_paper(extract=_arxiv_extract())]
        findings = [_finding()]
        report = render_review_report(
            _output(retrieved_papers=papers, findings=findings, search_rounds_used=2)
        )
        assert "Papers retrieved" in report
        assert "Findings" in report
        assert "Search rounds used" in report
        assert "| 1 (" in report  # one paper
        # findings count appears in its row
        lines = [line for line in report.split("\n") if "Findings" in line]
        assert any("1" in line for line in lines)

    def test_tier_breakdown_counts_by_extraction_method(self):
        papers = [
            _retrieved_paper(paper_id="arxiv:1", identifier="1", extract=_arxiv_extract()),
            _retrieved_paper(
                paper_id="arxiv:2",
                identifier="2",
                extract=_arxiv_extract(title="P2"),
            ),
            _retrieved_paper(paper_id="arxiv:3", identifier="3", extract=_pdfplumber_extract()),
        ]
        report = render_review_report(_output(retrieved_papers=papers))
        assert "2 × arxiv_source" in report
        assert "1 × pdfplumber_llm" in report
        assert "abstract_only" not in report  # no abstract_only paper this run

    def test_unresolved_papers_counted_separately(self):
        # A paper that failed resolution (no extract) shows up as "unresolved".
        papers = [
            _retrieved_paper(extract=_arxiv_extract()),
            _retrieved_paper(
                paper_id="arxiv:bad",
                identifier="bad",
                extract=None,
                verbosity_achieved=0,
                error="HTTP 404",
            ),
        ]
        report = render_review_report(_output(retrieved_papers=papers))
        assert "1 × arxiv_source" in report
        assert "1 × unresolved" in report

    def test_rubric_footnote_present(self):
        report = render_review_report(_output())
        assert "default" in report.lower() and "ConfidenceRubric" in report
        # Numeric thresholds appear so the reader can map labels to numbers.
        assert "≥0.80" in report and "≥0.60" in report and "≥0.40" in report


class TestRenderReviewReportTier1Paper:
    """A Tier-1 arxiv_source paper renders with the ✅ badge, no Tier-2
    callout, no per-section caveats, and all populated prose sections."""

    def test_arxiv_source_badge_with_check_mark(self):
        report = render_review_report(
            _output(retrieved_papers=[_retrieved_paper(extract=_arxiv_extract())])
        )
        assert "✅ `arxiv_source` (Tier 1 — clean LaTeX from arXiv source)" in report

    def test_no_tier2_trust_callout_for_arxiv_paper(self):
        report = render_review_report(
            _output(retrieved_papers=[_retrieved_paper(extract=_arxiv_extract())])
        )
        assert "Trust note — Tier 2 source" not in report
        assert "reconstructed from degraded PDF" not in report

    def test_paper_heading_carries_paper_id_and_title(self):
        report = render_review_report(
            _output(retrieved_papers=[_retrieved_paper(extract=_arxiv_extract(title="Mamba"))])
        )
        assert "### 1. `arxiv:2312.00752` — Mamba" in report

    def test_all_prose_sections_present_when_populated(self):
        report = render_review_report(
            _output(retrieved_papers=[_retrieved_paper(extract=_arxiv_extract())])
        )
        assert "**Core idea.**" in report
        assert "**Architecture details.**" in report
        assert "**Key results.**" in report
        assert "**Relevance to task.**" in report
        assert "**Key equations.**" in report
        assert "**Pseudocode.**" in report

    def test_empty_prose_field_is_skipped_not_left_as_hollow_heading(self):
        extract = _arxiv_extract()
        extract.core_idea = ""  # field genuinely empty
        report = render_review_report(_output(retrieved_papers=[_retrieved_paper(extract=extract)]))
        assert "**Core idea.**" not in report  # heading skipped entirely
        # Other sections still present.
        assert "**Architecture details.**" in report

    def test_empty_equations_and_pseudocode_skipped(self):
        extract = _arxiv_extract(key_equations_md="", pseudocode_md="")
        report = render_review_report(_output(retrieved_papers=[_retrieved_paper(extract=extract)]))
        assert "**Key equations.**" not in report
        assert "**Pseudocode.**" not in report


class TestRenderReviewReportTier2Paper:
    """A pdfplumber_llm paper renders with the ⚠️ badge AND the Tier-2 trust
    callout AND the per-section best-effort caveats — three trust channels
    working together per the design."""

    def test_pdfplumber_badge_with_warning_emoji(self):
        report = render_review_report(
            _output(retrieved_papers=[_retrieved_paper(extract=_pdfplumber_extract())])
        )
        assert "⚠️ `pdfplumber_llm` (Tier 2 — degraded PDF text, LLM-reconstructed)" in report

    def test_tier2_trust_callout_blockquote_present(self):
        report = render_review_report(
            _output(retrieved_papers=[_retrieved_paper(extract=_pdfplumber_extract())])
        )
        assert "> ⚠️ **Trust note — Tier 2 source.**" in report
        # The callout names which fields are reliable vs. best-effort.
        assert "best-effort" in report
        assert "verified against the source PDF" in report

    def test_per_section_caveat_on_equations_and_pseudocode(self):
        report = render_review_report(
            _output(retrieved_papers=[_retrieved_paper(extract=_pdfplumber_extract())])
        )
        # Caveat appears on BOTH the equations heading and the pseudocode heading.
        assert (
            "**Key equations.** *(reconstructed from degraded PDF — verify against source)*"
            in report
        )
        assert (
            "**Pseudocode.** *(reconstructed from degraded PDF — verify against source)*" in report
        )

    def test_tier2_paper_grepable_by_method_literal(self):
        # Per the design: the literal string ``pdfplumber_llm`` appears in the
        # extraction badge so reviewers can grep multi-paper reports. The
        # banner also includes it (no backticks) in the tier breakdown.
        report = render_review_report(
            _output(
                retrieved_papers=[
                    _retrieved_paper(extract=_arxiv_extract()),
                    _retrieved_paper(
                        paper_id="arxiv:tier2",
                        identifier="tier2",
                        extract=_pdfplumber_extract(),
                    ),
                ]
            )
        )
        # banner ("1 × pdfplumber_llm") + badge ("`pdfplumber_llm`") = at least 2.
        assert report.count("pdfplumber_llm") >= 2


class TestRenderReviewReportEdgeCases:
    """Unresolved papers, abstract-only fallback, no-papers run."""

    def test_unresolved_paper_renders_error_blockquote(self):
        paper = _retrieved_paper(
            paper_id="arxiv:bad",
            identifier="bad",
            extract=None,
            verbosity_achieved=0,
            error="HTTP 404 from arxiv.org",
            s2_metadata={"title": "Missing", "paperId": "x"},
        )
        report = render_review_report(_output(retrieved_papers=[paper]))
        assert "### 1. `arxiv:bad` — Missing" in report
        assert "> ❌ **Resolver error:** HTTP 404 from arxiv.org" in report
        # No prose / equation sections for an unresolved paper.
        assert "**Core idea.**" not in report

    def test_paper_without_s2_metadata_or_extract_renders_untitled(self):
        paper = _retrieved_paper(
            paper_id="local:foo.pdf",
            source_type="local",
            identifier="foo.pdf",
            extract=None,
            s2_metadata=None,
            verbosity_achieved=0,
        )
        report = render_review_report(_output(retrieved_papers=[paper]))
        assert "(untitled)" in report
        assert "(no extract)" in report  # badge fallback

    def test_no_retrieved_papers_section_shows_explicit_none(self):
        report = render_review_report(_output(retrieved_papers=[]))
        assert "## Retrieved papers" in report
        assert "*(none — the agent retrieved zero papers this run.)*" in report


class TestRenderReviewReportFindingsAbsent:
    """Phase-1-only runs (no synthesis) get an honest 'none' callout that
    surfaces the synthesis-didn't-run ambiguity."""

    def test_empty_findings_renders_phase1_callout(self):
        report = render_review_report(_output(findings=[]))
        assert "## Findings" in report
        assert "Phase-1-only extraction run" in report
        assert "synthesis was not invoked" in report
        # Reader is told what to cross-check.
        assert "search_rounds_used" in report

    def test_empty_findings_does_not_show_count_heading(self):
        report = render_review_report(_output(findings=[]))
        # The plural-count heading is reserved for the populated case.
        assert "## Findings (0 total" not in report


class TestRenderReviewReportFindingsPresent:
    """Findings render with cite_id + matched paper title in the heading,
    NEVER a title heuristically extracted from content (per the locked design
    decision)."""

    def test_finding_heading_uses_matched_paper_title(self):
        papers = [_retrieved_paper(extract=_arxiv_extract(title="Mamba"))]
        findings = [_finding(cite_id="arxiv:2312.00752")]
        report = render_review_report(_output(retrieved_papers=papers, findings=findings))
        # paper_id in code-quotes + dash + the matched title.
        assert "### 1. `arxiv:2312.00752` — Mamba" in report

    def test_finding_heading_falls_back_to_cite_id_only_when_no_match(self):
        # Retrieved papers DO have titles, but none of them match the finding's
        # cite_id — proves the renderer does not greedily inject the wrong
        # title or fall back to a heuristic.
        papers = [_retrieved_paper(extract=_arxiv_extract(title="Mamba"))]
        findings = [_finding(cite_id="arxiv:9999.99999")]
        report = render_review_report(_output(retrieved_papers=papers, findings=findings))
        # The cite_id appears in a finding heading.
        assert "### 1. `arxiv:9999.99999`" in report
        # The unmatched paper's title must NOT leak into the finding heading.
        # We extract the finding heading line and assert "Mamba" isn't on it.
        finding_heading = next(
            line
            for line in report.split("\n")
            if line.startswith("### 1.") and "arxiv:9999.99999" in line
        )
        assert "Mamba" not in finding_heading

    def test_finding_content_rendered_verbatim_below_heading(self):
        # The three-part content format is preserved exactly — the renderer
        # does NOT try to parse, summarise, or re-label it.
        findings = [_finding()]
        report = render_review_report(_output(findings=findings))
        assert "**Implication.** Replace FCNet attention" in report
        assert "**Mechanism.** Selective SSM" in report
        assert "**Adaptation.** Drop in Mamba-1.4B" in report
        assert "*(rationale: deep-read" in report

    def test_finding_metadata_line_shows_cite_source_kind(self):
        findings = [_finding(cite_id="arxiv:2312.00752")]
        report = render_review_report(_output(findings=findings))
        assert "**Cite:** `arxiv:2312.00752`" in report
        assert "**Source agent:** `ml_literature_review`" in report
        assert "**Kind:** `literature`" in report

    def test_confidence_band_label_mapping(self):
        findings = [
            _finding(cite_id="p:high", confidence=0.85),
            _finding(cite_id="p:mod", confidence=0.65),
            _finding(cite_id="p:low", confidence=0.45),
        ]
        report = render_review_report(_output(findings=findings))
        # Numeric + band label both appear.
        assert "confidence `0.85` (high)" in report
        assert "confidence `0.65` (moderate)" in report
        assert "confidence `0.45` (low)" in report

    def test_findings_sorted_high_to_low_by_confidence(self):
        # Deliberately fed in low-to-high order.
        findings = [
            _finding(cite_id="p:low", confidence=0.45),
            _finding(cite_id="p:high", confidence=0.85),
            _finding(cite_id="p:mod", confidence=0.65),
        ]
        report = render_review_report(_output(findings=findings))
        idx_high = report.index("`p:high`")
        idx_mod = report.index("`p:mod`")
        idx_low = report.index("`p:low`")
        assert idx_high < idx_mod < idx_low

    def test_none_confidence_sorts_last_and_omits_band(self):
        findings = [
            _finding(cite_id="p:has_conf", confidence=0.65),
            _finding(cite_id="p:no_conf", confidence=None),
        ]
        report = render_review_report(_output(findings=findings))
        # The None-confidence finding shows no confidence suffix at all.
        no_conf_block_start = report.index("`p:no_conf`")
        no_conf_block_end = report.index("---", no_conf_block_start)
        no_conf_block = report[no_conf_block_start:no_conf_block_end]
        assert "confidence" not in no_conf_block
        # ...and appears after the scored one.
        assert report.index("`p:has_conf`") < report.index("`p:no_conf`")


class TestRenderReviewReportDeterminism:
    """Pure function: same input → byte-identical output, no time-of-day, no
    randomness, no dict ordering ambiguity."""

    def test_byte_identical_across_repeated_calls(self):
        papers = [
            _retrieved_paper(paper_id="arxiv:a", identifier="a", extract=_arxiv_extract()),
            _retrieved_paper(paper_id="arxiv:b", identifier="b", extract=_pdfplumber_extract()),
        ]
        findings = [
            _finding(cite_id="arxiv:a", confidence=0.65),
            _finding(cite_id="arxiv:b", confidence=0.85),
        ]
        out = _output(retrieved_papers=papers, findings=findings, search_rounds_used=2)
        r1 = render_review_report(out)
        r2 = render_review_report(out)
        assert r1 == r2

    def test_tied_confidence_breaks_deterministically_by_cite_id(self):
        # Two findings with the same confidence — secondary sort key is
        # cite_id ascending — ensures stable diffs.
        findings = [
            _finding(cite_id="z:later", confidence=0.65),
            _finding(cite_id="a:earlier", confidence=0.65),
        ]
        report = render_review_report(_output(findings=findings))
        assert report.index("`a:earlier`") < report.index("`z:later`")


class TestRenderReviewReportIsAvailableAsPublicAPI:
    """The renderer is the documented public entrypoint — it must be
    importable from the package (not just the submodule) so callers don't
    couple to file layout."""

    def test_render_review_report_importable_from_package(self):
        from agent.prompt_templates.literature_review import render_review_report as r

        assert callable(r)
