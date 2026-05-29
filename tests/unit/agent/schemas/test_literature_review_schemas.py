"""
Unit tests for ``agent/schemas/literature_review.py`` and
``agent/schemas/external_agents.py`` — Pydantic validation only. No I/O, no
LLM, no S2 calls.

Covers Commit 1 of docs/commit_plan_ml_literature_review.md.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.external_agents import ExternalAgentOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import (
    ConfidenceBand,
    ConfidenceRubric,
    DynamicSearchConfig,
    LiteratureReviewInput,
    LiteratureReviewOutput,
    PaperExtract,
    PaperSource,
    RetrievedPaper,
    SynthesisConfig,
)
from agent.schemas.proposal import AgentCard, ExpertContextItem, VocabEntry
from agent.schemas.storage import LocalStorageConfig, StorageConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_card() -> AgentCard:
    return AgentCard(
        agent_name="ml_literature_review",
        role="Surface ML denoising literature relevant to the current iteration.",
        expertise_domain="ML denoising architectures; Semantic Scholar corpus.",
        coverage="ArXiv/S2 results any year; local PDFs in reference_data/.",
        limitations=(
            "Cannot run experiments; cannot judge SQUID-specific applicability "
            "without empirical confirmation."
        ),
        trust_guidance=(
            "Treat findings as promising priors; only experiment runs confirm applicability."
        ),
    )


def _make_interp_output() -> InterpretationOutput:
    return InterpretationOutput(
        model_types=["punet"],
        model_descriptions={"punet": "Probabilistic U-Net ..."},
        total_experiments=3,
        key_findings=["Wider receptive fields help on high-impact files."],
        bottlenecks=["Loss saturates after ~5 epochs."],
        take_home_message="Need both temporal depth and a richer loss.",
    )


def _make_storage() -> StorageConfig:
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="./ws", run_name="v1"),
    )


# ---------------------------------------------------------------------------
# PaperSource
# ---------------------------------------------------------------------------


class TestPaperSource:
    def test_arxiv_happy_path(self):
        s = PaperSource(source_type="arxiv", identifier="2406.04378", verbosity=1)
        assert s.source_type == "arxiv"
        assert s.identifier == "2406.04378"
        assert s.verbosity == 1

    def test_default_verbosity_is_one(self):
        s = PaperSource(source_type="arxiv", identifier="2406.04378")
        assert s.verbosity == 1

    def test_local_repo_relative_ok(self):
        s = PaperSource(
            source_type="local",
            identifier="reference_data/papers/tidmad.pdf",
        )
        assert s.identifier == "reference_data/papers/tidmad.pdf"

    def test_local_absolute_path_rejected(self):
        with pytest.raises(ValidationError):
            PaperSource(source_type="local", identifier="/home/foo/tidmad.pdf")

    def test_local_parent_traversal_rejected(self):
        with pytest.raises(ValidationError):
            PaperSource(
                source_type="local",
                identifier="reference_data/../secrets/tidmad.pdf",
            )

    def test_arxiv_absolute_string_not_rejected(self):
        # The local-path validator must only fire for source_type='local'.
        # Other source types are free-form identifiers (DOIs, URLs, ...).
        s = PaperSource(source_type="doi", identifier="10.1234/abc")
        assert s.identifier == "10.1234/abc"

    def test_invalid_source_type(self):
        with pytest.raises(ValidationError):
            PaperSource(source_type="biorxiv", identifier="abc")

    def test_invalid_verbosity_too_high(self):
        with pytest.raises(ValidationError):
            PaperSource(source_type="arxiv", identifier="x", verbosity=3)

    def test_invalid_verbosity_negative(self):
        with pytest.raises(ValidationError):
            PaperSource(source_type="arxiv", identifier="x", verbosity=-1)


# ---------------------------------------------------------------------------
# DynamicSearchConfig
# ---------------------------------------------------------------------------


class TestDynamicSearchConfig:
    def test_defaults(self):
        c = DynamicSearchConfig()
        assert c.enabled is True
        assert c.max_rounds == 3
        assert c.initial_verbosity == 0
        assert c.escalation_allowed is True
        assert c.results_per_query == 10
        assert c.max_escalations_per_round == 2

    def test_results_per_query_min(self):
        with pytest.raises(ValidationError):
            DynamicSearchConfig(results_per_query=0)

    def test_max_escalations_allows_zero(self):
        # 0 is valid — it disables escalation independently of escalation_allowed.
        assert DynamicSearchConfig(max_escalations_per_round=0).max_escalations_per_round == 0
        with pytest.raises(ValidationError):
            DynamicSearchConfig(max_escalations_per_round=-1)

    def test_max_rounds_zero_rejected(self):
        with pytest.raises(ValidationError):
            DynamicSearchConfig(max_rounds=0)

    def test_max_rounds_negative_rejected(self):
        with pytest.raises(ValidationError):
            DynamicSearchConfig(max_rounds=-1)


# ---------------------------------------------------------------------------
# PaperExtract — provisional schema
# ---------------------------------------------------------------------------


class TestPaperExtract:
    def test_field_set_is_locked(self):
        # Original seven-field set was locked after Commit 2's pilot (F3:
        # no LaTeX). Commit 2c amends the lock and adds three fields
        # (`key_equations_md`, `pseudocode_md`, `extraction_method`) once
        # three-tier extraction makes reliable formula content viable; see §5a
        # of docs/external_agents_for_proposer.md. The lock now guards the
        # ten-field set against re-adding `key_equations` (the OLD name, used
        # by F3), `limitations` (conflicts with AgentCard.limitations), or
        # `key_findings` (reserved for InterpretationOutput / CacheEntry).
        assert set(PaperExtract.model_fields) == {
            "title",
            "authors",
            "year",
            "core_idea",
            "architecture_details",
            "key_results",
            "relevance_to_task",
            "key_equations_md",
            "pseudocode_md",
            "extraction_method",
        }

    def test_all_defaults_empty_string(self):
        # Empty-string defaults are intentional — the compression LLM can
        # produce a partial extract without failing validation. The
        # `extraction_method` default ("abstract_only") is set node-side, not
        # by the LLM, but the schema default applies until the cascade wires it.
        e = PaperExtract()
        assert e.title == ""
        assert e.core_idea == ""
        assert e.relevance_to_task == ""
        assert e.key_equations_md == ""
        assert e.pseudocode_md == ""
        assert e.extraction_method == "abstract_only"

    def test_extraction_method_accepts_each_valid_tier(self):
        for tier in ("arxiv_source", "marker_pdf", "pdfplumber_llm", "abstract_only"):
            assert PaperExtract(extraction_method=tier).extraction_method == tier

    def test_extraction_method_unknown_value_rejected(self):
        # Literal validation — anything outside the four tiers is a validation
        # error (no quiet coerce; the field is a trust signal).
        with pytest.raises(ValidationError):
            PaperExtract(extraction_method="docling")  # type: ignore[arg-type]

    def test_populated(self):
        e = PaperExtract(
            title="Towards Robust Denoising",
            authors="A. Smith, B. Lee",
            year="2023",
            core_idea="Causal dilated CNN denoiser for time series.",
            architecture_details="Stacked dilated causal convolutions ...",
            key_results="SOTA on dataset X with 30% fewer params.",
            relevance_to_task="Receptive-field analysis transfers directly.",
        )
        assert e.title == "Towards Robust Denoising"
        assert e.year == "2023"


# ---------------------------------------------------------------------------
# RetrievedPaper
# ---------------------------------------------------------------------------


class TestRetrievedPaper:
    def test_verbosity_0_no_extract(self):
        p = RetrievedPaper(
            paper_id="arxiv:2406.04378",
            source=PaperSource(source_type="arxiv", identifier="2406.04378"),
            s2_metadata={"title": "TIDMAD"},
            extract=None,
            full_text=None,
            verbosity_achieved=0,
        )
        assert p.extract is None
        assert p.full_text is None
        assert p.verbosity_achieved == 0
        assert p.error is None

    def test_verbosity_2_full_text(self):
        p = RetrievedPaper(
            paper_id="arxiv:2406.04378",
            source=PaperSource(source_type="arxiv", identifier="2406.04378"),
            s2_metadata={"title": "TIDMAD"},
            extract=PaperExtract(title="TIDMAD"),
            full_text="Long extracted body ...",
            verbosity_achieved=2,
        )
        assert p.full_text == "Long extracted body ..."
        assert p.verbosity_achieved == 2

    def test_error_path(self):
        p = RetrievedPaper(
            paper_id="arxiv:bad",
            source=PaperSource(source_type="arxiv", identifier="bad"),
            verbosity_achieved=0,
            error="HTTP 404",
        )
        assert p.error == "HTTP 404"
        assert p.s2_metadata is None
        assert p.extract is None


# ---------------------------------------------------------------------------
# ExternalAgentOutput — universal base
# ---------------------------------------------------------------------------


class TestExternalAgentOutput:
    def test_minimal(self):
        out = ExternalAgentOutput(agent_card=_make_agent_card())
        assert out.findings == []
        assert out.new_vocab_candidates == []
        assert out.suggested_mindset is None

    def test_populated_findings(self):
        item = ExpertContextItem(
            source="ml_literature_review",
            kind="literature",
            content="Dilated CNNs improve receptive field without depth.",
            cite_id="lit_paper_001",
        )
        out = ExternalAgentOutput(agent_card=_make_agent_card(), findings=[item])
        assert len(out.findings) == 1
        assert out.findings[0].kind == "literature"

    def test_missing_agent_card_rejected(self):
        with pytest.raises(ValidationError):
            ExternalAgentOutput()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# LiteratureReviewInput
# ---------------------------------------------------------------------------


class TestSynthesisConfig:
    def test_default_transfer_tolerance_is_moderate(self):
        assert SynthesisConfig().transfer_tolerance == "moderate"

    def test_explicit_tolerances_accepted(self):
        for t in ("strict", "moderate", "liberal"):
            assert SynthesisConfig(transfer_tolerance=t).transfer_tolerance == t

    def test_unknown_transfer_tolerance_rejected(self):
        with pytest.raises(ValidationError):
            SynthesisConfig(transfer_tolerance="aggressive")  # type: ignore[arg-type]


class TestLiteratureReviewInput:
    def test_happy_path(self):
        i = LiteratureReviewInput(
            experiment_history=_make_interp_output(),
            root_papers=[
                PaperSource(source_type="arxiv", identifier="2406.04378"),
            ],
            storage=_make_storage(),
            run_name="lit_v1",
            llm_provider="openai",
            llm_model_id="gpt-4o-mini",
        )
        assert i.run_name == "lit_v1"
        assert i.dynamic_search.max_rounds == 3
        assert i.dynamic_search.enabled is True
        # Search-decision LLM override defaults to None (use the main bridge).
        assert i.search_llm_provider is None
        assert i.search_llm_model_id is None
        # confidence_rubric defaults to the standard ConfidenceRubric.
        assert isinstance(i.confidence_rubric, ConfidenceRubric)

    def test_search_llm_override(self):
        i = LiteratureReviewInput(
            experiment_history=_make_interp_output(),
            storage=_make_storage(),
            run_name="lit_v1",
            llm_provider="openai",
            llm_model_id="gpt-4o-mini",
            search_llm_provider="deepseek",
            search_llm_model_id="deepseek-v4-pro",
        )
        assert i.search_llm_provider == "deepseek"
        assert i.search_llm_model_id == "deepseek-v4-pro"

    def test_findings_verbosity_default_is_one(self):
        # Default = 1: structured three-part Markdown is the canonical
        # proposer-facing format paired with reference_library (§5b).
        i = LiteratureReviewInput(
            experiment_history=_make_interp_output(),
            storage=_make_storage(),
            run_name="lit_v1",
            llm_provider="openai",
            llm_model_id="gpt-4o-mini",
        )
        assert i.findings_verbosity == 1

    def test_findings_verbosity_zero_accepted(self):
        i = LiteratureReviewInput(
            experiment_history=_make_interp_output(),
            storage=_make_storage(),
            run_name="lit_v1",
            llm_provider="openai",
            llm_model_id="gpt-4o-mini",
            findings_verbosity=0,
        )
        assert i.findings_verbosity == 0

    def test_findings_verbosity_out_of_range_rejected(self):
        # Literal[0, 1] — anything else is a validation error (no quiet coerce).
        with pytest.raises(ValidationError):
            LiteratureReviewInput(
                experiment_history=_make_interp_output(),
                storage=_make_storage(),
                run_name="lit_v1",
                llm_provider="openai",
                llm_model_id="gpt-4o-mini",
                findings_verbosity=2,  # type: ignore[arg-type]
            )

    def test_synthesis_config_defaults_to_moderate(self):
        i = LiteratureReviewInput(
            experiment_history=_make_interp_output(),
            storage=_make_storage(),
            run_name="lit_v1",
            llm_provider="openai",
            llm_model_id="gpt-4o-mini",
        )
        assert isinstance(i.synthesis_config, SynthesisConfig)
        assert i.synthesis_config.transfer_tolerance == "moderate"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            LiteratureReviewInput(  # type: ignore[call-arg]
                experiment_history=_make_interp_output(),
                storage=_make_storage(),
                run_name="lit_v1",
                # Missing: llm_provider, llm_model_id
            )


# ---------------------------------------------------------------------------
# LiteratureReviewOutput
# ---------------------------------------------------------------------------


class TestLiteratureReviewOutput:
    def test_v1_wired_empty_channels(self):
        # v1 deliberately leaves new_vocab_candidates and suggested_mindset
        # empty. The schema must accept this configuration without error.
        out = LiteratureReviewOutput(
            agent_card=_make_agent_card(),
            findings=[],
            new_vocab_candidates=[],
            suggested_mindset=None,
            retrieved_papers=[],
            search_rounds_used=0,
            run_name="lit_v1",
            started_at="2026-05-26T17:00:00Z",
            finished_at="2026-05-26T17:01:00Z",
        )
        assert out.search_rounds_used == 0
        assert out.suggested_mindset is None
        assert out.new_vocab_candidates == []

    def test_full_population(self):
        item = ExpertContextItem(
            source="ml_literature_review",
            kind="literature",
            content="Paper X proposes Y.",
            cite_id="paper_x",
        )
        vocab = VocabEntry(
            name="dilated_causal_conv",
            kind="feature",
            description="A causal convolution with dilation gaps.",
            origin="ml_literature_review",
        )
        out = LiteratureReviewOutput(
            agent_card=_make_agent_card(),
            findings=[item],
            new_vocab_candidates=[vocab],
            suggested_mindset="explore",
            retrieved_papers=[
                RetrievedPaper(
                    paper_id="arxiv:2406.04378",
                    source=PaperSource(source_type="arxiv", identifier="2406.04378"),
                    verbosity_achieved=1,
                    extract=PaperExtract(title="TIDMAD"),
                ),
            ],
            search_rounds_used=2,
            run_name="lit_v1",
            started_at="2026-05-26T17:00:00Z",
            finished_at="2026-05-26T17:01:00Z",
        )
        assert out.suggested_mindset == "explore"
        assert out.new_vocab_candidates[0].origin == "ml_literature_review"
        assert len(out.retrieved_papers) == 1

    def test_negative_search_rounds_rejected(self):
        with pytest.raises(ValidationError):
            LiteratureReviewOutput(
                agent_card=_make_agent_card(),
                retrieved_papers=[],
                search_rounds_used=-1,
                run_name="lit_v1",
                started_at="2026-05-26T17:00:00Z",
                finished_at="2026-05-26T17:01:00Z",
            )


# ---------------------------------------------------------------------------
# ConfidenceRubric — unified confidence semantics (single source of truth)
# ---------------------------------------------------------------------------


class TestConfidenceRubric:
    def test_default_three_bands_and_omit(self):
        r = ConfidenceRubric()
        assert len(r.bands) == 3
        assert (r.bands[0].lower, r.bands[0].upper) == (0.80, 1.00)
        assert (r.bands[-1].lower, r.bands[-1].upper) == (0.40, 0.59)
        assert r.omit_below == 0.40

    def test_render_contains_bands_and_omit_threshold(self):
        text = ConfidenceRubric().render()
        assert "0.80-1.00" in text
        assert "0.40-0.59" in text
        assert "below 0.40: omit" in text
        assert "abstract-only evidence" in text

    def test_band_lower_gt_upper_rejected(self):
        with pytest.raises(ValidationError):
            ConfidenceBand(lower=0.9, upper=0.4, criteria="invalid")

    def test_custom_rubric_render(self):
        r = ConfidenceRubric(
            bands=[ConfidenceBand(lower=0.7, upper=1.0, criteria="replicated only")],
            omit_below=0.7,
        )
        text = r.render()
        assert "0.70-1.00" in text
        assert "replicated only" in text
        assert "below 0.70: omit" in text

    def test_default_abstract_only_ceiling(self):
        # The top band (0.80-1.00) requires a deep-read, so a verbosity-0 paper
        # caps at the top of the next band (0.79).
        assert ConfidenceRubric().abstract_only_ceiling == 0.79

    def test_abstract_only_ceiling_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            ConfidenceRubric(abstract_only_ceiling=1.5)

    def test_render_for_consumer_fits_trust_guidance_cap(self):
        # Must fit inside AgentCard.trust_guidance (max_length=800).
        assert len(ConfidenceRubric().render_for_consumer()) <= 800

    def test_render_for_consumer_has_band_definitions(self):
        text = ConfidenceRubric().render_for_consumer()
        assert "0.80" in text  # top band bound
        assert "0.40" in text  # bottom band bound
        assert "deep-read" in text  # band criteria carried over verbatim
        assert "abstract-only evidence" in text

    def test_render_for_consumer_has_consumer_leadin_not_producer(self):
        text = ConfidenceRubric().render_for_consumer()
        assert text.startswith("Confidence scores in findings from this agent follow this rubric")
        # The producer framing must NOT leak into the consumer legend.
        assert "Assign each finding's `confidence`" not in text
        assert "Assign each finding's confidence" not in text

    def test_render_for_consumer_omits_producer_only_omit_line(self):
        # The omit threshold is producer-only — a consumer never sees an omitted
        # finding, so render_for_consumer must not carry the omit instruction.
        text = ConfidenceRubric().render_for_consumer()
        assert "do NOT generate a finding" not in text
