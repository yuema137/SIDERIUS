"""
Unit tests for the T4c task-agnostic ``_AGENT_CARD`` in
``nodes/ml_literature_review/ml_literature_review.py``.

T4c removes SQUID / denoising specifics from the lit-review agent's static
self-description (the ``AgentCard`` emitted on every run). The card now
describes what the *agent* does (surface literature, S2 corpus, etc.),
not what the operator's *task* is — the task framing reaches the LLM via
the ``{TASK_DESCRIPTION}`` placeholder in the lit-review search prompts
(already wired in Commit 6.5b-5 from ``inp.task_description``).

Covers:

* SQUID-specific limitation phrasing is gone (was: "Cannot judge SQUID-
  specific applicability"; now: "Cannot judge task-specific applicability").
* "denoising" hardcode is gone from `role` and `expertise_domain`.
* All AgentCard field-length constraints are still satisfied.
* `agent_name`, `trust_level`, and `trust_guidance` (non-task fields) are
  unchanged.
* The card is still serializable through Pydantic.

See docs/design/enable_global_task_config.md § Commit T4.
"""

from __future__ import annotations

from agent.schemas.literature_review import (
    ConfidenceBand,
    ConfidenceRubric,
    DynamicSearchConfig,
    LiteratureReviewInput,
    LiteratureReviewInterpretationEvidence,
)
from nodes.ml_literature_review.ml_literature_review import _AGENT_CARD, MLLiteratureReviewAgent


class TestAgentCardTaskAgnostic:
    def test_no_squid_hardcode(self):
        for field in ("role", "expertise_domain", "limitations"):
            value = getattr(_AGENT_CARD, field)
            assert "SQUID" not in value, (
                f"_AGENT_CARD.{field}={value!r} still contains 'SQUID' — T4c "
                f"was meant to remove all task-anchored hardcodes."
            )

    def test_no_denoising_hardcode_in_role_and_expertise(self):
        # `role` and `expertise_domain` are the two fields that pre-T4c
        # carried the "denoising" qualifier. `limitations` never mentioned
        # "denoising" — verified separately by inspection.
        assert "denoising" not in _AGENT_CARD.role
        assert "denoising" not in _AGENT_CARD.expertise_domain

    def test_role_describes_agent_not_task(self):
        # The new role frames what the agent DOES (surface literature)
        # without re-encoding the task domain.
        assert "Surface ML literature" in _AGENT_CARD.role

    def test_limitations_use_generic_task_language(self):
        # The pre-T4c text mentioned "SQUID-specific applicability"; the
        # T4c replacement substitutes "task-specific applicability" so the
        # caveat survives without anchoring on the operator's task.
        assert "task-specific applicability" in _AGENT_CARD.limitations


class TestAgentCardFieldConstraintsSatisfied:
    """AgentCard schema enforces ``max_length`` on role / expertise_domain /
    limitations. Regression guard: the T4c rewrites must stay within those
    caps so a future edit catches an overflow at test time, not at
    Pydantic-validation time during a real chain run."""

    def test_role_within_200_chars(self):
        assert len(_AGENT_CARD.role) <= 200

    def test_expertise_domain_within_300_chars(self):
        assert len(_AGENT_CARD.expertise_domain) <= 300

    def test_limitations_within_300_chars(self):
        assert len(_AGENT_CARD.limitations) <= 300

    def test_coverage_unchanged(self):
        # `coverage` was already task-agnostic before T4c — regression guard
        # to confirm it wasn't accidentally edited.
        assert _AGENT_CARD.coverage == "ArXiv/S2 results any year; local PDFs in reference_data/."


class TestAgentCardNonTaskFieldsUnchanged:
    def test_agent_name(self):
        assert _AGENT_CARD.agent_name == "ml_literature_review"

    def test_trust_level(self):
        # Lit-review carries inspirational findings → soft_prior. T4c is
        # not allowed to touch this; regression guard.
        assert _AGENT_CARD.trust_level == "soft_prior"

    def test_trust_guidance_non_empty(self):
        # Rendered by ConfidenceRubric().render_for_consumer() at module
        # import time. Must be non-empty after T4c.
        assert _AGENT_CARD.trust_guidance.strip() != ""


class TestAgentCardSerializes:
    def test_pydantic_round_trip(self):
        """Pydantic validation must accept the post-T4c card unchanged."""
        as_dict = _AGENT_CARD.model_dump()
        from agent.schemas.proposal import AgentCard

        rehydrated = AgentCard.model_validate(as_dict)
        assert rehydrated.role == _AGENT_CARD.role
        assert rehydrated.expertise_domain == _AGENT_CARD.expertise_domain
        assert rehydrated.limitations == _AGENT_CARD.limitations


def test_published_agent_card_uses_run_rubric(tmp_path):
    """Catch a default-rubric card mislabeling custom-confidence findings."""

    class EmptySynthesisBridge:
        def generate(self, *_args, **_kwargs):
            return {"findings": []}

    rubric = ConfidenceRubric(
        bands=[ConfidenceBand(lower=0.91, upper=1.0, criteria="replicated on declared task")],
        omit_below=0.91,
    )
    inp = LiteratureReviewInput(
        interpretation_evidence=LiteratureReviewInterpretationEvidence(
            take_home_message="Investigate image classification failures."
        ),
        dynamic_search=DynamicSearchConfig(enabled=False),
        storage={
            "backend": "local",
            "local": {"workspace": str(tmp_path), "run_name": "rubric-check"},
        },
        run_name="rubric-check",
        llm_provider="openai",
        llm_model_id="test-model",
        task_description="Classify microscopy images.",
        confidence_rubric=rubric,
    )
    agent = MLLiteratureReviewAgent(
        bridge_factory=lambda **_kwargs: EmptySynthesisBridge(),
        root_cache_dir=str(tmp_path / "cache"),
    )
    output = agent.run(inp)
    assert output.agent_card.trust_guidance == rubric.render_for_consumer()
    assert output.agent_card.trust_guidance != _AGENT_CARD.trust_guidance
