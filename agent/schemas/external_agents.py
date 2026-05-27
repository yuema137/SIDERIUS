# agent/schemas/external_agents.py
"""
Universal output contract for every external agent.

External agents (literature review, physics, narrative, data analysis, ...) all
produce an ExternalAgentOutput. The workflow merges N such outputs into one
contribution to ProposalInput via the four channels declared below.

This module lives apart from any concrete external agent's schema so that
adding a second agent never requires touching the first agent's file — see
docs/external_agents_architecture.md §6 ("insertable, not refactorable").
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent.schemas.proposal import AgentCard, ExpertContextItem, VocabEntry


class ExternalAgentOutput(BaseModel):
    """Four-channel contribution from one external agent into ProposalInput.

    Channels rank from soft (always-on) to strong (rarely populated):

      - findings              : soft suggestion, populated every run
      - new_vocab_candidates  : mid-influence; gated by promotion maturity
      - suggested_mindset     : strong directional prior; only with strong
                                cross-source evidence

    See docs/external_agents_architecture.md §3 for the channel hierarchy.
    Concrete subclasses (e.g. LiteratureReviewOutput) may add agent-specific
    audit-trail fields but must not change the four base channels.
    """

    agent_card: AgentCard = Field(
        description="Static self-description of the producing agent. Tells the "
        "proposal LLM how to weight this agent's findings relative to "
        "experiment results and other sources.",
    )
    findings: list[ExpertContextItem] = Field(
        default_factory=list,
        description="Soft contextual signal — facts, citations, recommendations. "
        "The always-on channel: every external agent populates this whenever "
        "it has anything to say.",
    )
    new_vocab_candidates: list[VocabEntry] = Field(
        default_factory=list,
        description="Vocabulary entries the agent proposes for the runtime vocab. "
        "Externally-sourced entries must set VocabEntry.origin to the agent_name "
        "and never count toward seen_in_runs (see VocabEntry docstring).",
    )
    suggested_mindset: str | None = Field(
        default=None,
        description="Optional directional prior overriding the workflow's "
        "explore/exploit default. Populate only with high-confidence "
        "evidence (e.g. a physical constraint), not a literature hint.",
    )
