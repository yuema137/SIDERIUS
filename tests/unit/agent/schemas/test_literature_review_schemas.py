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
    DynamicSearchConfig,
    LiteratureReviewInput,
    LiteratureReviewOutput,
    PaperExtract,
    PaperSource,
    RetrievedPaper,
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
        # The canonical seven-field set is final (locked after the Commit 2
        # pilot). This guards against re-adding key_equations/limitations
        # (the latter conflicts with AgentCard.limitations) or key_findings
        # (reserved for InterpretationOutput/CacheEntry).
        assert set(PaperExtract.model_fields) == {
            "title",
            "authors",
            "year",
            "core_idea",
            "architecture_details",
            "key_results",
            "relevance_to_task",
        }

    def test_all_defaults_empty_string(self):
        # Empty-string defaults are intentional — the compression LLM can
        # produce a partial extract without failing validation.
        e = PaperExtract()
        assert e.title == ""
        assert e.core_idea == ""
        assert e.relevance_to_task == ""

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
