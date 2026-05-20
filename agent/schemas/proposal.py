# agent/schemas/proposal.py
"""
Input and output schemas for ml_model_proposal_agent.

This node consumes InterpretationOutput and produces a full model specification —
mathematical definition, model name, motivation, and structured expert advice —
for consumption by both ml_model_implementor and tune_ml_hyperparam_agent.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from agent.schemas.hyperparam_tuning import (
    ExpertAdvice,
    ExpertAdviceInput,
    GateExhaustionInfo,
)
from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.hardware_context import HardwareContext
from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG

# ---------------------------------------------------------------------------
# Phase B schemas — three-stage reasoning pipeline
# See docs/adaptive_new_model_proposer.md §2A, §2B, §2D
# ---------------------------------------------------------------------------


# B.1 — Falsifiable prediction
class FalsifiablePrediction(BaseModel):
    """A concrete numerical prediction tied to a measurable metric.

    The reflector checks this prediction after the experiment runs and
    labels the hypothesis 'confirmed' / 'refuted' / 'partial' (Phase E).

    The computed ``boldness`` property measures how ambitious the prediction
    is relative to the current value. The pipeline runner checks
    ``boldness >= policy.minimum_boldness`` at runtime — timid predictions
    are rejected before the experiment runs. See ResearchPolicy.
    """

    metric: str = Field(
        description="What to measure. Free-text, guided by expert advice. "
        "Examples: 'mean(file_vector[0:5])', 'denoising_score', "
        "'file_vector[17]'. The reflector evaluates the prediction "
        "by computing the metric from the actual results."
    )
    current_value: float = Field(description="The SOTA's current value for this metric.")
    predicted_value: float = Field(description="What the new model should achieve.")
    threshold_for_refutation: float = Field(
        description="Below this value, the hypothesis is considered refuted. "
        "Must be on the same side of current_value as predicted_value "
        "(i.e. if predicting improvement, threshold < current)."
    )
    rationale: str = Field(description="One sentence: why this specific predicted value.")

    @property
    def boldness(self) -> float:
        """Relative magnitude of the prediction vs current.

        ``abs(predicted - current) / max(abs(current), 1e-6)``.
        The pipeline runner compares this against ``policy.minimum_boldness``.
        The reflector uses it to compute information gain.
        """
        return abs(self.predicted_value - self.current_value) / max(abs(self.current_value), 1e-6)

    @model_validator(mode="after")
    def _prediction_differs_from_current(self):
        if self.predicted_value == self.current_value:
            raise ValueError(
                "predicted_value must differ from current_value — "
                "a prediction of no change is not falsifiable."
            )
        return self


# B.2 — Inherited component (lineage tracking)
class InheritedComponent(BaseModel):
    """One building block carried over from a past winning run.

    Can be a concrete feature ('dilated_causal_conv') or a higher-level
    concept ('receptive_field') — both are tracked in the unified vocabulary.
    See §2B of the V2 design doc.
    """

    component: str = Field(
        description="Short canonical name from the vocabulary. "
        "E.g. 'dilated_causal_conv' (feature) or 'receptive_field' (concept)."
    )
    from_model_type: str = Field(description="The ancestor model_type, e.g. 'wavenet'.")
    from_run: str | None = Field(
        default=None,
        description="The specific run where this component first proved out. "
        "None for built-in models.",
    )
    contribution_evidence: str = Field(
        max_length=1000,
        description="Why this component contributes — link it to its measured benefit.",
    )
    citation_source: str | None = Field(
        default=None,
        description="cite_id of the ExpertContextItem that motivated inheriting "
        "this component. None = driven purely by experiment records.",
    )


# B.3 — Expert context item (polymorphic upstream input)
class ExpertContextItem(BaseModel):
    """One piece of upstream context for the proposal agent.

    Treats human-written advice and machine-generated analysis through the
    same interface. Future agents (Data Analysis, Physics, Literature,
    Narrative) emit ExpertContextItems through their own protocol functions;
    the proposal agent treats all of them uniformly. See §2D.
    """

    source: str = Field(
        description="Identifier of the producer. E.g. 'human', "
        "'data_analysis_agent', 'physics_expert_agent'."
    )
    kind: Literal["empirical", "theoretical", "literature", "human", "narrative", "findings"] = (
        Field(
            description="What type of context this is. 'findings' is the "
            "accumulated key_findings union forwarded by chain-mode "
            "across iterations (workflows/model_exploration.py)."
        )
    )
    content: str = Field(max_length=100000, description="The actual advice / finding / constraint.")
    cite_id: str = Field(
        description="Short stable ID the proposal agent can reference in its "
        "DiscoveryMemo.citation_sources."
    )
    produced_at: str | None = Field(
        default=None, description="ISO timestamp of when the finding was produced."
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional self-reported confidence from the producing agent.",
    )


# B.3a — Agent name card (Phase F)
class AgentCard(BaseModel):
    """Static self-description of an external contributing agent.

    Defined once in the agent's implementation, emitted on every run.
    Collected into ProposalInput.agent_cards and rendered as a 'Contributors'
    section near the top of each stage prompt — before the Expert Context block.

    The key principle: findings are the evidence; the name card is the calibration.
    The LLM reads the name cards *before* reading the ExpertContextItem list, so
    it knows how to weight each source before it encounters any specific claim.
    """

    agent_name: str = Field(
        description="Stable identifier matching ExpertContextItem.source values "
        "this agent produces. E.g. 'ml_literature_review'."
    )
    role: str = Field(
        max_length=200, description="One sentence: what this agent does in the pipeline."
    )
    expertise_domain: str = Field(
        max_length=300,
        description="What this agent knows well — the domain its findings are grounded in.",
    )
    coverage: str = Field(
        max_length=300,
        description="Scope of its knowledge: time range, data sources, filtering criteria.",
    )
    limitations: str = Field(
        max_length=300, description="What this agent cannot assess or may get wrong."
    )
    trust_guidance: str = Field(
        max_length=400,
        description="One or two sentences instructing the proposal LLM how to weight "
        "this agent's findings relative to experiment results and other sources. "
        "E.g. 'Treat as promising priors — only experiment runs confirm applicability.' "
        "For physics agents: 'Physical constraints are HARD LIMITS.'",
    )


# B.4 — Model comparison (Stage 1 output)
class ModelComparison(BaseModel):
    """Structured analysis of one previously tested model.

    Produced by the comparison stage (Stage 1) of the reasoning pipeline.
    The reasoning stage (Stage 2) reads these to form its causal hypothesis.
    """

    model_type: str
    source: str = Field(description="'seed' or 'proposed_iter_N'.")
    best_score: float
    key_mechanism: str = Field(
        max_length=1000,
        description="What makes this model tick (or not). "
        "Must reference a specific architectural feature or concept.",
    )
    strengths: list[str] = Field(
        description="What this model does well, tied to file_vector or score evidence."
    )
    weaknesses: list[str] = Field(
        description="Where this model fails, tied to file_vector or score evidence."
    )
    lesson_for_next_proposal: str = Field(
        max_length=1000, description="What to inherit or avoid from this model."
    )


# B.5a — Proposed vocabulary link (feature → capability hypothesis)
class ProposedVocabLink(BaseModel):
    """A hypothesized connection between a feature and a capability.

    Proposed by the comparison stage based on model descriptions and
    experiment results. Tested via FalsifiablePrediction in the next
    experiment. Confirmed or refuted by the reflector.

    Only confirmed links (≥2 runs) get promoted to VocabEntry.related_to
    by the interpretation agent (Phase C).
    """

    feature: str = Field(description="The feature entry name, e.g. 'dilated_causal_conv'.")
    capability: str = Field(description="The capability entry name, e.g. 'receptive_field'.")
    evidence: str = Field(
        max_length=1000,
        description="Why the agent thinks this link exists — must reference "
        "specific model results or architectural analysis.",
    )
    status: Literal["proposed", "confirmed", "refuted"] = Field(
        default="proposed",
        description="Lifecycle: proposed → confirmed/refuted after experiment.",
    )

    @field_validator("status", mode="before")
    @classmethod
    def coerce_status(cls, v: object) -> str:
        """Coerce any LLM-invented status value to 'proposed'.

        LLMs occasionally produce values like 'uncertain' or 'refuted_for_this_integration'.
        All new links output by the proposal agent are inherently proposed — they haven't
        been tested yet — so falling back to 'proposed' is always semantically correct.
        """
        if v not in ("proposed", "confirmed", "refuted"):
            return "proposed"
        return v


# B.5 — Discovery memo (output of Stages 1+2, input to Stage 3)
class DiscoveryMemo(BaseModel):
    """The structured output of the reasoning pipeline (comparison + reasoning
    stages). The 'Final Verdict' that forces the LLM to articulate WHY
    before WHAT. Stage 3 (proposing) is structurally tethered to this memo.

    See §2A of the V2 design doc.
    """

    # --- Comparative analysis (Stage 1 output) ---
    comparative_analysis: list[ModelComparison] = Field(
        description="Systematic comparison of selected past models."
    )
    sota_model_type: str = Field(
        description="The current best-scoring model, identified from the comparisons."
    )
    sota_score: float
    sota_mechanism: str = Field(
        max_length=1000,
        description="WHY does the SOTA work? Must reference physical/architectural "
        "mechanism, not vague language.",
    )

    # --- Causal reasoning (Stage 2 output) ---
    proposed_change: str = Field(
        max_length=1000,
        description="What the new proposal changes RELATIVE TO the SOTA. "
        "Must be expressible as 'replace X with Y' or 'add Z'.",
    )
    causal_hypothesis: str = Field(
        max_length=1000,
        description="WHY the proposed change should improve the score. "
        "Must reference the SOTA mechanism preserved, the bottleneck "
        "relaxed, and the new mechanism introduced.",
    )

    # --- Falsifiable prediction ---
    falsifiable_prediction: FalsifiablePrediction

    # --- Devil's advocate ---
    predicted_failure_modes: list[str] = Field(
        min_length=1, max_length=3, description="At least one way the proposal could fail."
    )

    # --- Lineage ---
    inherited_components: list[InheritedComponent] = Field(
        default_factory=list,
    )

    # --- Vocabulary candidates discovered during comparison ---
    proposed_vocab_candidates: list[dict[str, str]] = Field(
        default_factory=list,
        description="New features or capabilities the comparison stage discovered "
        "that aren't in the current vocabulary. Each entry has "
        "'name', 'kind' (feature/capability), 'description'. "
        "These enter the candidate pool for future promotion.",
    )

    # --- Feature → capability link hypotheses ---
    proposed_vocab_links: list[ProposedVocabLink] = Field(
        default_factory=list,
        description="Hypothesized connections between features and capabilities. "
        "Proposed by the comparison stage, tested via the "
        "FalsifiablePrediction, confirmed/refuted by the reflector. "
        "Only confirmed links get promoted to VocabEntry.related_to.",
    )

    # --- Citations ---
    citation_sources: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="cite_id values of ExpertContextItems that materially "
        "shaped this memo. Max 5 — cite only items that changed "
        "your hypothesis. The pipeline runner verifies each cite_id "
        "appears in causal_hypothesis or proposed_change text.",
    )

    @model_validator(mode="after")
    def _causal_hypothesis_not_empty(self):
        if not self.causal_hypothesis.strip():
            raise ValueError("causal_hypothesis cannot be empty.")
        return self


# B.6 — Reasoning pipeline configuration
class ReasoningStage(BaseModel):
    """One stage in the reasoning pipeline. Each stage is one LLM call."""

    name: str
    system_prompt_key: str
    output_mode: Literal["json", "text"] = "json"
    enabled: bool = True


class ModelSelectionStrategy(BaseModel):
    """Pre-filter for which past models the comparison stage analyzes."""

    method: str = Field(
        default="top_n", description="'top_n', 'all', 'feature_match', or 'human_specified'."
    )
    params: dict[str, Any] = Field(
        default_factory=lambda: {"n": 5},
    )


class ResearchPolicy(BaseModel):
    """Tunable parameters for the reasoning pipeline's validators and triggers.

    The 'knobs' that control how aggressively the centrifugal forces are applied.
    Different research strategies need different settings. All defaults are
    conservative. Override via workflow config or ExpertContextItem(kind='strategy').

    See §2A 'Policy-Mechanism Decoupling' in docs/adaptive_new_model_proposer.md.
    """

    # --- Prediction quality ---
    minimum_boldness: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Minimum abs(predicted - current) / abs(current). "
        "Predictions below this are rejected as too conservative.",
    )

    # --- Citation discipline ---
    max_citations: int = Field(
        default=5,
        ge=1,
        description="Maximum ExpertContextItem citations per DiscoveryMemo.",
    )

    # --- Vocabulary health ---
    vocab_stagnation_threshold: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="If candidate/total vocab ratio drops below this in auto "
        "mode, the exploration resolver triggers explore mode.",
    )

    # --- Promotion strictness ---
    min_runs_for_promotion: int = Field(
        default=3,
        ge=2,
        description="Minimum distinct runs before a candidate vocab entry "
        "or a ProposedVocabLink can be promoted.",
    )
    require_positive_delta: bool = Field(
        default=True,
        description="Whether promotion requires component_delta > 0 "
        "(positive contribution when present vs absent).",
    )

    # --- Proposer stage-output management (C6.2 / Rev 8.6) ---
    comparative_analysis_top_k: int = Field(
        default=5,
        ge=1,
        description="Maximum number of ModelComparison entries retained in "
        "DiscoveryMemo.comparative_analysis when the comparison "
        "stage output is rendered into a downstream proposer "
        "user prompt. Entries are sorted by recency desc, "
        "tie-broken by best_score desc, then sliced to top_k. "
        "Caps the linear growth of prior_stage_outputs across "
        "iterations (see audit doc §8 Commit 6.2).",
    )
    prior_stage_max_chars: int = Field(
        default=4000,
        ge=1,
        description="Maximum chars per string value inside any non-input "
        "stage output dict before the JSON-safe backstop "
        "middle-truncates it. Catches future stages that may "
        "emit large raw strings; the Top-K clamp on "
        "comparative_analysis covers the current dominant "
        "growth driver.",
    )


class ReasoningPipelineConfig(BaseModel):
    """Configurable reasoning pipeline. Lives at the workflow level."""

    stages: list[ReasoningStage] = Field(
        default_factory=list,
        description="Ordered list of reasoning stages. Empty = legacy 2-call mode. "
        "The standard 3-stage pipeline is configured at the workflow level: "
        "[comparison, causal_reasoning]. The proposing stage always runs "
        "last and is not listed here.",
    )
    model_selection: ModelSelectionStrategy = Field(
        default_factory=ModelSelectionStrategy,
    )
    exploration_mode: Literal["auto", "explore", "exploit"] = Field(
        default="auto",
        description="'auto': system decides based on evidence depth. "
        "'explore': diagnostic experiments, honest uncertainty. "
        "'exploit': build on confirmed patterns.",
    )
    policy: ResearchPolicy = Field(
        default_factory=ResearchPolicy,
        description="Tunable thresholds for validators and exploration triggers. "
        "The 'software' that configures the 'hardware' of the pipeline. "
        "Override per-workflow or per-round via ExpertContextItem(kind='strategy').",
    )


# B.6a — Unified vocabulary entry (features + concepts)
class VocabEntry(BaseModel):
    """A single vocabulary entry — feature or capability.

    Adding a new kind (e.g. 'failure_pattern') requires NO code changes —
    just add entries with the new kind value. See §2B composability principle.
    """

    name: str = Field(description="Canonical snake_case name.")
    kind: str = Field(
        description="'feature' (concrete architectural building block, e.g. "
        "'dilated_causal_conv') or 'capability' (measurable "
        "architectural property the feature provides, e.g. "
        "'receptive_field'). New kinds can be added freely."
    )
    description: str = Field(max_length=1000)
    related_to: list[str] = Field(
        default_factory=list,
        description="Names of connected VocabEntry items. "
        "Feature→concept and concept→feature links.",
    )
    tier: Literal["canonical", "candidate"] = "candidate"
    pattern: str | None = Field(
        default=None, description="AST/regex for features. None for concepts."
    )
    proposed_by_run: str | None = None
    seen_in_runs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    origin: str | None = Field(
        default=None,
        description="Source agent for externally-contributed entries. "
        "E.g. 'ml_literature_review', 'physics_literature_review'. "
        "None = proposed during an experiment run (proposed_by_run carries the run name). "
        "When set, proposed_by_run must be None — external contributions do not "
        "count toward seen_in_runs and cannot be promoted via the run-count criterion.",
    )


# ---------------------------------------------------------------------------
# Existing schemas (ProposalInput / ProposalOutput)
# ---------------------------------------------------------------------------


class ProposalInput(BaseModel):
    """
    Input to ml_model_proposal_agent.

    Typically populated via the interpretation_to_proposal_v1 protocol,
    which maps InterpretationOutput → ProposalInput.
    """

    interpretation: dict[str, Any] = Field(
        description="Serialised InterpretationOutput — key findings, bottlenecks, "
        "and take-home message from result_interpretation_agent.",
    )
    existing_model_types: list[str] = Field(
        default_factory=list,
        description="Model type keys already registered in MODEL_REGISTRY. "
        "The proposal agent must not reuse any of these names.",
    )
    per_model_score_tables: dict[str, ScoreComparisonTable] | None = Field(
        default=None,
        description="model_type → best ScoreComparisonTable, carried forward from "
        "InterpretationOutput.per_model_score_tables. Typed mirror of the "
        "`interpretation['per_model_score_tables']` dict-carry payload — "
        "consumers may read either. Replaces the old per_model_file_vectors "
        "per §7.3 / Decision 6. None when no upstream tables are available.",
    )
    # --- Run-level data + time-budget context (workflow-supplied) ---
    # See docs/resource_estimator_implement.md §2.7.2. These fields originate at the
    # workflow/CLI entry point and fan out to both this node and the tuner so
    # the proposer can call build_sample_set + evaluate_time_skill on its own
    # baseline before emitting. The training-side trial-mode set mirrors
    # HyperparamTuningInput exactly so both gates see identical sample_sets;
    # legacy single_file mode (file_index, is_trial=False) is deliberately not
    # surfaced here — modern usage is is_trial=True with trial_strategy='target'
    # + target_files=[N] when a single file is wanted.
    is_trial: bool = Field(
        default=False,
        description="Whether the run uses trial (sparse) sampling. Forwarded to "
        "build_sample_set inside the proposer's evaluate_time_skill gate "
        "so it matches what the tuner will run.",
    )
    trial_strategy: Literal["snapshot", "anchors", "target"] = Field(
        default="snapshot",
        description="Sampling strategy for training data: 'snapshot' (all 20 files), "
        "'anchors' (files 0/10/19), 'target' (caller-specified files). "
        "Mirrors HyperparamTuningInput.trial_strategy.",
    )
    trial_portion: float = Field(
        default=0.1,
        ge=0.01,
        le=1.0,
        description="Fraction of segments per file for the training scope. "
        "Mirrors HyperparamTuningInput.trial_portion.",
    )
    target_files: list[int] = Field(
        default_factory=list,
        description="File indices to sample from. Required when trial_strategy='target'. "
        "Mirrors HyperparamTuningInput.target_files.",
    )
    train_portion: float = Field(
        default=0.1,
        ge=0.01,
        le=1.0,
        description="Per-epoch subsample fraction from the training scope. "
        "Forwarded to evaluate_time_skill so the proposer's wall-time "
        "estimate matches the tuner's. Default 0.1 mirrors "
        "HyperparamTuningInput.train_portion.",
    )
    sampling_seed: int | None = Field(
        default=None,
        description="Seed for build_sample_set(). When None the proposer auto-generates "
        "one for its estimate; the tuner uses its own auto-generation "
        "policy from HyperparamTuningInput.sampling_seed. The estimate is "
        "robust to which exact segments are picked, so identical seeds "
        "across the two gates are not required.",
    )
    trial_time_budget_minutes: float | None = Field(
        default=None,
        description="Wall-time budget in minutes against which evaluate_time_skill "
        "gates the baseline config when inp.is_trial=True. None = "
        "trial gate disabled (no estimate). "
        "See §2.7 + Phase I — the single time_budget_minutes field "
        "used in Phases D-G was split into trial/formal so each mode "
        "has its own ceiling.",
    )
    formal_time_budget_minutes: float | None = Field(
        default=None,
        description="Wall-time budget in minutes against which evaluate_time_skill "
        "gates the baseline config when inp.is_trial=False. None = "
        "formal gate disabled. Sized independently from the trial "
        "budget because formal runs use the full dataset and have a "
        "wall-time scale 50-100× longer.",
    )
    data_dir: str | None = Field(
        default=None,
        description="Filesystem path to the TIDMAD data directory. Required by the "
        "real-dataset warmup inside evaluate_time_skill; when None, the "
        "skill falls back to its static formula. See §2.6.3.",
    )
    # --- Phase 6.6 WS-B (B.1) — hardware awareness ---
    # The orchestrator threads the live HardwareContext manifest and the
    # active operator VRAM budget into the Proposer so it can render the
    # [HARDWARE CONTEXT] block (PHYSICAL / BUDGET / PHYSICAL VETO regimes).
    # Both Optional so CPU-only tests and legacy callers work unchanged —
    # when ctx is None or device_available=False, the prompt block is
    # suppressed. B.1 wires the field only; B.2 adds the renderer.
    # See docs/phase66_ws_b_proposer_hardening.md §2.3 / §3.1.
    hardware_context: HardwareContext | None = Field(
        default=None,
        description=(
            "Live hardware manifest from core.hardware_context. "
            "Populated by the workflow via HardwareContext.get_or_create(). "
            "None for CPU-only / test stubs and for standalone proposer "
            "invocations that bypass the workflow. When present and "
            "device_available=True, the Proposer's [HARDWARE CONTEXT] "
            "prompt block renders device_name, total_memory_gb, and "
            "usable_cap_gb."
        ),
    )
    vram_budget_gb: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Active operator-defined VRAM ceiling (GB) for the upcoming "
            "tuning iteration. Workflow picks trial_vram_budget_gb if "
            "set, else formal_vram_budget_gb, else None. When set and "
            "below hardware_context.usable_cap_gb, renders as the BUDGET "
            "regime; when above, renders as PHYSICAL VETO (physical cap "
            "wins). None + PHYSICAL cap → PHYSICAL regime."
        ),
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Hard limits the proposed architecture must respect "
        "(e.g. 'VRAM < 10 GB', 'params < 50M', 'no external dependencies').",
    )
    expert_advice: ExpertAdviceInput = Field(
        default="",
        description="Structured guidance from upstream agents or orchestrators. "
        "Accepts a plain string or a structured ExpertAdvice object.",
    )
    human_advice: ExpertAdviceInput | None = Field(
        default=None,
        description="DEPRECATED — use expert_context instead. Legacy human-provided guidance. "
        "When present, the protocol wraps it into an ExpertContextItem with "
        "source='human', kind='human'. Accepts a plain string or ExpertAdvice object.",
    )
    expert_context: list[ExpertContextItem] = Field(
        default_factory=list,
        description="Polymorphic upstream context — human advice, agent findings, etc. "
        "Each item carries a source, kind, content, and cite_id for attribution. "
        "Replaces human_advice as the primary advice channel. See §2D.",
    )
    reasoning_pipeline: ReasoningPipelineConfig = Field(
        default_factory=ReasoningPipelineConfig,
        description="Configurable reasoning pipeline (comparison → reasoning → proposing). "
        "Set at the workflow level; controls which stages run, model selection "
        "strategy, and exploration/exploitation mode. See §2A.",
    )
    vocab_seed: list[VocabEntry] = Field(
        default_factory=list,
        description="The runtime vocabulary available to the reasoning pipeline. "
        "In production, populated by the interpretation agent via the "
        "protocol (canonical seed + promoted candidates + active candidates). "
        "For standalone use, load from agent/schemas/vocab_seed.json. "
        "Empty list = vocabulary features disabled (backward compat).",
    )
    previous_failures: list[str] = Field(
        default_factory=list,
        description="Validation error messages from previous failed attempts in this "
        "iteration. The workflow populates this when retrying after a "
        "validation failure so the proposal agent avoids the same mistakes. "
        "Each entry is the error_message from a ValidatorOutput.",
    )
    recent_gate_exhaustions: list[GateExhaustionInfo] = Field(
        default_factory=list,
        description=(
            "Phase N (§14.N.1) — gate-exhaustion summaries from the "
            "most recent up-to-3 tuner iterations, oldest first. "
            "Iterations whose tuner produced no gate_exhaustion are "
            "omitted entirely (not represented as None). Empty list "
            "(the default) means no recent abort/gate-exhaustion "
            "feedback to surface; the proposer prompt's [RECENT GATE "
            "EXHAUSTIONS] block is suppressed. Populated by the "
            "interp→propose protocol from the workflow's bounded FIFO "
            "of recent HyperparamTuningOutputs. Replaces K.7.2's "
            "single-slot prior_iteration_gate_exhaustion. See "
            "docs/resource_estimator_implement.md §10.13 + §14.N."
        ),
    )

    @field_validator("recent_gate_exhaustions", mode="after")
    @classmethod
    def _cap_recent_gate_exhaustions(cls, v: list[GateExhaustionInfo]) -> list[GateExhaustionInfo]:
        """Safety rail: workflow enforces ``maxlen=3`` via a deque, but the
        schema guards against a caller supplying an unbounded list. Cap at 10.
        """
        if len(v) > 10:
            raise ValueError(
                f"recent_gate_exhaustions has {len(v)} entries; "
                f"maximum allowed is 10 (workflow enforces 3)."
            )
        return v

    mindset: str | None = Field(
        default=None,
        description="Mindset block injected at {# EXPLORATION_MODE_BLOCK #} in the "
        "causal reasoning stage prompt. Overrides the default _explore.md / "
        "_exploit.md fallback when provided. Sourced from advice['mindset']. "
        "When absent, the mode file is used (backward compatible with v1/v2).",
    )
    agent_cards: list[AgentCard] = Field(
        default_factory=list,
        description="Self-descriptions of all external agents contributing context this round. "
        "Rendered as a 'Contributors' section before the Expert Context block. "
        "The proposal LLM reads these first to calibrate trust in each source. "
        "Empty = no external agents this round (internal-only run).",
    )
    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node reads its inputs and writes its proposal output. "
        "When running standalone, the node reads interpretation output "
        "from storage.local.workspace.",
    )
    debug_dump_proposing_prompt_path: str | None = Field(
        default=None,
        description=(
            "Debug instrumentation (Phase K.8): when set, the proposer's "
            "pipeline mode writes the rendered proposing-stage system "
            "prompt to this path before calling the LLM. Used by smoke "
            "runs to audit the exact text the LLM saw — in particular "
            "the K.7.6 [PRIOR ITERATION GATE EXHAUSTION] block. "
            "None = no dump (default; production behaviour)."
        ),
    )


class ProposalOutput(BaseModel):
    """
    Output of ml_model_proposal_agent.

    A complete model specification ready for implementation and hyperparameter tuning.
    Consumed by ml_model_implementor (via proposal_to_implementor_v1) and by
    tune_ml_hyperparam_agent (via proposal_to_hyperparam_seeded_v1).
    """

    model_name: str = Field(
        min_length=1,
        description="Short, unique, snake_case identifier for the proposed model "
        "(e.g. 'attn_unet', 'dilated_rnn'). Must not clash with existing model types.",
    )
    model_description: str = Field(
        description="One paragraph plain-English description of the architecture "
        "and why it is expected to improve on the current best.",
    )
    mathematical_definition: str = Field(
        description="Precise layer-by-layer specification of the architecture. "
        "Must be concrete enough for an LLM to implement directly: "
        "include layer types, dimensions, activation functions, skip connections, "
        "and the forward pass data flow. "
        "Forward contract is fixed: input [B, T] int64 → output [B, 256, T] float32.",
    )
    motivation: str = Field(
        description="Why this specific architecture addresses the bottlenecks identified "
        "by result_interpretation_agent. Should reference the take-home message directly.",
    )
    expert_advice: ExpertAdvice = Field(
        description="Structured guidance for tune_ml_hyperparam_agent. "
        "Specifies safe starting hyperparameter ranges, known failure modes, "
        "and exploration focus areas for this specific architecture.",
    )
    baseline_config: dict[str, Any] = Field(
        description="A safe, moderate starting configuration for this architecture. "
        "Should use a conservative parameter count and GPU memory footprint "
        "suitable for initial exploration. "
        "Must include model_config, train_config, and loss_config keys.",
    )
    inherited_components: list[InheritedComponent] = Field(
        default_factory=list,
        description="Architectural primitives carried over from past winning runs. "
        "Copied from the DiscoveryMemo. The validator checks that each "
        "claimed component actually appears in the generated code.",
    )
    falsifiable_prediction: FalsifiablePrediction | None = Field(
        default=None,
        description="The numerical prediction from the DiscoveryMemo. "
        "Evaluated by the interpretation agent after tuning to "
        "determine if the hypothesis was confirmed or refuted. "
        "None in legacy mode (no pipeline).",
    )
    proposed_vocab_links: list[ProposedVocabLink] = Field(
        default_factory=list,
        description="Feature→capability link hypotheses from the DiscoveryMemo. "
        "Evaluated across iterations — confirmed links get promoted "
        "to VocabEntry.related_to by the interpretation agent.",
    )
    proposed_vocab_candidates: list[dict[str, str]] = Field(
        default_factory=list,
        description="New feature/capability candidates proposed by the comparison or "
        "reasoning stage. Each entry is a dict with 'name', 'kind' "
        "('feature' or 'capability'), and 'description'. These enter the "
        "candidate pool in build_runtime_vocab and are promoted to canonical "
        "after appearing in >= min_runs_for_promotion distinct runs. "
        "Separate from proposed_discoveries (which carries kind='discovery' only).",
    )
    proposed_discoveries: list[VocabEntry] = Field(
        default_factory=list,
        description="New kind='discovery' vocabulary entries the proposer suggests "
        "based on the reasoning pipeline's analysis. These are empirical "
        "findings expressed as long-form sentences (e.g. 'CONFIRMED: wavenet "
        "achieved score=5.57'). Short named architectural terms (features, "
        "capabilities) go into proposed_vocab_candidates instead.",
    )
    memo_consistency_notes: list[str] = Field(
        default_factory=list,
        description="Inconsistencies the proposing stage noticed between the "
        "DiscoveryMemo and what's physically implementable. "
        "Empty = no issues found. Non-empty = the validator surfaces "
        "these as warnings. This is a flag, not a veto.",
    )
    # Fix 2 Commit 6 — proposer-side pre-flight cost-check audit fields.
    # See docs/reliable_resource_proposer.md §9 Commit 6 Decisions 5 + 7.
    parameter_count_estimate: int | None = Field(
        default=None,
        description="LLM-emitted estimate of the total trainable parameter count "
        "for baseline_config. Consumed by the proposer's pre-flight "
        "static-cost gate (Fix 2) — an order-of-magnitude estimate "
        "is sufficient for gate-level decisions. None = pre-flight "
        "was not run for this draft (either the LLM omitted the field "
        "or the active time budget was disabled). See "
        "docs/reliable_resource_proposer.md §7 Decision 3 + §9 Commit 6.",
    )
    preflight_estimated_minutes: float | None = Field(
        default=None,
        description="Pre-flight static-formula wall-time estimate in minutes for "
        "the emitted baseline_config, evaluated against "
        "trial_time_budget_minutes (trial mode) or "
        "formal_time_budget_minutes (formal mode). None = pre-flight "
        "skipped; see parameter_count_estimate + memo_consistency_notes "
        "for the reason. Populated by estimate_proposal_time. "
        "Audit-only — does not gate downstream validation.",
    )
    preflight_factor: float | None = Field(
        default=None,
        description="preflight_estimated_minutes / active_budget_minutes, rounded "
        "to 3 decimal places. factor <= 1.0 means the draft is "
        "predicted to fit; factor > 1.0 would have triggered a "
        "pre-flight rejection. On exhaustion of the pre-flight revision "
        "loop the emitted candidate is the lowest-factor draft seen "
        "(not necessarily the last one).",
    )

    @model_validator(mode="after")
    def _validate_baseline_segmentation_size(self):
        """Ensure ``baseline_config`` respects the dataset's ``segmentation_size`` rule.

        See ``docs/improving_validation_awareness.md`` Phase A.1 — moves the
        ``psd_segment_length % segmentation_size == 0`` check from deep inside the
        tuner (``_validate_data_config``) up to the proposer's output gate, so
        an invalid baseline is rejected before the implementor and tuner are
        invoked. The proposer node's existing retry loop feeds this error back
        via ``previous_failures``, giving the LLM one upstream chance to fix it.

        No-ops gracefully when ``baseline_config`` lacks ``model_config`` or the
        nested ``segmentation_size`` field — some architectures don't have one,
        and existing tests construct ``ProposalOutput`` with ``baseline_config={}``.
        """
        model_cfg = self.baseline_config.get("model_config") if self.baseline_config else None
        if not isinstance(model_cfg, dict):
            return self
        seg = model_cfg.get("segmentation_size")
        if seg is None:
            return self
        if not isinstance(seg, int) or seg <= 0:
            raise ValueError(
                f"baseline_config['model_config']['segmentation_size'] must be a "
                f"positive int, got {seg!r}."
            )
        psd = DATASET_CONFIG.psd_segment_length
        if psd % seg != 0:
            valid = DATASET_CONFIG.valid_segmentation_sizes()
            raise ValueError(
                f"baseline_config['model_config']['segmentation_size'] ({seg}) "
                f"must exactly divide psd_segment_length ({psd}). "
                f"Remainder: {psd % seg}. "
                f"Valid segmentation_size values: {valid}."
            )
        return self
