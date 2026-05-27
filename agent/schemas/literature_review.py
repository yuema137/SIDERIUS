# agent/schemas/literature_review.py
"""
Input and output schemas for nodes/ml_literature_review.py.

Defines the typed surface for the lit-review node:
  - PaperSource          : a single root paper or search result reference
  - DynamicSearchConfig  : knobs for the per-iteration S2 search loop
  - PaperExtract         : LLM-compressed view of one paper (field set final;
                           see docs/paper_resolver_pilot.md)
  - RetrievedPaper       : audit-trail entry per paper the agent looked at
  - LiteratureReviewInput / LiteratureReviewOutput : node boundary schemas

LiteratureReviewOutput extends ExternalAgentOutput (the universal four-channel
contract). See docs/external_agents_for_proposer.md for the full design.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from agent.schemas.external_agents import ExternalAgentOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.storage import StorageConfig


class PaperSource(BaseModel):
    """A single paper identifier for the lit-review agent to resolve.

    Two categories of sources:
      - Identifier-based ('arxiv', 'doi', 'openreview') — resolved via the
        Semantic Scholar paper-lookup endpoint.
      - 'local' — resolved by reading a file checked into the repo.

    For 'local', paths must be repo-relative (no leading '/' or '..').
    Decided in Q4 of docs/commit_plan_ml_literature_review.md: per-machine
    override is not needed for v1; if it becomes needed, a .example.yaml
    split is added then.
    """

    source_type: Literal["arxiv", "doi", "openreview", "local"]
    identifier: str = Field(
        description="ArXiv ID / DOI / OpenReview URL / repo-relative path.",
    )
    verbosity: Literal[0, 1, 2] = Field(
        default=1,
        description="Resolution depth. "
        "0 = S2 metadata only (~200 tok). "
        "1 = LLM-compressed PaperExtract (~750 tok). "
        "2 = full text (~6k-10k tok). "
        "Root papers default to 1; dynamic-search results usually start at 0.",
    )

    @model_validator(mode="after")
    def _check_local_path(self) -> PaperSource:
        if self.source_type != "local":
            return self
        if self.identifier.startswith("/"):
            raise ValueError(
                f"source_type='local' requires a repo-relative path, "
                f"got absolute: {self.identifier!r}"
            )
        if ".." in self.identifier.split("/"):
            raise ValueError(
                f"source_type='local' path may not contain '..' segments: "
                f"{self.identifier!r}"
            )
        return self


class DynamicSearchConfig(BaseModel):
    """Knobs for the lit-review node's S2 keyword-search loop."""

    enabled: bool = Field(
        default=True,
        description="Master switch. When False, the agent resolves root papers "
        "only and skips the dynamic search loop entirely.",
    )
    max_rounds: int = Field(
        default=3,
        ge=1,
        description="Hard cap on dynamic search iterations. The loop terminates "
        "at this cap even if the LLM never emits {'done': true}.",
    )
    initial_verbosity: Literal[0, 1, 2] = Field(
        default=0,
        description="Verbosity used for the first round of search results. "
        "Subsequent rounds may escalate per-paper if escalation_allowed.",
    )
    escalation_allowed: bool = Field(
        default=True,
        description="Whether the LLM may request verbosity escalation on a "
        "specific paper mid-loop. When False, all search results stay at "
        "initial_verbosity.",
    )


class PaperExtract(BaseModel):
    """LLM-compressed extract of a single paper — the verbosity-1 view.

    Produced by the compression prompt in
    ``agent/prompt_templates/literature_review`` from a paper's full text.
    The field set is **final**, locked after the Commit 2 paper-resolver
    pilot (docs/paper_resolver_pilot.md): seven free-text string fields, no
    structured equation/diagram fields. Pilot finding F3 showed PDF-extracted
    equations are too degraded (``∑`` → ``(cid:88)``, flattened sub/super-
    scripts) to reconstruct as LaTeX, so mathematical methods are captured in
    prose inside ``key_results`` / ``architecture_details`` rather than a
    dedicated ``key_equations`` field.

    All fields default to empty string (not ``None``) so the compression LLM
    can emit a partial extract — Pydantic validation must not fail when a
    paper genuinely has no content for a field. The compression prompt
    instructs the LLM to use ``""`` (never ``null``) for anything it cannot
    ground in the source text.

    Per-field word budgets (enforced by the prompt, not by Pydantic):
      - ``core_idea``            ≤ 80 words
      - ``architecture_details`` ≤ 150 words
      - ``key_results``          ≤ 120 words
      - ``relevance_to_task``    ≤ 100 words
    """

    title: str = Field(default="", description="Paper title.")
    authors: str = Field(default="", description="Comma-separated author list.")
    year: str = Field(default="", description="Publication year as a string.")
    core_idea: str = Field(
        default="",
        description="One-paragraph summary of the central contribution (≤80 words).",
    )
    architecture_details: str = Field(
        default="",
        description="Architectural description: model type, layer/block "
        "structure, key design choices, and how the approach compares to "
        "alternatives the paper discusses (≤150 words). Math is described in "
        "prose, not LaTeX (pilot finding F3).",
    )
    key_results: str = Field(
        default="",
        description="Headline empirical results (≤120 words). Every performance "
        "ranking must carry the training regime it was measured under.",
    )
    relevance_to_task: str = Field(
        default="",
        description="Why this paper is relevant to the downstream task "
        "(≤100 words). Task-agnostic by name so the framework generalizes "
        "beyond SQUID; the compression prompt injects the concrete task "
        "description so the LLM knows what 'task' means in context.",
    )


class RetrievedPaper(BaseModel):
    """One paper retrieved by the lit-review agent — audit-trail unit.

    Captures everything the agent saw about the paper, regardless of which
    verbosity tier it ultimately landed at. verbosity_achieved may be lower
    than the requested verbosity if a fetch step failed (e.g. PDF 404).
    """

    paper_id: str = Field(
        description="Stable identifier prefixed by source — e.g. "
        "'arxiv:2406.04378', 'local:reference_data/papers/foo.pdf'. "
        "Used as cache key and dedup key across rounds.",
    )
    source: PaperSource
    s2_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Raw S2 paper object (title, authors, openAccessPdf, "
        "externalIds, abstract, ...). None for local sources or hard S2 "
        "failures.",
    )
    extract: PaperExtract | None = Field(
        default=None,
        description="LLM-compressed extract when verbosity_achieved >= 1. "
        "None when verbosity_achieved == 0 or compression failed.",
    )
    full_text: str | None = Field(
        default=None,
        description="Full extracted text when verbosity_achieved == 2. None otherwise.",
    )
    verbosity_achieved: Literal[0, 1, 2] = Field(
        description="Actual verbosity tier reached. May be less than the "
        "requested tier if PDF fetch or LLM compression failed.",
    )
    error: str | None = Field(
        default=None,
        description="Error message when the paper could not be fully resolved. "
        "None when everything succeeded.",
    )


class LiteratureReviewInput(BaseModel):
    """Input to the ml_literature_review node.

    experiment_history is the fresh InterpretationOutput from this iteration
    (decision Q1 — see docs/commit_plan_ml_literature_review.md). The
    lit-review prompt reads model_types, model_descriptions, key_findings,
    bottlenecks, take_home_message, runtime_vocab, new_discoveries — and
    ignores the rest. If a future use case needs cross-iteration architecture
    history that InterpretationOutput does not carry, the fix is a new
    chain_history field at the workflow layer, not a reshape of this schema.
    """

    experiment_history: InterpretationOutput = Field(
        description="Fresh InterpretationOutput from this iteration's "
        "result_interpretation_agent. Used to ground search queries in the "
        "current state of exploration.",
    )
    root_papers: list[PaperSource] = Field(
        default_factory=list,
        description="Foundational papers always resolved at agent start. "
        "Loaded from configs/lit_review_config.yaml. Per-paper extracts "
        "cached on disk under reference_data/root_papers_cache/.",
    )
    dynamic_search: DynamicSearchConfig = Field(
        default_factory=DynamicSearchConfig,
    )
    storage: StorageConfig = Field(
        description="Where the node writes ml_literature_review_{run_name}.json.",
    )
    run_name: str = Field(description="Run identifier shared with the workflow.")
    llm_provider: str = Field(description="LLMBridge provider name (e.g. 'openai').")
    llm_model_id: str = Field(description="LLMBridge model id (e.g. 'gpt-4o-mini').")


class LiteratureReviewOutput(ExternalAgentOutput):
    """Output of the ml_literature_review node.

    Inherits the four universal channels (agent_card, findings,
    new_vocab_candidates, suggested_mindset) from ExternalAgentOutput. Adds
    retrieved_papers as an audit trail plus run-level bookkeeping.

    For v1, new_vocab_candidates and suggested_mindset are deliberately left
    empty (see docs/external_agents_for_proposer.md §2). The fields exist on
    the base schema; this v1 just does not populate them.
    """

    retrieved_papers: list[RetrievedPaper] = Field(
        default_factory=list,
        description="Full list of papers the agent looked at this run — root "
        "papers plus dynamic-search results. Audit trail only; the workflow "
        "merge does not consume this field.",
    )
    search_rounds_used: int = Field(
        default=0,
        ge=0,
        description="Number of dynamic-search rounds executed. Bounded by "
        "DynamicSearchConfig.max_rounds.",
    )
    run_name: str
    started_at: str = Field(description="ISO-8601 UTC timestamp.")
    finished_at: str = Field(description="ISO-8601 UTC timestamp.")
