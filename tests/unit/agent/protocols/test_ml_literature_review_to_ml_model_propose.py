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

from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import AgentCard, ExpertContextItem, VocabEntry
from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import (
    database_all_channels,
    local_all_channels,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_agent_card() -> AgentCard:
    return AgentCard(
        agent_name="ml_literature_review",
        role="Surveys published ML literature for techniques that may break "
        "current architectural bottlenecks.",
        expertise_domain="Time-series denoising and 1-D sequence modeling.",
        coverage="Papers indexed by Semantic Scholar through 2026.",
        limitations="Cannot validate transfer to SQUID denoising empirically.",
        trust_guidance="Treat as promising priors — only experiment runs confirm applicability.",
    )


def _make_finding(cite_id: str, content_paper_id: str | None = None) -> ExpertContextItem:
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
        cite_id=cite_id,
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
) -> LiteratureReviewOutput:
    return LiteratureReviewOutput(
        agent_card=_make_agent_card(),
        findings=findings if findings is not None else [],
        new_vocab_candidates=vocab if vocab is not None else [],
        suggested_mindset=mindset,
        retrieved_papers=[],
        search_rounds_used=0,
        run_name="test_run",
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
        finding = _make_finding(cite_id="arxiv:2510.25800")
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
        output = _make_output(findings=[_make_finding(cite_id="arxiv:2312.00752")])

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
            findings=[_make_finding(cite_id="arxiv:2510.25800")],
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
