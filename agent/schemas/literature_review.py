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
                f"source_type='local' path may not contain '..' segments: {self.identifier!r}"
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
    results_per_query: int = Field(
        default=10,
        ge=1,
        description="Number of S2 hits requested per search query. Default 10: "
        "S2 relevance drops sharply past position ~10, and ~10 abstracts "
        "(~2k tokens) is a manageable decision surface for the loop LLM. Larger "
        "values mostly add low-relevance noise and prompt cost.",
    )
    max_escalations_per_round: int = Field(
        default=2,
        ge=0,
        description="Cap on verbosity escalations (deep-reads) the LLM may "
        "request within a single search round. Each escalation costs one PDF "
        "fetch + one LLM compression call, so an uncapped loop (e.g. 5 rounds "
        "with many escalations each) can balloon to 25+ extra calls. Escalation "
        "requests beyond this cap in the same round are logged and dropped. "
        "0 disables escalation entirely (independent of escalation_allowed).",
    )


class PaperExtract(BaseModel):
    """LLM-compressed extract of a single paper — the verbosity-1 view.

    Produced by the compression prompt in
    ``agent/prompt_templates/literature_review`` from a paper's full text.

    **Field-set history.** The original seven-field set was locked after
    Commit 2's paper-resolver pilot (docs/paper_resolver_pilot.md) per
    pilot finding F3: PDF-extracted equations are too degraded (``∑`` →
    ``(cid:88)``, flattened sub/superscripts) to reconstruct as LaTeX, so
    mathematical methods were captured in prose inside ``key_results`` /
    ``architecture_details``. Commit 2c **amends** that lock and adds three
    fields — ``key_equations_md``, ``pseudocode_md``, ``extraction_method``
    — once two-tier extraction (§5a of docs/external_agents_for_proposer.md)
    made reliable formula content viable. F3's "no LaTeX" rationale now
    applies only to the Tier-2 (pdfplumber) path; Tier-1 inputs carry
    equations and pseudocode verbatim.

    All string fields default to empty string (not ``None``) so the compression
    LLM can emit a partial extract — Pydantic validation must not fail when a
    paper genuinely has no content for a field. The compression prompt
    instructs the LLM to use ``""`` (never ``null``) for anything it cannot
    ground in the source text.

    Per-field word budgets (enforced by the prompt, not by Pydantic):
      - ``core_idea``            ≤ 80 words
      - ``architecture_details`` ≤ 150 words
      - ``key_results``          ≤ 120 words
      - ``relevance_to_task``    ≤ 100 words

    ``key_equations_md`` and ``pseudocode_md`` are code/LaTeX content; their
    length is paper-determined (no fixed word budget). ``extraction_method``
    is set by the resolver skill / node based on which extraction tier
    succeeded — it is NOT emitted by the LLM; the schema default
    ``"abstract_only"`` applies when no full-text path runs.
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
        "alternatives the paper discusses (≤150 words). Math goes in "
        "``key_equations_md`` for Tier-1 sources; prose-only for Tier-2 "
        "(per F3's conditional supersession in §5a).",
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
    key_equations_md: str = Field(
        default="",
        description="Core equations as Markdown LaTeX — ``$$...$$`` for display "
        "math, ``$...$`` for inline. Reliable for Tier-1 inputs (clean source); "
        "approximate / best-effort for Tier-2 (``pdfplumber_llm``); empty for "
        "``abstract_only``. Trust signal lives on ``extraction_method``.",
    )
    pseudocode_md: str = Field(
        default="",
        description="Algorithm / pseudocode blocks as fenced Markdown (e.g. "
        "`````python ... `````). Same tier "
        "reliability semantics as ``key_equations_md``.",
    )
    extraction_method: Literal["arxiv_source", "pdfplumber_llm", "abstract_only"] = Field(
        default="abstract_only",
        description="First-class trust signal indicating which extraction tier "
        "produced the source text. ``arxiv_source`` (Tier-1, ground-truth LaTeX) "
        "> ``pdfplumber_llm`` (Tier-2, degraded text + LLM reconstruction) > "
        "``abstract_only`` (no full text). Set by the resolver skill / node — "
        "NOT emitted by the LLM. The earlier three-tier design had a Tier-2 "
        "``marker_pdf`` slot (GPU-based PDF→Markdown); it was cancelled before "
        "2c-c — see ``docs/external_agents_for_proposer.md`` §5a.",
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


class ConfidenceBand(BaseModel):
    """One band of a ConfidenceRubric: a numeric range + the evidence criteria
    that map to it."""

    lower: float = Field(ge=0.0, le=1.0, description="Inclusive lower bound of the band.")
    upper: float = Field(ge=0.0, le=1.0, description="Inclusive upper bound of the band.")
    criteria: str = Field(
        description="Evidence conditions a finding must meet to receive a confidence in this band.",
    )

    @model_validator(mode="after")
    def _check_order(self) -> ConfidenceBand:
        if self.lower > self.upper:
            raise ValueError(f"band lower ({self.lower}) must be <= upper ({self.upper})")
        return self


def _default_confidence_bands() -> list[ConfidenceBand]:
    return [
        ConfidenceBand(
            lower=0.80,
            upper=1.00,
            criteria="deep-read (verbosity >= 1 extract) AND on-domain (1D / "
            "broadband signal denoising) AND directly addresses a current bottleneck",
        ),
        ConfidenceBand(
            lower=0.60,
            upper=0.79,
            criteria="deep-read with a clear mechanism transfer, OR an on-domain "
            "abstract with a strong specific signal",
        ),
        ConfidenceBand(
            lower=0.40,
            upper=0.59,
            criteria="abstract-only evidence, OR cross-domain with a plausible "
            "(unvalidated) transfer rationale",
        ),
    ]


class ConfidenceRubric(BaseModel):
    """Unified definition of what a finding's ``confidence`` (0.0-1.0) means.

    Single source of truth for confidence semantics — see the "Scoring and
    rubric design invariants" section of docs/external_agents_architecture.md.
    Defined once here; injected into the synthesis prompt via the
    ``{CONFIDENCE_RUBRIC}`` placeholder (never duplicated as numbers in prompt
    text); configurable per run via ``LiteratureReviewInput.confidence_rubric``.
    """

    bands: list[ConfidenceBand] = Field(
        default_factory=_default_confidence_bands,
        description="Confidence bands from strongest to weakest evidence. A "
        "finding's confidence must fall in the band whose criteria its evidence "
        "meets.",
    )
    omit_below: float = Field(
        default=0.40,
        ge=0.0,
        le=1.0,
        description="A finding whose confidence would fall below this threshold "
        "is omitted entirely (no finding generated). The omit threshold lives "
        "here, never as a number in prompt prose.",
    )
    abstract_only_ceiling: float = Field(
        default=0.79,
        ge=0.0,
        le=1.0,
        description="Maximum confidence a finding may keep when its cited paper "
        "was never deep-read (RetrievedPaper.verbosity_achieved == 0). The top "
        "confidence band requires a deep-read (verbosity >= 1) extract, so an "
        "abstract-only paper cannot enter it; the node clamps any v0-cited "
        "finding's confidence to this ceiling (the top of the highest band that "
        "does NOT require a deep-read). Lives here as the single source of truth, "
        "never as a number in the node or in prompt prose.",
    )

    def render(self) -> str:
        """Render the rubric as the ``{CONFIDENCE_RUBRIC}`` prompt block.

        This is the single place the numeric bands become prompt text — the
        ``.md`` template carries the placeholder only, never the numbers.
        """
        lines = [
            "Assign each finding's `confidence` using this rubric — pick the band "
            "whose criteria the evidence meets:"
        ]
        for b in self.bands:
            lines.append(f"- {b.lower:.2f}-{b.upper:.2f}: {b.criteria}")
        lines.append(
            f"- below {self.omit_below:.2f}: omit — do NOT generate a finding for this paper."
        )
        return "\n".join(lines)

    def render_for_consumer(self) -> str:
        """Render the rubric as a legend for a DOWNSTREAM consumer of the findings.

        Same band semantics as ``render()``, but framed for a reader who is
        *interpreting* confidence values (e.g. the proposer agent), not the
        lit-review LLM *assigning* them. Injected into the lit-review
        ``AgentCard.trust_guidance`` so the proposer knows what a finding's
        ``confidence`` number means — satisfying invariant 3 ("consistently
        interpreted by producer + consumer") of the "Scoring and rubric design
        invariants" in docs/external_agents_architecture.md. The omit threshold
        is producer-only (a consumer never sees an omitted finding), so it is
        left out here.
        """
        lines = [
            "Confidence scores in findings from this agent follow this rubric — "
            "use it to weight findings appropriately:"
        ]
        for b in self.bands:
            lines.append(f"- {b.lower:.2f}-{b.upper:.2f}: {b.criteria}")
        return "\n".join(lines)


class SynthesisConfig(BaseModel):
    """Controls the omission threshold / transfer tolerance for synthesis.

    ``min_confidence`` is intentionally NOT a field here — the omit threshold is
    ``ConfidenceRubric.omit_below`` (single source of truth; see "Scoring and
    rubric design invariants" in docs/external_agents_architecture.md). This
    config governs only how readily synthesis emits a finding for a *cross-
    domain* paper whose mechanism is transferable with caveats.
    """

    transfer_tolerance: Literal["strict", "moderate", "liberal"] = Field(
        default="moderate",
        description="How readily synthesis emits a finding for a cross-domain "
        "paper. 'strict' omits cross-domain papers with fundamental domain "
        "differences; 'moderate' (default) emits when a concrete mechanism "
        "transfer exists, provided the Adaptation states the transfer "
        "assumptions; 'liberal' emits for any potentially relevant technique and "
        "lets the proposer judge. Selects the {OMISSION_RULE} block injected "
        "into the synthesis prompt.",
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
    search_llm_provider: str | None = Field(
        default=None,
        description="Optional separate LLMBridge provider for the dynamic-search "
        "DECISION call only (the cheap, templated query/escalate/done step). When "
        "None, llm_provider is used. Lets the templated search step run on a cheaper "
        "model (e.g. 'deepseek') while compression + synthesis stay on "
        "llm_provider/llm_model_id. Mirrors LLMBridge.reflect_provider.",
    )
    search_llm_model_id: str | None = Field(
        default=None,
        description="Optional separate model id for the search-decision call "
        "(e.g. 'deepseek-v4-pro'). When None, llm_model_id is used.",
    )
    confidence_rubric: ConfidenceRubric = Field(
        default_factory=ConfidenceRubric,
        description="Rubric defining what a finding's confidence score means. "
        "Injected into the synthesis prompt; the single source of truth for "
        "confidence semantics (see 'Scoring and rubric design invariants' in "
        "docs/external_agents_architecture.md). Override to retune without "
        "touching any prompt file.",
    )
    findings_verbosity: Literal[0, 1] = Field(
        default=1,
        description="Detail level for each finding's `content` string. 1 = "
        "structured three-part Markdown (`**Implication:**` / `**Mechanism:**` / "
        "`**Adaptation:**` + closing `(rationale: ...)`), the canonical "
        "proposer-facing format paired with reference_library (§5b). 0 = "
        "single-paragraph backward-compat. Only the synthesis prompt's content "
        "format changes; the ExpertContextItem schema is unchanged either way.",
    )
    synthesis_config: SynthesisConfig = Field(
        default_factory=SynthesisConfig,
        description="Omission / transfer-tolerance knobs for the synthesis step. "
        "Default tolerance is 'moderate' — cross-domain papers with a transferable "
        "mechanism yield a finding carrying an explicit Adaptation transfer caveat, "
        "rather than being omitted. See SynthesisConfig.",
    )


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
