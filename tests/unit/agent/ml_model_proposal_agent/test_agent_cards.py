# tests/unit/agent/ml_model_proposal_agent/test_agent_cards.py
"""
Unit tests for Phase F: AgentCard schema, render_agent_cards(), and
render_expert_context() improvements (dedup + confidence sorting).

Covers F.1 (AgentCard schema), F.2 (ProposalInput.agent_cards),
F.3 (VocabEntry.origin), F.4 (render_agent_cards), F.5 (render_expert_context
dedup and sorting), and F.8 (local_full_context mindset/agent_cards params).
"""

import pytest

from agent.prompt_templates.proposal import render_agent_cards, render_expert_context
from agent.schemas.proposal import AgentCard, ProposalInput, VocabEntry
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_card(**kwargs) -> AgentCard:
    defaults = dict(
        agent_name="ml_literature_review",
        role="Scans ML papers for architectural techniques.",
        expertise_domain="Signal processing, deep learning for time-series.",
        coverage="arXiv + OpenReview 2018–present.",
        limitations="Cannot assess physics feasibility.",
        trust_guidance="Treat as promising priors — only experiment runs confirm applicability.",
    )
    defaults.update(kwargs)
    return AgentCard(**defaults)


def _make_item(
    cite_id: str,
    kind: str = "empirical",
    source: str = "ml_lit",
    confidence=None,
    content: str = "finding",
) -> dict:
    return {
        "cite_id": cite_id,
        "kind": kind,
        "source": source,
        "confidence": confidence,
        "content": content,
    }


# ---------------------------------------------------------------------------
# F.1 — AgentCard schema
# ---------------------------------------------------------------------------


class TestAgentCard:
    def test_valid_card(self):
        card = _make_card()
        assert card.agent_name == "ml_literature_review"
        assert card.trust_guidance.startswith("Treat as")

    def test_role_max_length_enforced(self):
        with pytest.raises(Exception):
            _make_card(role="x" * 201)

    def test_expertise_domain_max_length_enforced(self):
        with pytest.raises(Exception):
            _make_card(expertise_domain="x" * 301)

    def test_trust_guidance_max_length_enforced(self):
        with pytest.raises(Exception):
            _make_card(trust_guidance="x" * 401)

    def test_missing_required_field_raises(self):
        with pytest.raises(Exception):
            AgentCard(
                role="r",
                expertise_domain="e",
                coverage="c",
                limitations="l",
                trust_guidance="t",
                # missing agent_name
            )


# ---------------------------------------------------------------------------
# F.2 — ProposalInput.agent_cards field
# ---------------------------------------------------------------------------


class TestProposalInputAgentCards:
    def test_defaults_to_empty_list(self):
        inp = ProposalInput(
            interpretation={"model_types": ["wavenet"]},
            storage={"backend": "local", "local": {"workspace": "/tmp", "run_name": "test"}},
        )
        assert inp.agent_cards == []

    def test_accepts_agent_cards(self):
        card = _make_card()
        inp = ProposalInput(
            interpretation={"model_types": ["wavenet"]},
            agent_cards=[card],
            storage={"backend": "local", "local": {"workspace": "/tmp", "run_name": "test"}},
        )
        assert len(inp.agent_cards) == 1
        assert inp.agent_cards[0].agent_name == "ml_literature_review"

    def test_accepts_agent_cards_as_dicts(self):
        inp = ProposalInput(
            interpretation={"model_types": ["wavenet"]},
            agent_cards=[_make_card().model_dump()],
            storage={"backend": "local", "local": {"workspace": "/tmp", "run_name": "test"}},
        )
        assert len(inp.agent_cards) == 1


# ---------------------------------------------------------------------------
# F.3 — VocabEntry.origin field
# ---------------------------------------------------------------------------


class TestVocabEntryOrigin:
    def test_origin_defaults_to_none(self):
        entry = VocabEntry(name="dilated_causal_conv", kind="feature", description="DCCs.")
        assert entry.origin is None

    def test_origin_set_for_external_agent(self):
        entry = VocabEntry(
            name="learnable_filterbank",
            kind="feature",
            description="Filterbank.",
            origin="ml_literature_review",
        )
        assert entry.origin == "ml_literature_review"
        assert entry.proposed_by_run is None  # external entries leave proposed_by_run unset


# ---------------------------------------------------------------------------
# F.4 — render_agent_cards()
# ---------------------------------------------------------------------------


class TestRenderAgentCards:
    def test_empty_list_returns_empty_string(self):
        assert render_agent_cards([]) == ""

    def test_single_card_contains_agent_name(self):
        result = render_agent_cards([_make_card()])
        assert "ml_literature_review" in result
        assert "## External Contributors" in result

    def test_single_card_contains_all_fields(self):
        result = render_agent_cards([_make_card()])
        assert "Role:" in result
        assert "Expertise Domain:" in result
        assert "Coverage:" in result
        assert "Limitations:" in result
        assert "Trust Guidance:" in result

    def test_trust_guidance_read_before_findings_marker(self):
        result = render_agent_cards([_make_card()])
        assert "Read each contributor" in result

    def test_two_cards_both_rendered(self):
        card1 = _make_card(agent_name="ml_literature_review")
        card2 = _make_card(
            agent_name="physics_literature_review", role="Extracts physical constraints."
        )
        result = render_agent_cards([card1, card2])
        assert "ml_literature_review" in result
        assert "physics_literature_review" in result

    def test_accepts_dicts(self):
        result = render_agent_cards([_make_card().model_dump()])
        assert "ml_literature_review" in result


# ---------------------------------------------------------------------------
# F.5 — render_expert_context(): dedup by cite_id + confidence sorting
# ---------------------------------------------------------------------------


class TestRenderExpertContextDedup:
    def test_duplicate_cite_id_deduplicated(self):
        items = [
            _make_item("arxiv_001", content="first version"),
            _make_item("arxiv_001", content="second version"),
        ]
        result = render_expert_context(items)
        # Only one entry should appear; last-wins means "second version"
        assert result.count("arxiv_001") == 1
        assert "second version" in result
        assert "first version" not in result

    def test_different_cite_ids_both_rendered(self):
        items = [
            _make_item("arxiv_001", content="finding A"),
            _make_item("arxiv_002", content="finding B"),
        ]
        result = render_expert_context(items)
        assert "arxiv_001" in result
        assert "arxiv_002" in result

    def test_empty_cite_id_dedup(self):
        """Items with empty cite_id should deduplicate to last one."""
        items = [
            _make_item("", content="first empty"),
            _make_item("", content="second empty"),
        ]
        result = render_expert_context(items)
        assert "second empty" in result
        assert "first empty" not in result


class TestRenderExpertContextConfidenceSorting:
    def test_higher_confidence_appears_first(self):
        items = [
            _make_item("low", confidence=0.3, content="low confidence finding"),
            _make_item("high", confidence=0.9, content="high confidence finding"),
        ]
        result = render_expert_context(items)
        pos_high = result.index("high confidence finding")
        pos_low = result.index("low confidence finding")
        assert pos_high < pos_low, "Higher confidence items should appear before lower ones"

    def test_none_confidence_sorts_last(self):
        items = [
            _make_item("none_conf", confidence=None, content="no confidence"),
            _make_item("has_conf", confidence=0.5, content="has confidence"),
        ]
        result = render_expert_context(items)
        pos_has = result.index("has confidence")
        pos_none = result.index("no confidence")
        assert pos_has < pos_none, "Items with confidence should appear before None items"

    def test_same_confidence_all_rendered(self):
        items = [
            _make_item("a", confidence=0.7, content="item A"),
            _make_item("b", confidence=0.7, content="item B"),
        ]
        result = render_expert_context(items)
        assert "item A" in result
        assert "item B" in result


# ---------------------------------------------------------------------------
# F.8 — local_full_context protocol: mindset and agent_cards params
# ---------------------------------------------------------------------------


class TestLocalFullContextPhaseF:
    def _make_interp_output(self):
        """Minimal InterpretationOutput for protocol tests."""
        from agent.schemas.interpretation import InterpretationOutput

        return InterpretationOutput(
            model_types=["wavenet"],
            model_descriptions={"wavenet": "Wavenet model."},
            total_experiments=5,
            best_denoising_score=5.576,
            worst_denoising_score=1.2,
            per_model_best={"wavenet": 5.576},
            per_model_worst={"wavenet": 1.2},
            key_findings=["wavenet excels at high-freq"],
            bottlenecks=["low-freq gap"],
            take_home_message="Address low-freq.",
            overall_best_score=5.576,
            runtime_vocab=[],
            prediction_outcomes_history={"confirmed": 0, "partial": 0, "refuted": 0},
            vocab_link_confirmations={},
        )

    def _make_storage(self):
        from agent.schemas.storage import LocalStorageConfig, StorageConfig

        return StorageConfig(
            backend="local", local=LocalStorageConfig(workspace="/tmp", run_name="test")
        )

    def test_mindset_passed_through(self):
        output = self._make_interp_output()
        storage = self._make_storage()
        inp = local_full_context(output, storage, mindset="Focus on low-freq recovery.")
        assert inp.mindset == "Focus on low-freq recovery."

    def test_mindset_none_by_default(self):
        output = self._make_interp_output()
        storage = self._make_storage()
        inp = local_full_context(output, storage)
        assert inp.mindset is None

    def test_agent_cards_passed_through(self):
        output = self._make_interp_output()
        storage = self._make_storage()
        card = _make_card()
        inp = local_full_context(output, storage, agent_cards=[card])
        assert len(inp.agent_cards) == 1
        assert inp.agent_cards[0].agent_name == "ml_literature_review"

    def test_agent_cards_none_defaults_to_empty(self):
        output = self._make_interp_output()
        storage = self._make_storage()
        inp = local_full_context(output, storage, agent_cards=None)
        assert inp.agent_cards == []
