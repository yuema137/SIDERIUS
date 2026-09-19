# agent/schemas/interpretation.py
"""
Input and output schemas for result_interpretation_agent.

This node consumes run-level summaries (one per model) and produces a structured
interpretation — key findings, bottlenecks, and a take-home message — for
consumption by ml_model_proposal_agent.

InterpretationInput accepts:
  - summaries: a list of ModelRunSummary objects (one per model)
  - model_types: an explicit list of model types whose descriptions to include
  - Either summaries or model_types must be non-empty (or both)

ModelRunSummary is a condensed view of a HyperparamTuningOutput — it contains
the run-level aggregates (best/worst score, best config, status) and a condensed
per-round trajectory (scores + conclusions), but NOT the raw experiment records.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.prompt_templates.timing_attribution import TIMING_SPLIT_SEMANTICS
from agent.schemas.data_analysis.access import AnalysisAccessPolicy
from agent.schemas.data_analysis.context import AnalysisBrief
from agent.schemas.health_feedback import (
    CollapseFingerprint,
    CollapseFingerprintHistoryEntry,
    HealthFeedbackRetentionPolicy,
    RoundHealth,
)
from agent.schemas.hyperparam_tuning import ExpertAdviceInput
from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.training_diagnosis import TrainingDiagnosis
from agent.schemas.vocab import VocabEntry
from execute_tools.evaluation_metric import (
    MetricDirection,
    MetricResult,
    MetricSpecField,
    NotScoreableResult,
)
from ml_models.model_descriptions import DescriptionSourcePolicy

# ---------------------------------------------------------------------------
# Prediction-accounting vocabulary — the ONE declaration (Step 09a C4, F-09a-17)
# ---------------------------------------------------------------------------
# These are framework-level contract values, not node policy: they are the
# literal keys of `InterpretationOutput.prediction_evaluation_semantics`,
# `prediction_outcomes_by_semantics` and `prediction_pool_sizes`, which this
# module declares. They live HERE because this is the lowest layer every
# consumer already depends on downward — the schema itself, the interpreter's
# `prediction.py` (which implements the v2 rule and re-exports these under the
# same names), `nodes/interpretation_helpers.py`, and `core/resume.py`. The
# reverse edge (schema -> node) would be a genuine import cycle, which is why
# the first implementation copied the literals instead; centralizing here
# removes the copies without adding a module or a layer.

#: Evaluation semantics implemented by `prediction.py`: direction read from the
#: bound metric via `MetricOrder`, band measured as a sign-safe distance.
PREDICTION_SEMANTICS_SIGNSAFE_V2 = "metric_order_signsafe_v2"

#: What an evaluation carrying no recorded semantics was produced under.
#: Absence means legacy; it is NEVER back-filled onto an old record, because
#: nobody can know which rule actually ran. This is the schema default.
PREDICTION_SEMANTICS_LEGACY_V1 = "legacy_v1"

#: The three COMPARABLE outcomes. `unevaluated` is deliberately not among them:
#: it is the absence of an observation, not a fourth verdict.
COMPARABLE_OUTCOMES = ("confirmed", "partial", "refuted")

#: The outcome recorded when the comparison could not be made at all.
OUTCOME_UNEVALUATED = "unevaluated"


class PredictionMemory(BaseModel):
    """The interpreter's prediction state, carried between iterations.

    Step 09a C5 (operator ruling Q-09a-1 = A, NARROW). Four digest fields
    travelling together because they are read and written together; NOT a
    second store. The canonical interpretation digest remains the ONE record,
    and this is the typed shape in which four of its keys ride the EXISTING
    lifecycle: digest -> workflow loop carry -> `RestoredState` latest-wins
    -> the next `InterpretationInput`.

    Why it had to be wired at all: at the pre-09a anchor NO production path
    carried or restored any of these (parent §0.3 erratum E2). Every
    production digest's pool therefore held exactly ONE outcome, and the
    proposer's "Prediction Track Record" always read N=1. Without C5 the
    versioned pools C4 introduced would be dead schema.

    The v1/v2 separation is preserved across the hop: the legacy pool and
    scalar travel beside the versioned ones and are never merged into them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prediction_outcomes_history: dict[str, int] = Field(
        default_factory=dict,
        description="The LEGACY v1 pool, carried verbatim and never incremented.",
    )
    prediction_outcomes_by_semantics: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Version-keyed comparable pools; the v2 key is the live one.",
    )
    cumulative_information_gain: float = Field(
        default=0.0,
        description="The LEGACY accumulated gain, preserved and never pooled with v2.",
    )
    cumulative_information_gain_by_semantics: dict[str, float] = Field(
        default_factory=dict,
        description="Version-keyed running gain sums.",
    )


class SecondaryMetricEvidence(BaseModel):
    """One DECLARED secondary metric and whatever is known about it.

    Step 09a C6 (parent §4b; operator ruling Q-09-7 = B). Secondaries are
    OBSERVATIONAL evidence only. Each carries its own identity and direction
    and is rendered with its own direction words; none of them ever affects
    primary ordering, incumbent selection, active-model selection, cache
    capping, the prediction default or prediction evaluation.

    The three states are distinguishable ON PURPOSE. "declared but not
    available" is a different fact from "not declared", and both are different
    from "refused by its scoreability contract". Collapsing them would let a
    renderer print a confident silence where a named absence belongs — the
    failure mode this whole step is about.

    Step 09a populates this from FIXTURES only. There is no record-level
    carrier to read: `ExperimentRecord.secondary_metric_results`,
    `secondary_metric_refusals` and `HyperparamTuningOutput.secondary_metric_specs`
    are Step 10's, and reading undeclared keys would be a hidden contract. The
    production builder therefore leaves this EMPTY rather than inventing
    placeholder numbers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: MetricSpecField = Field(
        description="The secondary metric's own declaration — its id and its OWN direction."
    )
    result: MetricResult | None = Field(
        default=None, description="Its value, when it was evaluated."
    )
    refusal: NotScoreableResult | None = Field(
        default=None, description="Its structured refusal, when the contract rejected the input."
    )

    @model_validator(mode="after")
    def _result_and_refusal_are_exclusive(self) -> SecondaryMetricEvidence:
        if self.result is not None and self.refusal is not None:
            raise ValueError(
                f"secondary metric {self.spec.id!r} carries both a result and a refusal; "
                "an evaluation either produced a value or refused to."
            )
        return self

    @property
    def status(self) -> str:
        """``scored`` | ``refused`` | ``unavailable`` — a NAMED absence."""
        if self.result is not None:
            return "scored"
        if self.refusal is not None:
            return "refused"
        return "unavailable"


class RecordFailureCounts(BaseModel):
    """What went wrong across one model's records, counted by EXISTING vocabularies.

    Step 09a C6 (parent §5). Deliberately NOT a new closed ``FailureKind``
    enum: the interpreter is a projection layer, and inventing its own failure
    taxonomy would mean a fourth task's novel pathology needs a SIDERIUS source
    change before it can be reported. Every key below comes from an authority
    that already owns it — ``ExperimentRecord.status``, ``TrainingDiagnosis``,
    ``ValidationState``, ``NotScoreableResult``'s contract id, and Health's
    ``GateAction`` / ``RoundHealth.provenance`` — so an unknown future value
    simply appears under its own key.

    Ids are OPAQUE: ``refusal_contract_ids`` is counted, never parsed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    records_total: int = Field(default=0)
    status_counts: dict[str, int] = Field(
        default_factory=dict, description="ExperimentRecord.status, verbatim."
    )
    diagnosis_state_counts: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "TrainingDiagnosis.state for records carrying one, plus "
            "'diagnosis_missing' for records with no diagnosis object at all — "
            "an absence, counted rather than silently folded into 'absent'."
        ),
    )
    validation_state_counts: dict[str, int] = Field(default_factory=dict)
    metric_refusal_count: int = Field(default=0)
    refusal_contract_ids: dict[str, int] = Field(
        default_factory=dict, description="Opaque contract ids, counted and never parsed."
    )
    gate_action_counts: dict[str, int] = Field(
        default_factory=dict, description="RoundHealth.gate_action; None is counted as 'none'."
    )
    health_provenance_counts: dict[str, int] = Field(default_factory=dict)


class MetricIdentity(BaseModel):
    """Which metric a number is on, and which way is better.

    Step 09a C2. Two fields, both read from an existing authority — never
    parsed, never inferred from a name. It appears in two roles that must not
    be confused (parent §4a):

    * on ``ModelRunSummary`` it is EVIDENCE — the identity the records were
      actually scored under, projected from their ``metric_result``;
    * on ``InterpretationOutput`` it is PROVENANCE — the identity the digest
      was actually ORDERED under, echoed from the run's bound ``MetricSpec``.

    Whenever both exist they must agree exactly; a disagreement is a contract
    error, never a silent preference for one source.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str = Field(description="The metric's stable id, carried verbatim and never parsed.")
    direction: MetricDirection = Field(
        description="'higher' or 'lower' — the ONLY thing ordering may read."
    )


class InterpretationTaskBlocks(BaseModel):
    """Task-owned interpretation guidance — prose VALUES under framework keys.

    Step 09b (parent §13 ¶3, Q-09-1 = B refined). The FRAMEWORK owns the key
    set and where each section renders (``evidence_reading`` in BOTH phase
    system prompts; ``per_model_guidance`` in Phase 1; ``synthesis_guidance``
    and ``prediction_guidance`` in Phase 2); the TASK owns the prose. Each
    field is optional: an absent section is a legal named absence and renders
    NOTHING — no header, no bytes. The interpreter never reads task files;
    the CALLER supplies this value (the workflow's bounded Regime-A adapter
    today, the Step-12 composition root later). Key-set growth is a framework
    protocol decision, never a per-task extension mechanism.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_reading: str | None = Field(
        default=None,
        description="How to read THIS task's evidence. Rendered in both phase system prompts.",
    )
    per_model_guidance: str | None = Field(
        default=None,
        description="Phase-1 per-model analysis guidance.",
    )
    synthesis_guidance: str | None = Field(
        default=None,
        description="Phase-2 cross-model synthesis guidance.",
    )
    prediction_guidance: str | None = Field(
        default=None,
        description=(
            "Prediction-interpretation guidance (Phase 2). The reference "
            "task's declaration supplies none today — absence is legal and "
            "renders nothing."
        ),
    )

    @model_validator(mode="after")
    def present_sections_are_non_empty(self) -> InterpretationTaskBlocks:
        """A present section must carry prose.

        An empty or whitespace-only string is a malformed declaration and is
        refused — never silently treated as absence, because a task that
        MEANT to supply guidance would otherwise render nothing without any
        signal. No other normalisation happens: prose bytes are preserved
        verbatim (the TIDMAD migration parity depends on it).
        """
        for name in (
            "evidence_reading",
            "per_model_guidance",
            "synthesis_guidance",
            "prediction_guidance",
        ):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(
                    f"InterpretationTaskBlocks.{name} is present but empty — supply prose or omit the section"
                )
        return self


class RoundOrdering(BaseModel):
    """What data ordering one round actually ran, and where it came from.

    Interpreter-facing view of the ordering provenance
    (``docs/design/v19_priorities/pr2_data_ordering.md`` §3.7). Two rules
    govern how downstream reasoning may use it:

    - ``resolved_*`` is the ONLY pair that describes execution. A proposal
      the operator overrode was not what ran, and must never be reported as
      though it were.
    - a REJECTED proposal is not the same as no proposal. The agent tried to
      steer this round and was overruled by validation; reading that as
      agent silence would misdescribe its behavior.

    Ordering can differ between rounds of one iteration (the agent may
    propose differently each round when no override is set), so these are
    carried per round rather than collapsed to one value for the run.
    """

    exp_id: str | None = Field(
        default=None,
        description="Experiment this ordering belongs to. None on legacy records.",
    )
    resolved_order_strategy: str | None = Field(
        default=None,
        description=(
            "The visitation order that ACTUALLY RAN for this round. None when "
            "nothing ran — i.e. resolution_source is 'not_executed', an "
            "attempt rejected at pre-flight. Downstream must not describe a "
            "None as having executed any ordering."
        ),
    )
    resolved_file_order: list[int] | None = Field(
        default=None,
        description="File order that actually ran; None when the strategy was 'shuffle'.",
    )
    resolution_source: str = Field(
        description=(
            "Which level decided it: 'operator_override', 'agent_proposal', "
            "or 'default' when an ordering actually ran; 'legacy_default' for "
            "a pre-ordering artifact; 'not_executed' for a current attempt "
            "rejected at pre-flight, where no ordering ran at all."
        ),
    )
    proposed_order_strategy: str | None = Field(
        default=None,
        description="What the agent proposed, rejected or not. None = it proposed nothing.",
    )
    proposal_rejected: bool = Field(
        default=False,
        description="True when a proposal arrived but was not applied.",
    )
    proposal_rejection_reason: str | None = Field(
        default=None,
        description="Why the proposal was not applied. None unless rejected.",
    )


class ModelRunSummary(BaseModel):
    """
    Condensed summary of one tuning run for one model type.

    Built from HyperparamTuningOutput by extracting aggregates and condensing
    per-round information. The raw experiment records are NOT included — only
    the score trajectory and one-line conclusions from each round.
    """

    model_type: str = Field(
        description="Architecture key (e.g. 'punet', 'fcnet').",
    )
    run_name: str = Field(
        description="Run identifier (e.g. 'v3_file6').",
    )
    status: str = Field(
        description="Run status: 'completed', 'partial', or 'failed'.",
    )
    completed_rounds: int = Field(
        description="Number of successfully completed experiment rounds.",
    )
    best_denoising_score: float | None = Field(
        default=None,
        description="Highest raw denoising score achieved in this run.",
    )
    best_valid_denoising_score: float | None = Field(
        default=None,
        description="Highest HealthGate-valid denoising score; None when none is valid.",
    )
    best_raw_health_validity: str = Field(
        default="unknown",
        description="Health validity of the raw-best record: valid, invalid, or unknown.",
    )
    worst_denoising_score: float | None = Field(
        default=None,
        description="Lowest denoising score achieved in this run (excluding OOM-skipped).",
    )
    best_config: dict[str, Any] | None = Field(
        default=None,
        description="The params dict (model_config, train_config, loss_config) "
        "that produced the best denoising score.",
    )
    best_valid_config: dict[str, Any] | None = Field(
        default=None,
        description="Config that produced the highest HealthGate-valid score.",
    )
    round_scores: list[float | None] = Field(
        default_factory=list,
        description="Denoising score per round in chronological order. "
        "None entries indicate OOM-skipped or failed rounds.",
    )
    round_conclusions: list[str] = Field(
        default_factory=list,
        description="One-line conclusion from each round's LLM reflection. "
        "Extracted from the 'memory.conclusion' field of each record.",
    )
    round_ordering: list[RoundOrdering] = Field(
        default_factory=list,
        description="Data ordering that actually ran, per round, in the same "
        "chronological order as round_scores. Kept per round because ordering "
        "may legitimately differ between rounds when no operator override is "
        "in force. Empty on runs that predate the ordering option.",
    )
    round_health: list[RoundHealth] = Field(
        default_factory=list,
        description="Condensed HealthGate evidence per round, in the same "
        "chronological order as round_scores (V19 PR 3, "
        "docs/design/v19_priorities/pr3_healthgate_feedback.md §3.2). Built "
        "deterministically from each record's persisted gate fields under "
        "the evidence-precedence rule — never from LLM prose. Provenance "
        "labels the evidence source (gated / gates_disabled / "
        "round_fields_only / gate_not_evaluated / legacy); a round without "
        "evidence is carried labeled, never guessed at. Empty on summaries "
        "built before this field existed.",
    )
    model_description: str | None = Field(
        default=None,
        description="Architecture description (markdown + math). For built-in models "
        "this is loaded from description.md by the interpretation agent. "
        "For agent-generated models, the workflow passes it directly so "
        "the interpretation agent doesn't need filesystem access.",
    )

    # --- Per-file performance (from file_vector) ---
    best_file_vector: list[float | None] | None = Field(
        default=None,
        description="Score vector from the best experiment, one entry per validation "
        "file. None for files not evaluated. Per-file semantics are defined "
        "by the dataset configuration; the agent reads opportunity from the "
        "Impact_Score column rather than fixed file-index labels.",
    )
    formal_score: float | None = Field(
        default=None,
        description="Denoising score from the formal (final) round specifically. "
        "Distinct from best_denoising_score which may come from a trial round.",
    )
    best_valid_formal_score: float | None = Field(
        default=None,
        description="Highest HealthGate-valid formal score; None when none is valid.",
    )
    scientific_authority: dict[str, Any] | None = Field(
        default=None,
        description=(
            "V20 PR D (D-C5) — the authority verdict of the FORMAL record "
            "this summary's `formal_score` came from "
            "(core.scientific_authority.ScientificAuthority.model_dump()). "
            "Decides whether this model's formal result may inform a "
            "scientific aggregate; `execute_tools.scientific_aggregation` "
            "consumes it. None on a summary with no formal record, and on "
            "summaries predating the field — both of which are EXCLUDED "
            "from aggregation, because authority that cannot be established "
            "is not authority. HealthGate validity is a different question: "
            "a diagnostic run's formal record can be perfectly valid and "
            "still carry no scientific authority."
        ),
    )
    formal_file_vector: list[float | None] | None = Field(
        default=None,
        description="File vector from the formal round. Definitive per-file performance.",
    )

    # --- Enriched per-file tables (file_vector + baseline + ground truth) ---
    best_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description="ScoreComparisonTable for the best experiment — the enriched "
        "view of best_file_vector alongside raw_baseline and "
        "ground_truth columns with pre-rendered markdown. "
        "Downstream agents prefer this over best_file_vector.",
    )
    best_valid_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description="Score table for the highest HealthGate-valid experiment.",
    )
    formal_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description="ScoreComparisonTable for the formal (final) round. "
        "Definitive enriched per-file view without the trial-subset caveat.",
    )

    # --- Model efficiency ---
    best_model_params: int | None = Field(
        default=None,
        description="Number of trainable parameters in the best-scoring model.",
    )

    # --- Compute cost ---
    best_timing: dict[str, Any] | None = Field(
        default=None,
        description="Timing dict from the best experiment: "
        "train_time_s, validation_time_s, inference_time_s, scoring_time_s. "
        "Used to generate timing discoveries and warn the planner. "
        "F-SCANE-3; N-4 for what the split means: " + TIMING_SPLIT_SEMANTICS + " "
        "`validation_time_s` is `None` where the producer recorded no split, "
        "never 0.0.",
    )

    # --- Data volume context ---
    training_psd_segments: int | None = Field(
        default=None,
        description="PSD segments used for training in the best experiment. "
        "Compare against baseline (typically 4000) to assess data sufficiency.",
    )
    eval_psd_segments: int | None = Field(
        default=None,
        description="PSD segments used for evaluation in the best experiment.",
    )
    trial_portion: float | None = Field(
        default=None,
        description="Trial portion used in the best experiment (if trial mode).",
    )

    # --- Per-round detail (for trend analysis) ---
    round_trial_portions: list[float | None] | None = Field(
        default=None,
        description="Trial portion used in each round. Shows if the agent adapted data volume.",
    )
    round_model_params: list[int | None] | None = Field(
        default=None,
        description="Model parameter count per round. Shows if the agent explored model sizes.",
    )

    # --- Evidence-borne metric identity (Step 09a C2) ---
    metric_identity: MetricIdentity | None = Field(
        default=None,
        description=(
            "The metric identity the records behind this summary were actually "
            "scored under, projected from their MetricResult. Every scored record "
            "in one tuning output must agree, or the builder refuses. None when no "
            "record carries a MetricResult (outputs predating Step 06). This is "
            "EVIDENCE; the run's bound MetricSpec is what ORDERS — they are "
            "checked against each other, never substituted for each other."
        ),
    )

    # --- Deterministic evidence projection (Step 09a C6) ---
    best_training_diagnosis: TrainingDiagnosis | None = Field(
        default=None,
        description=(
            "Step 09a — the 07a diagnosis of the record the summary's BEST score "
            "came from, carried verbatim. Before this the interpreter could see "
            "that a score existed but nothing about how the training that "
            "produced it behaved. None on records predating 07a or without a "
            "diagnosis."
        ),
    )
    formal_training_diagnosis: TrainingDiagnosis | None = Field(
        default=None,
        description=(
            "Step 09a — the same, for the FORMAL record. Two roles, two "
            "diagnoses: a best trial round and the formal round are different "
            "experiments and may have behaved differently."
        ),
    )
    secondary_metrics: list[SecondaryMetricEvidence] = Field(
        default_factory=list,
        description=(
            "Step 09a — declared secondary metrics, present-when-present. "
            "OBSERVATIONAL only: never consulted for ordering, incumbent or "
            "active-model selection, cache capping, or prediction. EMPTY in "
            "production until Step 10 lands the record-level carrier and the "
            "tuner-side evaluation (Q-09-7 = B) — the builder does not invent "
            "values, and a declared-but-unavailable secondary is a NAMED absence."
        ),
    )
    failure_counts: RecordFailureCounts | None = Field(
        default=None,
        description=(
            "Step 09a — what went wrong across this model's records, counted by "
            "vocabularies that already exist. No new failure enum: the "
            "interpreter reports what the authorities state."
        ),
    )


class InterpretationInput(BaseModel):
    """
    Input to result_interpretation_agent.

    Accepts run-level summaries from one or more models. Each summary is a
    condensed view of a tuning run — NOT the raw experiment records.

    Constraint: at least one model type must be reachable — either derived from
    summaries or listed explicitly in model_types.
    """

    summaries: list[ModelRunSummary] = Field(
        default_factory=list,
        description="Condensed summaries for NEW models only — models being interpreted "
        "for the first time this iteration. Models already in model_knowledge_cache "
        "do not need a summary here; Phase 1 will use the cache instead. "
        "On the first iteration, pass all seed model summaries (cache is empty).",
    )
    model_knowledge_cache: dict[str, Any] = Field(
        default_factory=dict,
        description="Carry-forward cache from the previous InterpretationOutput.model_knowledge_cache. "
        "Each entry is self-sufficient: Phase 1 LLM text + '_stats' with numerical facts. "
        "Agent skips Phase 1 LLM calls for models present here. "
        "Empty on the first iteration.",
    )
    model_types: list[str] | None = Field(
        default=None,
        description="Explicit list of model types whose descriptions to include. "
        "When None, model types are derived from summaries. "
        "Cannot be an empty list — use None to derive from summaries.",
    )
    cold_start: bool = Field(
        default=False,
        description="Explicit cold-start state. True means this is the first "
        "iteration of a chain with NO prior experimental evidence (no seeds, no "
        "committed prior iters, empty cache). Set by the workflow — never inferred "
        "downstream from missing prompt text. When True, require_at_least_one_model "
        "permits an empty model set and the interpreter renders explicit 'no prior "
        "evidence' language instead of ranking non-existent history. Registries "
        "remain available options, not historical runs.",
    )
    baseline_isolation: bool = Field(
        default=False,
        description="arXiv U3 (#260 / ruling R6) — the explicit, recorded flag of "
        "the WITHOUT arm. When True the interpreter refuses to load a BUNDLED "
        "built-in description (ml_models/*/description.md) and therefore never "
        "carries one into the model_knowledge_cache `_stats`; plugin and "
        "workspace descriptions resolve as before. Set by the workflow from its "
        "launch config; the lock pins the same value.",
    )
    description_source_policy: DescriptionSourcePolicy = Field(
        default=DescriptionSourcePolicy.LEGACY,
        description=(
            "Typed description-source authority. Composed inputs explicitly "
            "exclude packaged model descriptions and permit authorized absence."
        ),
    )
    task_description: str = Field(
        default="",
        description="Plain-English description of the research task, sourced from "
        "``configs/task_config.yaml``. Injected into the ``{TASK_DESCRIPTION}`` "
        "placeholder in both ``PER_MODEL_SYSTEM_PROMPT`` and "
        "``SYNTHESIS_SYSTEM_PROMPT`` at call time. Default empty string is for "
        "test fixtures only; production callers (workflow) always populate via "
        "``get_task_description(load_task_config())`` which rejects empty values "
        "upstream. The interpreter only needs the description (not the full "
        "forward contract) — its job is reading run summaries and synthesizing "
        "findings, not designing models.",
    )
    expert_advice: ExpertAdviceInput = Field(
        default="",
        description="Structured guidance from upstream agents or orchestrators. "
        "Accepts a plain string or a structured ExpertAdvice object.",
    )
    human_advice: str | None = Field(
        default=None,
        description="Optional human-provided guidance (highest priority — overrides expert_advice). "
        "When present, injected into the LLM prompt as high-priority context.",
    )
    analysis_brief_requested: bool = Field(
        default=False,
        exclude_if=lambda value: value is False,
        description=(
            "Whether this invocation should run the optional separate AnalysisBrief "
            "generation stage after legacy interpretation. False preserves the legacy "
            "prompt, response contract, call count and serialized input identity."
        ),
    )
    analysis_access_policy: AnalysisAccessPolicy | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Caller-bound evidence permissions for optional AnalysisBrief questions. "
            "This is reasoning context, not a grant of access or an executable plan."
        ),
    )
    # --- Vocabulary feedback (Phase C) ---
    runtime_vocab: list[VocabEntry] = Field(
        default_factory=list,
        description="Current vocabulary (seed + candidates + discoveries) from "
        "previous iterations. Empty on first iteration (uses seed). "
        "This IS the compressed memory of iterations 0..N-2.",
    )
    previous_proposal: dict[str, Any] | None = Field(
        default=None,
        description="Serialized ProposalOutput from the previous iteration. "
        "Contains falsifiable_prediction, proposed_vocab_links, "
        "inherited_components. None on the first iteration.",
    )

    # --- Centrifugal metrics (carried forward across iterations) ---
    cumulative_information_gain: float = Field(
        default=0.0,
        description="Sum of information_gain from all previous iterations. "
        "Carries forward the history of how many bold predictions were confirmed. "
        "Populated by the previous InterpretationOutput.cumulative_information_gain "
        "via the workflow's carry-forward logic. Zero on the first iteration.",
    )

    # --- Scientific accuracy (carried forward across iterations) ---
    prediction_outcomes_history: dict[str, int] = Field(
        default_factory=lambda: {"confirmed": 0, "partial": 0, "refuted": 0},
        description="Running count of each prediction outcome across all past iterations. "
        "Carry forward from InterpretationOutput.prediction_outcomes_history. "
        "Zero on first iteration.",
    )

    # --- Vocab link promotion tracking (carried forward across iterations) ---
    vocab_link_confirmations: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Carry-forward mapping: 'feature:capability' → list of run_names "
        "where that link was confirmed. Populated by "
        "InterpretationOutput.vocab_link_confirmations. Empty on first iteration.",
    )

    # --- Structured HealthGate feedback (V19 PR 3 —
    #     docs/design/v19_priorities/pr3_healthgate_feedback.md §3.6/§3.8/§3.9) ---
    enable_structured_health_feedback: bool = Field(
        default=False,
        description="Gates the PROMPT rendering of structured HealthGate "
        "evidence (§3.6 trajectory labels, HealthGate summary section, "
        "system-prompt instruction block). OFF (default): prompts are "
        "byte-identical to the pre-PR3 condition. The OUTPUT fields below "
        "are populated deterministically REGARDLESS of this flag "
        "(recording-only provenance). Part of the run-invariants lock — "
        "flipping it mid-workspace is rejected at startup.",
    )
    collapse_fingerprint_history: dict[str, list[CollapseFingerprintHistoryEntry]] = Field(
        default_factory=dict,
        description="Carry-forward from the previous "
        "InterpretationOutput.collapse_fingerprint_history: model_type → "
        "bounded per-iteration occurrence history of collapse fingerprints. "
        "Deterministic data — never LLM-derived. Empty on the first "
        "iteration and on legacy digests without the field.",
    )
    health_feedback_history_window_iterations: int = Field(
        default=3,
        ge=1,
        description="Retention window for the fingerprint history: the TOTAL "
        "number of iterations retained INCLUDING the current one "
        "(minimum_retained_iter = current_iter - window + 1). Part of the "
        "run-invariants lock. Follows the active_model_* typed-knob "
        "convention; consumed as a resolved HealthFeedbackRetentionPolicy, "
        "never as a module constant.",
    )
    health_feedback_history_max_entries_per_model: int = Field(
        default=8,
        ge=1,
        description="Deterministic trim bound on retained fingerprint history "
        "entries per model. Part of the run-invariants lock.",
    )

    def health_feedback_retention_policy(self) -> HealthFeedbackRetentionPolicy:
        """The RESOLVED retention policy (design §3.8) — the single object
        renderers and the history merge consume."""
        return HealthFeedbackRetentionPolicy(
            history_window_iterations=self.health_feedback_history_window_iterations,
            max_entries_per_model=self.health_feedback_history_max_entries_per_model,
        )

    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node reads its inputs and writes its interpretation output.",
    )

    # --- Iteration index (V8 Domain 3 — evolution observability) ---
    iteration: int = Field(
        default=1,
        ge=1,
        description="1-based iteration index within the current chain or workflow "
        "run. Stamped into the per-iter row appended to "
        "{workspace}/evolution_log.jsonl by the interpretation agent. "
        "Populated by the workflow (model_exploration.run_workflow) "
        "from its loop variable. Defaults to 1 for ad-hoc / single-iter "
        "callers. See docs/V8_Gap_Report.md Domain 3.",
    )

    # --- Active-Model policy (Commit 6.1 — Stability Filter + Synthesis Window) ---
    # K/N/Δ thresholds shared by select_active_models() and should_recall_per_model()
    # in nodes/interpretation_helpers.py. The active model_types are the union of:
    #   Top-K by best_denoising_score ∪ Last-N by recency ∪ models with |Δ| ≥ threshold
    # Stable (non-active) models are pulled from the cache verbatim — no fresh LLM call.
    active_model_top_k: int = Field(
        default=3,
        ge=0,
        description="Top-K cap by best_denoising_score for the active-model set. "
        "These models keep their full per_model summary expanded in "
        "the synthesis prompt and are eligible for fresh per_model "
        "LLM re-calls. Set to 0 to disable the Top-K pathway.",
    )
    active_model_last_n: int = Field(
        default=2,
        ge=0,
        description="Last-N cap by recency for the active-model set. The N model_types "
        "from the current iter's `summaries` list (taken in the order "
        "supplied) are unconditionally active. Set to 0 to disable the "
        "Last-N pathway.",
    )
    active_model_score_delta: float = Field(
        default=0.05,
        ge=0.0,
        description="Absolute score-delta threshold (in normalized denoising-score "
        "units) at or above which a model with both a prior cache entry "
        "and a current-iter summary is considered active. Also used by "
        "should_recall_per_model() to decide whether new evidence "
        "warrants a fresh per_model LLM call. Set to 0.0 to make any "
        "non-zero score change trigger activation.",
    )

    # --- Versioned prediction memory (Step 09a C4) ---
    prediction_outcomes_by_semantics: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description=(
            "Step 09a — outcome counts keyed by the SEMANTICS that produced them, "
            "e.g. {'metric_order_signsafe_v2': {'confirmed': 2, 'partial': 1}}. "
            "Carried forward beside the legacy `prediction_outcomes_history`, never "
            "merged with it: outcomes produced by the pre-09a direction-blind, "
            "sign-degenerate rule are not comparable with corrected ones, so pooling "
            "them would yield a hit-rate that means nothing. Empty on a legacy input."
        ),
    )
    cumulative_information_gain_by_semantics: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Step 09a — running information-gain sums keyed by semantics, for the same "
            "reason as the counts above. The legacy scalar "
            "`cumulative_information_gain` is preserved separately and never added to "
            "these; no single number anywhere means 'legacy + v2'."
        ),
    )

    # --- The run's bound evaluation metric (Step 09a C2) ---
    metric_spec: MetricSpecField | None = Field(
        default=None,
        description=(
            "The run's ALREADY-RESOLVED MetricSpec, reconciled across every "
            "tuning output feeding this interpretation and forwarded by the "
            "caller. It is the SINGLE authority for ordering direction, the "
            "run-level metric identity and the prediction default. Nothing "
            "here derives it: the tuner resolved it once and stamped it on its "
            "output. None is legal ONLY for a cold start or a genuinely "
            "scoreless input — see the validator below."
        ),
    )

    # --- Task-owned interpretation guidance (Step 09b C2) ---
    task_blocks: InterpretationTaskBlocks | None = Field(
        default=None,
        description=(
            "Task-owned interpretation guidance, supplied by the CALLER "
            "(the workflow's bounded Regime-A adapter today; the Step-12 "
            "composition root later). None ⇒ every task-guidance section is "
            "omitted from the prompts — legal for cold starts, scoreless "
            "inputs, ad-hoc callers and tasks that supply no guidance. The "
            "interpreter never discovers task files itself."
        ),
    )

    @model_validator(mode="after")
    def metric_spec_is_present_and_agrees_with_the_evidence(self) -> InterpretationInput:
        """Fail closed BEFORE anything reads a score (parent §4a, Q-09a-4).

        Two clauses, both refusals rather than defaults:

        (a) an input carrying ORDERING EVIDENCE — any summary score field or
            any cached ``_stats`` score — must carry the run's ``metric_spec``.
            There is no "assume higher is better" fallback: under a
            lower-is-better metric that assumption inverts every ranking
            silently, which is precisely the failure Step 09 exists to remove.
            A cold start or a genuinely scoreless input needs no ordering and
            is accepted with a NAMED absence.

        (b) where a summary carries its own evidence-borne ``metric_identity``,
            it must equal the run spec's id AND direction. A record scored
            under a different metric than the run is bound to is a contract
            error — never resolved by preferring one side.

        Construction time is the earliest possible point, so the refusal lands
        before ordering, active-model selection, prediction evaluation,
        evidence rendering and any LLM call.
        """
        if self.metric_spec is None:
            witness = self._first_score_bearing_witness()
            if witness is not None:
                raise ValueError(
                    f"metric_spec is required for score-bearing interpretation: {witness} "
                    "carries a score, but no run MetricSpec was supplied. A legacy/pre-09a "
                    "tuning output lacks the stamped run MetricSpec this contract needs to "
                    "order results — re-produce the output under Step 09a or start a fresh "
                    "chain. Ordering direction is never assumed."
                )
            return self

        for summary in self.summaries:
            identity = summary.metric_identity
            if identity is None:
                continue
            if identity.metric_id != self.metric_spec.id:
                raise ValueError(
                    f"metric identity mismatch on summary {summary.model_type!r} "
                    f"(run {summary.run_name!r}): its records were scored under "
                    f"metric_id={identity.metric_id!r}, but the run's MetricSpec is "
                    f"{self.metric_spec.id!r}. One interpretation covers one metric."
                )
            if identity.direction != self.metric_spec.direction:
                raise ValueError(
                    f"metric direction mismatch on summary {summary.model_type!r} "
                    f"(run {summary.run_name!r}): its records carry "
                    f"direction={identity.direction!r}, but the run's MetricSpec declares "
                    f"{self.metric_spec.direction!r}. Ordering cannot proceed on a "
                    "contradiction."
                )
        return self

    def _first_score_bearing_witness(self) -> str | None:
        """Name the first thing that would need an ordering direction.

        Returning the WITNESS rather than a bool is what makes the refusal
        actionable: the message says which summary or cache entry made the
        spec mandatory.
        """
        score_fields = (
            "best_denoising_score",
            "best_valid_denoising_score",
            "worst_denoising_score",
            "formal_score",
            "best_valid_formal_score",
        )
        for summary in self.summaries:
            for field in score_fields:
                if getattr(summary, field, None) is not None:
                    return f"summary {summary.model_type!r} field {field!r}"
            if any(score is not None for score in summary.round_scores):
                return f"summary {summary.model_type!r} field 'round_scores'"

        cached_fields = (
            "best_denoising_score",
            "best_valid_denoising_score",
            "worst_denoising_score",
            "formal_score",
        )
        for model_type, entry in self.model_knowledge_cache.items():
            stats = entry.get("_stats", {}) if isinstance(entry, dict) else {}
            if not isinstance(stats, dict):
                continue
            for field in cached_fields:
                if stats.get(field) is not None:
                    return f"cache entry {model_type!r} _stats field {field!r}"
        return None

    @model_validator(mode="after")
    def require_at_least_one_model(self) -> InterpretationInput:
        if self.model_types is not None and len(self.model_types) == 0:
            raise ValueError(
                "model_types cannot be an empty list. "
                "Use None to derive model types from summaries."
            )
        derived = {s.model_type for s in self.summaries}
        effective = derived | set(self.model_types or []) | set(self.model_knowledge_cache.keys())
        if not effective and not self.cold_start:
            raise ValueError(
                "At least one model type must be provided — "
                "via summaries, model_types, or model_knowledge_cache. "
                "(Set cold_start=True to intentionally start a chain with no "
                "prior experimental evidence.)"
            )
        return self


class InterpretationOutput(BaseModel):
    """
    Output of result_interpretation_agent.

    Covers all model types provided in the input. Per-model scores give
    the full performance picture; overall best/worst give the global range.
    Consumed by ml_model_proposal_agent via ``local_full_context`` in
    ``agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py``.
    """

    # --- Models covered ---
    model_types: list[str] = Field(
        description="All model types analysed (union of summaries and explicit model_types).",
    )
    model_descriptions: dict[str, str] = Field(
        description="model_type → full markdown description loaded from description.md. "
        "Carries architecture knowledge forward to the proposal agent.",
    )

    # --- Experiment counts ---
    total_experiments: int = Field(
        description="Total completed rounds across all summaries.",
    )

    # --- Cold-start state ---
    cold_start: bool = Field(
        default=False,
        description="True when this interpretation was produced for a cold-start "
        "iteration (no prior experimental evidence). Propagated to the proposer so "
        "its prompt states there is no history and treats registries as available "
        "options, not completed runs. False for all history-backed iterations.",
    )
    analysis_brief: AnalysisBrief | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Optional Interpreter-owned semantic questions produced by a separate bounded "
            "stage. Contains no assets, access grants, skills, execution plan, preprocessing "
            "action or modeling decision."
        ),
    )

    # --- Per-model scores ---
    per_model_best: dict[str, float | None] = Field(
        default_factory=dict,
        description="model_type → best denoising score. "
        "None if the model has no successful experiments.",
    )
    per_model_best_valid: dict[str, float | None] = Field(
        default_factory=dict,
        description="model_type → highest HealthGate-valid score; None when unavailable.",
    )
    per_model_raw_best_health_validity: dict[str, str] = Field(
        default_factory=dict,
        description="model_type → validity label for its raw-best record.",
    )
    per_model_worst: dict[str, float | None] = Field(
        default_factory=dict,
        description="model_type → worst denoising score. "
        "None if the model has no successful experiments.",
    )
    scientific_aggregation: dict[str, Any] | None = Field(
        default=None,
        description=(
            "V20 PR D (D-C5) — which formal results informed the scientific "
            "aggregate and which were excluded, as an "
            "execute_tools.scientific_aggregation.AggregationScope dump: "
            "included / excluded / included_count / excluded_count / "
            "all_excluded / no_records / exclusion_reason_counts. Derived "
            "DETERMINISTICALLY before any LLM call and never written by a "
            "model (§4.7): a model may simply omit the exclusion, and "
            "exclusion text placed inside a prompt can steer the "
            "interpretation it then writes. Excluded results are retained "
            "here as evidence — nothing is deleted. `all_excluded` is "
            "explicit because an empty aggregate alone is ambiguous: it "
            "reads identically to a campaign that found nothing, which is "
            "the opposite conclusion. Render with "
            "AggregationScope.provenance_lines()."
        ),
    )

    # --- Overall best ---
    best_denoising_score: float | None = Field(
        default=None,
        description="Highest raw denoising score observed across all models.",
    )
    best_valid_denoising_score: float | None = Field(
        default=None,
        description="Highest HealthGate-valid score observed across all models.",
    )
    worst_denoising_score: float | None = Field(
        default=None,
        description="Lowest denoising score observed across all models.",
    )
    best_config: dict[str, Any] | None = Field(
        default=None,
        description="The params dict that produced the overall raw-best score.",
    )
    best_valid_config: dict[str, Any] | None = Field(
        default=None,
        description="The params dict that produced the overall best valid score.",
    )

    # --- Per-model knowledge cache (from Phase 1) ---
    model_knowledge_cache: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="model_type → self-sufficient cache entry produced by Phase 1. "
        "Each entry contains: Phase 1 LLM text (key_findings, bottlenecks, "
        "best_config_analysis, score_trend, per_file_analysis, data_sensitivity, "
        "efficiency_assessment, strategy_assessment) plus a '_stats' sub-dict "
        "(best_denoising_score, worst_denoising_score, best_file_vector, "
        "best_model_params, completed_rounds). Carry this forward as "
        "InterpretationInput.model_knowledge_cache in the next iteration — "
        "the agent skips Phase 1 LLM calls for models already in the cache.",
    )

    # --- LLM-generated analysis (from Phase 2) ---
    key_findings: list[str] = Field(
        description="Concrete, ranked observations extracted from the run summaries.",
    )
    bottlenecks: list[str] = Field(
        description="Root causes currently limiting further improvement.",
    )
    take_home_message: str = Field(
        description="Single critical insight that directly motivates proposing a new architecture.",
    )

    # --- Per-file analysis (from score_table) ---
    per_model_score_tables: dict[str, ScoreComparisonTable] | None = Field(
        default=None,
        description="model_type → best ScoreComparisonTable. Strict superset of the "
        "old per_model_file_vectors (every rows[i].model equals the old "
        "fv[i]) plus raw_baseline, ground_truth, gain_vs_raw, "
        "headroom_vs_gt, linear_weight, and impact_score columns plus "
        "pre-rendered markdown. The Impact_Score column is the canonical "
        "per-file opportunity ranking — downstream consumers read levers "
        "from the table directly rather than relying on a separate "
        "threshold-derived index list.",
    )

    # --- Efficiency context ---
    per_model_params: dict[str, int] | None = Field(
        default=None,
        description="model_type → parameter count of best model.",
    )

    # --- Data volume context ---
    per_model_training_segments: dict[str, int] | None = Field(
        default=None,
        description="model_type → training PSD segments used in best experiment.",
    )

    # --- Vocabulary feedback (Phase C) ---
    runtime_vocab: list[VocabEntry] = Field(
        default_factory=list,
        description="Updated vocabulary: seed + candidates + discoveries from all "
        "iterations including this one. This is the compressed memory "
        "that the next iteration's proposal agent receives. "
        "Empty in legacy mode (no vocabulary).",
    )
    prediction_evaluation: dict[str, Any] | None = Field(
        default=None,
        description="Evaluation of the previous proposal's FalsifiablePrediction. "
        "Outcome is SOTA-based (not predicted-value-based) and DIRECTION-correct "
        "under the run's bound metric (Step 09a): confirmed = better than SOTA, "
        "partial = within the relative band abs(actual - sota) <= 0.05 * abs(sota), "
        "refuted = outside it, unevaluated = the comparison could not be made at all "
        "(counted in NO pool and never published as a discovery). "
        "Contains: metric, metric_resolution, predicted_value, actual_value, "
        "current_sota, delta_from_sota, outcome "
        "('confirmed'/'partial'/'refuted'/'unevaluated'), boldness, "
        "information_gain, notes, prediction_evaluation_semantics. "
        "predicted_value is echoed from the proposal so that "
        "generate_discoveries can render it; the outcome does not depend on it. "
        "The key set is UNIFORM across every branch — the pre-09a uncomputable "
        "path returned a different one. None if no previous prediction exists.",
    )
    new_discoveries: list[VocabEntry] = Field(
        default_factory=list,
        description="New kind='discovery' entries generated from this round's "
        "evaluation. These are empirical findings expressed as "
        "sentences, added to runtime_vocab for the next iteration.",
    )
    vocab_changes: list[str] = Field(
        default_factory=list,
        description="Human-readable log of vocabulary promotion events made "
        "this iteration. One entry per promoted candidate, e.g. "
        "'Promoted log_fno to canonical (seen in 3 runs).' "
        "Empty when no candidates met the promotion threshold.",
    )

    # --- Centrifugal health metrics ---
    vocab_diversity_ratio: float | None = Field(
        default=None,
        description="Fraction of feature/capability vocab entries that are still candidates "
        "(not yet promoted to canonical). Range [0, 1]. A low value signals "
        "vocabulary stagnation — the system is reusing only established terms "
        "rather than proposing new ones. The exploration resolver uses this to "
        "trigger explore mode when the ratio falls below policy.vocab_stagnation_threshold.",
    )
    cumulative_information_gain: float = Field(
        default=0.0,
        description="Running total of information_gain across all iterations. "
        "Increases when a bold prediction is confirmed (boldness × 1). "
        "Unchanged when predictions are refuted or partial. "
        "Surfaced to the Phase 2 synthesis prompt so the LLM can see "
        "how much confirmed knowledge has been built up over the run.",
    )

    # --- Scientific accuracy (Phase E) ---
    scientific_accuracy: dict[str, float] | None = Field(
        default=None,
        description="Prediction hit-rate fractions: e.g. {'confirmed': 0.38, 'partial': 0.22, "
        "'refuted': 0.40}. Values sum to 1.0. None until the first prediction "
        "has been evaluated (first iteration has no prior prediction).",
    )
    prediction_outcomes_history: dict[str, int] = Field(
        default_factory=lambda: {"confirmed": 0, "partial": 0, "refuted": 0},
        description="Cumulative count of each prediction outcome across all iterations. "
        "Carry forward as InterpretationInput.prediction_outcomes_history "
        "in the next iteration.",
    )

    # --- Vocab link promotion (Phase E.7) ---
    vocab_link_confirmations: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Updated feature→capability link confirmation counts: "
        "'feature:capability' → list of run_names where the link was confirmed. "
        "Carry forward as InterpretationInput.vocab_link_confirmations "
        "in the next iteration.",
    )

    # --- Structured HealthGate feedback (V19 PR 3 — deterministic, NEVER
    #     LLM-derived; populated regardless of the prompt flag and of
    #     interpreter degradation, per the §3.10 invariant) ---
    per_model_round_health_counts: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="model_type → {'valid': n, 'invalid': n, 'unknown': n} "
        "over this iteration's rounds, from each round's deterministic "
        "health_validity classification. Computed from RoundHealth, not "
        "from LLM findings.",
    )
    per_model_collapse_fingerprints: dict[str, list[CollapseFingerprint]] = Field(
        default_factory=dict,
        description="model_type → distinct collapse fingerprints observed "
        "THIS iteration (deduped by signature, chronological first-seen "
        "order). Deterministic — built from persisted gate evidence only.",
    )
    collapse_fingerprint_history: dict[str, list[CollapseFingerprintHistoryEntry]] = Field(
        default_factory=dict,
        description="Bounded cross-iteration fingerprint history AFTER this "
        "iteration's deterministic merge and retention "
        "(pr3_healthgate_feedback.md §3.8). Carry forward as "
        "InterpretationInput.collapse_fingerprint_history. The merge runs "
        "regardless of interpreter LLM success or degradation — real gate "
        "evidence is never lost to an LLM failure.",
    )

    # --- Degraded-mode flag (V8 hardening Domain 2b) ---
    is_degraded: bool = Field(
        default=False,
        description="True when the interpreter produced this digest via the "
        "fallback path (LLM call failed after the Bridge's 3-retry "
        "envelope). Degraded outputs preserve the incoming "
        "runtime_vocab verbatim (no growth this iter), have empty "
        "key_findings/bottlenecks/new_discoveries, and are still "
        "written to disk so the chain's load_latest_knowledge() "
        "step finds a digest. Without this flag, an interp LLM "
        "failure left no digest on disk and the next iter's "
        "load_latest_knowledge skipped the affected iter — "
        "causing a 2-iter vocab regression. See "
        "docs/V8_Gap_Report.md Domain 2b.",
    )

    # --- Per-iteration evolution metrics (V8 hardening Domain 3) ---
    evolution_stats: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-iteration vocabulary evolution metrics, snapshotted at "
        "the end of result_interpretation_agent.run(). Populated keys: "
        "vocab_total (int), vocab_canonical (int), vocab_candidate "
        "(int), promoted_this_iter (int — count from "
        "promote_candidates() this iter, reflects the Tested-only "
        "threshold), is_degraded (bool — mirrors the field above). "
        "Also appended as one row to {workspace}/evolution_log.jsonl "
        "for tail -f monitoring. See docs/V8_Gap_Report.md Domain 3.",
    )

    # --- Ordering provenance (Step 09a C2) ---
    metric_identity: MetricIdentity | None = Field(
        default=None,
        description=(
            "PROVENANCE: the metric identity this iteration was actually ordered "
            "under, echoed from the run's bound MetricSpec. Threaded into BOTH the "
            "healthy and the degraded digest, so an interpreter LLM failure cannot "
            "lose it. None ONLY on a cold start or a genuinely scoreless input — a "
            "NAMED absence, which is why a reader never has to guess whether a "
            "digest's numbers are higher- or lower-is-better."
        ),
    )

    # --- Versioned prediction accounting (Step 09a C4) ---
    prediction_evaluation_semantics: str = Field(
        # The DEFAULT is the legacy id on purpose: a digest written before
        # Step 09a has no such key, and it must read as what actually produced
        # it. Step-09a runs write the v2 id explicitly.
        default=PREDICTION_SEMANTICS_LEGACY_V1,
        description=(
            "Step 09a — the semantics `scientific_accuracy` and the v2 pool of THIS "
            "digest were computed under. A digest written before Step 09a has no such "
            "key and reads as `legacy_v1`; old digests are NEVER rewritten."
        ),
    )
    prediction_outcomes_by_semantics: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description=(
            "Step 09a — version-keyed comparable pools. "
            "`['metric_order_signsafe_v2']` owns the confirmed / partial / refuted "
            "counts this iteration contributes to; the legacy "
            "`prediction_outcomes_history` below is a DIFFERENT pool under a different "
            "rule and is never incremented here. An `unevaluated` outcome is counted "
            "in neither."
        ),
    )
    cumulative_information_gain_by_semantics: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Step 09a — version-keyed information-gain sums. The legacy scalar is "
            "preserved in `cumulative_information_gain`; the two are never added."
        ),
    )
    prediction_pool_sizes: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Step 09a — how many outcomes each pool holds, e.g. "
            "{'legacy_v1': 2, 'metric_order_signsafe_v2': 1}. Explicit provenance so a "
            "reader cannot mistake a version-pure `scientific_accuracy` for a "
            "statistic over every prediction on record."
        ),
    )

    # --- Per-model evidence projection (Step 09a C6) ---
    per_model_secondary_metrics: dict[str, list[SecondaryMetricEvidence]] = Field(
        default_factory=dict,
        description=(
            "Step 09a — secondary-metric evidence per model, present-when-present. "
            "Empty in production until Step 10 carries secondaries upstream."
        ),
    )
    per_model_failure_counts: dict[str, RecordFailureCounts] = Field(
        default_factory=dict,
        description=(
            "Step 09a — authority-derived failure counts per model, threaded into "
            "BOTH the healthy and the degraded digest so an interpreter LLM "
            "failure cannot lose them."
        ),
    )
