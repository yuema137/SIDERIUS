"""
Unit tests for Commit 6 lit-review workflow wiring helpers in
``workflows/model_exploration.py``:

  - ``merge_external_agent_outputs`` (the 4-channel aggregator)
  - ``should_run_literature_review`` (the resolved-enabled gate)
  - ``_build_lit_review_input`` (YAML dict + workflow state →
    ``LiteratureReviewInput``)

Workflow-level integration tests (``lit_review_config_path`` passthrough +
absence-tolerance + the wiring smoke) live in the dual-mode integration
extension (separate commit). This file covers ONLY the standalone helpers
and the YAML→LiteratureReviewInput transformation; running the full
workflow is out of scope.
"""

from __future__ import annotations

import yaml

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import AgentCard
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from workflows.model_exploration import (
    _build_lit_review_input,
    merge_external_agent_outputs,
    should_run_literature_review,
)
from workflows.task_config import get_task_description, load_task_config

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _interp() -> InterpretationOutput:
    return InterpretationOutput(
        take_home_message="stub",
        model_types=[],
        summaries=[],
        cumulative_information_gain=0.0,
        best_denoising_score=None,
        convergence_signal="no_history",
        iteration=1,
        model_descriptions={},
        total_experiments=0,
        key_findings=[],
        bottlenecks=[],
    )


def _agent_card() -> AgentCard:
    return AgentCard(
        agent_name="ml_literature_review",
        role="lit scout",
        expertise_domain="ML denoising",
        coverage="root + dynamic",
        limitations="abstract-only fallback",
        trust_guidance="soft",
        trust_level="soft_prior",
    )


def _lit_output(*, mindset: str | None = None) -> LiteratureReviewOutput:
    return LiteratureReviewOutput(
        agent_card=_agent_card(),
        findings=[],
        new_vocab_candidates=[],
        suggested_mindset=mindset,
        retrieved_papers=[],
        search_rounds_used=0,
        run_name="t",
        started_at="2026-06-12T00:00:00Z",
        finished_at="2026-06-12T00:00:00Z",
    )


_LLM_KWARGS = {
    "llm_provider": "deepseek",
    "llm_model_id": "deepseek-v4-pro",
    "search_llm_provider": "deepseek",
    "search_llm_model_id": "deepseek-v4-pro",
}


def _storage(tmp_path) -> StorageConfig:
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="t"),
    )


# ---------------------------------------------------------------------------
# merge_external_agent_outputs
# ---------------------------------------------------------------------------


class TestMergeExternalAgentOutputs:
    def test_empty_returns_4_channel_default(self):
        out = merge_external_agent_outputs([])
        assert out == {
            "expert_context": [],
            "vocab_seed": [],
            "agent_cards": [],
            "mindset": None,
        }

    def test_single_lit_review_returns_4_channel_dict(self):
        """N=1 + LiteratureReviewOutput delegates to the Commit-5 protocol;
        verify shape rather than identity (the protocol's exact behaviour is
        covered by its own tests in ``tests/unit/agent/protocols/``)."""
        out = merge_external_agent_outputs([_lit_output()])
        assert set(out.keys()) == {"expert_context", "vocab_seed", "agent_cards", "mindset"}
        assert len(out["agent_cards"]) == 1

    def test_n2_concat_and_last_non_none_mindset_wins(self):
        a = _lit_output(mindset=None)
        b = _lit_output(mindset="exploratory")
        out = merge_external_agent_outputs([a, b])
        assert len(out["agent_cards"]) == 2
        assert out["mindset"] == "exploratory"

    def test_n2_first_non_none_keeps_under_later_none(self):
        """The rule is 'last non-None wins'; a later None does NOT overwrite
        an earlier non-None mindset."""
        a = _lit_output(mindset="exploratory")
        b = _lit_output(mindset=None)
        out = merge_external_agent_outputs([a, b])
        assert out["mindset"] == "exploratory"


# ---------------------------------------------------------------------------
# should_run_literature_review
# ---------------------------------------------------------------------------


class TestShouldRunLiteratureReview:
    def test_respects_enabled_true(self):
        assert should_run_literature_review(_interp(), enabled=True) is True

    def test_respects_enabled_false(self):
        assert should_run_literature_review(_interp(), enabled=False) is False


# ---------------------------------------------------------------------------
# _build_lit_review_input
# ---------------------------------------------------------------------------


class TestBuildLitReviewInput:
    def test_canonical_yaml_round_trips_every_knob(self, tmp_path):
        """The repo's default YAML at configs/lit_review_config.yaml carries
        every operator-visible knob explicit; verify each round-trips into
        the resulting LiteratureReviewInput."""
        with open("configs/lit_review_config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        inp = _build_lit_review_input(
            cfg,
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="t",
        )
        assert inp.llm_provider == "deepseek"
        assert inp.search_llm_provider == "deepseek"
        assert len(inp.root_papers) == 1
        assert inp.root_papers[0].identifier == "2406.04378"
        assert inp.dynamic_search.max_rounds == 3
        assert inp.dynamic_search.initial_verbosity == 0
        assert inp.findings_verbosity == 1
        assert inp.synthesis_config.transfer_tolerance == "moderate"
        assert inp.confidence_rubric.omit_below == 0.40
        assert len(inp.confidence_rubric.bands) == 3

    def test_custom_root_papers_override(self, tmp_path):
        """A custom YAML with a different root_papers list is reflected in
        the resulting LiteratureReviewInput — confirms the YAML's
        root_papers block drives the input, not a hardcoded default."""
        cfg = {
            "root_papers": [
                {"source_type": "arxiv", "identifier": "1234.56789", "verbosity": 1},
                {"source_type": "doi", "identifier": "10.1234/test", "verbosity": 0},
            ],
        }
        inp = _build_lit_review_input(
            cfg,
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="t",
        )
        assert len(inp.root_papers) == 2
        assert inp.root_papers[0].identifier == "1234.56789"
        assert inp.root_papers[1].source_type == "doi"
        assert inp.root_papers[1].verbosity == 0

    def test_empty_yaml_falls_back_to_schema_defaults(self, tmp_path):
        """An empty config dict produces a valid LiteratureReviewInput with
        Pydantic ``default_factory`` filling each block — the
        ``_build_lit_review_input`` contract is "no key in YAML → schema
        default". Operators relying on this is discouraged (Design Decision
        3 — every knob explicit), but the path still has to work."""
        inp = _build_lit_review_input(
            {},
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="t",
        )
        assert inp.root_papers == []
        assert inp.dynamic_search.enabled is True  # schema default
        assert inp.findings_verbosity == 1

    def test_lit_review_yaml_is_no_longer_a_task_description_authority(self, tmp_path):
        """Step 04b: a stale ``task_description`` in the lit-review config
        must be IGNORED, not preferred and not merged.

        Defect this catches, and nothing else does: someone restores
        ``config.get("task_description")`` — as a read, an ``or`` fallback or
        a precedence rule — and the duplicate authority silently returns.
        The sentinel is what makes it catchable. Asserting the built input is
        merely non-empty, or equal to the shipped TIDMAD text, would pass
        just as happily while the YAML was still authoritative, because the
        two declarations were byte-identical before the collapse.
        """
        sentinel = "STALE-LOCAL-COPY: denoise audio recordings of whale song"
        inp = _build_lit_review_input(
            {"task_description": sentinel},
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="t",
        )
        assert sentinel not in inp.task_description
        assert inp.task_description == get_task_description(load_task_config())

    def test_task_description_needs_no_key_in_the_lit_review_yaml(self, tmp_path):
        """The key is not merely ignored — it is not required either.

        The pre-04b builder printed a warning and shipped ``""`` for a config
        with no ``task_description``. That state is now unreachable: the
        canonical loader rejects an empty description upstream, so a
        lit-review config without the key builds a fully populated input.
        """
        inp = _build_lit_review_input(
            {},
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="t",
        )
        assert inp.task_description == get_task_description(load_task_config())
        assert inp.task_description.strip() != ""
