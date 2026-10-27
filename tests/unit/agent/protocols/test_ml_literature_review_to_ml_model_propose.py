"""
Unit tests for agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py

Tests cover:
  local_all_channels
    - Maps all four channels correctly with a fully populated output.
    - Passes through empty new_vocab_candidates and None mindset (v1 wired-empty).
    - Wraps the single agent_card in a one-element list (target kwarg is list).
    - Does NOT emit a reference_library / reference_library_md kwarg
      (regression guard against the cancelled 2d design).

  database_all_channels
    - Raises NotImplementedError (placeholder).
"""

import pytest
from pydantic import ValidationError

from agent.prompt_templates.proposal import render_literature_review_evidence
from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import AgentCard, ExpertContextItem, ProposalInput, VocabEntry
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import (
    NamedLiteratureReviewOutput,
    database_all_channels,
    local_all_channels,
    local_typed_evidence_many,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_agent_card(agent_name: str = "ml_literature_review") -> AgentCard:
    return AgentCard(
        agent_name=agent_name,
        role="Surveys published ML literature for techniques that may break "
        "current architectural bottlenecks.",
        expertise_domain="Time-series denoising and 1-D sequence modeling.",
        coverage="Papers indexed by Semantic Scholar through 2026.",
        limitations="Cannot validate transfer to SQUID denoising empirically.",
        trust_level="soft_prior",
        trust_guidance="Treat as promising priors — only experiment runs confirm applicability.",
    )


def _make_finding(source_ref: str, content_paper_id: str | None = None) -> ExpertContextItem:
    # content_paper_id is a soft contract enforced inside the lit-review node;
    # here we only need a valid ExpertContextItem for the protocol pass-through.
    return ExpertContextItem(
        source="ml_literature_review",
        kind="literature",
        content=(
            "Implication: a frequency-aware loss may widen WaveNet's effective "
            "spectral coverage. Mechanism: composite loss $\\min_\\theta "
            "\\delta L^f + (1-\\delta) L^t$ (FreLE). Adaptation: apply to the "
            "SQUID denoiser with clean-signal Fourier magnitudes as target."
        ),
        source_ref=source_ref,
        confidence=0.85,
    )


def _make_vocab_entry(name: str) -> VocabEntry:
    return VocabEntry(
        name=name,
        kind="feature",
        description="Composite frequency-domain + time-domain reconstruction loss.",
        tier="candidate",
        origin="ml_literature_review",
    )


def _make_output(
    findings: list[ExpertContextItem] | None = None,
    vocab: list[VocabEntry] | None = None,
    mindset: str | None = None,
    *,
    agent_name: str = "ml_literature_review",
    run_name: str = "test_run",
) -> LiteratureReviewOutput:
    return LiteratureReviewOutput(
        agent_card=_make_agent_card(agent_name),
        findings=findings if findings is not None else [],
        new_vocab_candidates=vocab if vocab is not None else [],
        suggested_mindset=mindset,
        retrieved_papers=[],
        search_rounds_used=0,
        run_name=run_name,
        started_at="2026-06-02T00:00:00Z",
        finished_at="2026-06-02T00:01:00Z",
    )


# ---------------------------------------------------------------------------
# local_all_channels
# ---------------------------------------------------------------------------


class TestLocalAllChannels:
    def test_fully_populated_output_maps_all_four_channels(self):
        """All four kwargs land in the returned dict, each from the right
        source field on the lit-review output."""
        finding = _make_finding(source_ref="arxiv:2510.25800")
        vocab = _make_vocab_entry(name="composite_frequency_loss")
        mindset = "Prioritise spectral-coverage adaptations of the existing backbone."
        output = _make_output(findings=[finding], vocab=[vocab], mindset=mindset)

        channels = local_all_channels(output)

        # Exactly the four kwargs that local_full_context exposes for external
        # agents — no more, no less.
        assert set(channels.keys()) == {
            "expert_context",
            "vocab_seed",
            "agent_cards",
            "mindset",
        }

        # expert_context = output.findings (identity-preserving list copy is fine;
        # the contents must be the same ExpertContextItem objects).
        assert channels["expert_context"] == [finding]

        # vocab_seed = output.new_vocab_candidates.
        assert channels["vocab_seed"] == [vocab]

        # agent_cards wrapped in a one-element list because the upstream
        # protocol's kwarg type is list[AgentCard] | None.
        assert channels["agent_cards"] == [output.agent_card]
        assert isinstance(channels["agent_cards"], list)
        assert len(channels["agent_cards"]) == 1

        # mindset passes through as-is.
        assert channels["mindset"] == mindset

    def test_v1_wired_empty_channels_pass_through_without_error(self):
        """v1 leaves new_vocab_candidates empty and suggested_mindset None.
        The protocol must surface those as empty list / None, not raise."""
        output = _make_output(findings=[_make_finding(source_ref="arxiv:2312.00752")])

        channels = local_all_channels(output)

        assert channels["vocab_seed"] == []
        assert channels["mindset"] is None
        # Findings still come through.
        assert len(channels["expert_context"]) == 1
        # Agent card still wrapped.
        assert channels["agent_cards"] == [output.agent_card]

    def test_empty_findings_still_yields_all_four_keys(self):
        """Even a no-finding run produces the four-kwarg shape — the workflow
        merge layer downstream still needs the keys present so it can
        concatenate safely across multiple external agents."""
        output = _make_output(findings=[])

        channels = local_all_channels(output)

        assert set(channels.keys()) == {
            "expert_context",
            "vocab_seed",
            "agent_cards",
            "mindset",
        }
        assert channels["expert_context"] == []

    def test_agent_card_wrapped_in_list(self):
        """The upstream local_full_context's kwarg is list[AgentCard] | None.
        Lit-review produces exactly one card per run; the protocol must
        wrap it in a one-element list, not pass the bare object."""
        output = _make_output()

        channels = local_all_channels(output)

        assert isinstance(channels["agent_cards"], list)
        assert len(channels["agent_cards"]) == 1
        assert channels["agent_cards"][0] is output.agent_card

    def test_no_reference_library_kwarg(self):
        """Regression guard: the cancelled 2d ``reference_library`` channel
        must not reappear. The returned dict must contain none of the
        names that earlier drafts proposed for that channel."""
        output = _make_output(
            findings=[_make_finding(source_ref="arxiv:2510.25800")],
            vocab=[_make_vocab_entry(name="composite_frequency_loss")],
            mindset="any mindset",
        )

        channels = local_all_channels(output)

        forbidden = {
            "reference_library",
            "reference_library_md",
            "reference_papers",
            "reference_entries",
        }
        assert not (forbidden & channels.keys()), (
            f"Forbidden cancelled-design kwargs leaked into protocol output: "
            f"{forbidden & channels.keys()}"
        )


# ---------------------------------------------------------------------------
# database_all_channels
# ---------------------------------------------------------------------------


class TestDatabaseAllChannels:
    def test_raises_not_implemented(self):
        output = _make_output()
        with pytest.raises(NotImplementedError, match="Postgres StorageConfig backend"):
            database_all_channels(output)


def _proposal_input() -> ProposalInput:
    return ProposalInput(interpretation_evidence=build_proposer_evidence({}))


def _named(contribution_id: str, agent_name: str, source_ref: str, claim: str):
    return NamedLiteratureReviewOutput(
        contribution_id=contribution_id,
        output=_make_output(
            findings=[
                ExpertContextItem(
                    source="ml_literature_review",
                    kind="literature",
                    content=claim,
                    source_ref=source_ref,
                    confidence=0.7,
                )
            ],
            agent_name=agent_name,
        ),
    )


def test_plural_adapter_preserves_three_named_conflicting_reviews_and_order():
    """Catches two-only handling, claim deduplication, attribution loss or reordering."""

    proposal = local_typed_evidence_many(
        [
            _named("review-a", "spectral-reviewer", "doi:10.0000/a", "Use a spectral loss."),
            _named("review-b", "time-domain-reviewer", "doi:10.0000/b", "Avoid spectral loss."),
            _named("review-c", "hybrid-reviewer", "doi:10.0000/a", "Use a spectral loss."),
        ],
        proposal_input=_proposal_input(),
    )

    collection = proposal.literature_review_evidence
    assert collection is not None
    serialized = collection.model_dump(mode="json")
    assert [item["contribution_id"] for item in serialized["reviews"]] == [
        "review-a",
        "review-b",
        "review-c",
    ]
    assert [item["evidence"]["agent_card"]["agent_name"] for item in serialized["reviews"]] == [
        "spectral-reviewer",
        "time-domain-reviewer",
        "hybrid-reviewer",
    ]
    assert [item["evidence"]["findings"][0]["content"] for item in serialized["reviews"]] == [
        "Use a spectral loss.",
        "Avoid spectral loss.",
        "Use a spectral loss.",
    ]
    rendered = render_literature_review_evidence(collection)
    positions = [
        rendered.index(value)
        for value in (
            "Review: review-a",
            "spectral-reviewer",
            "doi:10.0000/a",
            "Use a spectral loss.",
            "Review: review-b",
            "time-domain-reviewer",
            "doi:10.0000/b",
            "Avoid spectral loss.",
            "Review: review-c",
        )
    ]
    assert positions == sorted(positions)


def test_plural_adapter_refuses_duplicate_ids_and_mixed_run_identity():
    """Catches ambiguous contribution identity or reviews from different runs."""

    duplicate_ids = [
        _named("same", "reviewer-a", "doi:10.0000/a", "Claim A."),
        _named("same", "reviewer-b", "doi:10.0000/b", "Claim B."),
    ]
    with pytest.raises((ValueError, ValidationError), match="contribution IDs must be unique"):
        local_typed_evidence_many(duplicate_ids, proposal_input=_proposal_input())

    mixed_runs = [
        _named("review-a", "reviewer-a", "doi:10.0000/a", "Claim A."),
        NamedLiteratureReviewOutput(
            contribution_id="review-b",
            output=_make_output(run_name="other_run"),
        ),
    ]
    with pytest.raises(ValueError, match="share the same run_name"):
        local_typed_evidence_many(mixed_runs, proposal_input=_proposal_input())


def test_plural_adapter_refuses_existing_evidence_and_incomplete_output():
    """Catches silent replacement and a malformed producer object crossing the edge."""

    with pytest.raises(ValueError, match="at least one named literature review"):
        local_typed_evidence_many([], proposal_input=_proposal_input())

    seed = _proposal_input().model_copy(
        update={
            "literature_review_evidence": local_typed_evidence_many(
                [_named("existing", "reviewer", "doi:10.0000/x", "Existing claim.")],
                proposal_input=_proposal_input(),
            ).literature_review_evidence
        }
    )
    with pytest.raises(ValueError, match="already contains"):
        local_typed_evidence_many(
            [_named("new", "reviewer", "doi:10.0000/y", "New claim.")],
            proposal_input=seed,
        )

    with pytest.raises(ValidationError, match="run_name"):
        NamedLiteratureReviewOutput.model_validate(
            {"contribution_id": "incomplete", "output": {"agent_card": _make_agent_card()}}
        )


def test_plural_adapter_refuses_collection_over_shared_prompt_byte_limit():
    """Catches aggregate byte growth beyond the single-review prompt ceiling."""

    reviews = [
        NamedLiteratureReviewOutput(
            contribution_id=f"review-{index}",
            output=_make_output(
                findings=[
                    ExpertContextItem(
                        source="ml_literature_review",
                        kind="literature",
                        content=f"Claim {index}: " + "x" * 7_500,
                        source_ref=f"doi:10.0000/{index}",
                        confidence=0.7,
                    )
                    for _ in range(5)
                ],
                agent_name=f"reviewer-{index}",
            ),
        )
        for index in range(2)
    ]
    with pytest.raises(ValidationError, match="collection exceeds the 65536-byte"):
        local_typed_evidence_many(reviews, proposal_input=_proposal_input())
