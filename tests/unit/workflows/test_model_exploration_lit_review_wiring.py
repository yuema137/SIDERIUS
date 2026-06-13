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

    def test_warns_on_empty_task_description(self, tmp_path, capsys):
        # Fix 6 (Commit 6.5b-5) + Commit F: when the YAML config has no
        # task_description key (or an empty/whitespace-only value),
        # _build_lit_review_input prints a Warning so operators know the
        # lit-review LLM calls will receive no task-domain anchor (the
        # {TASK_DESCRIPTION} placeholder is filled with empty string).
        # All three "no usable value" inputs trigger the warning.

        # Case 1: key missing entirely.
        _build_lit_review_input(
            {},
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="t",
        )
        captured = capsys.readouterr()
        assert "Warning: lit_review config has no `task_description`" in captured.out
        assert "no task-domain anchor" in captured.out

        # Case 2: key present but empty string.
        _build_lit_review_input(
            {"task_description": ""},
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="t",
        )
        captured2 = capsys.readouterr()
        assert "Warning: lit_review config has no `task_description`" in captured2.out

        # Case 3: key present but whitespace-only — .strip() collapses it
        # to empty, same warning fires.
        _build_lit_review_input(
            {"task_description": "   \n\t  "},
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="t",
        )
        captured3 = capsys.readouterr()
        assert "Warning: lit_review config has no `task_description`" in captured3.out

    def test_no_warning_when_task_description_set(self, tmp_path, capsys):
        # Fix 6 (Commit 6.5b-5): when the YAML config carries a non-empty
        # task_description, NO warning is printed AND the value flows
        # through to LiteratureReviewInput.task_description for the node
        # to read.
        inp = _build_lit_review_input(
            {"task_description": "denoise audio recordings of whale song"},
            _interp(),
            llm_kwargs=_LLM_KWARGS,
            storage=_storage(tmp_path),
            run_name="t",
        )
        captured = capsys.readouterr()
        assert "Warning: lit_review config has no `task_description`" not in captured.out
        # And the value reaches the validated input.
        assert inp.task_description == "denoise audio recordings of whale song"
