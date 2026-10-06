# agent/schemas/hyperparam_tuning.py
"""
Input and output schemas for tune_ml_hyperparam_agent.

ExpertAdvice supports two protocols:
  - Plain string  : human-written guidance via CLI or config file
  - ExpertAdvice  : structured object produced by ml_model_proposal_agent

Both are accepted wherever ExpertAdviceInput is used.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from agent.prompt_templates.timing_attribution import TIMING_SPLIT_SEMANTICS
from agent.schemas.custom_loss_contract import CustomLossApplicability, TaskOwnedCustomLoss
from agent.schemas.data_analysis.trained_model import TrainedModelArtifactRef
from agent.schemas.health_feedback import FormalValidityFeedback, TrialValidityFeedback
from agent.schemas.model_io_contract import TensorContract
from agent.schemas.ordering import (
    OrderingObservation,
    OrderingValidationError,
    OrderStrategy,
    RejectedOrderingProposal,
    resolve_ordering,
    validate_ordering_shape,
)
from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.training_diagnosis import TrainingDiagnosis
from core.checkpoint_selection import SelectedCheckpoint
from core.planner_strategy_identity import PlannerStrategyIdentity
from core.record_role import AttemptRole, RecordRoleError, is_formal_role

# One vocabulary for the admission posture, shared with the policy that
# enforces it. Two independent spellings would let a value be acceptable
# at intake and impossible one layer down -- which is exactly what this
# field did before. Same layering as proposal.py importing
# core.hardware_context.
from core.runtime_control.admission import AdmissionEnforcement
from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
from core.runtime_control.records import RuntimeObservation
from core.runtime_control.training_budget import TrainingBudgetReceipt
from core.runtime_control.validation_limits import validate_phase_deadline
from core.target_standardization import TargetStandardizationReceipt
from execute_tools.dataset_config import NUM_FILES, DataScope
from execute_tools.evaluation_execution import CandidateEvaluationResult
from execute_tools.evaluation_metric import MetricResult, MetricSpecField, NotScoreableResult
from execute_tools.health_checks.schemas import PersistedHealthGateResult
from execute_tools.training_history import TrainingHistory
from ml_models.model_descriptions import DescriptionSourcePolicy

TrainingValidationPortion = Annotated[float, Field(gt=0, le=1)]


#: What a HealthGate verdict DOES in this run: enforce, or only record.
#:
#: Declared by the operator, never reconstructed by diffing the effective
#: YAML against the shipped one. The predecessor role hotfix (`af5339ce`)
#: already proved why: enforcement and science are different properties,
#: and deriving one from the other inverts the answer under observe-only.
HealthGateMode = Literal["blocking", "observe_only"]

#: Whether this run's results may inform science, or are diagnostic only.
#:
#: A SEPARATE axis from :data:`HealthGateMode` (D-D-5). The pairing rules
#: are enforced at the launcher, not here:
#:
#:     blocking     + scientific  -> the normal formal campaign
#:     blocking     + diagnostic  -> coherent: enforced, deliberately not promoted
#:     observe_only + diagnostic  -> the normal observation run
#:     observe_only + scientific  -> REFUSED, a contradiction
ResultAuthority = Literal["scientific", "diagnostic"]

#: The single wall-time admission authority selected for one candidate role.
#:
#: ``forecast`` uses the advance workload forecast and leaves in-process
#: measurements observational. ``measured`` skips advance forecast admission
#: and lets the executing-device measurement enforce the configured budget.
#: There is intentionally no hybrid value: one budget must have one authority.
TimeAdmissionSource = Literal["forecast", "measured"]


# ---------------------------------------------------------------------------
# Expert advice — two protocols
# ---------------------------------------------------------------------------


class ExpertAdvice(BaseModel):
    """
    Structured expert guidance produced by an upstream agent
    (e.g. ml_model_proposal_agent) and consumed by tune_ml_hyperparam_agent.

    Each field is a list of concrete, actionable statements — not free prose.
    The agent serializes this into its LLM prompt automatically.
    """

    focus_areas: list[str] = Field(
        default_factory=list,
        description="Aspects to prioritize during exploration (e.g. 'increase depth before width').",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Hard limits that must not be violated (e.g. 'VRAM < 10 GB', 'epochs <= 30').",
    )
    known_failures: list[str] = Field(
        default_factory=list,
        description="Configs or approaches already shown to fail — avoid repeating them.",
    )
    suggested_directions: list[str] = Field(
        default_factory=list,
        description="Concrete things to try (e.g. 'try focal loss with gamma=3', 'reduce batch_size to 4').",
    )
    rationale: str = Field(
        default="",
        description="Why this guidance was given — context for the agent's planning phase.",
    )
    freeform_notes: str | None = Field(
        default=None,
        description=(
            "Catch-all slot for unstructured advice text. Used by legacy entry "
            "points (e.g. scripts/run_comparison.py) that pass a single free-form preamble "
            "string instead of structured fields. Newer code paths should populate "
            "the structured fields above and leave this None."
        ),
    )


# Union type accepted wherever expert advice is expected
ExpertAdviceInput = str | ExpertAdvice


def serialize_expert_advice(advice: ExpertAdviceInput) -> str:
    """
    Serialize ExpertAdvice to a human-readable string for LLM prompts.

    If advice is already a string, return it as-is.
    If it is a structured ExpertAdvice object, format it into a multi-line
    string. Returns empty string if no advice is provided.

    Used by all nodes to inject expert_advice into LLM prompts.
    """
    if isinstance(advice, str):
        return advice
    parts = []
    if advice.focus_areas:
        parts.append("Focus areas: " + "; ".join(advice.focus_areas))
    if advice.constraints:
        parts.append("Constraints: " + "; ".join(advice.constraints))
    if advice.known_failures:
        parts.append("Known failures: " + "; ".join(advice.known_failures))
    if advice.suggested_directions:
        parts.append("Suggested directions: " + "; ".join(advice.suggested_directions))
    if advice.rationale:
        parts.append("Rationale: " + advice.rationale)
    if advice.freeform_notes:
        parts.append("Notes: " + advice.freeform_notes)
    return "\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Per-experiment record (mirrors what is written to summary_{run_name}.json)
# ---------------------------------------------------------------------------


class ExperimentTiming(BaseModel):
    train_time_s: float = Field(
        description=(
            "Wall time of the WHOLE training subprocess, spawn to exit — so it "
            "also contains process start, CUDA init, model and dataset "
            "construction and checkpoint save, none of which the trainer's own "
            "clock (which starts after setup) counts. The budget is measured "
            "against this number, so it must not be narrowed. Read it beside "
            "`validation_time_s` (F-SCANE-3; N-4 for what the split means): "
            + TIMING_SPLIT_SEMANTICS
        )
    )
    validation_time_s: float | None = Field(
        default=None,
        description=(
            "F-SCANE-3 — the seconds of `train_time_s` spent in the 07a "
            "validation pass, summed over epochs from "
            "`training_history.validation_seconds`. The subprocess has always "
            "computed this split (`train_engine_sandbox` subtracts it from the "
            "training ACTUAL) but it reached only the calibration store, so no "
            "LLM could see the term it was being asked to attribute to "
            "architecture and a candidate could be shrunk for time spent "
            "validating it. `None` means the producer recorded no validation "
            "split — a legacy record, a failure record, or an attempt with no "
            "validation pass — NOT that the pass took zero seconds."
        ),
    )
    inference_time_s: float
    scoring_time_s: float


class ExperimentMemory(BaseModel):
    expert_advice_followed: str
    hypothesis: str
    conclusion: str | None = None
    key_factor: str | None = None
    discovery: str | None = None
    memory_update: str | None = None

    # Phase J — pre-flight time-budget context surfaced to the planner via the
    # next round's experiment_history. Populated only when the time gate ran
    # (i.e. the active mode's budget was set); absent on records produced with
    # the gate disabled, so the reflector doesn't have to filter None values.
    # See docs/resource_estimator_implement.md §J.1.
    time_estimate_minutes: float | None = Field(
        default=None,
        description="Pre-flight wall-time prediction from evaluate_time_skill (minutes).",
    )
    time_budget_minutes: float | None = Field(
        default=None,
        description="Active mode's time ceiling that the estimate was checked against (minutes).",
    )
    time_mode: Literal["trial", "formal"] | None = Field(
        default=None,
        description="Which budget was active for this round — 'trial' or 'formal'.",
    )

    # Phase K — pre-flight VRAM-budget context surfaced to the planner via the
    # next round's experiment_history. Populated only when the VRAM gate ran
    # with a budget set; absent on records where the gate was disabled. Mirrors
    # the time fields above so the planner sees both resource estimates side by
    # side. Mode is inferred from `time_mode` (the two gates run in the same
    # round) — no separate vram_mode is stored.
    # See docs/resource_estimator_implement.md §10.4.
    vram_estimate_gb: float | None = Field(
        default=None,
        description="Pre-flight VRAM prediction from evaluate_vram_skill (GB).",
    )
    vram_budget_gb: float | None = Field(
        default=None,
        description="Active mode's VRAM ceiling the estimate was checked against (GB).",
    )

    # K.2.5-8 — soft-fallback flag from the inference estimator. Set to True
    # when the proposer invented a model_type that has no entry in
    # core/inference_defaults._INFERENCE_BATCH_SIZES; the estimator falls
    # back to the runtime default (25) and the per-sample activation model
    # is uncalibrated for the novel architecture. Operators reviewing the
    # gate verdict (or K.7's gate_exhaustion summary) can use this flag to
    # discount estimates from rounds that ran on a guess. Default None
    # keeps pre-K.2.5-8 records valid. See §10.14 K.2.5-8.
    inference_batch_uncalibrated: bool | None = Field(
        default=None,
        description=(
            "True when the inference estimator substituted the runtime "
            "fallback inference_batch (25) for an unregistered model_type; "
            "estimate is uncalibrated for the novel architecture. "
            "None on records where the gate did not run."
        ),
    )

    # refine_inference_time_estimator.md — measured per-PSD-segment inference
    # cost captured during a successful trial round. Commit C populates the
    # five measurement fields below from the trial-mode subprocess sidecar
    # (see core/sandbox_executor.py::execute_inference); Commit D consumes
    # ``inference_per_psd_seg_ms_measured`` to feed the formal round's time
    # gate as a hint, replacing the hand-calibrated × 2.7 ratio that
    # over-predicts for archs whose true ratio is lower. All optional so
    # pre-Commit-C records still validate.
    inference_per_psd_seg_ms_measured: float | None = Field(
        default=None,
        description=(
            "Median per-PSD-segment inference cost (ms) measured during the "
            "trial round, after dropping a leading warmup fraction. None on "
            "rounds with too few timed files (n_files < 2) or zero elapsed."
        ),
    )
    inference_warmup_aggregator: Literal["median"] | None = Field(
        default=None,
        description=(
            "Which aggregator produced ``inference_per_psd_seg_ms_measured``. "
            "Currently only 'median'; field exists so future aggregator "
            "variants stay distinguishable in audit logs without a schema "
            "migration."
        ),
    )
    inference_n_timed_files: int | None = Field(
        default=None,
        description=(
            "Number of files contributing to the median (n_files − n_warmup). "
            "0 when the aggregator returned None."
        ),
    )
    inference_warmup_fraction: float | None = Field(
        default=None,
        description=(
            "Fraction of leading files discarded as warmup (default 0.20). "
            "Applied as ``round(n_files × fraction)``, clamped to "
            "``[1, n_files−1]``."
        ),
    )
    inference_process_startup_ms: float | None = Field(
        default=None,
        description=(
            "Parent-measured fixed cost per inference call: subprocess wall "
            "minus sum of per-file elapsed. Captures Python import + CUDA "
            "context init + ``torch.load`` + h5py library init. Reported for "
            "audit; not consumed by the gate (the gate uses only the "
            "per-file marginal). None if the sidecar was missing."
        ),
    )
    inference_ms_source: str | None = Field(
        default=None,
        description=(
            "Provenance tag set by the time gate when the inference-ms "
            "estimate is computed. One of "
            "'trial_inference_warmup' (Commit D measured-hint path), "
            "'training_warmup_x2.7_fallback' (legacy ratio scaling when no "
            "trial measurement is available), or 'static_formula' "
            "(no warmup signal at all). None on records where the gate did "
            "not run."
        ),
    )

    # Phase L — per-round attempt-budget bookkeeping. The tuner now counts
    # SUCCESSFUL rounds, not raw attempts, so a single round can span
    # multiple attempts (each one a separate ExperimentRecord). These two
    # fields disambiguate the bucketing for §10.13.1's exhaustion math and
    # for any post-hoc audit that needs to know "this skipped_oom_risk
    # record was the 2nd attempt of round 1 (which still landed on attempt
    # 3)". Optional with default None for backward compat with pre-L
    # records. See docs/resource_estimator_implement.md §11.3.
    round_index: int | None = Field(
        default=None,
        description=(
            "Which logical round this attempt belonged to (1-indexed). "
            "Same value across all attempts of the same round."
        ),
    )
    attempt_in_round: int | None = Field(
        default=None,
        description=(
            "Attempt counter within the round (1..N). N = "
            "attempts_per_round for trial rounds, attempts_per_formal_round "
            "for the formal-promotion round."
        ),
    )


class ExperimentRecord(BaseModel):
    record_type: Literal["experiment", "attempt_failure"] = "experiment"
    exp_id: str
    status: Literal[
        "success",
        "error",
        "skipped_oom_risk",
        "skipped_time_risk",
        "skipped_schema_violation",
        "error_training",
        "error_training_oom",
        "error_inference",
        "error_inference_oom",
        "error_scoring",
        "failed_mode_collapse",
        # V20 B-C4a0 — the environment did not permit starting the phase.
        # Deliberately NOT `skipped_time_risk`, which already carries three
        # distinct meanings and feeds five time-factor consumers; a fourth
        # producer would pollute statistics that mean something else. This
        # status says nothing about the candidate and carries no authority
        # to shrink it. No production emitter yet — that is B-C4.
        "skipped_resource_admission",
        # V20 attempt 2 — the phase was not started because the MEASUREMENT
        # could not be established, so no admission decision was possible.
        #
        # Split out from `skipped_resource_admission` after that campaign
        # wrote 15 records under it while the GPU held 1.6 of 32.6 GiB: the
        # isolated measurement worker had failed, and the status made it
        # read as a resource refusal. Says nothing about the candidate's
        # size, speed or capacity, and carries no authority to shrink it.
        "skipped_infrastructure_failure",
    ]
    model_type: str
    #: V21 PR E — observational candidate identity (O-E-4/O-E-5), stamped by
    #: ``_emit_record`` from the tuner input. None on records written before
    #: PR E or by non-proposer candidates; never synthesised retroactively.
    candidate_id: str | None = None
    timestamp: str
    file_index: int = Field(
        default=6,
        description="Training/validation file index. Defaults to the standard split used in the TIDMAD paper.",
    )
    params: dict[str, Any]
    logical_round: int | None = None
    attempt_index: int | None = None
    failure_stage: str | None = None
    failure_type: str | None = None
    proposed_config: dict[str, Any] | None = None
    #: V20 B-C2b — bounded GPU evidence around a FAILED phase: the
    #: pre-spawn baseline, the observed peak, the last sample while the
    #: child was alive, and what remained afterwards, plus coverage.
    #: Present only on failure records; absent means it was not captured,
    #: never that the device was idle. Optional and defaulted, so every
    #: existing record still validates.
    gpu_evidence: dict[str, Any] | None = None
    #: V20 B-C3b — why the phase failed, as classified by the generic
    #: runtime layer at the point the evidence still existed. Shape:
    #: ``{attribution, may_recommend_resource_reduction, reason,
    #: evidence}``. Only ``candidate_gpu_capacity`` carries the authority
    #: to tell a planner the candidate was too large.
    #:
    #: Absent on every record written before B-C3b, and on any failure
    #: the executor could not classify. Absent means ``unknown`` — it
    #: never means the candidate was at fault. Readers must go through
    #: ``may_recommend_resource_reduction`` rather than testing the
    #: attribution string, so a new outcome cannot silently inherit
    #: authority.
    failure_attribution: dict[str, Any] | None = None
    traceback_summary: str | None = None
    counts_toward_completed_rounds: bool | None = None
    counts_toward_attempt_budget: bool = True

    # --- Training results ---
    final_loss: float | None = Field(
        default=None,
        description="Final training loss (last epoch). Comparable only across same loss_type.",
    )
    loss_history: list[float | None] | None = Field(
        default=None,
        description=(
            "Training loss per epoch. An element is None where the objective "
            "was non-finite (a diverged epoch): that is the STORAGE IMAGE of "
            "NaN/±inf written by scoring_utils.coerce_nonfinite_to_none at the "
            "recorder boundary, exactly as file_vector already carries it. "
            "Positions are preserved, so len() still equals the epoch count."
        ),
    )
    model_params: int | None = Field(
        default=None,
        description="Number of trainable model parameters.",
    )
    # --- Step 07a: the training observation payload and its diagnosis (ADDITIVE) ---
    # ``final_loss`` / ``loss_history`` / ``model_params`` keep their names and
    # semantics (OD-S7-3: ``final_loss`` stays the LAST TRAINING objective
    # observation). These two sit BESIDE them: persisted evidence, HIDDEN from
    # both LLM-facing renders in 07a (planner hidden-key set; reflector receives
    # the legacy payload only) — persistence ≠ visibility (roadmap §22.6). Every
    # record written before 07a validates unchanged; failure / skip records
    # carry None for both.
    training_history: TrainingHistory | None = Field(
        default=None,
        description=(
            "Step 07a — the trainer's typed per-epoch observation payload: R2 "
            "(train_objective == loss_history), R3 (validation_objective, on the "
            "run-bound validation scope; None only when no validation was expected), "
            "objective identity (kind + config fingerprint + reduction), the "
            "R2/R3 comparability stamp, materialized validation sample counts and "
            "per-epoch validation seconds. None on pre-07a records and on attempts "
            "that never produced training results."
        ),
    )
    training_diagnosis: TrainingDiagnosis | None = Field(
        default=None,
        description=(
            "Step 07a — the deterministic, calibration-free diagnosis derived ONCE "
            "from training_history at the tuner boundary (state, best validation "
            "epoch, trends with an explicit symmetric deadband, degradation, gap "
            "gated on comparability). None wherever training_history is None."
        ),
    )
    trained_model_artifact_ref: TrainedModelArtifactRef | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Optional immutable historical-inference artifact produced after a successful "
            "checkpoint is fully certified. Legacy records remain valid without it."
        ),
    )
    static_observations: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "`R-OBS-1` — the run's DECLARED STATIC observables, read off the "
            "TRAINED model once after the final optimizer step, keyed by the "
            "name the task's manifest declared. Empty for every run that "
            "declares none, and then the record writer emits no key at all.\n\n"
            "Its DYNAMIC sibling is not here: a per-epoch series belongs on "
            "`training_history.observations`, beside the R2/R3 series it is "
            "aligned to, and putting a second copy here would create two "
            "carriers for one family.\n\n"
            "OBSERVATIONAL, always. Nothing in this mapping may become an "
            "operand of an ordering expression — not ranking, not champion "
            "selection, not a skip/bypass threshold (`D-BUD-16`)."
        ),
    )

    # --- Scoring results ---
    denoising_score: float | None = Field(
        default=None,
        description="Anchor-normalized denoising score (validation).",
    )
    file_vector: list[float | None] | None = Field(
        default=None,
        description="Length-20 score vector. None for files not included in the run.",
    )
    score_table: ScoreComparisonTable | None = Field(
        default=None,
        description=(
            "Per-file comparison table (model vs raw_baseline vs ground_truth) "
            "with subset-scoped aggregate scalars and the pre-rendered markdown "
            "that gets substituted into tuner/reflector/interpreter/proposer "
            "prompts. Populated by build_score_table() after scoring whenever "
            "denoising_score is not None; None on failed or skipped rounds. "
            "See docs/aggregated_score_table_awareness.md §7.1."
        ),
    )
    failure_reason: str | None = Field(
        default=None,
        description=(
            "Human-readable health-check failure message from tuner-side gate "
            "evaluation (commit-5b). Pipe-concatenated over all failed gates "
            "at the round boundary, prefixed by gate_id: "
            "``[gate_id_1] reason1 | [gate_id_2] reason2``. Populated together "
            "with ``status='failed_mode_collapse'`` when the resolved gate "
            "action was non-``CONTINUE``; None on healthy rounds. Trial rounds "
            "with a non-``CONTINUE`` action still populate this field so the "
            "next planner iteration sees the diagnostic, but the score itself "
            "is preserved (trial-round penalty immunity per "
            "``_apply_degeneracy_reaction``). Surfaced verbatim to the LLM "
            "planner via memory_history."
        ),
    )
    gate_action: str | None = Field(
        default=None,
        description=(
            "The resolved ``GateAction`` string from tuner-side gate "
            "evaluation (commit-5b) — ``continue`` or "
            "``invalidate_round`` (``skip_iter`` / ``skip_to_formal`` "
            "were retired from the vocabulary, F-SCANC-1; historical "
            "records could only ever carry the two live values, since no "
            "shipped config declared the skip actions). ``None`` when "
            "no gate fired at this round or scoring didn't run (error "
            "paths, single-file legacy mode). Non-``continue`` values "
            "pair with ``is_degenerate``-analog behavior via "
            "``_apply_degeneracy_reaction``; gate actions carry no loop "
            "control. See "
            "``docs/design/pluggable_health_checks.md`` §4 for action "
            "semantics and §8 for severity resolution."
        ),
    )
    health_gate_results: list[PersistedHealthGateResult] = Field(
        default_factory=list,
        description="Full typed results for every HealthGate configured for this experiment.",
    )
    external_evaluation: CandidateEvaluationResult | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Original deployment evaluation facts; absent on native local evaluations.",
    )
    scientific_authority: dict[str, Any] | None = Field(
        default=None,
        description=(
            "V20 PR D — the formal record's authority verdict "
            "(core.scientific_authority.ScientificAuthority.model_dump()). "
            "Present on FORMAL records only; None on trial records, where "
            "the question does not apply, and on records predating D-C2b. "
            "Carries the three facts (healthgate_mode, "
            "declared_result_authority, formal_validity) beside the derived "
            "conclusions, which is what makes it recomputable and therefore "
            "tamper-EVIDENT. Deliberately typed as a plain dict rather than "
            "the model: ScientificAuthority sets extra='forbid' and exposes "
            "its conclusions as computed fields, so its own dump cannot be "
            "re-validated into it. Consumers must NOT trust the stored "
            "conclusions — re-derive via resolve_record_authority(), which "
            "refuses a verdict that disagrees with its own facts."
        ),
    )

    # --- Data volume ---
    training_psd_segments: int | None = Field(
        default=None,
        description="Number of PSD segments used for training.",
    )
    eval_psd_segments: int | None = Field(
        default=None,
        description="Number of PSD segments used for evaluation.",
    )

    timing: ExperimentTiming | None = None
    training_budget: TrainingBudgetReceipt | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    selected_checkpoint: SelectedCheckpoint | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    target_standardization: TargetStandardizationReceipt | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    runtime_verification: RuntimeObservation | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    memory: ExperimentMemory | None = None

    # --- Trial context (optional — absent or default in normal mode) ---
    attempt_role: AttemptRole | None = Field(
        default=None,
        exclude_if=lambda v: v is None,
        description="Explicit current-attempt role; absent on historical records.",
    )
    is_trial: bool = Field(
        default=False,
        description="Whether this experiment ran in trial-explore mode with sparse sampling.",
    )
    trial_strategy: Literal["snapshot", "anchors", "target"] | None = Field(
        default=None,
        description="Sampling strategy used for training.",
    )
    trial_portion: float | None = Field(
        default=None,
        description="Fraction of segments per file for training scope.",
    )
    eval_strategy: Literal["snapshot", "anchors", "target"] | None = Field(
        default=None,
        description="Sampling strategy used for validation.",
    )
    eval_portion: float | None = Field(
        default=None,
        description="Fraction of segments per file for validation scope.",
    )
    train_portion: float | None = Field(
        default=None,
        description="Per-epoch subsample from training scope.",
    )
    target_files: list[int] | None = Field(
        default=None,
        description="File indices sampled (only for 'target' strategy).",
    )
    validation_workload_ceiling: dict[str, Any] | None = Field(
        default=None,
        description=(
            "VALIDATION POSTURE ONLY (V20 FU-D-12). Workload-ceiling "
            "provenance for this round: whether a ceiling was configured, its "
            "value, the PLANNED trial portions, and the RESOLVED ones after "
            "clamping. None on ordinary campaigns.\n\n"
            "Declared here because an undeclared field is silently dropped by "
            "Pydantic's default extra='ignore' — the defect that hit this PR "
            "three times. The planned/resolved PAIR is the point: without it a "
            "clamp that stopped firing would look identical to a planner that "
            "happened to choose small values, and a Gate could not PROVE the "
            "workload was bounded."
        ),
    )

    # --- DataScope stamps + strategy-normalization provenance (DS5) ---
    # The existing ``trial_strategy`` / ``eval_strategy`` fields above hold
    # the EFFECTIVE (executed) strategies; the ``planned_*`` fields record
    # what the LLM plan proposed before any partial-scope normalization.
    task_composition_fingerprint: str | None = Field(
        default=None,
        description=(
            "The COMPOSED run's semantic task-composition fingerprint, or "
            "None for an un-composed run and for every record written "
            "before Step 11. Stamped at the single validate-and-persist "
            "seam so no construction site can forget it, and checked at "
            "ingress: a composed run must not admit a record it cannot "
            "certify as its own (Step 11 C8 / R-11-9, F-11-6)."
        ),
    )
    experiment_arm: str | None = Field(
        default=None,
        description=(
            "arXiv U1 (#254) — the OPAQUE experiment-arm label of the run "
            "that produced this record, the same value the run-invariants "
            "lock pins; None for an unlabelled run and for every record "
            "written before U1. Stamped at the single validate-and-persist "
            "seam ONLY when the run is labelled, so an unlabelled run's "
            "on-disk record carries no key (byte-identical to pre-U1). "
            "Checked at ingress under the same three-case rule as the "
            "composition fingerprint: a labelled run refuses an unstamped "
            "record. Never read to decide behaviour (ruling R2)."
        ),
    )
    resolved_data_scope: list[int] | None = Field(
        default=None,
        description=(
            "The run's resolved DataScope (sorted allowed file indices). "
            "None on legacy records = full scope. Scope-homogeneity ingress "
            "checks compare this stamp."
        ),
    )
    health_gate_enabled: bool | None = Field(
        default=None,
        description=(
            "Whether the HealthGate subsystem was enabled for this run. "
            "False makes candidate eligibility waive the gate requirement "
            "(self-describing record — see candidate_eligibility). "
            "None on legacy records = enabled."
        ),
    )
    planned_trial_strategy: Literal["snapshot", "anchors", "target"] | None = Field(
        default=None,
        description="LLM-planned training strategy before normalization.",
    )
    planned_eval_strategy: Literal["snapshot", "anchors", "target"] | None = Field(
        default=None,
        description="LLM-planned eval strategy before normalization.",
    )
    strategy_normalization_reason: str | None = Field(
        default=None,
        description=(
            "Why the planned strategies were normalized to the effective "
            "ones (e.g. 'partial_data_scope'). None = no normalization."
        ),
    )
    # --- Data-ordering provenance (V19 PR 2) ---
    # The three levels kept distinct, so a reader can reconstruct "the agent
    # proposed X, the operator overrode with Y, Z was selected, because S".
    # Only resolved_* describes selected settings, never completed traversal.
    # Unstamped inputs stay readable through ResolvedOrdering.from_record;
    # absence does not establish what actually ran.
    proposed_order_strategy: str | None = Field(
        default=None,
        description=(
            "Ordering the agent proposed, REJECTED OR NOT. None = no proposal "
            "(or legacy record). Typed as str because a rejected proposal is "
            "preserved verbatim and may not be a valid strategy."
        ),
    )
    proposed_file_order: list[int] | None = Field(
        default=None,
        description="File order the agent proposed, if any (rejected or not).",
    )
    ordering_proposal_rejected: bool = Field(
        default=False,
        description=(
            "True when an ordering proposal arrived but was not applied. "
            "Downstream must not read a rejected proposal as agent silence: "
            "the agent DID try to steer this round and was overruled."
        ),
    )
    ordering_proposal_rejection_reason: str | None = Field(
        default=None,
        description=(
            "Why the proposal was not applied — distinguishing an invalid "
            "ordering from one discarded because another plan field failed."
        ),
    )
    override_order_strategy: OrderStrategy | None = Field(
        default=None,
        description="Operator ordering override in force for the chain, if any.",
    )
    override_file_order: list[int] | None = Field(
        default=None,
        description="File order the operator forced, if any.",
    )
    ordering_observation: OrderingObservation | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Explicit current selection/refusal evidence; absent on unstamped records.",
    )
    resolved_order_strategy: OrderStrategy | None = Field(
        default=None,
        description=(
            "Selected effective ordering for this attempt, including errors "
            "after resolution; not proof of completed traversal. None on "
            "unstamped records or explicitly unresolved attempts."
        ),
    )
    resolved_file_order: list[int] | None = Field(
        default=None,
        description=(
            "Selected file visitation order. None for 'shuffle', unstamped "
            "records, or unresolved attempts; not a list of files visited."
        ),
    )
    ordering_resolution_source: (
        Literal["operator_override", "agent_proposal", "default", "legacy_default"] | None
    ) = Field(
        default=None,
        description=(
            "Which level supplied selected ordering. None when unstamped, "
            "including old preflight skips or explicitly unresolved attempts."
        ),
    )
    file_vector: list[float | None] | None = Field(
        default=None,
        description="Length-20 score vector. None for files not included in the run.",
    )

    # --- Step 06: the metric interface's record-facing payload (ADDITIVE) ---
    # ``denoising_score`` / ``file_vector`` / ``score_table`` keep their names and
    # semantics (renaming is D1, not authorized). These two fields sit BESIDE
    # them so identity, direction and value are machine-readable on every
    # record for Steps 07a/09; every record written before Step 06 validates
    # unchanged (optional, default None).
    metric_result: MetricResult | None = Field(
        default=None,
        description=(
            "Step 06 — the evaluation metric's own result for this attempt, produced "
            "by the metric handle on the live scoring route: ``metric_id``, ``direction``, "
            "the metric's scalar (``denoising_score`` under TIDMAD; the storage boundary "
            "writes a non-finite sentinel as null on both), optional per-sample "
            "evidence (``file_vector`` under TIDMAD) and the reference kinds consumed. "
            "None on records written before Step 06 and on attempts that never "
            "reached scoring. On a ``failed_mode_collapse`` record this is the metric's "
            "RAW evaluation while ``denoising_score`` carries the HealthGate policy's "
            "penalty (``_apply_degeneracy_reaction``) — the two agree by construction "
            "on ``success`` records and are validated to."
        ),
    )
    metric_refusal: NotScoreableResult | None = Field(
        default=None,
        description=(
            "Step 06 — the structured not-scoreable result when the produced "
            "deliverable failed the metric's scoreability contract BEFORE any scorer "
            "arithmetic ran (``status='error_scoring'``, ``failure_type='not_scoreable'``): "
            "which contract, which requirement, which input identity. None otherwise. "
            "Never set together with ``metric_result``."
        ),
    )

    # --- Step 10 / P2b: the OBSERVATIONAL secondary metrics (ADDITIVE) ---
    # The names are the ones the receiving side reserved for them verbatim
    # (`SecondaryMetricEvidence`'s docstring, `agent/schemas/interpretation.py`),
    # and the results/refusals pair deliberately mirrors the primary's
    # `metric_result`/`metric_refusal` split above rather than inventing a
    # third shape. Secondaries are OBSERVATIONAL: nothing below may ever
    # become an operand of an ordering decision.
    secondary_metric_results: list[MetricResult] = Field(
        default_factory=list,
        description=(
            "Step 10 — one entry per DECLARED secondary metric that produced a value "
            "for this attempt, each carrying its OWN id and direction (DAVIS declares "
            "`psnr` higher beside a `mse` primary that is lower-is-better). Evaluated "
            "wherever the primary evaluates and only AFTER a successful primary "
            "result, so an error record carries none by construction. Empty on every "
            "record of a run that declared no secondary, and on every record written "
            "before Step 10."
        ),
    )
    secondary_metric_refusals: list[NotScoreableResult] = Field(
        default_factory=list,
        description=(
            "Step 10 — one entry per declared secondary whose deliverable failed THAT "
            "metric's scoreability contract: a scientific refusal, structured exactly "
            "as the primary's `metric_refusal` is. A refused secondary leaves the "
            "attempt successful — the primary already produced its result."
        ),
    )
    secondary_metric_errors: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Step 10 — diagnostic PROVENANCE for a declared secondary whose evaluation "
            "CRASHED: metric id -> a concise one-line diagnostic. Deliberately NOT a "
            "scientific state: a crash is an implementation failure and must never be "
            "dressed as a `NotScoreableResult`, which would report a contract verdict "
            "nothing produced. The interpreter projects such a secondary as "
            "`unavailable` while this field keeps the reason. `ScopeViolationError` is "
            "never recorded here — it is re-raised so the run terminates, because "
            "'observational' bounds ordinary secondary outcomes, not framework-"
            "integrity failures."
        ),
    )

    @model_validator(mode="after")
    def _attempt_role_matches_trial_flag(self) -> ExperimentRecord:
        if self.attempt_role is not None:
            try:
                is_formal_role(
                    {
                        "attempt_role": self.attempt_role,
                        "is_trial": self.is_trial,
                        "status": self.status,
                        "trial_portion": self.trial_portion,
                    },
                    self.exp_id,
                )
            except RecordRoleError as exc:
                raise ValueError(str(exc)) from exc
        return self

    @model_validator(mode="after")
    def _ordering_observation_matches_selection(self) -> ExperimentRecord:
        if self.ordering_observation is not None:
            self.ordering_observation.validate_selection(
                self.resolved_order_strategy,
                self.resolved_file_order,
                self.ordering_resolution_source,
            )
        return self

    @model_validator(mode="after")
    def _each_secondary_metric_id_appears_in_exactly_one_carrier(self) -> ExperimentRecord:
        """Per-id exclusivity, the primary pair's rule applied per secondary.

        One evaluation of one metric has ONE outcome: it produced a value, it
        refused, or it crashed. An id in two carriers would make "what happened
        to `psnr` on this attempt" unanswerable, and an id repeated within one
        carrier would make the interpreter's join ambiguous — which matters
        because the projection keys absence rows on exactly these ids.
        """
        seen: dict[str, str] = {}
        for carrier, ids in (
            ("secondary_metric_results", [r.metric_id for r in self.secondary_metric_results]),
            ("secondary_metric_refusals", [r.metric_id for r in self.secondary_metric_refusals]),
            ("secondary_metric_errors", list(self.secondary_metric_errors)),
        ):
            for metric_id in ids:
                if metric_id in seen:
                    where = (
                        f"twice in {carrier}"
                        if seen[metric_id] == carrier
                        else f"in both {seen[metric_id]} and {carrier}"
                    )
                    raise ValueError(
                        f"secondary metric {metric_id!r} appears {where}; one evaluation "
                        "of one metric has exactly one outcome — a value, a refusal, or "
                        "a crash."
                    )
                seen[metric_id] = carrier
        return self

    @model_validator(mode="after")
    def _metric_payload_agrees_with_the_score_fields(self) -> ExperimentRecord:
        """One value, two names — they must agree (design §19 C4).

        On a ``success`` record ``metric_result.scalar`` IS ``denoising_score``
        and ``metric_result.per_sample`` IS ``file_vector``; a record whose
        additive payload disagrees with the frozen fields is rejected. Non-finite
        values compare as equal to their storage-boundary image (``None``) and to
        each other, because the same record is validated in memory (``-inf``)
        and again after reload (``null``). Not applied on ``failed_mode_collapse``:
        there ``denoising_score`` is the gate policy's penalty by design.
        ``metric_result`` and ``metric_refusal`` are mutually exclusive.
        """
        if self.metric_result is not None and self.metric_refusal is not None:
            raise ValueError(
                "metric_result and metric_refusal are mutually exclusive: an attempt is "
                "either scored or refused, never both."
            )
        if self.metric_result is None or self.status != "success":
            return self
        if not _same_score(self.metric_result.scalar, self.denoising_score):
            raise ValueError(
                f"metric_result.scalar={self.metric_result.scalar!r} disagrees with "
                f"denoising_score={self.denoising_score!r} on a success record; the "
                f"additive payload must carry the same value the frozen field carries."
            )
        if self.metric_result.per_sample is not None and self.file_vector is not None:
            same_shape = len(self.metric_result.per_sample) == len(self.file_vector)
            if not same_shape or not all(
                _same_score(a, b)
                for a, b in zip(self.metric_result.per_sample, self.file_vector, strict=True)
            ):
                raise ValueError(
                    "metric_result.per_sample disagrees with file_vector on a success "
                    "record; the additive payload must carry the same values."
                )
        return self

    @model_validator(mode="after")
    def _training_history_agrees_with_the_legacy_keys(self) -> ExperimentRecord:
        """Step 07a (design §3.8) — the additive payload and the frozen keys agree.

        When both ``training_history`` and ``loss_history`` are present they are
        the same series (R2 IS ``loss_history``); when ``final_loss`` and the
        history are present, ``final_loss`` equals the last training
        observation (OD-S7-3); when ``training_diagnosis`` is present, its
        ``epochs_completed`` equals ``len(training_history.train_objective)``
        unless the diagnosis is ``absent`` (no history to count) — an
        ``invalid`` diagnosis still counts epochs. Non-finite values compare
        as equal to their storage image (``None``) and to each other, exactly
        as ``_same_score`` does for the metric payload. Pre-07a records (both
        fields None) pass unchanged.
        """
        history = self.training_history
        if history is not None:
            if self.loss_history is not None:
                same = len(self.loss_history) == len(history.train_objective) and all(
                    _same_score(a, b)
                    for a, b in zip(self.loss_history, history.train_objective, strict=True)
                )
                if not same:
                    raise ValueError(
                        "training_history.train_objective disagrees with loss_history; the "
                        "additive payload must carry the same R2 series."
                    )
            if (
                self.final_loss is not None
                and history.train_objective
                and not _same_score(self.final_loss, history.train_objective[-1])
            ):
                raise ValueError(
                    f"final_loss={self.final_loss!r} is not the last training objective "
                    f"observation {history.train_objective[-1]!r} (OD-S7-3)."
                )
        diagnosis = self.training_diagnosis
        if diagnosis is not None and diagnosis.state != "absent":
            if history is None:
                raise ValueError(
                    f"training_diagnosis.state={diagnosis.state!r} requires a training_history."
                )
            if diagnosis.epochs_completed != len(history.train_objective):
                raise ValueError(
                    f"training_diagnosis.epochs_completed={diagnosis.epochs_completed!r} "
                    f"disagrees with len(training_history.train_objective)="
                    f"{len(history.train_objective)}."
                )
        return self


def _same_score(a: float | None, b: float | None) -> bool:
    """Equality that treats non-finite values and their storage image alike."""
    a_finite = a is not None and math.isfinite(a)
    b_finite = b is not None and math.isfinite(b)
    if a_finite and b_finite:
        return a == b
    return not a_finite and not b_finite


# ---------------------------------------------------------------------------
# Trial config (validated trial/formal decision per round)
# ---------------------------------------------------------------------------


class TrialConfig(BaseModel):
    """
    Validated trial/formal configuration for a single round.

    Training and validation (inference + scoring) are **independent pipelines**
    operating on different physical files (``abra_training_*.h5`` vs
    ``abra_validation_*.h5``). They share the same file/segment index space
    but the SampleSets are built independently.

    Training side:
    - ``trial_strategy`` + ``trial_portion`` → training scope (which segments to train on)
    - ``train_portion`` → per-epoch subsample from the training scope (speed optimization)

    Validation side:
    - ``eval_strategy`` + ``eval_portion`` → validation scope (what to inference + score on)
    - In formal mode: strategy is locked to ``snapshot``; portion defaults to
      1.0 (all segments) for production cross-arch comparability, but is
      operator-controllable via ``HyperparamTuningInput.formal_eval_portion``
      (Phase R, docs/resource_estimator_implement.md §13).

    ``train_validation_align``:
    - True: train and eval scopes use the same seed → same file/segment indices
    - False: independent seeds → potentially different segment selections
    """

    is_trial: bool = Field(
        description="Whether this round uses trial (sparse) or formal (full) mode.",
    )
    mode: Literal["trial", "formal", "single_file"] = Field(
        description="Execution mode: trial (sparse multi-file), formal (full multi-file), or single_file (legacy).",
    )

    # --- Training data ---
    trial_strategy: Literal["snapshot", "anchors", "target"] = Field(
        default="snapshot",
        description="Sampling strategy for training data — which files to train on.",
    )
    trial_portion: float = Field(
        default=0.02,
        ge=0.01,
        le=1.0,
        description="Fraction of segments per file for the training scope.",
    )
    train_portion: float = Field(
        default=0.1,
        ge=0.01,
        le=1.0,
        description="Per-epoch subsample from the training scope (speed optimization).",
    )
    target_files: list[int] = Field(
        default_factory=list,
        description="File indices for 'target' strategy (training).",
    )

    # --- Validation (inference + scoring) data ---
    eval_strategy: Literal["snapshot", "anchors", "target"] = Field(
        default="snapshot",
        description="Sampling strategy for validation data — which files to evaluate on.",
    )
    eval_portion: float = Field(
        default=0.02,
        ge=0.01,
        le=1.0,
        description="Fraction of segments per file for validation. 1.0 in formal mode.",
    )

    # --- Alignment ---
    train_validation_align: bool = Field(
        default=True,
        description="When True, train and eval scopes use the same seed (same segment indices).",
    )

    # --- Legacy ---
    file_index: int | None = Field(
        default=None,
        description="Training/validation file index. Only used in single_file mode.",
    )

    # --- Data ordering, RESOLVED (V19 PR 2) ---
    # Execution truth for this round: already resolved from the agent
    # proposal and any operator override. The training subprocess receives
    # ONLY these values and never learns how they were reached. Full
    # provenance (proposal, override, source) lives on ExperimentRecord.
    resolved_order_strategy: OrderStrategy = Field(
        default="shuffle",
        description=(
            "The visitation order that will execute. Default 'shuffle' is "
            "the pre-PR2 behavior: a global uniform shuffle."
        ),
    )
    resolved_file_order: list[int] | None = Field(
        default=None,
        description=(
            "The file visitation order that will execute. None exactly when "
            "resolved_order_strategy is 'shuffle'; otherwise a full "
            "permutation of the resolved DataScope."
        ),
    )

    # --- Reproducibility seeds ---
    train_sampling_seed: int = Field(
        description="Seed for build_sample_set() to select training PSD segments.",
    )
    eval_sampling_seed: int = Field(
        description="Seed for build_sample_set() to select validation PSD segments. "
        "Same as train_sampling_seed when train_validation_align=True.",
    )
    train_base_seed: int = Field(
        description="Base seed for per-epoch training subsampling. Epoch n uses seed = train_base_seed + n.",
    )

    @model_validator(mode="after")
    def _validate_fields(self):
        """Cross-field validation."""
        if self.mode == "single_file" and self.file_index is None:
            raise ValueError("file_index required when mode='single_file'.")
        if self.is_trial and self.trial_strategy == "target" and not self.target_files:
            raise ValueError(
                "target_files required when is_trial=True and trial_strategy='target'."
            )
        if self.train_validation_align and self.train_sampling_seed != self.eval_sampling_seed:
            raise ValueError(
                "train_validation_align=True but seeds differ: "
                f"train={self.train_sampling_seed}, eval={self.eval_sampling_seed}."
            )
        if self.resolved_order_strategy == "shuffle" and self.resolved_file_order is not None:
            raise ValueError(
                "resolved_file_order must be None when resolved_order_strategy="
                "'shuffle' — a file order is meaningful only for sequential "
                "ordering, and carrying a stale one would misreport what ran."
            )
        return self


# ---------------------------------------------------------------------------
# Experiment plan (validated output from brain.plan())
# ---------------------------------------------------------------------------


class ExperimentPlan(BaseModel):
    """
    Validated output from brain.plan() — one plan per round.

    The LLM planner returns a raw dict with hyperparameter decisions and
    (optionally) trial-mode parameters. This schema validates the output
    and provides safe defaults when the LLM omits or returns invalid trial
    fields.

    The override chain applied by the agent loop after validation:
      1. Expert constraint: if input says is_trial=False, force formal for all rounds.
      2. Final-round constraint: last round is always formal (is_trial=False).

    Note: ``model_config`` is a reserved attribute in Pydantic v2, so we use
    ``model_cfg`` / ``train_cfg`` / ``loss_cfg`` as field names with
    ``alias`` and ``populate_by_name=True`` so the LLM's JSON keys
    (``model_config``, ``train_config``, ``loss_config``) are accepted.
    """

    model_config = ConfigDict(populate_by_name=True)

    # --- Hyperparameter decisions ---
    model_type: str = Field(
        default="fcnet",
        description="Architecture to use for this experiment.",
    )
    hypothesis: str = Field(
        default="N/A",
        description="Specific prediction for this experiment.",
    )
    reasoning: str = Field(
        default="",
        description="How this experiment aligns with expert advice and past memory.",
    )
    model_cfg: dict[str, Any] = Field(
        default_factory=dict,
        alias="model_config",
        description="Architecture-specific hyperparameters.",
    )
    train_cfg: dict[str, Any] = Field(
        default_factory=dict,
        alias="train_config",
        description="Training hyperparameters (lr, epochs, batch_size, device).",
    )
    loss_cfg: dict[str, Any] = Field(
        default_factory=dict,
        alias="loss_config",
        description="Loss function specification (loss_type, etc.).",
    )

    # --- Trial/formal decision (per-round) ---
    is_trial: bool = Field(
        default=True,
        description="Whether this round uses trial (sparse) or formal (full) mode.",
    )

    # Training data
    trial_strategy: Literal["snapshot", "anchors", "target"] = Field(
        default="snapshot",
        description="Sampling strategy for training — which files to train on.",
    )
    trial_portion: float = Field(
        default=0.02,
        ge=0.01,
        le=1.0,
        description="Fraction of segments per file for the training scope.",
    )
    target_files: list[int] = Field(
        default_factory=list,
        description="File indices for 'target' strategy.",
    )
    train_portion: float = Field(
        default=0.1,
        ge=0.01,
        le=1.0,
        description="Per-epoch subsample from training scope. Default 0.1 matches legacy TIDMAD.",
    )

    # Validation data
    eval_strategy: Literal["snapshot", "anchors", "target"] = Field(
        default="snapshot",
        description="Sampling strategy for validation — which files to evaluate on.",
    )
    eval_portion: float = Field(
        default=0.02,
        ge=0.01,
        le=1.0,
        description="Fraction of segments per file for validation. Set to 1.0 for formal mode.",
    )

    # Alignment
    train_validation_align: bool = Field(
        default=True,
        description="When True, train and eval scopes use the same segment indices.",
    )

    # --- Data ordering PROPOSAL (V19 PR 2) ---
    # Intent, not execution truth. The resolver combines this with any
    # operator override; only the resolved value reaches training and only
    # the resolved value describes what ran (see agent/schemas/ordering.py).
    order_strategy: OrderStrategy | None = Field(
        default=None,
        description=(
            "PROPOSED visitation order for training samples: 'shuffle' "
            "(global uniform shuffle) or 'sequential' (fixed file order, "
            "samples shuffled within each file). None = no proposal, which "
            "leaves the default in place. An operator override, when set, "
            "wins over this proposal — the proposal is still recorded."
        ),
    )
    file_order: list[int] | None = Field(
        default=None,
        description=(
            "PROPOSED file visitation order, valid only alongside "
            "order_strategy='sequential'. Must ultimately be a full "
            "permutation of the resolved DataScope (ordering must not change "
            "selection); the scope-dependent check runs at resolution. None "
            "with 'sequential' = ascending scope order."
        ),
    )

    @model_validator(mode="after")
    def _validate_target_files(self):
        """target_files required when using trial target strategy."""
        if self.is_trial and self.trial_strategy == "target" and not self.target_files:
            raise ValueError(
                "target_files required when is_trial=True and trial_strategy='target'."
            )
        return self

    @model_validator(mode="after")
    def _validate_ordering_proposal(self):
        """Structural validation of the ordering proposal (scope-independent).

        Scope-dependent validation (full permutation of the resolved
        DataScope) belongs to the resolver, which is the only place that
        knows the resolved scope AND whether an override supersedes this
        proposal. Note the proposal is validated even when an override will
        discard it — malformed agent output is a defect to surface, not to
        mask (see agent/schemas/ordering.py).
        """
        validate_ordering_shape(self.order_strategy, self.file_order, level="agent proposal")
        return self

    @classmethod
    def with_defaults(cls, raw: dict[str, Any] | list[Any]) -> ExperimentPlan:
        """Validate raw LLM output, falling back to defaults on invalid fields.

        Thin wrapper over :meth:`parse_with_fallback` for callers that do not
        need to know whether an ordering proposal was discarded.
        """
        plan, _rejected_ordering = cls.parse_with_fallback(raw)
        return plan

    @classmethod
    def parse_with_fallback(
        cls, raw: dict[str, Any] | list[Any]
    ) -> tuple[ExperimentPlan, RejectedOrderingProposal | None]:
        """
        Validate raw LLM output, reporting any ordering proposal that was lost.

        If the full dict fails validation (e.g. trial_portion=5.0), strip the
        trial fields and retry — preserving the LLM's experiment design while
        falling back to safe trial defaults.

        Defensive unwrap: LLMs occasionally emit a single-element list
        ``[{...}]`` instead of ``{...}`` — the input type therefore admits
        ``list[Any]`` to honestly reflect that runtime contract. Unwrap that
        case before validation; any other shape raises a clear TypeError.

        Ordering proposals ride this same path: a bad one does not kill the
        round, which is the established treatment of any invalid LLM trial
        field. But falling back must never be SILENT — a rejected proposal is
        materially different from no proposal, and downstream interpretation
        has to be able to tell them apart. So when the fallback discards an
        ordering proposal, this method returns it alongside the plan, with a
        reason that distinguishes the two possible failures:

        - the ordering fields were themselves invalid, or
        - the ordering was well-formed but was discarded because a DIFFERENT
          plan field failed validation.

        Reporting the second as the first would blame the agent's ordering for
        someone else's defect.

        Returns:
            ``(plan, rejected_ordering)`` — the second element is None when no
            ordering proposal was lost.
        """
        if isinstance(raw, list):
            if len(raw) == 1 and isinstance(raw[0], dict):
                print("[ExperimentPlan] LLM returned a single-element list — unwrapping to dict.")
                raw = raw[0]
            else:
                raise TypeError(
                    f"ExperimentPlan expected a dict, got list of length "
                    f"{len(raw)}. LLM output is malformed."
                )
        if not isinstance(raw, dict):
            raise TypeError(f"ExperimentPlan expected a dict, got {type(raw).__name__}.")
        try:
            return cls.model_validate(raw), None
        except Exception as exc:
            plan_error = str(exc)
            # Keep only experiment fields, let trial fields take defaults.
            # Use alias names (model_config, train_config, loss_config) since
            # that's what the LLM outputs.
            _EXPERIMENT_KEYS = {
                "model_type",
                "hypothesis",
                "reasoning",
                "model_config",
                "train_config",
                "loss_config",
            }
            safe = {k: v for k, v in raw.items() if k in _EXPERIMENT_KEYS}
            print(
                f"[ExperimentPlan] LLM returned invalid trial fields — "
                f"falling back to defaults. Kept keys: {list(safe.keys())}"
            )
            rejected = cls._describe_lost_ordering(raw, plan_error)
            if rejected is not None:
                print(f"[ExperimentPlan] ordering proposal not applied: {rejected.reason}")
            return cls.model_validate(safe), rejected

    @staticmethod
    def _describe_lost_ordering(
        raw: dict[str, Any], plan_error: str
    ) -> RejectedOrderingProposal | None:
        """Report the ordering proposal the fallback discarded, if there was one.

        Distinguishes "your ordering was invalid" from "your ordering was fine
        but the plan failed elsewhere" by re-validating the ordering fields on
        their own. Without that split, an unrelated ``trial_portion`` error
        would be recorded as an ordering defect.
        """
        strategy = raw.get("order_strategy")
        file_order = raw.get("file_order")
        if strategy is None and file_order is None:
            return None  # nothing was proposed, so nothing was lost

        try:
            validate_ordering_shape(strategy, file_order, level="agent proposal")
        except OrderingValidationError as ordering_exc:
            reason = f"the ordering proposal itself was invalid: {ordering_exc}"
        except Exception:
            # Not even shape-checkable (e.g. a non-list file_order); the plan
            # error already describes it.
            reason = f"the ordering proposal was not well-formed: {plan_error}"
        else:
            reason = (
                "the ordering proposal was well-formed but was discarded with "
                "the other trial fields because the plan failed validation: "
                f"{plan_error}"
            )
        return RejectedOrderingProposal(
            strategy=strategy if isinstance(strategy, str) else None,
            file_order=(
                file_order
                if isinstance(file_order, list) and all(isinstance(i, int) for i in file_order)
                else None
            ),
            reason=reason,
        )


# ---------------------------------------------------------------------------
# Task-composition projection (Step 12 / PR-12a, D-12a-1)
# ---------------------------------------------------------------------------


class TaskCompositionRef(BaseModel):
    """What the tuner needs to know about its run's task composition.

    **This is a PROJECTION, never a second semantic authority.** The composed
    run's real authorities stay exactly where Step 10 put them: the metric,
    dataset profile, task config and data-path implementation are run-scoped
    ContextVar bindings resolved at the composition edge, and the record and
    output composition-fingerprint STAMPS keep reading
    ``active_composition_fingerprint()`` (Step 11's F-11-C10-a fix, AST-pinned
    at exactly two call sites). Nothing here replaces any of them.

    **What it does replace** is the tuner ASKING THE AMBIENT ENVIRONMENT
    whether its own run is composed. Before PR-12a the W4 reference-science
    guard called ``active_task_data_path()`` — a subsystem seam consulted as a
    discriminator — and the tuner's per-model ``build_run_invariants`` call
    simply had no composition values to pass, so a composed run's per-model
    lock recorded none. A node should learn what kind of run it is from its
    INPUT.

    Every field is a value the composition already resolved; none is
    re-derived here. The whole model is optional at the input (``None`` =
    un-composed), so every existing caller is unaffected and regime A is
    untouched.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    semantic_fingerprint: str = Field(
        description=(
            "The composition's semantic identity, as computed at the "
            "composition edge. Carried so the tuner's per-model "
            "run-invariants lock can record WHICH task produced that "
            "workspace. It is NOT the source of the record/output stamps — "
            "those read the run-scoped authority, and Gate 2 caught the two "
            "disagreeing when they had separate sources (F-11-C10-a)."
        )
    )
    task_data_path_id: str = Field(
        description=(
            "The bound data-path implementation's declared id. The W4 "
            "reference-science guard keys on this projection's PRESENCE; the "
            "id is carried for provenance and for error messages that have to "
            "name what the run is bound to."
        )
    )
    task_health_binding: Any = Field(
        description=(
            "The run's Health binding — a task-health config path, or a "
            "``HealthBindingState`` naming an absence. Typed ``Any`` because "
            "``TaskHealthBinding`` is ``HealthBindingState | str`` and this "
            "schema must not import the health package to say so. Carried so "
            "the tuner's per-model effective config is materialized under the "
            "SAME binding as the chain's, instead of re-resolving "
            "``LEGACY_OMITTED`` and stamping ``legacy_default`` on a document "
            "that carries the task's roster."
        )
    )
    segmentation_applicability: Literal["temporal", "not_applicable"] | None = Field(
        default=None,
        description=(
            "Task-owned resource-probe segmentation declaration projected at the "
            "composition edge. None is undeclared, never a temporal default."
        ),
    )
    supervision_target: TensorContract | None = Field(default=None)
    custom_loss_applicability: CustomLossApplicability | None = Field(
        default=None,
        discriminator="mode",
    )
    task_owned_custom_loss: TaskOwnedCustomLoss | None = Field(
        default=None,
        description="Exact custom-loss implementation selected by the composition edge.",
    )
    objective: Any = Field(
        default=None,
        description=(
            "The task's AUTHORITATIVE training objective as a validated "
            "``LossConfig``, or ``None`` when the task declares none. Step 12 "
            "/ PR-12d, F-12d-31: a task that ships its own objective must not "
            "depend on the planner choosing it — two real composed DAVIS runs "
            "trained with ``smooth_l1`` because the planner is told that is "
            "the only valid regressor loss and never learns the task declares "
            "exact L1. Typed ``Any`` for the same reason "
            "``task_health_binding`` is: this schema must not import "
            "``ml_models`` to name ``LossConfig``. ``None`` is every run that "
            "exists today and leaves the planner's choice standing."
        ),
    )
    parameter_rules: ParameterRules | None = Field(
        default=None,
        description=(
            "Task-owned parameter constraints resolved at the composition edge. "
            "None leaves every plan parameter agent-controlled. Typed Any keeps "
            "this projection independent of the parameter-rule implementation."
        ),
    )
    description_source_policy: DescriptionSourcePolicy = Field(
        default=DescriptionSourcePolicy.COMPOSED,
        description=(
            "Description-source authority projected from the composition. "
            "Composed runs exclude packaged descriptions; legacy callers use "
            "the standalone policy."
        ),
    )


# ---------------------------------------------------------------------------
# Agent input
# ---------------------------------------------------------------------------


#: Lane F / F14 — the ONE authority for "trial-scoped plan_overrides keys"
#: (review C4 closed the shared-name gap): TWO different sets both used to be
#: called this. The tuner CLI's ``--is_trial`` BUNDLE is only
#: {is_trial, trial_portion, eval_portion}; the RESOLVER's formal branch
#: (``_resolve_sample_set_cfg("formal")``) replaces FIVE plan fields by
#: default — trial_strategy, trial_portion, train_portion, eval_strategy,
#: eval_portion. In opt-in agent-owned formal training, the two training
#: portions remain effective. This set is the legacy superset; the schema
#: validator and the node's
#: formal-round disclosure both consume it, so ``--plan_overrides
#: '{"train_portion": 1.0}'`` can no longer be silently discarded one key
#: outside the guarded set. Layering: defined HERE because the schema may
#: not import from nodes; the node imports it from the schema.
TRIAL_SCOPED_OVERRIDE_KEYS: frozenset[str] = frozenset(
    {
        "is_trial",
        "trial_strategy",
        "trial_portion",
        "train_portion",
        "eval_strategy",
        "eval_portion",
    }
)


def validate_trial_override_schedule(
    *,
    plan_overrides: dict[str, Any],
    is_trial: bool,
    max_rounds: int,
    force_formal_round: bool,
    formal_training_scope_source: Literal["operator", "agent"],
) -> None:
    """Refuse overrides discarded by every round, at launch and tuner intake.

    This is the existing tuner invariant, shared without changing round
    resolution. Callers supply their effective merged operator overrides.
    """
    discarded = TRIAL_SCOPED_OVERRIDE_KEYS
    if formal_training_scope_source == "agent":
        discarded = discarded - {"trial_portion", "train_portion"}
    trial_scoped = discarded & set(plan_overrides)
    if trial_scoped and is_trial and max_rounds == 1 and force_formal_round:
        # Remedy ORDER is deliberate (F-316 finding: a remedy must be
        # REACHABLE from the surface that names it). The refusal fires
        # in practice on the tuner node CLI (`--is_trial` there is the
        # only auto-bundling route), and that surface HAS NO
        # force-formal flag — so the universally-typeable remedies
        # lead, and the force-formal escape is marked chain-path-only.
        raise ValueError(
            f"plan_overrides carries trial-scoped key(s) {sorted(trial_scoped)} "
            "but max_rounds=1 with force_formal_round=True forces the run's "
            "only round to FORMAL, so the override would apply to zero "
            "rounds (formal workload comes from --formal_strategy / "
            "--formal_portion / --formal_train_portion / "
            "--formal_eval_portion, with eval_strategy locked to "
            "'snapshot'). Refusing "
            "instead of silently ignoring the request. Remedies: raise "
            "--max_rounds so trial rounds exist, or drop the trial-scoped "
            "request (--is_trial / the trial overrides); on the CHAIN "
            "launcher only, --no-force_formal_round makes the final round "
            "honor the trial plan (the tuner node CLI has no such flag)."
        )


class EpochCapResolution(NamedTuple):
    """Resolved epoch ceiling for ONE round role (campaign decision D-BUD-6).

    ``cap`` is the effective ceiling the clamp applies (``None`` = no clamp);
    ``source`` names the :class:`HyperparamTuningInput` field that supplied
    it, so the clamp's log line and any provenance can say WHICH bound fired.
    ``source`` is ``None`` exactly when ``cap`` is ``None``.
    """

    cap: int | None
    source: Literal["trial_max_epochs", "formal_max_epochs", "max_epochs"] | None


class HyperparamTuningInput(BaseModel):
    """
    Full specification for a tune_ml_hyperparam_agent run.

    Fields are grouped by concern:
      - Research:  what to explore and how hard to push
      - Trial:     optional sparse-sampling mode for fast iteration (default = off)
      - Guidance:  expert advice steering the LLM planner
      - Seeding:   pre-existing records the agent should treat as prior knowledge
      - LLM:       which model drives the planning and reflection steps
      - Infra:     storage paths (managed by the communication interface in production)

    When ``is_trial=False`` (the default), the agent runs in normal single-file
    mode using ``file_index``. All trial fields are ignored. When ``is_trial=True``,
    the agent builds a SampleSet from the trial strategy and ignores ``file_index``.
    """

    # --- Research ---
    expected_planner_strategy: PlannerStrategyIdentity | None = Field(
        default=None,
        description="Parent workflow's resolved planner identity; standalone callers may omit it.",
    )
    planner_strategy: str | None = Field(
        default=None,
        description="Explicit installed planner strategy; omitted uses the installed default declaration.",
    )

    model_type: str = Field(
        description="Architecture to tune. One of the registered model keys, or 'auto' to let the agent decide.",
    )
    task_description: str = Field(
        default="",
        description="Plain-English description of the research task, sourced from "
        "``configs/task_config.yaml``. Injected into the ``{TASK_DESCRIPTION}`` "
        "placeholder in ``PLANNER_PROMPT`` at call time. Default empty string is "
        "for test fixtures only; production callers (workflow) always populate "
        "via ``get_task_description(load_task_config())`` which rejects empty "
        "values upstream. The tuner only needs the description (not the full "
        "forward contract) because hyperparameter optimization happens within "
        "an existing model architecture — the contract is already fixed by the "
        "implementor.",
    )
    seed_plugin_path: str | None = Field(
        default=None,
        description=(
            "Optional path to a plugin .py file used as the seed model for "
            "this run. When set, the file's PLUGIN_MODEL_TYPE must equal "
            "model_type. The tuner copies the file into the run's plugin "
            "directory (<workspace>/plugins/<run_name>/) at run start, so "
            "the training subprocess sees it via SIDERIUS_PLUGIN_DIRS. "
            "Leave None when seeding from a built-in model_type. "
            "See docs/run_scoped_plugins.md (Phase 3)."
        ),
    )
    file_index: int = Field(
        default=6,
        ge=0,
        # The previous description claimed the range was 0..39; the dataset
        # has NUM_FILES=20 files. The bound is dataset-owned, so it is not
        # restated here as a literal.
        description=(
            "Validation/training file index, within the configured dataset "
            "(see dataset_config.NUM_FILES). Default 6 matches the paper's "
            "standard split. Ignored when is_trial=True."
        ),
    )
    max_rounds: int = Field(
        default=50,
        ge=1,
        description="Maximum number of completed experiment rounds (OOM-skipped attempts do not count).",
    )
    health_checks_config: str | None = Field(
        default=None,
        description=(
            "Optional HealthGate YAML override. None preserves the shipped default config."
        ),
    )
    measurement_capability: ResolvedMeasurementCapability | None = Field(
        default=None,
        description=(
            "Caller-resolved measurement identity and availability. Generic tuning "
            "never derives a scientific task identity from the dataset path."
        ),
    )
    resume: bool = Field(
        default=False,
        description="Resume from validated completed rounds already present in this run workspace.",
    )

    # --- Phase L — per-round attempt budget + fail-round abort ---
    # Pre-Phase-L the tuner used a single shared pool (max_rounds * 3) and
    # counted any attempt against it, so a string of trial-round failures
    # could exhaust the pool before the loop ever reached the formal-promotion
    # round (the v2 0418 incident — see docs §11.1). Phase L splits the
    # budget per round and counts SUCCESSFUL rounds against max_rounds, with
    # a separate consecutive-failure brake (max_fail_rounds) that aborts the
    # iteration cleanly when the architecture is fundamentally too heavy.
    # The formal round gets its own (typically larger) budget because formal
    # is the only round with cross-architecture comparable scoring; an
    # iteration with no formal score is wasted entirely. See docs §11.2-11.5.
    attempts_per_round: int = Field(
        default=3,
        ge=1,
        description=(
            "Per-round attempt budget for trial rounds. Each round retries up "
            "to this many times after a gate-skip or error before the round "
            "is declared failed and consecutive_fails increments."
        ),
    )
    attempts_per_formal_round: int = Field(
        default=5,
        ge=1,
        description=(
            "Per-round attempt budget for the formal-promotion round. Higher "
            "than attempts_per_round (default 5 vs 3) because the formal "
            "round is the only one whose denoising_score is comparable across "
            "architectures, so an iteration with no formal score gives the "
            "next-iteration proposer no usable signal."
        ),
    )
    max_fail_rounds: int = Field(
        default=3,
        ge=1,
        description=(
            "Consecutive-failed-round abort trigger. When this many rounds in "
            "a row exhaust their attempt budget without a success, the tuner "
            "exits with termination_reason='aborted_fail_rounds' and (if the "
            "burst was gate-dominated) populates gate_exhaustion via Trigger "
            "B for the next-iteration proposer."
        ),
    )

    # --- Trial mode (optional — all defaults preserve normal single-file behavior) ---
    is_trial: bool = Field(
        default=False,
        description="When True, run in trial-explore mode with sparse sampling across multiple files.",
    )

    # Training data
    # DS7 — the operator-side ``trial_strategy`` / ``target_files`` /
    # ``eval_strategy`` input fields were deleted: dead at both ends
    # (threaded from CLI into this schema but never read by the tuner loop —
    # per-round strategy comes from the LLM plan, normalized under a partial
    # DataScope). Old serialized inputs carrying the removed keys still
    # validate (no ``extra="forbid"``). Per-round provenance lives on
    # ``ExperimentRecord``; data restriction is ``data_scope``'s job.
    trial_portion: float = Field(
        default=0.1,
        # ge=0.01, matching ExperimentPlan, TrialConfig and ProposalInput.
        # This was ge=0.0, which accepted a run with NO training data and
        # was then rejected by the plan schema mid-run. Nothing treats 0.0
        # as a sentinel; the intake bound was the outlier, not a feature.
        ge=0.01,
        le=1.0,
        description="Fraction of segments per file for the training scope. "
        "TRANSIT ONLY (Lane F2 truth): the tuner's executed TRIAL workload "
        "never reads this field — it reads the (possibly overridden) plan; "
        "the operator lock for portions is plan_overrides. The chain "
        "restores this schema default on bare launches so input bytes are "
        "unchanged.",
    )
    train_portion: float = Field(
        default=0.1,
        ge=0.01,
        le=1.0,
        description="Per-epoch subsample from training scope. Default 0.1 matches "
        "legacy TIDMAD. TRANSIT ONLY for trial execution — see trial_portion "
        "(Lane F2).",
    )

    # Validation data
    eval_portion: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Fraction of segments per file for validation. Set to 1.0 for "
        "formal mode. TRANSIT ONLY for trial execution — see trial_portion "
        "(Lane F2).",
    )

    # Alignment
    train_validation_align: bool = Field(
        default=True,
        description="When True, train and eval scopes use the same segment indices (different physical files).",
    )

    # --- Formal-mode training levers (Phase M — see docs/resource_estimator_implement.md §12) ---
    # Formal-mode eval defaults to snapshot + eval_portion=1.0 (full clone)
    # so cross-architecture scores are physically comparable. Phase R
    # (docs §13) adds ``formal_eval_portion`` so smoke / CI runs can opt
    # into a smaller deterministic eval scope without changing physical
    # constants — production runs should keep the 1.0 default.
    formal_strategy: Literal["snapshot", "anchors", "target"] = Field(
        default="snapshot",
        description=(
            "Training-side sampling strategy in formal mode. Overrides the "
            "planner's trial_strategy on any round promoted to formal. Eval "
            "strategy is always locked to ``snapshot``; eval scope is "
            "controlled by ``formal_eval_portion`` (default 1.0)."
        ),
    )
    formal_training_scope_source: Literal["operator", "agent"] = Field(
        default="operator",
        description=(
            "Source of formal training portions. 'operator' uses formal_portion "
            "and formal_train_portion; 'agent' uses the validated ExperimentPlan. "
            "Formal evaluation always uses formal_eval_portion."
        ),
    )
    formal_portion: float = Field(
        default=0.1,
        # F-RC-1: this becomes TrialConfig.trial_portion in FORMAL mode
        # (policy.py:1167), which declares ge=0.01. Accepting a lower
        # operator value admitted a config that could only fail later.
        ge=0.01,
        le=1.0,
        description="Fraction of segments per file for training scope in formal mode.",
    )
    formal_train_portion: float = Field(
        default=1.0,
        ge=0.01,
        le=1.0,
        description="Per-epoch iteration fraction from the formal training scope.",
    )
    formal_eval_portion: float = Field(
        default=1.0,
        # F-RC-1: this becomes TrialConfig.eval_portion in FORMAL mode
        # (policy.py:1169), which declares ge=0.01 — the same mismatch
        # `validation_max_portion` had.
        ge=0.01,
        le=1.0,
        description=(
            "Fraction of segments per file used for the formal-mode eval "
            "scope (snapshot strategy). Default 1.0 reproduces the legacy "
            "full-clone behaviour required for production score "
            "comparability. Smoke / CI runs may lower this (e.g. 0.05) "
            "to fit a tight time budget — Phase R, §13."
        ),
    )
    force_formal_round: bool = Field(
        default=True,
        description=(
            "When True (default), the last round of every iteration forces "
            "``plan.is_trial = False`` so it always runs in formal mode "
            "regardless of what the planner picked — this is the "
            "'cross-architecture comparable formal score' contract that the "
            "downstream interpreter/proposer rely on. The planner prompt is "
            "told formal mode is MANDATORY on the final round. "
            "Set to False ONLY for testing/debugging where you want the last "
            "round to honor the planner's mode choice (so trial-mode "
            "``trial_portion`` / ``train_portion`` / ``eval_portion`` actually "
            "take effect on the final round). When False, the planner prompt "
            "is told formal mode is OPTIONAL on the final round and the "
            "post-LLM override at ``_apply_mode_override_chain`` is skipped, "
            "so the formal-mode sample-set lock at "
            "``_resolve_sample_set_cfg(mode='formal')`` is bypassed for the "
            "last round because ``mode`` is derived from the un-overridden "
            "``plan.is_trial``."
        ),
    )
    formal_round_strategy: Literal[
        "full_clone",
        "hybrid_params",
        "independent",
        "inherit_best_trial",  # legacy alias of full_clone
        "llm_propose",  # legacy alias of independent
    ] = Field(
        default="full_clone",
        description=(
            "Orchestration policy for the forced formal round. Canonical "
            "values + legacy aliases — the validator canonicalises legacy "
            "literals to their canonical form before downstream code sees "
            "the value, so call sites only handle canonical names.\n\n"
            "Canonical values:\n"
            "* ``full_clone`` (default) — the formal round inherits "
            "  ``model_config``, ``loss_config``, ``train_config.lr``, "
            "  ``train_config.epochs``, and ``train_config.batch_size`` "
            "  from the highest-scoring trial-mode success record in the "
            "  current iteration. Maximum execution certainty: the formal "
            "  round is a longer training of the trial winner with full "
            "  eval — not a sandbox for new architectures, losses, or "
            "  hyperparameters. Required for the trial→formal "
            "  inference-time measurement reuse landed in commits B-D of "
            "  ``docs/refine_inference_time_estimator.md``.\n"
            "* ``hybrid_params`` — the formal round inherits "
            "  ``loss_config`` and ``train_config.lr`` only; the "
            "  planner's ``model_config``, ``train_config.epochs``, and "
            "  ``train_config.batch_size`` survive verbatim. Audit / "
            "  exploration use case: lock the evaluation surface (loss + "
            "  lr) but let the LLM scale capacity for the full-data pass. "
            "  The time gate may reject the planner's heavier choice; "
            "  that is the trade-off.\n"
            "* ``independent`` — the planner's choices for the formal "
            "  round are honored verbatim (no inheritance). Use only "
            "  when the formal round is meant to be a sandbox for new "
            "  hyperparameters; trial-round measurements are NOT reused.\n\n"
            "All three strategies share the no-winner fallback: if no "
            "successful trial round exists in the current iteration, the "
            "planner's plan is preserved unchanged and a WARNING is "
            "logged. Strategy only controls *what to copy when a winner "
            "exists* — it does not change no-winner behavior. ``is_trial`` "
            "is always flipped to ``False`` regardless of strategy.\n\n"
            "Legacy aliases (accepted for backward compat with running "
            "chains and pre-2026-05-02 ``advice/workflow/*.json`` configs):\n"
            "* ``inherit_best_trial`` → canonicalised to ``full_clone``.\n"
            "* ``llm_propose`` → canonicalised to ``independent``.\n\n"
            "Has no effect when ``force_formal_round=False`` or on non-last "
            "rounds. Generic across tasks — the predicate ``time_mode == "
            "'trial' AND status == 'success'`` is task-agnostic."
        ),
    )

    @field_validator("formal_round_strategy", mode="before")
    @classmethod
    def _canonicalise_legacy_strategy(cls, v):
        """Resolve legacy literals to their canonical name before
        Literal-validation runs. See docs/refactor_formal_round_strategy.md
        §2.1 for the alias table.
        """
        legacy = {
            "inherit_best_trial": "full_clone",
            "llm_propose": "independent",
        }
        if isinstance(v, str):
            return legacy.get(v, v)
        return v

    # --- Post-v15 delta gates: skip_formal + bypass_formal_time_budget ---
    # Both gates use ``current_run_best_formal_score`` as the reference point.
    # V19 PR 1 (docs/design/v19_priorities/pr1_chain_incumbents.md): the
    # reference is ``float | None`` with ``None`` = "no chain incumbent"
    # (both gates short-circuit). In chain production the value is injected
    # from committed prior-iteration state reconstructed by
    # ``core/resume.py`` (commit-time HealthGate validity only); it is never
    # a fixed constant. Explicit numeric values remain legal for
    # standalone/test runs.
    #
    # Do NOT use 5.5763 as the default. That value is the deterministic
    # scoring fingerprint of the class-127 mode-collapse attractor:
    # constant int8=-1 output → PSD is all FP subnormals → SNR = 2^17
    # exactly → ``log_5.27(10592.7443) = 5.5762667``. Every v15/v16
    # arch-chain "successful" formal score matched this artifact, not a
    # WaveNet denoising baseline. See
    # ``docs/design/pluggable_health_checks.md`` §7.1 and the v16
    # forensic audit in ``reports/v16_20260630.md``.
    #
    # Motivation — v15 retrospective (reports/v15_20260628.md):
    # * arch chain's mamba_multirate_fuser (trial=7.65) and
    #   dualpath_spectral_router (trial=7.77) had every formal attempt
    #   rejected by the time-risk gate (formal_time_budget=120 min while
    #   the estimator predicted >150 min). The bypass gate gives any
    #   trial winner that beats the current best a chance to run formal.
    # * trial rounds that score well below the current best formal still
    #   consumed formal-round budget without producing useful data. The
    #   skip gate cuts that waste while keeping borderline cases.

    current_run_best_formal_score: float | None = Field(
        default=None,
        description=(
            "Chain formal-incumbent reference (V19 PR 1). ``None`` = no "
            "incumbent: both delta gates short-circuit and never fire. In "
            "chain production, populated from committed prior iterations "
            "by ``core.resume``; consumption gated by "
            "``enable_chain_incumbent_formal_gates``. Full semantics: "
            "``nodes/ml_hyperparameter_tune_agent/"
            "ml_hyperparameter_tune_agent.md`` under 'Chain "
            "formal-incumbent reference'. Never 0.0 as a default (the "
            "pre-V19 defect); never 5.5763 (class-127 phantom; see block "
            "comment above)."
        ),
    )
    skip_formal_min_delta: float = Field(
        default=-1.0,
        description=(
            "Skip all formal rounds when the best trial score is WORSE than "
            "the incumbent moved by this margin. Declared in the GOLDEN "
            "METRIC'S OWN UNITS (dB under TIDMAD, whose metric is log-space); "
            "the framework supplies the orientation, the operator supplies the "
            "number. It is a coordinate on the better-direction axis: negative "
            "loosens the threshold, positive tightens it, under a maximised "
            "and a minimised metric alike (Step 07 PR 07b). "
            "When the reference is ``None`` the resolved threshold is "
            "``None`` and this gate never fires. "
            "Default ``-1.0``: only skip formal when trial is more than "
            "1.0 unit worse than the current best formal score. Set to "
            "``0.0`` to skip formal whenever trial does not beat current "
            "best. Set to ``float('-inf')`` to disable this gate entirely — "
            "that resolves to the metric's WORST value under either "
            "direction, so the disable convention needs no second form."
        ),
    )
    bypass_formal_time_budget_min_delta: float = Field(
        default=0.0,
        description=(
            "Bypass the formal time-budget gate when the best trial score is "
            "at least as good as the incumbent moved by this margin. Declared "
            "in the GOLDEN METRIC'S OWN UNITS (dB under TIDMAD) and, like "
            "``skip_formal_min_delta``, a coordinate on the better-direction "
            "axis rather than a raw addition (Step 07 PR 07b). When the "
            "reference is ``None`` the resolved threshold is ``None`` and this "
            "gate never fires. Default ``0.0``: "
            "bypass the time gate whenever trial sets a new run best. "
            "Set to ``0.5`` to only bypass when trial beats current "
            "best by >= 0.5 units. Set to ``float('inf')`` to disable "
            "bypass entirely — that resolves to the metric's BEST value "
            "under either direction."
        ),
    )

    bypass_formal_time_budget_minutes: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "Lane F3 / F-BYPASS-WD-1: the ELEVATED wall-time ceiling (minutes) "
            "a score-QUALIFIED bypass formal attempt may use — ONE resolved "
            "value consumed by BOTH the admission time gate (feasibility is "
            "RE-EVALUATED against it, never flag-forced: a forecast past even "
            "this ceiling is refused under bypass) AND the runtime watchdog's "
            "operator_budget_seconds, so the two can never disagree. "
            "``None`` (default) is load-bearing safety: a qualified bypass "
            "grants NO extension — the elevated ceiling must be explicitly "
            "materialised at launch (campaign: 200; normal formal: "
            "formal_time_budget_minutes 120), so this can never become a "
            "global raise through a schema default. The watchdog is never "
            "disabled by this value."
        ),
    )

    enable_chain_incumbent_formal_gates: bool = Field(
        default=False,
        description=(
            "V19 PR 1 consumption-only switch. ON: formal delta gates "
            "use ``chain_incumbent + fixed_delta``. OFF (default): the "
            "incumbent is still reconstructed and recorded, but the "
            "gates do not consume it. OFF is NOT a fixed-0.0 mode. "
            "Full semantics: ``nodes/ml_hyperparameter_tune_agent/"
            "ml_hyperparameter_tune_agent.md`` under 'Chain "
            "formal-incumbent reference'."
        ),
    )

    # --- V19 PR 3 — structured-health-feedback policy PASS-THROUGH
    #     (pr3_healthgate_feedback.md §3.9, §6 'tuner lock site'). The
    #     tuner has NO PR 3 behavior of its own: these exist solely so the
    #     tuner's run-invariants lock call and run_config stamps carry the
    #     chain's policy consistently with the workflow and chain runner.
    enable_structured_health_feedback: bool = Field(
        default=False,
        description=(
            "V19 PR 3 chain policy pass-through: whether structured "
            "HealthGate feedback prompt rendering is enabled for the "
            "chain's interpreter/proposer. The tuner only locks and "
            "stamps it — no tuner behavior changes with the flag."
        ),
    )
    health_feedback_history_window_iterations: int = Field(
        default=3,
        ge=1,
        description=(
            "V19 PR 3 retention-policy pass-through (locked + stamped "
            "only; consumed by the interpreter, not the tuner)."
        ),
    )
    health_feedback_history_max_entries_per_model: int = Field(
        default=8,
        ge=1,
        description=(
            "V19 PR 3 retention-policy pass-through (locked + stamped "
            "only; consumed by the interpreter, not the tuner)."
        ),
    )

    # --- arXiv U1 (#253 / #254) — run-identity PASS-THROUGH. Same contract
    #     as the V19 PR 3 block above: the tuner locks these into its
    #     per-model run-invariants lock and stamps them onto its records /
    #     output; it never CONSUMES them. `experiment_arm` is opaque (R2).
    experiment_arm: str | None = Field(
        default=None,
        description=(
            "arXiv U1 pass-through: the opaque experiment-arm label of the "
            "chain this tuner invocation belongs to, or None (unlabelled). "
            "Locked + stamped only — no tuner behaviour keys on it (R2)."
        ),
    )
    lit_review_enabled: bool = Field(
        default=False,
        description=(
            "arXiv U1 pass-through: whether the literature-review node is "
            "part of the chain's workflow topology. Locked only; the tuner "
            "has no lit-review behaviour of its own."
        ),
    )
    data_analysis_enabled: bool | None = Field(
        default=None,
        description=(
            "Workflow Data Analysis treatment pass-through. Locked and stamped only; "
            "the tuner does not consume analysis evidence through this field."
        ),
    )
    lit_review_config_sha256: str | None = Field(
        default=None,
        description=(
            "arXiv U1 pass-through: sha256 of the resolved lit-review YAML "
            "when enabled, else None. Locked only; the tuner never reads the "
            "config. The lock refuses enabled-without-sha at construction."
        ),
    )
    scientific_evidence_order: Literal["analysis_then_literature", "literature_then_analysis"] = (
        Field(
            default="analysis_then_literature",
            description="Workflow-owned analysis/literature order; locked only by the tuner.",
        )
    )
    baseline_isolation: bool = Field(
        default=False,
        description=(
            "arXiv U3 (#260) — the WITHOUT arm's explicit isolation flag. "
            "Locked into the per-model run-invariants lock and forwarded to "
            "the model-description loader, which then refuses a BUNDLED "
            "built-in description; the tuner has no other behaviour under it "
            "(a built-in candidate is refused before it reaches the tuner)."
        ),
    )

    degenerate_penalty_score: float | None = Field(
        default=None,
        description=(
            "Operator policy for the agent's reaction when "
            "``execute_tools.scoring_utils.score_vector`` flags a degenerate "
            "output on a formal round (``is_degenerate=True`` AND "
            "``not plan.is_trial``).\n"
            "* ``None`` (default) — null the ``denoising_score`` so the round "
            "  cannot be picked as 'best'. Conservative; preserves prior "
            "  behaviour from the legacy zero-output sanity check.\n"
            "* float (typically large negative, e.g. ``-5.0``) — use the value "
            "  as the round's ``denoising_score``. Lets the planner's "
            "  best-tracking still rank the round, but pushes it strictly below "
            "  any healthy success.\n"
            "In both cases ``status`` is set to ``'failed_mode_collapse'`` and "
            "``failure_reason`` is populated from the health-check message. "
            "Trial rounds are immune (no benchmark to compare against).\n"
            "**Direction (Step 07 PR 07b §3.3 row 5).** The float convention "
            "describes a MAXIMISED metric: under a minimised one the same "
            "``-5.0`` is the best score in the run and the planner would read "
            "a collapsed round as the campaign's finest. A finite float is "
            "therefore REFUSED at startup when the bound golden metric is "
            "lower-is-better — not negated, not reinterpreted. ``None`` is "
            "direction-free and always accepted."
        ),
    )

    # --- Reproducibility seeds (optional — auto-generated when not provided) ---
    sampling_seed: int | None = Field(
        default=None,
        description=(
            "Seed for build_sample_set() — determines which PSD segments form the "
            "data scope. When None, auto-generated from SHA-256(run_name + attempt). "
            "Set this to replay a previous run's exact data sampling. "
            "Read from a previous trial_config_{exp_id}.json."
        ),
    )
    train_base_seed: int | None = Field(
        default=None,
        description=(
            "Base seed for per-epoch training subsampling. Epoch n uses "
            "train_base_seed + n. When None, auto-generated. "
            "Read from a previous trial_config_{exp_id}.json."
        ),
    )

    # --- Time-budget gate (evaluate_time_skill) ---
    # See docs/resource_estimator_implement.md §2.7 + Phase I. The single
    # `time_budget_minutes` field used in Phases D-G was split into two so the
    # per-round gate uses the right ceiling for the mode the round runs in.
    # Both fields originate at the workflow/CLI level and are forwarded through
    # the validator→tuner protocol. Each is independently optional: setting
    # only the trial budget gates trial rounds and skips formal rounds, and
    # vice versa. The tuner picks the right one each round via plan.is_trial.
    trial_time_budget_minutes: float | None = Field(
        default=None,
        description=(
            "Wall-time budget in minutes against which evaluate_time_skill "
            "gates rounds where the planner picks trial mode (plan.is_trial=True). "
            "None = trial gate disabled; the tuner prints a one-time warning at "
            "startup and skips the time check for trial rounds. Set at the "
            "workflow level so both the proposer's baseline gate and the "
            "tuner's per-round gate see the same number for trial-mode "
            "estimates."
        ),
    )
    trial_time_admission_source: TimeAdmissionSource = Field(
        default="measured",
        description=(
            "Single wall-time admission authority for Trial rounds. "
            "'forecast' uses the advance workload forecast; 'measured' uses "
            "executing-device in-process evidence. The unselected authority "
            "may record observations but cannot reject the attempt."
        ),
    )
    formal_time_budget_minutes: float | None = Field(
        default=None,
        description=(
            "Wall-time budget in minutes against which evaluate_time_skill "
            "gates rounds where the planner picks formal mode (plan.is_trial=False). "
            "None = formal gate disabled; the tuner prints a one-time warning "
            "at startup and skips the time check for formal rounds. Sized "
            "independently from the trial budget because formal runs use the "
            "full dataset and have a wall-time scale 50-100× longer."
        ),
    )
    formal_time_admission_source: TimeAdmissionSource = Field(
        default="measured",
        description=(
            "Single wall-time admission authority for Formal rounds. "
            "'forecast' uses the advance workload forecast; 'measured' uses "
            "executing-device in-process evidence. The unselected authority "
            "may record observations but cannot reject the attempt."
        ),
    )

    # --- Step/batch guardrails (RT5, runtime-control design §5) ---
    # Defense-in-depth SECONDARY sanity checks — the primary admission
    # criterion is predicted total runtime (in-subprocess verification).
    # These catch degenerate counts even when the estimator claims they
    # are cheap. Schema defaults are None (disabled) so programmatic
    # callers keep pre-RT5 behavior; the §5 PROVISIONAL operational
    # values (150k steps / batch 4) are applied by the chain/CLI launch
    # wiring (RT6), where they are operator-visible configuration.
    max_steps_per_attempt: int | None = Field(
        default=None,
        gt=0,
        description=(
            "§5 guardrail: a plan whose resolved optimizer-step count "
            "exceeds this is skipped pre-flight (planner-visible record) "
            "unless allow_extreme_steps is set. None disables "
            "(provisional operational value: 150,000 — set by the chain "
            "launch wiring)."
        ),
    )
    min_formal_batch_size: int | None = Field(
        default=None,
        gt=0,
        description=(
            "§5 guardrail: formal rounds with batch_size below this are "
            "skipped pre-flight — encodes the known launch-overhead "
            "pathology (V18 incident: batch=2). Trial rounds are exempt. "
            "None disables (provisional operational value: 4 — set by "
            "the chain launch wiring)."
        ),
    )
    allow_extreme_steps: bool = Field(
        default=False,
        description=(
            "§5 operator override: bypass BOTH step/batch guardrails for "
            "this run. An explicit schema field recorded in run_config "
            "provenance — never a prompt instruction."
        ),
    )
    runtime_watchdog_enabled: bool = Field(
        default=False,
        description=(
            "§4 runtime watchdog (RT4/RT6): when True, training/inference "
            "subprocesses run in their own process group under the "
            "deadline max(floor, min(operator_budget, verified_estimate x "
            "safety)). Disabled by default; Gate 2 enables it explicitly."
        ),
    )
    runtime_safety_factor: float = Field(
        default=1.0,
        ge=1.0,
        description=(
            "§2.10 safety multiplier applied to the known-cost sum at "
            "admission time and to the verified estimate in the watchdog "
            "deadline. Schema default 1.0 preserves programmatic-caller "
            "behavior; the V18 production posture (1.5) is passed "
            "explicitly by the launch configuration (Gate 2 wiring, "
            "2026-07-24). Phase-specific overrides: "
            "runtime_trial_safety_factor / runtime_formal_safety_factor "
            "take precedence for their phase when provided."
        ),
    )
    runtime_trial_safety_factor: float | None = Field(
        default=None,
        ge=1.0,
        description=(
            "§2.10 phase-specific safety factor for TRIAL attempts. "
            "Precedence: this value when provided → runtime_safety_factor "
            "→ its schema default. Wave-1A diagnostic (2026-07-24): trial "
            "attempts of novel architectures ran a systematic 1.54-1.61x "
            "past stable verification under 2-way concurrency, so the V18 "
            "production posture is 2.0 for trials while formals keep 1.5."
        ),
    )
    runtime_formal_safety_factor: float | None = Field(
        default=None,
        ge=1.0,
        description=(
            "§2.10 phase-specific safety factor for FORMAL attempts. "
            "Precedence: this value when provided → runtime_safety_factor "
            "→ its schema default. None keeps formal admission on the "
            "calibrated base factor."
        ),
    )
    runtime_watchdog_safety_factor: float | None = Field(
        default=None,
        ge=1.0,
        description=(
            "V19 watchdog-only deadline multiplier (admission/watchdog "
            "split, 2026-07-29). None (default) → the watchdog uses the "
            "phase-effective admission factor exactly as V18 — omitting "
            "this flag reproduces V18 behavior. When set, ONLY the "
            "watchdog deadline uses it (both phases); admission keeps "
            "the phase-effective factor. V19 single-GPU launch posture: 3.5."
        ),
    )
    runtime_watchdog_floor_seconds: float = Field(
        default=60.0,
        ge=0.0,
        description=(
            "§4 watchdog deadline floor. Schema default 60.0 mirrors "
            "WatchdogConfig; the V18 production posture (120.0 — covers "
            "the measured 20-25 s subprocess startup that verified "
            "components do not include) is passed explicitly by the "
            "launch configuration."
        ),
    )
    runtime_verification_max_wall_seconds: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "Optional wall-time ceiling for adaptive in-subprocess runtime "
            "verification. None preserves AdaptiveVerificationConfig's "
            "default. Increase this for workloads whose individual optimizer "
            "steps are too slow for the default window to observe steady "
            "state; this does not change the Trial or Formal run budget."
        ),
    )

    # --- VRAM-budget gate (evaluate_vram_skill, Phase K) ---
    # Mirrors the trial/formal split of the time gate. The tuner picks the
    # right one per round via plan.is_trial. Each is independently optional:
    # setting only the trial budget gates trial rounds and skips formal rounds,
    # and vice versa. The budget here acts as an operator-defined ceiling; the
    # skill compares vram_estimate against min(defensive_floor, budget).
    # See docs/resource_estimator_implement.md §10.4 / §10.5.
    gpu_admission_measurement_source: str | None = Field(
        default=None,
        description=(
            "V20 B-G3. Where an authoritative GPU measurement for a "
            "candidate would be resolved from — a REFERENCE, never a "
            "figure. There is deliberately no field and no flag carrying a "
            "raw MiB number: one an operator could type would impersonate "
            "a measurement in formal mode, which is the estimate-as-fact "
            "defect PR B removes. Until PR C provides an acquisition and "
            "promotion path, this resolves to nothing and formal rounds "
            "refuse with policy_unavailable. None = no source configured."
        ),
    )
    gpu_admission_enforcement: AdmissionEnforcement = Field(
        default="observe_only",
        description=(
            "V20 B-G3/D-B4/M5. What the run DOES about an adverse GPU "
            "admission decision. Orthogonal to trial/formal posture: the "
            "posture says what the round is, this says what the run does "
            "about a refusal. `observe_only` is the compatibility default "
            "— it records the decision and proceeds. "
            "`enforce_resource_limits` is the V20 PRODUCTION posture: a "
            "resource verdict (`insufficient_headroom`) stops the phase, "
            "an evidence gap is recorded. `enforce` stops on any adverse "
            "decision and is the B-G validation-harness posture, not a "
            "campaign posture. The phase is never relabelled."
        ),
    )
    gpu_pair_ceiling_gib: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "V20 B-G3. Aggregate GPU ceiling in GiB passed explicitly to "
            "the admission gate. None = defer to the environment resolver "
            "(SIDERIUS_PAIR_VRAM_CEILING_GIB, then the compatibility "
            "default), which is exactly the pre-B-G3 behaviour."
        ),
    )
    trial_vram_budget_gb: float | None = Field(
        default=None,
        description=(
            "VRAM budget in GB against which evaluate_vram_skill gates rounds "
            "where the planner picks trial mode (plan.is_trial=True). "
            "None = trial VRAM gate disabled; the tuner prints a one-time "
            "warning at startup and skips the VRAM check for trial rounds. "
            "Operator-defined ceiling — set conservatively so the gate rejects "
            "models that exceed it even when raw free-VRAM is plentiful."
        ),
    )
    formal_vram_budget_gb: float | None = Field(
        default=None,
        description=(
            "VRAM budget in GB against which evaluate_vram_skill gates rounds "
            "where the planner picks formal mode (plan.is_trial=False). "
            "None = formal VRAM gate disabled; the tuner prints a one-time "
            "warning at startup and skips the VRAM check for formal rounds. "
            "Sized independently from the trial budget because formal runs may "
            "use larger batch sizes or full-dataset sampling."
        ),
    )
    vram_probe_step_timeout_seconds: float = Field(
        default=180.0,
        gt=0.0,
        description=(
            "Maximum wall time for one training-mode or inference VRAM "
            "footprint forward. This is not an epoch, optimizer step, or "
            "candidate-runtime budget. The workflow owns this safeguard "
            "because one task-valid batch may have very different execution "
            "cost across task types."
        ),
    )
    vram_preflight_total_timeout_seconds: float = Field(
        default=900.0,
        gt=0.0,
        description=(
            "Maximum wall time for the complete isolated VRAM preflight "
            "worker, including model construction, training-footprint "
            "measurement, inference-batch search, and inference-footprint "
            "measurement. Independent of Trial/Formal training budgets."
        ),
    )
    vram_preflight_host_memory_limit_gb: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "Optional maximum resident host memory in GiB for the complete isolated "
            "VRAM-preflight process tree. This is a workflow-owned safety "
            "limit, not a GPU VRAM ceiling or a model-capacity verdict. "
            "Task-valid batches and model inspection can have different host "
            "memory costs across task types. None preserves the deployment "
            "default, normally 24 GiB."
        ),
    )
    data_dir: str | None = Field(
        default=None,
        description=(
            "Filesystem path to the dataset directory, for an UN-COMPOSED "
            "run. Forwarded to evaluate_time_skill so its real-dataset warmup "
            "can read 1 PSD from the actual disk path the training run will "
            "use. When None, the skill falls back to its static-formula "
            "estimate. Step 11 C4 (R-11-7): a COMPOSED run's bound physical "
            "data root wins over this field — there is ONE authority for "
            "where the data physically lives, and pricing a warmup against a "
            "different root would measure the wrong disk."
        ),
    )

    # --- Hard constraints on LLM plan output (enforced after plan, not by the LLM) ---
    max_epochs: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Hard cap on epochs per round. When set, the tuner clamps the LLM's "
            "planned epochs to min(planned_epochs, max_epochs). Use this to prevent "
            "the LLM from choosing excessively long training in integration tests "
            "or resource-constrained environments. Mode-aware overrides: "
            "trial_max_epochs / formal_max_epochs take precedence for their "
            "round role when provided (D-BUD-6); this field is the fallback "
            "for a role with no per-mode ceiling."
        ),
    )
    training_budget_reserve_fraction: float | None = Field(
        default=None,
        gt=0,
        lt=1,
        description="Opt in to cooperative epoch allocation; reserve this fraction of the role budget for inference/scoring/save. Requires an explicit role epoch cap <=100. No scientific early stopping; retain last weights.",
    )
    trial_max_epochs: int | None = Field(
        default=None,
        ge=1,
        description=(
            "TRIAL-role epoch ceiling (campaign decision D-BUD-6: the frozen "
            "campaign posture is trial 2 / formal 1). Precedence for a trial "
            "round: this value when provided -> max_epochs -> no clamp; formal "
            "rounds never read it. The round's role identity is plan.is_trial "
            "AFTER the mode-override chain — the same authority that stamps "
            "record.is_trial (PR #217) — and resolution happens ONLY in "
            "resolve_epoch_cap(). The clamp arithmetic is unchanged "
            "min(planned_epochs, cap); a ceiling can only reduce a planned "
            "value, never raise one. None (default) leaves trial rounds on "
            "the mode-agnostic max_epochs, byte-identical to pre-D-BUD-6 "
            "behavior. Same per-mode split shape as "
            "runtime_trial_safety_factor (Wave-1A)."
        ),
    )
    formal_max_epochs: int | None = Field(
        default=None,
        ge=1,
        description=(
            "FORMAL-role epoch ceiling (campaign decision D-BUD-6). Precedence "
            "for a formal round: this value when provided -> max_epochs -> no "
            "clamp; trial rounds never read it. See trial_max_epochs for the "
            "role-identity authority and the resolution rule; None (default) "
            "leaves formal rounds on the mode-agnostic max_epochs."
        ),
    )

    @model_validator(mode="after")
    def validate_training_allocation(self):
        """Reject an incomplete opt-in policy before tuner work begins."""
        if self.training_budget_reserve_fraction is not None:
            for is_trial, budget in (
                (True, self.trial_time_budget_minutes),
                (False, self.formal_time_budget_minutes),
            ):
                cap = self.resolve_epoch_cap(is_trial=is_trial).cap
                if budget is None or cap is None or cap > 100:
                    raise ValueError(
                        "Cooperative training requires both role time budgets and "
                        "explicit epoch caps in 1..100; no implicit unbounded training"
                    )
        return self

    def resolve_epoch_cap(self, *, is_trial: bool) -> EpochCapResolution:
        """THE resolution rule for a round's epoch ceiling (D-BUD-6).

        Precedence for the round's role: the per-mode ceiling
        (``trial_max_epochs`` / ``formal_max_epochs``) when provided -> the
        mode-agnostic ``max_epochs`` -> no clamp. Every consumer of the cap
        (the planning clamp, the planner-prompt disclosure, the clamp's log
        label) calls THIS method — re-deriving the rule at a call site is
        how a split value ships silently disabled (the F2 ownership-gap
        lesson).

        Args:
            is_trial: the round's role identity — ``plan.is_trial`` AFTER
                ``_apply_mode_override_chain``, the same authority that
                stamps ``record.is_trial`` (PR #217). Never
                ``memory.time_mode``, which is time-gate metadata.

        Returns:
            EpochCapResolution: the effective cap (``None`` = no clamp) and
            the name of the field that supplied it. With both per-mode
            fields unset this resolves to ``max_epochs`` for every round —
            the legacy mode-agnostic behavior, byte-identical.
        """
        per_mode = self.trial_max_epochs if is_trial else self.formal_max_epochs
        if per_mode is not None:
            return EpochCapResolution(
                cap=per_mode,
                source="trial_max_epochs" if is_trial else "formal_max_epochs",
            )
        if self.max_epochs is not None:
            return EpochCapResolution(cap=self.max_epochs, source="max_epochs")
        return EpochCapResolution(cap=None, source=None)

    validation_max_portion: float | None = Field(
        default=None,
        # F-RC-1: `ge=0.01`, NOT `gt=0.0`. This ceiling is applied as
        # `min(planned, ceiling)` to trial_portion / train_portion /
        # eval_portion, every one of which declares `ge=0.01`. A ceiling below
        # that floor therefore cannot produce a legal `TrialConfig` for ANY
        # plan — the clamp manufactures a schema violation the planner cannot
        # avoid, because the planner never chose the value. Accepting
        # 0.0 < x < 0.01 here was a contract mismatch between the boundary
        # that ADMITS the value and the boundary that CONSUMES it.
        #
        # Found by a real Gate run: `--validation_max_portion 0.002` was
        # accepted here and then rejected 17 times inside the retry budget,
        # each rejection costing a real LLM planning call.
        ge=0.01,
        le=1.0,
        description=(
            "VALIDATION POSTURE ONLY (V20 FU-D-12). Hard ceiling on the "
            "RESOLVED trial-mode data portions — trial_portion, train_portion "
            "and eval_portion — applied as min(planned, ceiling) at the "
            "plan-to-trial boundary, beside the existing max_epochs clamp.\n\n"
            "It exists because those three values are resolved from the LLM "
            "PLAN, not from operator input: a Gate that requested 0.02 "
            "measured 0.1 in practice. Time budgets bound wall time but do "
            "not bound WORKLOAD, and the harness — not the planner — must own "
            "the maximum.\n\n"
            "A maximum, never a replacement: it can only reduce a planned "
            "portion, never raise one, so it cannot make a run larger. "
            "``None`` (the default) leaves ordinary campaigns completely "
            "unchanged.\n\n"
            "It governs FORMAL rounds too, and that is deliberate. "
            "``_resolve_sample_set_cfg`` funnels trial, formal and "
            "single-file mode into these same three values, and the clamp "
            "runs after it — after the planner, after ``plan_overrides``, "
            "after the formal-round override chain, and immediately before "
            "``TrialConfig`` and ``build_sample_set``. That is what makes "
            "it a workload ENVELOPE rather than a trial-mode default: a "
            "Gate does not have to control which mode the planner elects, "
            "only how much real work that election may execute. (Formal's "
            "``formal_eval_portion`` default of 1.0 is exactly the value "
            "this must be able to reduce.)\n\n"
            "Floor: ``ge=0.01``, the SAME executable floor its three targets "
            "declare. A ceiling below it can only produce an invalid "
            "``TrialConfig``, so it is refused here rather than at the clamp."
        ),
    )
    validation_max_train_samples: int | None = Field(
        default=None,
        ge=1,
        description=(
            "VALIDATION POSTURE ONLY. Absolute ceiling on the ML segments "
            "one training epoch may contain — the Gate's workload "
            "envelope, and the mechanism that makes a functional Gate "
            "cheap.\n\n"
            "``validation_max_portion`` bounds the FRACTION; this bounds "
            "the AMOUNT. Both are needed because the fraction's base is "
            "not harness-owned: samples per PSD segment are "
            "``psd_segment_length // seg_size`` and seg_size is the "
            "planner's model config, so 1 % of the scope resolved to "
            "12,500 optimizer steps during Step 03.\n\n"
            "Applied where the epoch is BUILT, so fewer segments are read "
            "and fewer steps exist before any of them run — the bound is "
            "spent before expensive work starts, never by killing a run "
            "that already cost 25 minutes. It CLAMPS rather than rejects, "
            "unlike ``max_steps_per_attempt``, whose refusal skipped every "
            "round of a Gate attempt and produced no training at all.\n\n"
            "Because it is exact, the resolved step count is computable "
            "before launch: ``min(planned_samples, ceiling) // batch_size "
            "× epochs``. ``None`` (the default) leaves every campaign "
            "unchanged. Never use it on a scientific run."
        ),
    )
    training_validation_portion: TrainingValidationPortion | None = Field(
        default=None,
        description=(
            "Optional task-owned snapshot fraction for per-epoch validation loss only. "
            "Selected once per attempt with the evaluation seed and reused every epoch. "
            "Independent of final inference/scoring scope; None preserves shared eval scope. "
            "Requires a composed trial/formal task with a seeded scope capability."
        ),
    )
    validation_max_samples: int | None = Field(
        default=None,
        ge=1,
        description=(
            "VALIDATION POSTURE ONLY (Step 07 / PR 07c C6). Absolute ceiling "
            "on the ML segments one VALIDATION pass may contain — the "
            "validation-row counterpart of ``validation_max_train_samples``, "
            "which bounds TRAINING rows.\n\n"
            "The two names differ by one word and bound DIFFERENT sets, which "
            "is exactly why both exist. 07a's Gate 2 capped the training epoch "
            "at 2,000 rows while validation ran the full 15,000-row eval "
            "SampleSet — 7.5x the training work, per epoch, unpriced.\n\n"
            "Applied to the REQUESTED scope, before materialization, so 07a's "
            "exact-materialization invariant (``validation_samples == "
            "validation_requested_samples``) is never relaxed. A ceiling "
            "applied afterwards would not merely lose provenance: it would "
            "make every clamped run RAISE.\n\n"
            "Clamps, never rejects. Whole PSD segments are the unit a "
            "SampleSet can express, so the resolved count is the largest "
            "multiple of ``psd_segment_length // seg_size`` that does not "
            "exceed the ceiling — a maximum is never overshot. A ceiling "
            "below one PSD segment's worth of rows is refused explicitly "
            "rather than resolving to an empty scope.\n\n"
            "INTERIM cost bounding, not the root fix: a slow model can still "
            "be misjudged at 2,000 validation rows, and the priced deadline "
            "(C5) is what makes the estimate correct. Operator/runtime input "
            "only — never planner-visible. ``None`` (the default, and every "
            "production campaign) leaves validation untouched."
        ),
    )
    validation_max_phase_seconds: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "VALIDATION POSTURE ONLY. Absolute wall-clock ceiling for one "
            "execution phase, enforced by the EXISTING runtime watchdog "
            "(RT4 §4: own process group, SIGTERM, grace, SIGKILL) as an "
            "extra deadline candidate — never as an admission input, so "
            "it cannot cause the attempt to be skipped.\n\n"
            "**A fuse, not a sizing mechanism.** The workload envelope — "
            "``validation_max_train_samples`` with ``data_scope``, "
            "``validation_max_portion`` and ``max_epochs`` — is what makes "
            "a Gate cheap, and it is enforced before launch. This only "
            "catches what no pre-launch bound can predict: a hung step, a "
            "CUDA stall, a deadlocked subprocess. Reaching it should be "
            "read as a runtime abnormality, never as normal Gate sizing — "
            "a run killed at the deadline yields no evidence and wastes "
            "the whole attempt, which is exactly why it is set well above "
            "the expected duration.\n\n"
            "``trial_time_budget_minutes`` does NOT serve this purpose — "
            "it is forecast-based admission, and a round once ran 33m53s "
            "under a 5-minute budget.\n\n"
            "Requires ``runtime_watchdog_enabled``: the watchdog is the "
            "only thing that enforces it, so accepting one without the "
            "other would record a hard bound that does nothing. Note the "
            "watchdog floor still applies — the effective ceiling is "
            "max(this, runtime_watchdog_floor_seconds)."
        ),
    )
    plan_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Hard overrides applied to every ExperimentPlan after the LLM "
            "produces it. Keys must be valid ExperimentPlan field names or "
            "aliases (e.g. trial_portion, model_config) — unknown keys fail "
            "schema validation, and keys are normalized to alias form. The "
            "merged plan is re-validated every round; an invalid effective "
            "plan raises PlanOverridesError and terminates the run (FU-10 — "
            "the operator lock is never silently released). Empty dict "
            "(default) = LLM has full control."
        ),
    )
    data_scope: DataScope = Field(
        default_factory=DataScope.default,
        description=(
            "Which subset of the dataset this run may access. Default = the "
            "complete dataset (behavior identical to pre-scope runs). Under "
            "a partial scope only 'snapshot' sampling is legal; enforcement "
            "is constructive (build_sample_set) + the sandbox boundary "
            "invariant — never prompts. Dataset-resolved validation (is the "
            "scope partial? is file_index inside it?) happens at startup via "
            "validate_runtime_config(), NOT in schema validators. "
            "See docs/design/enable_partial_file_list.md."
        ),
    )
    candidate_id: str | None = Field(
        default=None,
        description=(
            "V21 PR E — the proposer-minted observational identity of the "
            "candidate this tuning run belongs to, carried verbatim from "
            "ValidatorOutput by the valid->tune protocol. Stamped onto every "
            "ExperimentRecord and echoed on the output. Join key for the "
            "read-side funnel ONLY (O-E-5); None = pre-PR-E input or a "
            "non-proposer candidate."
        ),
    )
    healthgate_mode: HealthGateMode | None = Field(
        default=None,
        description=(
            "Whether HealthGate verdicts ENFORCE (`blocking`) or only "
            "record (`observe_only`). Declared, never reconstructed by "
            "diffing YAML.\n\n"
            "Optional here **only so historical replays still load**. A new "
            "formal campaign that omits it is refused at the launcher "
            "(D-C1b) — there is no safe default, because defaulting to "
            "`blocking` would silently claim authority a run may not have."
        ),
    )
    result_authority: ResultAuthority | None = Field(
        default=None,
        description=(
            "Whether this run's results may inform science (`scientific`) "
            "or are for diagnosis only (`diagnostic`).\n\n"
            "A SEPARATE axis from `healthgate_mode` (D-D-5), not a second "
            "spelling of it. `observe_only + scientific` is a contradiction "
            "and is refused; `blocking + diagnostic` is coherent and "
            "legitimate — a fully-enforced run whose results are "
            "deliberately not promoted. Same optionality rule as above."
        ),
    )
    health_gate_enabled: bool = Field(
        default=True,
        description=(
            "Whether the HealthGate subsystem participates in this run. "
            "False = no gate evaluation, no gate persistence, and candidate "
            "eligibility waives the gate requirement (successful finite-"
            "score records are VALID). Score-validity classification of "
            "non-finite scores stays active regardless."
        ),
    )
    health_gate_files: list[int] | None = Field(
        default=None,
        description=(
            "Run-level shared monitored-file list for ALL file-accessing "
            "HealthGate checks (v1: uniform across blocking + recording-"
            "only). None + full scope = YAML defaults; None + partial scope "
            "= startup error (an explicit in-scope list is required — no "
            "automatic default, no intersection). Requires "
            "health_gate_enabled=True."
        ),
    )

    # --- Data ordering OVERRIDE (V19 PR 2) ---
    # Operator control, stable for a chain. When set it wins over any agent
    # proposal; the proposal is still recorded. Pinned in the run-invariants
    # lock so the chain's control policy cannot change mid-flight — the
    # RESOLVED value is deliberately not locked, since it may vary per round
    # when no override is active.
    order_strategy_override: OrderStrategy | None = Field(
        default=None,
        description=(
            "Operator override forcing the training sample visitation order "
            "for the whole chain: 'shuffle' or 'sequential'. None (default) "
            "= no override, so the agent's proposal decides, falling back to "
            "'shuffle'. Set this to run a controlled comparison in which "
            "every round uses the same ordering."
        ),
    )
    file_order_override: list[int] | None = Field(
        default=None,
        description=(
            "Operator-forced file visitation order, valid only alongside "
            "order_strategy_override='sequential'. Must be a full permutation "
            "of the resolved DataScope (checked at startup, once the scope is "
            "resolved). None with 'sequential' = ascending scope order."
        ),
    )

    @model_validator(mode="after")
    def _validate_ordering_override(self):
        """Structural validation of the ordering override (scope-independent).

        The full-permutation check needs the resolved DataScope and therefore
        runs in ``validate_runtime_config`` (same schema/runtime split as the
        DataScope rules — see docs/design/enable_partial_file_list.md).
        """
        validate_ordering_shape(
            self.order_strategy_override,
            self.file_order_override,
            level="operator override",
        )
        return self

    @model_validator(mode="after")
    def _validate_health_gate_consistency(self):
        """Dataset-independent internal consistency only (see the schema/
        runtime validation split in docs/design/enable_partial_file_list.md
        — anything requiring dataset resolution lives in
        ``validate_runtime_config``)."""
        if not self.health_gate_enabled and self.health_gate_files is not None:
            raise ValueError(
                "health_gate_files must be None when health_gate_enabled=False "
                "— a disabled HealthGate subsystem monitors nothing."
            )
        if self.health_gate_files is not None and not self.health_gate_files:
            raise ValueError(
                "health_gate_files must be non-empty when provided — to "
                "monitor nothing, set health_gate_enabled=False (or use an "
                "observe/disabled gate config), never an empty file list."
            )
        return self

    @model_validator(mode="after")
    def _validate_validation_wall_clock(self):
        """A hard bound nothing enforces is worse than no bound.

        ``validation_max_phase_seconds`` is a watchdog deadline candidate
        and the watchdog is disabled by default, so accepting the ceiling
        with the watchdog off would let a Gate command record a wall-clock
        limit, run past it, and still report the run as bounded.
        """
        validate_phase_deadline(
            self.validation_max_phase_seconds, watchdog_enabled=self.runtime_watchdog_enabled
        )
        return self

    @model_validator(mode="after")
    def _validate_trial_overrides_satisfiable(self):
        """Lane F / F14 (fresh-user witness, 2026-08-26): an override that
        can never apply is a lie the run tells the operator.

        Overrides discarded by the formal resolver constrain only Trial
        rounds. Under agent-owned formal training, the two training portions
        are also effective in Formal, so they cannot trigger this refusal.
        With ``is_trial=True`` (trial mode
        allowed), ``max_rounds == 1`` and ``force_formal_round`` (default
        True), the run's ONLY round is formal-forced, so the override would
        apply to ZERO rounds while "Plan overrides applied" prints that it
        did — the F14 witness asked for ``--trial_portion 1.0`` and trained
        on 10%. The FU-10 lock's contract ("never silently released") makes
        the combination a refusal, not a silent discard.

        The ``is_trial`` conjunct is load-bearing (review B1): with
        ``is_trial=False`` the round resolves to SINGLE_FILE mode, whose
        branch READS the overridden plan values (``trial_portion`` /
        ``train_portion``) — the override demonstrably applies, so refusing
        there was simply wrong.
        """
        validate_trial_override_schedule(
            plan_overrides=self.plan_overrides,
            is_trial=self.is_trial,
            max_rounds=self.max_rounds,
            force_formal_round=self.force_formal_round,
            formal_training_scope_source=self.formal_training_scope_source,
        )
        return self

    @model_validator(mode="after")
    def _validate_seed_plugin_path(self):
        """Validate that ``seed_plugin_path`` (if set) points at a real plugin
        file whose declared ``PLUGIN_MODEL_TYPE`` matches ``model_type``.

        Uses ``ast.parse`` rather than executing the file so that a malicious
        or broken seed cannot run code at validation time, and so that
        ``sys.modules`` is not polluted before the tuner has even started.
        See docs/run_scoped_plugins.md (Phase 3).
        """
        if not self.seed_plugin_path:
            return self

        import ast
        import os as _os

        path = self.seed_plugin_path
        if not _os.path.isfile(path):
            raise ValueError(f"seed_plugin_path does not exist or is not a file: {path}")

        try:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
        except SyntaxError as e:
            raise ValueError(f"seed_plugin_path is not valid Python ({path}): {e}") from e

        declared_type: str | None = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "PLUGIN_MODEL_TYPE"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    declared_type = node.value.value
                    break
            if declared_type is not None:
                break

        if declared_type is None:
            raise ValueError(
                f"seed_plugin_path file does not declare a top-level "
                f'PLUGIN_MODEL_TYPE = "..." string constant: {path}'
            )
        if declared_type != self.model_type:
            raise ValueError(
                f"seed_plugin_path declares PLUGIN_MODEL_TYPE={declared_type!r} "
                f"but the tuner's model_type is {self.model_type!r}. "
                f"They must match, otherwise the training subprocess would "
                f"register the seed under the wrong key."
            )
        return self

    # --- Guidance ---
    expert_advice: ExpertAdviceInput = Field(
        default="",
        description=(
            "Structured guidance from upstream agents (e.g. ml_model_proposal_agent). "
            "Accepts a plain string or a structured ExpertAdvice object. "
            "Populated by the validate→tune protocol; not intended for direct human input."
        ),
    )
    human_advice: str | None = Field(
        default=None,
        description=(
            "Optional human-provided guidance for the tuning agent. "
            "When present, injected into the LLM planner prompt alongside expert_advice "
            "(e.g. 'keep epochs <= 5 for this test run')."
        ),
    )

    # --- Seeding ---
    # DS7 — ``seed_records`` deleted: schema-only with zero consumers
    # (discovered during DS6d). Seeding flows through
    # ``run_comparison.seed_agent_memory`` → summary file →
    # ``sandbox.get_summary()``, which the DS6b ingress validation covers.

    # --- LLM (planner) ---
    llm_provider: Literal["gemini", "openai", "deepseek"] = Field(
        default="gemini",
        description=(
            "LLM provider for the planner sub-call (and the default for the "
            "reflector when not overridden)."
        ),
    )
    llm_model_id: str = Field(
        default="gemini-3.1-flash-lite-preview",
        description=(
            "Model ID for the planner sub-call (and the default for the "
            "reflector when not overridden)."
        ),
    )
    reasoning_effort: str | None = Field(
        default=None, description="Explicit OpenAI planner reasoning effort."
    )

    # --- LLM (reflector — optional sub-agent override) ---
    # The tuner makes two distinct LLM calls per round: a reasoning-heavy
    # planner (uses llm_provider + llm_model_id above) and a templated
    # reflector. The reflector can be routed to a different provider AND/OR
    # a different model than the planner — see docs/break_tuner_agent.md.
    # When both reflect_* fields are None (default), the reflector uses the
    # planner's provider and model (legacy behavior).
    reflect_provider: Literal["gemini", "openai", "deepseek"] | None = Field(
        default=None,
        description=(
            "Optional separate provider for the reflector sub-call. "
            "When None, the reflector uses llm_provider. Set to a different "
            "value (e.g. 'openai') to route the reflector to a different "
            "vendor than the planner — the bridge will hold two clients."
        ),
    )
    reflect_model_id: str | None = Field(
        default=None,
        description=(
            "Optional separate model ID for the reflector sub-call. "
            "When None, the reflector uses llm_model_id. Set to a faster / "
            "cheaper / higher-quota model (e.g. 'gemini-2.5-flash') to free "
            "the main provider's quota for the reasoning-heavy planner."
        ),
    )
    reflect_reasoning_effort: str | None = Field(
        default=None, description="Explicit OpenAI reflector reasoning effort."
    )
    max_retries: int | None = Field(
        default=None,
        description=(
            "Maximum retry attempts for transient API errors (429, 5xx). "
            "None (default) = retry indefinitely — the process owner "
            "(Slurm wall time, Ctrl-C) is the natural timeout. Set to a "
            "positive integer for interactive use."
        ),
    )

    # --- Infra ---
    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node reads its inputs and writes its outputs. "
        "Supports local filesystem now; postgres backend is a placeholder.",
    )
    cleanup_denoised: bool = Field(
        default=False,
        description=(
            "Delete denoised HDF5 files after scoring each round. "
            "Saves disk space (~4 GB per file × 20 files = 80 GB per formal round). "
            "Scores and file_vector are preserved in the experiment record."
        ),
    )
    retain_model_outputs: StrictBool = Field(
        default=False,
        description=(
            "Whether to retain per-sample model outputs after inference, scoring, "
            "and Health have consumed them. False retires only exact task-declared "
            "output artifacts; model checkpoints and scientific receipts remain."
        ),
    )
    retain_training_checkpoints: StrictBool = Field(
        default=False,
        description=(
            "Keep attempt-owned training checkpoint originals after inference, scoring, "
            "Health, and model certification. Certified model artifacts are always kept."
        ),
    )
    progress_bar: bool = Field(
        default=False,
        description="Stream live tqdm progress bars from training/inference subprocesses.",
    )

    @model_validator(mode="after")
    def _validate_output_retention_switches(self):
        if self.cleanup_denoised and self.retain_model_outputs:
            raise ValueError(
                "cleanup_denoised and retain_model_outputs request contradictory output lifetimes"
            )
        return self

    task_composition_ref: TaskCompositionRef | None = Field(
        default=None,
        description=(
            "Step 12 / PR-12a (D-12a-1) — the run's task-composition "
            "PROJECTION, or None for an un-composed (regime-A) run. Additive "
            "and default-None by contract: every existing caller constructs "
            "this input without it and gets byte-identical legacy behaviour. "
            "It carries composition facts the tuner used to read from the "
            "ambient environment; it is never a second authority for them."
        ),
    )
    workflow_parameter_rules: ParameterRules | None = Field(
        default=None,
        description=(
            "Workflow-owned constraints on resolved model, training, or loss "
            "parameters. None leaves the workflow unconstrained. These rules "
            "are enforced together with, and may only narrow, task-owned rules."
        ),
    )

    @field_validator("plan_overrides")
    @classmethod
    def _validate_plan_override_keys(cls, v: dict[str, Any]) -> dict[str, Any]:
        """FU-10 — operator overrides are a contract, validated at the
        earliest possible point (input construction).

        Unknown keys are a hard error, not a per-round warning. Keys are
        normalized to the alias form that ``ExperimentPlan.model_dump(
        by_alias=True)`` emits (``model_cfg`` → ``model_config``, …), so
        the tuner's merge REPLACES the intended field instead of adding a
        stray key next to its aliased twin. Passing both a field's python
        name and its alias is ambiguous and rejected.

        Value validation needs the complete plan (cross-field validators)
        and therefore happens at each round's merge — where an invalid
        effective plan raises ``PlanOverridesError`` instead of falling
        back to the unclamped LLM plan.
        """
        if not v:
            return v
        key_map: dict[str, str] = {}
        for name, field in ExperimentPlan.model_fields.items():
            canonical = field.alias or name
            key_map[name] = canonical
            if field.alias:
                key_map[field.alias] = canonical
        unknown = sorted(k for k in v if k not in key_map)
        if unknown:
            raise ValueError(
                f"plan_overrides contains unknown ExperimentPlan field(s): "
                f"{unknown}. Valid keys: {sorted(set(key_map))}"
            )
        normalized: dict[str, Any] = {}
        for k, val in v.items():
            canonical = key_map[k]
            if canonical in normalized:
                raise ValueError(
                    f"plan_overrides sets {canonical!r} twice (python name "
                    f"and alias both given) — pass exactly one."
                )
            normalized[canonical] = val
        return normalized


class PlanOverridesError(ValueError):
    """Operator-supplied ``plan_overrides`` produced an invalid effective plan.

    Raised at the per-round merge (FU-10): the override lock is a contract,
    so an effective plan that fails validation terminates the run instead
    of silently releasing the lock and continuing with the LLM's unclamped
    plan. Deterministic on retry — the tuner must never catch this in its
    attempt-retry machinery.
    """


def validate_runtime_config(
    agent_input: HyperparamTuningInput,
    partition_count: int = NUM_FILES,
) -> list[int]:
    """Dataset-resolved startup validation for a tuner run.

    The second stage of the schema/runtime validation split
    (docs/design/enable_partial_file_list.md): schema validators check
    dataset-independent internal consistency; this function resolves the
    DataScope against the dataset definition and validates everything that
    depends on that resolution. Called at tuner ``run()`` entry and workflow
    pre-flight, BEFORE any LLM call or file I/O. Pure — no I/O; the
    subsequent health-config materialization (``materialize_effective_config``
    + ``validate_health_scope``) performs the monitored-file subset check.

    Args:
        agent_input: The validated tuner input.
        partition_count: How many partitions the DataScope resolves against —
            GENERIC IDENTITY since Step 12 / PR-12bc B2, where this function
            was proven to read nothing but the partition count. **Step 05a:
            the tuner — the only production caller — supplies its run-bound
            ``DatasetProfile.partition_count`` explicitly.** The ``NUM_FILES`` default is
            the Regime-A compatibility adapter for callers that predate the
            profile transport, exactly like ``resolve_dataset_profile()``'s own
            fallback; it is not this function's authority.

            Why it mattered: the tuner separately computes ``scope_is_partial``
            from the same fact. While this argument defaulted to the singleton,
            a run bound to a smaller topology could have its scope early-return
            here as "full" — skipping every partial-scope legality check below
            — while the tuner classified and stamped the same run as partial.
            Recorded by Step 02b, closed by Step 05a.

    Returns:
        The resolved scope (sorted list of allowed file indices).

    Raises:
        ValueError: Out-of-range scope; an ordering override whose file order
            is not a full permutation of the resolved scope; partial scope
            with a non-snapshot ``formal_strategy`` (illegal operator
            configuration); partial scope with gates enabled but no explicit
            ``health_gate_files``; single-file mode with ``file_index``
            outside the scope.
    """
    resolved = agent_input.data_scope.resolve(partition_count)

    # Ordering override: the scope-dependent half of the ordering contract
    # (the structural half ran in the schema validator). Checked for EVERY
    # scope, full or partial, so it precedes the full-scope early return
    # below. Resolving with no proposal is enough to validate the override
    # itself — the per-round resolution that mixes in the agent's proposal
    # happens later, in the tuner.
    if agent_input.order_strategy_override is not None:
        resolve_ordering(
            resolved_scope=resolved,
            override_strategy=agent_input.order_strategy_override,
            override_file_order=agent_input.file_order_override,
        )

    is_partial = resolved != list(range(partition_count))
    if not is_partial:
        return resolved

    if agent_input.formal_strategy != "snapshot":
        raise ValueError(
            f"formal_strategy={agent_input.formal_strategy!r} is not allowed "
            f"under a partial DataScope {resolved} — only 'snapshot' may be "
            f"used when the scope is a subset of the dataset. Operator "
            f"configuration is a contract: fix the flag, it is not "
            f"normalized."
        )
    if agent_input.health_gate_enabled and agent_input.health_gate_files is None:
        raise ValueError(
            f"A partial DataScope {resolved} with HealthGate enabled requires "
            f"an explicit --health_gate_files list (the YAML default "
            f"monitored files are full-dataset placements; there is no "
            f"automatic default and no intersection). Pass in-scope files, "
            f"or disable the subsystem with --no-health_gate_enabled."
        )
    if not agent_input.is_trial and agent_input.file_index not in resolved:
        raise ValueError(
            f"file_index={agent_input.file_index} (single-file mode) is "
            f"outside the DataScope {resolved}."
        )
    return resolved


# ---------------------------------------------------------------------------
# Phase K (K.7) — iteration-boundary gate-exhaustion feedback
# See docs/resource_estimator_implement.md §10.13.
# ---------------------------------------------------------------------------


class GateExhaustionInfo(BaseModel):
    """
    Structured failure report produced by the tuner when an iteration ends
    without ever training successfully AND at least one attempt was rejected
    by the pre-flight resource gate (vram or time).

    Surfaced to the next iteration's proposer via
    ``ProposalInput.prior_iteration_gate_exhaustion`` so it can learn that
    the prior architecture was fundamentally too heavy for the active
    budgets and propose something lighter.
    """

    # --- Counts (every attempt is in exactly one bucket) ---
    total_attempts: int = Field(
        description="Total number of attempts in the iteration (len(all_records)).",
    )
    vram_gated_attempts: int = Field(
        description="Attempts rejected by evaluate_vram_skill (status='skipped_oom_risk').",
    )
    time_gated_attempts: int = Field(
        description="Attempts rejected by evaluate_time_skill (status='skipped_time_risk').",
    )
    other_failure_attempts: int = Field(
        description=(
            "Attempts that fell into none of the gate buckets — covers "
            "error_*, skipped_schema_violation, etc. Always 0 when the "
            "trigger criterion fires (no successes), but distinguishing "
            "gate-rejected from other-failed clarifies the picture for "
            "the next proposer."
        ),
    )

    # --- Active budgets ---
    active_mode: Literal["trial", "formal"] = Field(
        description=(
            "Which budget set the iteration ran against. Sourced from "
            "plan.is_trial of the most recent plan."
        ),
    )
    vram_budget_gb: float | None = Field(
        default=None,
        description="Active mode's VRAM ceiling. None when the VRAM gate was disabled.",
    )
    time_budget_minutes: float | None = Field(
        default=None,
        description="Active mode's time ceiling. None when the time gate was disabled.",
    )

    # --- Baseline (round-0) factors — diagnoses whether the proposer's own
    # baseline was already over budget vs the tuner mutating it heavier. ---
    baseline_vram_estimate_gb: float | None = Field(
        default=None,
        description="round-0 record's vram_estimate_gb (memory.vram_estimate_gb).",
    )
    baseline_vram_factor: float | None = Field(
        default=None,
        description=(
            "baseline_vram_estimate_gb / vram_budget_gb. None when either side is missing."
        ),
    )
    baseline_time_estimate_minutes: float | None = Field(
        default=None,
        description="round-0 record's time_estimate_minutes (memory.time_estimate_minutes).",
    )
    baseline_time_factor: float | None = Field(
        default=None,
        description=(
            "baseline_time_estimate_minutes / time_budget_minutes. None when "
            "either side is missing."
        ),
    )

    # --- Worst-case factors — bounds how much lighter the next baseline must be. ---
    worst_vram_factor: float | None = Field(
        default=None,
        description=(
            "max(vram_estimate_gb / vram_budget_gb) across all records that "
            "carry a vram_estimate_gb. None when no record carries one."
        ),
    )
    worst_time_factor: float | None = Field(
        default=None,
        description=(
            "max(time_estimate_minutes / time_budget_minutes) across all "
            "records that carry a time_estimate_minutes. None when no record "
            "carries one."
        ),
    )

    # --- Synthesis ---
    summary_message: str = Field(
        description=(
            "Human/LLM-readable one-paragraph synthesis of the failure mode, "
            "rendered by _render_summary in the tuner. Forms the lead line of "
            "the proposer's [PRIOR ITERATION GATE EXHAUSTION] prompt block."
        ),
    )

    # --- Fix 1 (docs/reliable_resource_proposer.md §7 Decision 1 + §8.1) ---
    # Structured architectural-class blacklist. Written by the tuner when an
    # iteration ends with all-gate-exhausted attempts whose worst-case factor
    # exceeds the configured thresholds; read by the next iteration's proposer
    # as a hard DO-NOT-PROPOSE list surfaced into the [DISALLOWED PATTERNS]
    # prompt block. Empty by default so pre-Fix-1 records round-trip unchanged.
    disallowed_architectural_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Structured architectural-class tags the tuner has marked as "
            "infeasible for the active (seg_size, budget) combination. "
            "Populated from the tag_architecture() tagger in "
            "agent/utils/architectural_pattern_tagger.py over every "
            "gate-rejected attempt in this iteration, but only when "
            "worst_time_factor > 5.0 OR worst_vram_factor > 2.0 — marginal "
            "overshoots do not ban the class because they may be recoverable "
            "by reducing depth/width. "
            "The next iteration's proposer renders each tag under a "
            "[DISALLOWED PATTERNS] DO-NOT-PROPOSE block with its English "
            "description. v1 vocabulary (extensible without schema migration): "
            "'recurrent_over_T', 'scan_over_T', 'dense_attention_over_T'. "
            "Empty list (default) preserves pre-Fix-1 behavior."
        ),
    )


# ---------------------------------------------------------------------------
# Phase 6.6 WS-B (B.1) — per-attempt VRAM-gate rejection feedback
# See docs/phase66_ws_b_proposer_hardening.md §2.3.
# ---------------------------------------------------------------------------


class PhysicalRejection(BaseModel):
    """
    One VRAM-gate rejection, captured at the moment evaluate_vram_skill
    returned ``feasible=False``. A run can produce up to
    ``attempts_per_round + attempts_per_formal_round`` rejections; the
    orchestrator aggregates them per-architecture (worst offender) before
    rendering to the Proposer prompt. See WS-B doc §2.4.

    Frozen: the tuner appends fully-constructed rejections to its run-level
    buffer; no post-append mutation is supported by design.
    """

    model_config = ConfigDict(frozen=True)

    attempt_config: dict[str, Any] = Field(
        description=(
            "Compact snapshot of the tuner's active_params at rejection "
            "time — enough to identify which hyperparameters drove the "
            "overshoot (architecture-specific dims + batch_size + "
            "segmentation_size). Not the full active_params dict; the "
            "orchestrator may prune further before rendering."
        ),
    )
    binding_cap: Literal["vram", "compute_intensity", "vram+compute_intensity"] = Field(
        description=(
            "Which cap the attempt violated. Mirrors "
            "MemoryKillerDetails.binding_cap from the VRAM skill — the "
            "intensity and combined variants produce different "
            "suggestion phrasing and the Proposer reads them differently."
        ),
    )
    dominant_layer: str = Field(
        description=(
            "Name of the layer that consumed the largest share of the "
            "predicted peak. Empty string on compute_intensity-only "
            "rejections where no single layer dominates."
        ),
    )
    dominant_layer_gb: float = Field(
        ge=0.0,
        description="Dominant layer's contribution in GB.",
    )
    dominant_fraction: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Dominant layer's share of the predicted peak (0.0-1.0). "
            "Feeds the Proposer prompt's percentage rendering "
            "('consumed 68% of the peak')."
        ),
    )
    budget_gb: float = Field(
        ge=0.0,
        description=(
            "Effective VRAM cap at rejection time — "
            "min(HardwareContext.usable_cap_gb, operator_budget_gb)."
        ),
    )
    estimated_gb: float = Field(
        ge=0.0,
        description="Predicted peak that failed the cap.",
    )
    suggestion: str = Field(
        description=(
            "Calibrated mitigation suggestion from killer_report "
            "(rendered verbatim in the [PHYSICAL REJECTION] block)."
        ),
    )


# ---------------------------------------------------------------------------
# Agent output
# ---------------------------------------------------------------------------


class HyperparamTuningOutput(BaseModel):
    """
    Full report produced by a completed tune_ml_hyperparam_agent run.

    Interpretation of what these results mean across multiple runs is the
    responsibility of result_interpretation_agent, not this agent.
    """

    # --- Identity ---
    run_name: str
    model_type: str
    file_index: int
    health_checks_config: str | None = Field(
        default=None,
        description=(
            "EFFECTIVE HealthGate YAML consumed by this tuner invocation "
            "(the per-workspace materialized path since DS5; the operator's "
            "source path is in health_checks_config_source). None means the "
            "shipped default configuration was used pre-DS5, or the "
            "subsystem was disabled."
        ),
    )
    # --- DataScope + HealthGate subsystem stamps (DS5) ---
    resolved_data_scope: list[int] | None = Field(
        default=None,
        description=(
            "The run's resolved DataScope (sorted allowed file indices). "
            "None on legacy outputs = full scope. Ingress scope-homogeneity "
            "checks compare this stamp."
        ),
    )
    health_gate_enabled: bool | None = Field(
        default=None,
        description=(
            "Whether the HealthGate subsystem participated in this run. "
            "None on legacy outputs = enabled."
        ),
    )
    healthgate_mode: HealthGateMode | None = Field(
        default=None,
        description=(
            "The declared enforcement mode this run ran under. None on "
            "legacy outputs = not declared, which downstream reads as "
            "'authority cannot be established from the declaration alone'."
        ),
    )
    result_authority: ResultAuthority | None = Field(
        default=None,
        description=(
            "The declared result authority this run ran under. None on "
            "legacy outputs = not declared."
        ),
    )
    candidate_id: str | None = Field(
        default=None,
        description=(
            "V21 PR E — echoed verbatim from the input on BOTH the healthy "
            "and the degraded exit path, mirroring the healthgate_mode echo. "
            "Run-level funnel label: every record in all_records belongs to "
            "this candidate. None on legacy outputs."
        ),
    )
    health_checks_config_source: str | None = Field(
        default=None,
        description=(
            "Operator-supplied HealthGate config path before materialization "
            "(None = shipped default, or subsystem disabled)."
        ),
    )
    health_config_sha256: str | None = Field(
        default=None,
        description=(
            "sha256 of the materialized effective config body — the value "
            "the run-invariants lock pins. None when the subsystem is "
            "disabled or on legacy outputs."
        ),
    )
    task_composition_fingerprint: str | None = Field(
        default=None,
        description=(
            "The COMPOSED run's semantic task-composition fingerprint — the "
            "same value the run-invariants lock pins — or None for an "
            "un-composed run and for every output written before Step 11. "
            "Step 11 C8 / R-11-9: without this stamp the ingress validator "
            "cannot tell a record produced under THIS composition from one "
            "produced under a different task, so a composed run must refuse "
            "an unstamped record. Additive and defaulted, so a legacy output "
            "still validates and an un-composed run's outputs are unchanged."
        ),
    )
    experiment_arm: str | None = Field(
        default=None,
        description=(
            "arXiv U1 (#254) — the OPAQUE experiment-arm label this run was "
            "launched under, echoed from the input on BOTH the healthy and "
            "the degraded exit path (the candidate_id precedent), so a later "
            "resume can certify that the output it restores belongs to its "
            "arm. None for an unlabelled run and for every pre-U1 output. "
            "Never read to decide behaviour (ruling R2)."
        ),
    )
    formal_reference_score: float | None = Field(
        default=None,
        description=(
            "Resolved current_run_best_formal_score used by this tuner invocation. "
            "None on historical outputs written before this metadata existed, "
            "on invocations that ran with the chain-incumbent gates disabled, "
            "AND — V20 PR D §16.C — whenever the effective reference was "
            "infinite. -inf is a RESOLVER value, never a stored one: "
            "non-standard JSON `Infinity` is rejected by strict parsers, so an "
            "infinite bound persists as null and "
            "formal_comparison_reference_source carries the meaning instead. "
            "Read the two fields together; null alone is ambiguous."
        ),
    )
    formal_comparison_reference_source: str | None = Field(
        default=None,
        description=(
            "Provenance of formal_reference_score (V20 PR D §16.C). One of: "
            "'restored_valid_formal_incumbent' (a real HealthGate-valid "
            "incumbent was restored and consumed), 'negative_infinity_bootstrap' "
            "(no incumbent existed, so the reference resolved to -inf and the "
            "first valid trial establishes the chain's first formal baseline), "
            "or 'gates_disabled' (the chain-incumbent formal gates were off, so "
            "the deltas were never consumed). None on outputs written before "
            "this field existed. This is what distinguishes the three cases "
            "that all persist formal_reference_score as null."
        ),
    )
    resolved_skip_formal_threshold: float | None = Field(
        default=None,
        description=(
            "Resolved formal_reference_score + skip_formal_min_delta for this "
            "invocation. Null when infinite, for the reason given on "
            "formal_reference_score."
        ),
    )
    resolved_bypass_formal_threshold: float | None = Field(
        default=None,
        description=(
            "Resolved formal_reference_score + bypass_formal_time_budget_min_delta "
            "for this invocation. Null when infinite, for the reason given on "
            "formal_reference_score."
        ),
    )

    # --- Execution summary ---
    status: Literal["completed", "partial", "failed"] = Field(
        description=(
            "'completed' = reached max_rounds. "
            "'partial' = hit attempt limit before max_rounds. "
            "'failed' = unrecoverable error."
        ),
    )
    completed_rounds: int
    total_attempts: int

    # --- Best result ---
    best_exp_id: str | None = Field(
        default=None,
        description="exp_id of the experiment with the highest denoising_score.",
    )
    best_denoising_score: float | None = Field(
        default=None,
        description="Highest denoising_score achieved across all completed rounds.",
    )
    best_formal_denoising_score: float | None = Field(
        default=None,
        description=(
            "Highest denoising_score achieved across completed FORMAL rounds "
            "only (excludes trial rounds). This raw scientific field remains "
            "separate from best_valid_formal_denoising_score and is NOT "
            "eligible for chain-incumbent reconstruction (raw ≠ valid)."
        ),
    )
    best_valid_exp_id: str | None = Field(
        default=None,
        description="Experiment id of the highest HealthGate-valid scored record.",
    )
    best_valid_denoising_score: float | None = Field(
        default=None,
        description=(
            "Highest finite denoising_score among HealthGate-valid records. "
            "None when no valid candidate exists; never falls back to raw best."
        ),
    )
    best_valid_formal_exp_id: str | None = Field(
        default=None,
        description="Experiment id of the highest HealthGate-valid formal record.",
    )
    best_valid_formal_denoising_score: float | None = Field(
        default=None,
        description=(
            "Highest finite denoising_score among HealthGate-valid formal records. "
            "V19 PR 1: this committed field is the source of truth for "
            "chain-incumbent reconstruction (core/resume.py), validated "
            "against its source record before use (design doc §3.3)."
        ),
    )
    best_valid_trial_exp_id: str | None = Field(
        default=None,
        description=(
            "V19 PR 1 (P1-C4): experiment id of the highest HealthGate-valid "
            "TRIAL record. Read-only bookkeeping — the trial incumbent is "
            "context, never decision state. NOTE: bookkeeping notion; the "
            "gate-side _best_trial_winner additionally requires "
            "memory.time_mode=='trial' and may disagree (design doc §3.5)."
        ),
    )
    best_valid_trial_denoising_score: float | None = Field(
        default=None,
        description=(
            "V19 PR 1 (P1-C4): highest finite denoising_score among "
            "HealthGate-valid TRIAL records. Small-sample estimate "
            "(trial eval portions) — never comparable to formal scores, "
            "never eligible for the formal incumbent."
        ),
    )
    best_valid_config: dict[str, Any] | None = Field(
        default=None,
        description="Configuration that produced best_valid_denoising_score.",
    )
    best_valid_file_vector: list[float | None] | None = Field(
        default=None,
        description="File vector from the highest HealthGate-valid record.",
    )
    best_valid_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description="Score table from the highest HealthGate-valid record.",
    )
    best_valid_formal_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description="Score table from the highest HealthGate-valid formal record.",
    )
    best_config: dict[str, Any] | None = Field(
        default=None,
        description="model_config + train_config + loss_config that produced best_denoising_score.",
    )
    best_file_vector: list[float | None] | None = Field(
        default=None,
        description="Length-20 score vector from the best experiment. None for files not included.",
    )
    best_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description=(
            "Score comparison table from the experiment with the highest "
            "denoising_score. Enriches best_file_vector with raw_baseline + "
            "ground_truth anchors and subset-scoped aggregates; the "
            "rendered_markdown is what the downstream interpreter and "
            "proposer prompts consume. None when no round succeeded."
        ),
    )
    formal_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description=(
            "Score comparison table from the most recent successful formal "
            "(full 20-file) round. Distinct from best_score_table because "
            "cross-architecture comparability only holds at formal scope — "
            "the interpreter prefers this table when deciding which models "
            "to promote. None when no formal round succeeded."
        ),
    )

    # --- Full history ---
    all_records: list[ExperimentRecord] = Field(
        default_factory=list,
        description=(
            "Complete experiment history including successful, failed, and OOM-skipped rounds. "
            "Each record contains params, results, timing, and LLM-generated memory fields."
        ),
    )

    # --- Phase K (K.7) — iteration-boundary feedback to the next proposer ---
    gate_exhaustion: GateExhaustionInfo | None = Field(
        default=None,
        description=(
            "Populated when EITHER gate-exhaustion trigger fires. Trigger A: "
            "no attempt reached status=='success' AND >=1 attempt was rejected "
            "by the pre-flight resource gate. Trigger B: the outer loop aborted "
            "on the consecutive-failure brake after completed_rounds>0 -- so "
            "under Trigger B earlier rounds DID succeed. Consumed by the next "
            "iteration's proposer via "
            "ProposalInput.prior_iteration_gate_exhaustion."
        ),
    )
    formal_validity_feedback: FormalValidityFeedback | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Failed Formal evidence, never a valid candidate or incumbent.",
    )
    trial_validity_feedback: TrialValidityFeedback | None = Field(
        default=None,
        description=(
            "V20 PR D (D-C6) — populated only when the iteration ran trial "
            "rounds but produced NO HealthGate-valid winner. Consumed by the "
            "next iteration's proposer via ProposalInput.recent_trial_validity. "
            "Deliberately SEPARATE from gate_exhaustion, which reports BUDGET "
            "exhaustion (OOM/time skips): an all-invalid iteration has trials "
            "that ran and succeeded and then failed their scientific gates, so "
            "gate_exhaustion's triggers never fire for it. The two call for "
            "opposite planner responses — propose something lighter, versus "
            "propose something that does not collapse. None whenever at least "
            "one trial is valid, so healthy runs are byte-identical."
        ),
    )

    # --- Phase 6.6 WS-B (B.1) — per-attempt VRAM-gate rejection log ---
    # Populated on every round where evaluate_vram_skill returned
    # feasible=False; empty list on runs with no infeasible attempts.
    # Consumed by workflows/model_exploration.py which aggregates by
    # architecture (worst offender) and renders [PHYSICAL REJECTION]
    # strings into the next iteration's ProposalInput.previous_failures.
    # See docs/phase66_ws_b_proposer_hardening.md §2.3 / §2.4.
    physical_rejections: list[PhysicalRejection] = Field(
        default_factory=list,
        description=(
            "One entry per VRAM-gate rejection in this run. Empty list "
            "on iterations with no infeasible attempts — back-compat "
            "with pre-WS-B callers. Capture lands in B.3; this B.1 "
            "commit only introduces the typed channel."
        ),
    )

    # --- Phase L — per-round attempt-budget echoes + terminal state ---
    # The three echo fields make the post-hoc audit unambiguous: a record
    # showing "ran 11 attempts, completed_rounds=2, consecutive_fail_rounds_at_exit=0"
    # only makes sense if the reader knows the budget that was in force.
    # termination_reason promotes the existing implicit "did the loop exit
    # because of max_rounds vs max_fail_rounds" question to a first-class
    # field that downstream protocols (notably interp→propose) can branch
    # on without re-deriving from counts. Defaults preserve forward-compat
    # for tests/code that build outputs without specifying these fields.
    # See docs §11.3.
    attempts_per_round: int = Field(
        default=3,
        ge=1,
        description="Echo of the input attempts_per_round used for this run.",
    )
    attempts_per_formal_round: int = Field(
        default=5,
        ge=1,
        description="Echo of the input attempts_per_formal_round used for this run.",
    )
    max_fail_rounds: int = Field(
        default=3,
        ge=1,
        description="Echo of the input max_fail_rounds used for this run.",
    )
    consecutive_fail_rounds_at_exit: int = Field(
        default=0,
        ge=0,
        description=(
            "Terminal value of the loop's consecutive-failure counter. "
            "0 on a healthy completion; equals max_fail_rounds when the "
            "loop aborted via the consecutive-failure brake."
        ),
    )
    termination_reason: Literal[
        "completed",
        "aborted_fail_rounds",
        "aborted_by_gate",
        "scope_violation",
        "infrastructure_abort",
    ] = Field(
        default="completed",
        description=(
            "Why the loop exited. 'completed' = reached max_rounds successful "
            "rounds; 'aborted_fail_rounds' = max_fail_rounds consecutive "
            "rounds exhausted their attempt budgets; 'aborted_by_gate' = "
            "HISTORICAL (records predating the F-SCANC-1 retirement of the "
            "SKIP_ITER gate action; the Literal member stays so those "
            "records deserialize, and no current code path produces it — "
            "see docs/design/pluggable_health_checks.md "
            "§4); 'scope_violation' = a DataScope violation reached an "
            "executor (non-retryable configuration/invariant failure, "
            "status='failed' — docs/design/enable_partial_file_list.md DS5); "
            "'infrastructure_abort' = the runtime EVIDENCE CHANNEL failed "
            "(C9c) — registry/persistence/schema/probe-executor/telemetry/"
            "communication failure or a policy invariant breach. Outranks "
            "every other reason: nothing measured in this run can be "
            "trusted, and the chain must halt instead of retrying the next "
            "candidate into the same broken environment "
            "(docs/design/runtime_estimation_and_calibration.md §23-C9c)."
        ),
    )

    # --- Timing ---
    started_at: str
    finished_at: str

    # --- The run's bound evaluation metric (Step 09a C2) ---
    metric_spec: MetricSpecField | None = Field(
        default=None,
        description=(
            "Step 09a — the run's ALREADY-RESOLVED MetricSpec, transported so the "
            "interpreter can order and label results without deriving a second "
            "instance. Written ONCE by finalize_run_output from "
            "bindings.run_metric.spec (the tuner's single derivation at "
            "ml_hyperparameter_tune_agent.py:541); nothing downstream re-derives "
            "it. None on outputs predating this field — a legacy output therefore "
            "fails closed at score-bearing interpretation rather than falling back "
            "to a guessed direction (child design §3.2, Q-09a-4/Q-09a-6)."
        ),
    )

    # --- The run's DECLARED observational secondaries (Step 10 / P2b C2) ---
    secondary_metric_specs: list[MetricSpecField] | None = Field(
        default=None,
        description=(
            "Step 10 — the run's DECLARED secondary metrics, in manifest order, "
            "stamped once by finalize_run_output from the bound tuple exactly as "
            "`metric_spec` is stamped from the bound primary. This is what makes a "
            "NAMED ABSENCE possible: a secondary present here but carrying neither a "
            "result nor a refusal on a record is reported as `unavailable` rather "
            "than silently omitted. Artifact-borne on purpose, so it survives the "
            "chain-subprocess restore and mixed legacy/new corpora — consumers read "
            "what is persisted and never re-derive it. Absent, `null` and `[]` are "
            "EQUIVALENT on read: all three mean this run declared no secondary, and "
            "an output with no stamp fabricates no absence rows."
        ),
    )
