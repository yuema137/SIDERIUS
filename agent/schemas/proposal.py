# agent/schemas/proposal.py
"""
Input and output schemas for ml_model_proposal_agent.

This node consumes InterpretationOutput and produces a full model specification —
mathematical definition, model name, motivation, and structured expert advice —
for consumption by both ml_model_implementor and tune_ml_hyperparam_agent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

from agent.schemas.hyperparam_tuning import ExpertAdvice, ExpertAdviceInput
from agent.schemas.storage import StorageConfig, LocalStorageConfig


# ---------------------------------------------------------------------------
# Phase B schemas — three-stage reasoning pipeline
# See docs/adaptive_new_model_proposer.md §2A, §2B, §2D
# ---------------------------------------------------------------------------

# B.1 — Falsifiable prediction
class FalsifiablePrediction(BaseModel):
    """A concrete numerical prediction tied to a measurable metric.

    The reflector checks this prediction after the experiment runs and
    labels the hypothesis 'confirmed' / 'refuted' / 'partial' (Phase E).
    """
    metric: str = Field(
        description="What to measure. Free-text, guided by expert advice. "
                    "Examples: 'mean(file_vector[0:5])', 'denoising_score', "
                    "'file_vector[17]'. The reflector evaluates the prediction "
                    "by computing the metric from the actual results."
    )
    current_value: float = Field(
        description="The SOTA's current value for this metric."
    )
    predicted_value: float = Field(
        description="What the new model should achieve."
    )
    threshold_for_refutation: float = Field(
        description="Below this value, the hypothesis is considered refuted. "
                    "Must be on the same side of current_value as predicted_value "
                    "(i.e. if predicting improvement, threshold < current)."
    )
    rationale: str = Field(
        description="One sentence: why this specific predicted value."
    )

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
    from_model_type: str = Field(
        description="The ancestor model_type, e.g. 'wavenet'."
    )
    from_run: Optional[str] = Field(
        default=None,
        description="The specific run where this component first proved out. "
                    "None for built-in models."
    )
    contribution_evidence: str = Field(
        max_length=300,
        description="One sentence linking the component to its measured benefit."
    )
    citation_source: Optional[str] = Field(
        default=None,
        description="cite_id of the ExpertContextItem that motivated inheriting "
                    "this component. None = driven purely by experiment records."
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
    kind: Literal["empirical", "theoretical", "literature", "human", "narrative"] = Field(
        description="What type of context this is."
    )
    content: str = Field(
        max_length=4000,
        description="The actual advice / finding / constraint."
    )
    cite_id: str = Field(
        description="Short stable ID the proposal agent can reference in its "
                    "DiscoveryMemo.citation_sources."
    )
    produced_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp of when the finding was produced."
    )
    confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Optional self-reported confidence from the producing agent."
    )


# B.4 — Model comparison (Stage 1 output)
class ModelComparison(BaseModel):
    """Structured analysis of one previously tested model.

    Produced by the comparison stage (Stage 1) of the reasoning pipeline.
    The reasoning stage (Stage 2) reads these to form its causal hypothesis.
    """
    model_type: str
    source: str = Field(
        description="'seed' or 'proposed_iter_N'."
    )
    best_score: float
    key_mechanism: str = Field(
        max_length=300,
        description="One sentence: what makes this model tick (or not). "
                    "Must reference a specific architectural feature or concept."
    )
    strengths: List[str] = Field(
        description="What this model does well, tied to file_vector or score evidence."
    )
    weaknesses: List[str] = Field(
        description="Where this model fails, tied to file_vector or score evidence."
    )
    lesson_for_next_proposal: str = Field(
        max_length=300,
        description="What to inherit or avoid from this model."
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
    feature: str = Field(
        description="The feature entry name, e.g. 'dilated_causal_conv'."
    )
    capability: str = Field(
        description="The capability entry name, e.g. 'receptive_field'."
    )
    evidence: str = Field(
        max_length=300,
        description="Why the agent thinks this link exists — must reference "
                    "specific model results or architectural analysis."
    )
    status: Literal["proposed", "confirmed", "refuted"] = Field(
        default="proposed",
        description="Lifecycle: proposed → confirmed/refuted after experiment.",
    )


# B.5 — Discovery memo (output of Stages 1+2, input to Stage 3)
class DiscoveryMemo(BaseModel):
    """The structured output of the reasoning pipeline (comparison + reasoning
    stages). The 'Final Verdict' that forces the LLM to articulate WHY
    before WHAT. Stage 3 (proposing) is structurally tethered to this memo.

    See §2A of the V2 design doc.
    """
    # --- Comparative analysis (Stage 1 output) ---
    comparative_analysis: List[ModelComparison] = Field(
        description="Systematic comparison of selected past models."
    )
    sota_model_type: str = Field(
        description="The current best-scoring model, identified from the comparisons."
    )
    sota_score: float
    sota_mechanism: str = Field(
        max_length=600,
        description="WHY does the SOTA work? Must reference physical/architectural "
                    "mechanism, not vague language."
    )

    # --- Causal reasoning (Stage 2 output) ---
    proposed_change: str = Field(
        max_length=400,
        description="What the new proposal changes RELATIVE TO the SOTA. "
                    "Must be expressible as 'replace X with Y' or 'add Z'."
    )
    causal_hypothesis: str = Field(
        max_length=600,
        description="WHY the proposed change should improve the score. "
                    "Must reference the SOTA mechanism preserved, the bottleneck "
                    "relaxed, and the new mechanism introduced."
    )

    # --- Falsifiable prediction ---
    falsifiable_prediction: FalsifiablePrediction

    # --- Devil's advocate ---
    predicted_failure_modes: List[str] = Field(
        min_length=1, max_length=3,
        description="At least one way the proposal could fail."
    )

    # --- Lineage ---
    inherited_components: List[InheritedComponent] = Field(
        default_factory=list,
    )

    # --- Vocabulary candidates discovered during comparison ---
    proposed_vocab_candidates: List[Dict[str, str]] = Field(
        default_factory=list,
        description="New features or capabilities the comparison stage discovered "
                    "that aren't in the current vocabulary. Each entry has "
                    "'name', 'kind' (feature/capability), 'description'. "
                    "These enter the candidate pool for future promotion."
    )

    # --- Feature → capability link hypotheses ---
    proposed_vocab_links: List[ProposedVocabLink] = Field(
        default_factory=list,
        description="Hypothesized connections between features and capabilities. "
                    "Proposed by the comparison stage, tested via the "
                    "FalsifiablePrediction, confirmed/refuted by the reflector. "
                    "Only confirmed links get promoted to VocabEntry.related_to."
    )

    # --- Citations ---
    citation_sources: List[str] = Field(
        default_factory=list,
        description="cite_id values of ExpertContextItems that materially "
                    "shaped this memo."
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
        default="top_n",
        description="'top_n', 'all', 'feature_match', or 'human_specified'."
    )
    params: Dict[str, Any] = Field(
        default_factory=lambda: {"n": 10},
    )


class ReasoningPipelineConfig(BaseModel):
    """Configurable reasoning pipeline. Lives at the workflow level."""
    stages: List[ReasoningStage] = Field(
        default_factory=lambda: [
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ],
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
    description: str = Field(max_length=200)
    related_to: List[str] = Field(
        default_factory=list,
        description="Names of connected VocabEntry items. "
                    "Feature→concept and concept→feature links."
    )
    tier: Literal["canonical", "candidate"] = "candidate"
    pattern: Optional[str] = Field(
        default=None,
        description="AST/regex for features. None for concepts."
    )
    proposed_by_run: Optional[str] = None
    seen_in_runs: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Existing schemas (ProposalInput / ProposalOutput)
# ---------------------------------------------------------------------------

class ProposalInput(BaseModel):
    """
    Input to ml_model_proposal_agent.

    Typically populated via the interpretation_to_proposal_v1 protocol,
    which maps InterpretationOutput → ProposalInput.
    """

    interpretation: Dict[str, Any] = Field(
        description="Serialised InterpretationOutput — key findings, bottlenecks, "
                    "and take-home message from result_interpretation_agent.",
    )
    existing_model_types: List[str] = Field(
        default_factory=list,
        description="Model type keys already registered in MODEL_REGISTRY. "
                    "The proposal agent must not reuse any of these names.",
    )
    constraints: List[str] = Field(
        default_factory=list,
        description="Hard limits the proposed architecture must respect "
                    "(e.g. 'VRAM < 10 GB', 'params < 50M', 'no external dependencies').",
    )
    expert_advice: ExpertAdviceInput = Field(
        default="",
        description="Structured guidance from upstream agents or orchestrators. "
                    "Accepts a plain string or a structured ExpertAdvice object.",
    )
    human_advice: Optional[ExpertAdviceInput] = Field(
        default=None,
        description="DEPRECATED — use expert_context instead. Legacy human-provided guidance. "
                    "When present, the protocol wraps it into an ExpertContextItem with "
                    "source='human', kind='human'. Accepts a plain string or ExpertAdvice object.",
    )
    expert_context: List[ExpertContextItem] = Field(
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
    vocab_seed: List[VocabEntry] = Field(
        default_factory=list,
        description="The runtime vocabulary available to the reasoning pipeline. "
                    "In production, populated by the interpretation agent via the "
                    "protocol (canonical seed + promoted candidates + active candidates). "
                    "For standalone use, load from agent/schemas/vocab_seed.json. "
                    "Empty list = vocabulary features disabled (backward compat).",
    )
    previous_failures: List[str] = Field(
        default_factory=list,
        description="Validation error messages from previous failed attempts in this "
                    "iteration. The workflow populates this when retrying after a "
                    "validation failure so the proposal agent avoids the same mistakes. "
                    "Each entry is the error_message from a ValidatorOutput.",
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
    baseline_config: Dict[str, Any] = Field(
        description="A safe, moderate starting configuration for this architecture. "
                    "Should use a conservative parameter count and GPU memory footprint "
                    "suitable for initial exploration. "
                    "Must include model_config, train_config, and loss_config keys.",
    )
