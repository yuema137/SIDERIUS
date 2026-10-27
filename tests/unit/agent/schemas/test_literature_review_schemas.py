"""Local-source path safety, legacy input mapping, and confidence rendering."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import (
    ConfidenceBand,
    ConfidenceRubric,
    LiteratureReviewInput,
    PaperSource,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig


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


class TestPaperSource:
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


class TestConfidenceRubric:
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

    def test_render_for_searcher_has_all_default_bands(self):
        text = ConfidenceRubric().render_for_searcher()
        # Default 3 bands appear in the same "L.LL-U.UU" formatting as render()
        # / render_for_consumer() — single source of truth is self.bands.
        assert "0.80-1.00" in text
        assert "0.60-0.79" in text
        assert "0.40-0.59" in text
        # Band criteria carried over verbatim from _default_confidence_bands()
        assert "deep-read" in text
        assert "abstract-only evidence" in text

    def test_render_for_searcher_has_search_leadin_not_producer_or_consumer(self):
        text = ConfidenceRubric().render_for_searcher()
        # Search-decision framing: tell the searcher how the synthesis LLM
        # assigns confidence, so it can reason about verbosity → band →
        # escalation payoff. The leadin must explicitly name the synthesis LLM.
        assert text.startswith("Confidence bands (the synthesis LLM assigns one")
        # Producer framing ("Assign each finding's confidence") must NOT leak
        # in — the searcher is not assigning anything itself.
        assert "Assign each finding's `confidence`" not in text
        assert "Assign each finding's confidence" not in text
        # Consumer framing ("Confidence scores in findings from this agent
        # follow this rubric") also must NOT leak in — the searcher is not a
        # downstream consumer of findings.
        assert "Confidence scores in findings from this agent follow" not in text
        # The omit-below instruction is producer-only (the searcher cannot
        # omit anything); render_for_searcher must not carry it.
        assert "do NOT generate a finding" not in text

    def test_render_for_searcher_with_custom_rubric(self):
        # Custom bands must flow through render_for_searcher() — exercises the
        # "single source of truth = self.bands" guarantee for the third
        # renderer, matching test_custom_rubric_render for render().
        r = ConfidenceRubric(
            bands=[ConfidenceBand(lower=0.7, upper=1.0, criteria="replicated only")],
            omit_below=0.7,
        )
        text = r.render_for_searcher()
        assert "0.70-1.00" in text
        assert "replicated only" in text
        # Default-rubric bands must NOT appear when a custom rubric is supplied.
        assert "0.40-0.59" not in text
