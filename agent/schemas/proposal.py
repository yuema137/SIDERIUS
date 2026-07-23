# agent/schemas/proposal.py
"""
Input and output schemas for ml_model_proposal_agent.

This node consumes InterpretationOutput and produces a full model specification —
mathematical definition, model name, motivation, and structured expert advice —
for consumption by both ml_model_implementor and tune_ml_hyperparam_agent.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from agent.schemas.hyperparam_tuning import (
    ExpertAdvice,
    ExpertAdviceInput,
    GateExhaustionInfo,
)
from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
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


# L3 — Custom loss specification (agent-generated loss plugin)
class CustomLossSpec(BaseModel):
    """Specification for an agent-generated custom loss function.

    Emitted by ``ml_model_proposal_agent`` when the proposer decides that
    none of the four built-in loss types (``focal``, ``focal_cw``, ``ce``,
    ``smooth_l1``) fits the current research direction and a novel loss is
    warranted. Consumed by ``ml_model_implementor`` at L4 to generate a
    loss plugin under ``agent_generated/losses/{loss_name}.py``.

    Round-trip contract: when ``ProposalOutput.custom_loss_spec`` is set,
    ``baseline_config['loss_config']['loss_type']`` must be ``"custom"`` and
    ``baseline_config['loss_config']['loss_name']`` must equal
    ``custom_loss_spec.loss_name``. Enforced by
    ``ProposalOutput._validate_custom_loss_spec_consistency``.

    See ``docs/design/enable_loss_inventory.md`` § Commit L3.
    """

    loss_name: str = Field(
        min_length=1,
        description="Snake_case unique key for this loss. Becomes the "
        "``PLUGIN_LOSS_TYPE`` constant of the generated plugin and the "
        "filename ``agent_generated/losses/{loss_name}.py``. Must not "
        "clash with existing losses in the registry.",
    )
    description: str = Field(
        min_length=1,
        description="Plain-English description of what this loss computes "
        "and why it is expected to outperform the built-in alternatives "
        "on the current research direction.",
    )
    mathematical_definition: str = Field(
        min_length=1,
        description="Precise mathematical definition of the loss function "
        "in terms of model outputs and targets. Must be concrete enough "
        "for the implementor to generate code directly — include reduction "
        "behavior, weighting terms, and any auxiliary tensors (e.g. spectral "
        "windows). Avoid hand-waving like 'a weighted variant of...'.",
    )
    config_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Hyperparameter fields for the plugin's "
        "``PLUGIN_LOSS_CONFIG_CLASS``. Keys are field names; values describe "
        "type, default, and meaning. Concrete structure validated at L4 by "
        "the implementor. Empty dict = the plugin has no tunable "
        "hyperparameters (a pure functional loss).",
    )


# B.2 — Inherited component (lineage tracking)
_EXTERNAL_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*:[\w./-]+$")


class InheritedComponent(BaseModel):
    """One building block carried over into the proposed architecture.

    Can be a concrete feature ('dilated_causal_conv') or a higher-level
    concept ('receptive_field') — both are tracked in the unified vocabulary.
    Generic across source types: an inherited component may come from a past
    experiment, from an external agent's finding, or from a human directive.
    See §2B of the V2 design doc + §11.3 of
    ``docs/external_agents_for_proposer.md``.
    """

    component: str = Field(
        description="Short canonical name from the vocabulary. "
        "E.g. 'dilated_causal_conv' (feature) or 'receptive_field' (concept)."
    )
    source_type: Literal["experiment", "external_agent", "human"] = Field(
        description=(
            "Where this inherited component comes from:\n"
            "  - ``experiment``: a past run of the chain. ``source_id`` is the "
            "    ``model_type`` (e.g. 'wavenet'); ``from_run`` may carry the "
            "    specific run name.\n"
            "  - ``external_agent``: an external agent's finding. ``source_id`` "
            "    is the ``source_ref`` of the originating ExpertContextItem "
            "    (e.g. 'arxiv:2312.00752', 'physics:squid_band_limit_v1').\n"
            "  - ``human``: a human directive. ``source_id`` is the human "
            "    instruction identifier (e.g. 'human:instruction_20260603')."
        )
    )
    source_id: str = Field(
        description=(
            "Stable identifier for the source. Format depends on ``source_type``:\n"
            "  - experiment: a bare ``model_type`` token (no colon required), "
            "    e.g. 'wavenet'.\n"
            "  - external_agent / human: ``<prefix>:<identifier>`` matching the "
            "    regex ``^[a-z][a-z0-9_-]*:[\\w./-]+$`` — same format as "
            "    ExpertContextItem.source_ref. The validator rejects obviously "
            "    malformed values for these source types."
        )
    )
    from_run: str | None = Field(
        default=None,
        description="The specific run where this component first proved out. "
        "Only meaningful when ``source_type='experiment'``. None for built-in "
        "models and for non-experiment sources.",
    )
    contribution_evidence: str = Field(
        max_length=1000,
        description="Why this component contributes. For experiment sources: link "
        "to measured benefit. For external_agent sources: state the mechanism the "
        "source describes plus why it addresses the current bottleneck. For human "
        "sources: state the directive in one line.",
    )

    @model_validator(mode="after")
    def _validate_source_id_format(self):
        # source_type='experiment' accepts any non-empty source_id (a model_type
        # is a bare snake_case token, no colon). For external_agent and human
        # the source_id must match '<prefix>:<identifier>'.
        if self.source_type in {"external_agent", "human"} and not _EXTERNAL_SOURCE_ID_RE.match(
            self.source_id
        ):
            raise ValueError(
                f"source_id {self.source_id!r} does not match the required "
                f"format for source_type={self.source_type!r}: expected "
                f"'<prefix>:<identifier>' (regex "
                f"{_EXTERNAL_SOURCE_ID_RE.pattern!r}). "
                f"Examples: 'arxiv:2312.00752', 'human:instruction_20260603', "
                f"'physics:squid_band_limit_v1'."
            )
        return self


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
    source_ref: str = Field(
        description="Short stable ID the proposal agent can reference in its "
        "DiscoveryMemo.source_refs."
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
    trust_level: Literal["hard_limit", "strong_prior", "soft_prior"] = Field(
        description=(
            "Structured trust calibration the proposer reads programmatically. "
            "The free-text ``trust_guidance`` stays for human-readable explanation; "
            "``trust_level`` is the machine-readable equivalent the proposer prompt "
            "references via its synthesis rules. When the two disagree, "
            "``trust_level`` is authoritative for routing decisions (rule application, "
            "synthesis weighting); ``trust_guidance`` is authoritative for human review. "
            "\n\n"
            "Levels:\n"
            "  - ``hard_limit``: findings define non-negotiable constraints; the "
            "    proposer MUST NOT violate them. Reserved for objective constraint "
            "    agents (physics, hardware). No default — explicit assignment only.\n"
            "  - ``strong_prior``: findings carry weight comparable to experiment "
            "    data. Reserved for high-confidence empirical or theoretical sources, "
            "    and for human directives wrapped into the expert_context channel.\n"
            "  - ``soft_prior``: findings are inspirational priors; the proposer may "
            "    use them to expand beyond what experiment history has tried, but "
            "    experiment data takes precedence on conflict. Default for "
            "    survey-style sources like literature review."
        ),
    )
    trust_guidance: str = Field(
        max_length=800,
        description="Human-readable explanation of the trust calibration. Renders "
        "alongside ``trust_level`` in the Contributors block. May carry a confidence "
        "rubric legend so the proposer knows what a finding's confidence score means "
        "(see ConfidenceRubric.render_for_consumer); 800 chars accommodates the full "
        "band criteria. E.g. 'Treat as promising priors — only experiment runs confirm "
        "applicability.' For physics agents: 'Physical constraints are HARD LIMITS.'",
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
    source_refs: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="source_ref values of ExpertContextItems that materially "
        "shaped this memo. Max 5 — cite only items that changed "
        "your hypothesis. The pipeline runner verifies each source_ref "
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
    cold_start: bool = Field(
        default=False,
        description="True when there is no prior experimental evidence (first "
        "iteration of a cold chain). Propagated from InterpretationOutput.cold_start. "
        "When True the proposer prompt states explicitly that no prior runs exist and "
        "asks for a first experiment grounded in the task contract, available "
        "model/loss registries (as options, not history), advice, and resource "
        "constraints — without claiming improvement over non-existent results.",
    )
    task_description: str = Field(
        default="",
        description="Plain-English description of the research task, sourced from "
        "``configs/task_config.yaml``. Injected into the ``{TASK_BACKGROUND}`` "
        "placeholder in the proposer system prompt and into ``template_vars`` "
        "for the proposal-stage ``.md`` templates. Default empty string is for "
        "test fixtures only; production callers (workflow) always populate via "
        "``get_task_description(load_task_config())`` which rejects empty values "
        "upstream.",
    )
    forward_contract: ForwardContract = Field(
        default_factory=ForwardContract,
        description="Typed forward-pass contract from ``configs/task_config.yaml``. "
        "Rendered into the ``{TASK_BACKGROUND}`` placeholder in the proposer "
        "system prompt and the ``{FORWARD_CONTRACT}`` placeholder in "
        "``proposing_stage.md``. Default ``ForwardContract()`` (all fields "
        "empty) is for test fixtures only; production callers always populate "
        'via ``ForwardContract(**load_task_config()["forward_contract"])``.',
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
    # baseline before emitting.
    # DS7 — the mirrored ``trial_strategy`` / ``target_files`` fields were
    # deleted: consumed by nobody (the round-3 audit found the pre-flight
    # synthesizes its sample set with a hardcoded snapshot strategy, and no
    # prompt template reads them). Old serialized inputs still validate.
    is_trial: bool = Field(
        default=False,
        description="Whether the run uses trial (sparse) sampling. Forwarded to "
        "build_sample_set inside the proposer's evaluate_time_skill gate "
        "so it matches what the tuner will run.",
    )
    trial_portion: float = Field(
        default=0.1,
        ge=0.01,
        le=1.0,
        description="Fraction of segments per file for the training scope. "
        "Mirrors HyperparamTuningInput.trial_portion.",
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
    # NOTE: ProposalInput.expert_advice was hard-removed in Commit P-d.
    # Rationale: for the Proposal node specifically, human directives and
    # external agent findings are parallel inputs at the same level — both
    # flow through `expert_context` with `agent_cards` for trust calibration,
    # and the proposer treats them uniformly. The `expert_advice` raw-string
    # pattern still applies to nodes that receive human guidance only
    # (Interpretation / Implementor / Validator / HyperparamTune); once a
    # node needs to synthesize multiple external sources, `expert_context`
    # supersedes it. See docs/soft_edge_for_all_nodes.md "Exceptions" for
    # the cross-cutting note.
    human_advice: ExpertAdviceInput | None = Field(
        default=None,
        description="DEPRECATED — use expert_context instead. Legacy human-provided guidance. "
        "When present, the protocol wraps it into an ExpertContextItem with "
        "source='human', kind='human'. Accepts a plain string or ExpertAdvice object.",
    )
    expert_context: list[ExpertContextItem] = Field(
        default_factory=list,
        description="Polymorphic upstream context — human advice, agent findings, etc. "
        "Each item carries a source, kind, content, and source_ref for attribution. "
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
        "Empty = no external agents this round (internal-only run). "
        "When a facilitator agent is used to combine multiple external agents' "
        "outputs, include the cards of the original agents (not the facilitator's "
        "own card) so the proposer can calibrate trust per source. The "
        "facilitator's synthesis is reflected in the ExpertContextItem list, "
        "not in this field.",
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
    custom_loss_spec: CustomLossSpec | None = Field(
        default=None,
        description="Specification for a novel loss function to be generated "
        "by the implementor at L4. When set, "
        "``baseline_config['loss_config']['loss_type']`` MUST be ``'custom'`` "
        "AND ``baseline_config['loss_config']['loss_name']`` MUST equal "
        "``custom_loss_spec.loss_name`` — enforced by "
        "``_validate_custom_loss_spec_consistency``. When ``None``, the "
        "proposer is using one of the four built-in loss types and no "
        "implementor loss-generation step is triggered.",
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

    @model_validator(mode="after")
    def _validate_custom_loss_spec_consistency(self):
        """Enforce the round-trip contract between ``custom_loss_spec`` and
        ``baseline_config['loss_config']``.

        Two failure modes this catches:
          1. ``custom_loss_spec`` set but ``baseline_config`` does not declare
             ``loss_type='custom'`` — the implementor would generate the
             plugin but training would never route to it.
          2. ``loss_name`` mismatch between the spec and the baseline — the
             implementor would write ``foo.py`` but training would try to
             load ``bar``.

        No-op when ``custom_loss_spec is None`` (back-compat with all
        existing built-in-loss proposals) or when ``baseline_config`` lacks
        a ``loss_config`` dict (some legacy test fixtures pass
        ``baseline_config={}``; that path is still routed through built-in
        defaults at the executor layer).
        """
        if self.custom_loss_spec is None:
            return self
        loss_cfg = self.baseline_config.get("loss_config") if self.baseline_config else None
        if not isinstance(loss_cfg, dict):
            raise ValueError(
                "custom_loss_spec is set but baseline_config['loss_config'] is "
                "missing or not a dict. When proposing a custom loss, "
                "baseline_config must include a loss_config dict with "
                "loss_type='custom' and loss_name matching "
                "custom_loss_spec.loss_name."
            )
        baseline_loss_type = loss_cfg.get("loss_type")
        if baseline_loss_type != "custom":
            raise ValueError(
                f"custom_loss_spec is set but "
                f"baseline_config['loss_config']['loss_type'] is "
                f"{baseline_loss_type!r}, not 'custom'. When proposing a "
                f"custom loss, baseline_config['loss_config']['loss_type'] "
                f"must be 'custom' so the executor routes through the "
                f"agent-generated plugin instead of a built-in loss."
            )
        baseline_loss_name = loss_cfg.get("loss_name")
        if baseline_loss_name != self.custom_loss_spec.loss_name:
            raise ValueError(
                f"baseline_config['loss_config']['loss_name'] "
                f"({baseline_loss_name!r}) does not match "
                f"custom_loss_spec.loss_name "
                f"({self.custom_loss_spec.loss_name!r}). These must match — "
                f"the spec defines the plugin to generate; the baseline "
                f"config selects which plugin to load at training time."
            )
        return self

    @model_validator(mode="after")
    def _validate_branch_b_registry_membership(self, info):
        """Reject phantom Branch B at schema-validation time when caller
        provides the loss registry as Pydantic context.

        Branch B (reuse a previously-generated custom loss) is the proposer
        choice when ``loss_type='custom'`` AND ``loss_name`` is set AND
        ``custom_loss_spec is None``. It is only legal when ``loss_name``
        appears in the capability registry; otherwise the implementor and
        downstream training have no plugin to load and will fail.

        Gate 2 + Gate 3 (2026-06-22) both reproduced the same failure mode:
        the proposer LLM (gpt-5.4) emits Branch C *in intent* (motivation
        text says "register custom_loss_spec for that loss") but the agent
        was silently dropping ``custom_loss_spec`` from the LLM raw
        response. Even after that extraction bug is fixed, this validator
        catches the regression where the LLM forgets to populate
        ``custom_loss_spec`` and emits a phantom Branch B — diagnosed *at
        the same LLM call* so LLMBridge's schema-retry loop re-prompts
        immediately, rather than waiting for the workflow-level retry one
        attempt later.

        Activated only when the caller passes ``context={"loss_registry_names":
        [...]}`` to ``model_validate``. With no context (e.g. unit tests
        building ``ProposalOutput`` directly), this is a no-op — preserving
        back-compat with all existing fixtures.
        """
        if self.custom_loss_spec is not None:
            return self  # Branch C — consistency validator above handles this.
        loss_cfg = self.baseline_config.get("loss_config") if self.baseline_config else None
        if not isinstance(loss_cfg, dict):
            return self
        if loss_cfg.get("loss_type") != "custom":
            return self  # Branch A — built-in loss, no registry check needed.
        loss_name = loss_cfg.get("loss_name")
        if not loss_name:
            raise ValueError(
                "baseline_config['loss_config']['loss_type'] is 'custom' but "
                "loss_name is missing or empty. Branch A (built-in) does not "
                "use 'custom'; Branch B (reuse) requires loss_name to match a "
                "registry entry; Branch C (new) requires both loss_name AND a "
                "populated top-level custom_loss_spec object. Pick one."
            )
        ctx = (info.context or {}) if info is not None else {}
        registry_names = ctx.get("loss_registry_names")
        if registry_names is None:
            return self  # No context — schema can't verify Branch B vs phantom.
        if loss_name in registry_names:
            return self  # Legitimate Branch B reuse.
        # Phantom Branch B — name not in the registry.
        registry_display = (
            "no losses registered yet" if not registry_names else f"only {sorted(registry_names)!r}"
        )
        raise ValueError(
            f"Phantom Branch B detected: loss_type='custom' + "
            f"loss_name={loss_name!r} + custom_loss_spec=None implies you "
            f"intend to REUSE an existing registered loss (Branch B), but "
            f"the loss registry contains {registry_display}. This is the "
            f"single most common LLM mistake on the loss-inventory surface — "
            f"the typical INTENT is Branch C (generate a NEW loss), but the "
            f"emitted SHAPE is Branch B (reuse). To fix: either (Branch C) "
            f"populate the top-level custom_loss_spec object with loss_name="
            f"{loss_name!r}, description, mathematical_definition, and "
            f"config_fields; OR (Branch A) set loss_type to one of 'focal', "
            f"'focal_cw', 'ce', 'smooth_l1' and remove loss_name. Do NOT "
            f"submit Branch B with a loss_name that is not in the registry."
        )

    @model_validator(mode="after")
    def _validate_branch_b_model_registry_membership(self, info):
        """Reject phantom Branch B for the MODEL surface — symmetric to
        ``_validate_branch_b_registry_membership`` above for losses.

        Branch B for model (reuse a previously-generated model plugin) is
        the proposer choice when ``baseline_config['model_config']['model_name']``
        is set. Branch A (built-in model) and Branch C (generate new) both
        leave ``model_name`` unset. It is only legal when ``model_name``
        appears in the model capability registry; otherwise the implementor
        and downstream training have no plugin to load and will fail.

        Activated only when the caller passes ``context={"model_registry_names":
        [...]}`` to ``model_validate``. With no context (e.g. unit tests
        building ``ProposalOutput`` directly), this is a no-op — preserving
        back-compat with all existing fixtures.

        See the loss-side validator above for the design rationale; the
        gate-2/gate-3 LLM failure mode (Branch C in intent, Branch B in
        shape) applies to the model surface for the same reason.
        """
        model_cfg = self.baseline_config.get("model_config") if self.baseline_config else None
        if not isinstance(model_cfg, dict):
            return self
        model_name = model_cfg.get("model_name")
        if not model_name:
            return self  # Branch A or Branch C — no registry check needed.
        ctx = (info.context or {}) if info is not None else {}
        registry_names = ctx.get("model_registry_names")
        if registry_names is None:
            return self  # No context — schema can't verify Branch B vs phantom.
        if model_name in registry_names:
            return self  # Legitimate Branch B reuse.
        # Phantom Branch B — name not in the registry.
        registry_display = (
            "no models registered yet" if not registry_names else f"only {sorted(registry_names)!r}"
        )
        raise ValueError(
            f"Phantom Branch B detected (model surface): "
            f"baseline_config['model_config']['model_name']={model_name!r} "
            f"implies you intend to REUSE an existing registered model "
            f"(Branch B), but the model registry contains "
            f"{registry_display}. To fix: either (Branch C) leave "
            f"model_name unset and describe the new architecture so the "
            f"implementor generates a fresh plugin; OR (Branch A) leave "
            f"model_name unset and set model_type to a built-in name "
            f"(e.g. 'wavenet', 'punet'); OR (Branch B) set model_name to "
            f"a value that actually appears in the model registry. Advice-"
            f"file model-name suggestions are not registry entries — they "
            f"only become registered after a prior iteration successfully "
            f"generated them via Branch C."
        )
