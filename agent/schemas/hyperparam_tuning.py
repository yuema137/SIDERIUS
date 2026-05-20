# agent/schemas/hyperparam_tuning.py
"""
Input and output schemas for tune_ml_hyperparam_agent.

ExpertAdvice supports two protocols:
  - Plain string  : human-written guidance via CLI or config file
  - ExpertAdvice  : structured object produced by ml_model_proposal_agent

Both are accepted wherever ExpertAdviceInput is used.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.storage import LocalStorageConfig, StorageConfig

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
            "points (e.g. run_comparison.py) that pass a single free-form preamble "
            "string instead of structured fields. Newer code paths should populate "
            "the structured fields above and leave this None."
        ),
    )


# Union type accepted wherever expert advice is expected
ExpertAdviceInput = Union[str, ExpertAdvice]


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
    train_time_s: float
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
    ]
    model_type: str
    timestamp: str
    file_index: int = Field(
        default=6,
        description="Training/validation file index. Defaults to the standard split used in the TIDMAD paper.",
    )
    params: dict[str, Any]

    # --- Training results ---
    final_loss: float | None = Field(
        default=None,
        description="Final training loss (last epoch). Comparable only across same loss_type.",
    )
    loss_history: list[float] | None = Field(
        default=None,
        description="Training loss per epoch.",
    )
    model_params: int | None = Field(
        default=None,
        description="Number of trainable model parameters.",
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
            "Human-readable health-check failure message when the task-specific "
            "predicate inside ``execute_tools.scoring_utils.score_vector`` "
            "flagged a degenerate output (e.g. amplitude collapse on a formal "
            "round). Populated together with ``status='failed_mode_collapse'``; "
            "None on healthy rounds and on trial rounds (which are immune to "
            "the magnitude check). Surfaced verbatim to the next planner "
            "iteration via memory_history so the LLM gets a learning signal."
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
    memory: ExperimentMemory | None = None

    # --- Trial context (optional — absent or default in normal mode) ---
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
    file_vector: list[float | None] | None = Field(
        default=None,
        description="Length-20 score vector. None for files not included in the run.",
    )


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

    @model_validator(mode="after")
    def _validate_target_files(self):
        """target_files required when using trial target strategy."""
        if self.is_trial and self.trial_strategy == "target" and not self.target_files:
            raise ValueError(
                "target_files required when is_trial=True and trial_strategy='target'."
            )
        return self

    @classmethod
    def with_defaults(cls, raw: dict[str, Any]) -> ExperimentPlan:
        """
        Validate raw LLM output, falling back to defaults on invalid trial fields.

        If the full dict fails validation (e.g. trial_portion=5.0), strip the
        trial fields and retry — preserving the LLM's experiment design while
        falling back to safe trial defaults.

        Defensive unwrap: LLMs occasionally emit a single-element list
        ``[{...}]`` instead of ``{...}``. Unwrap that case before validation.
        Any other non-dict input raises a clear TypeError.
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
            return cls.model_validate(raw)
        except Exception:
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
            return cls.model_validate(safe)


# ---------------------------------------------------------------------------
# Agent input
# ---------------------------------------------------------------------------


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
    model_type: str = Field(
        description="Architecture to tune. One of the registered model keys, or 'auto' to let the agent decide.",
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
        description="Validation/training file index (0-39). Default 6 matches the paper's standard split. Ignored when is_trial=True.",
    )
    max_rounds: int = Field(
        default=50,
        ge=1,
        description="Maximum number of completed experiment rounds (OOM-skipped attempts do not count).",
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
    trial_strategy: Literal["snapshot", "anchors", "target"] = Field(
        default="snapshot",
        description="Sampling strategy for training: 'snapshot' (all 20 files), 'anchors' (files 0/10/19), 'target' (specific files).",
    )
    trial_portion: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Fraction of segments per file for the training scope.",
    )
    target_files: list[int] = Field(
        default_factory=list,
        description="File indices to sample from. Required when trial_strategy='target'.",
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
        description="Sampling strategy for validation.",
    )
    eval_portion: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Fraction of segments per file for validation. Set to 1.0 for formal mode.",
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
    formal_portion: float = Field(
        default=0.1,
        ge=0.0,
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
        gt=0.0,
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
            "  inference-time measurement reuse landed in commits B–D of "
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
            "chains and pre-2026-05-02 ``tuner_advice/*.json`` configs):\n"
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
            "Trial rounds are immune (no benchmark to compare against)."
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
    formal_time_budget_minutes: float | None = Field(
        default=None,
        description=(
            "Wall-time budget in minutes against which evaluate_time_skill "
            "gates rounds where the planner picks formal mode (plan.is_trial=False). "
            "None = formal gate disabled; the tuner prints a one-time warning "
            "at startup and skips the time check for formal rounds. Sized "
            "independently from the trial budget because formal runs use the "
            "full dataset and have a wall-time scale 50–100× longer."
        ),
    )

    # --- VRAM-budget gate (evaluate_vram_skill, Phase K) ---
    # Mirrors the trial/formal split of the time gate. The tuner picks the
    # right one per round via plan.is_trial. Each is independently optional:
    # setting only the trial budget gates trial rounds and skips formal rounds,
    # and vice versa. The budget here acts as an operator-defined ceiling; the
    # skill compares vram_estimate against min(defensive_floor, budget).
    # See docs/resource_estimator_implement.md §10.4 / §10.5.
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
    data_dir: str | None = Field(
        default=None,
        description=(
            "Filesystem path to the TIDMAD data directory. Forwarded to "
            "evaluate_time_skill so its real-dataset warmup can read 1 PSD "
            "from the actual disk path the training run will use. When None, "
            "the skill falls back to its static-formula estimate."
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
            "or resource-constrained environments."
        ),
    )
    plan_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Hard overrides applied to every ExperimentPlan after the LLM "
            "produces it. Keys must be valid ExperimentPlan field names "
            "(e.g. trial_portion, train_portion). The merged result is "
            "re-validated through Pydantic, so invalid values are caught. "
            "Empty dict (default) = LLM has full control."
        ),
    )

    @model_validator(mode="after")
    def _validate_trial_fields(self):
        """Cross-field validation for trial mode parameters."""
        if self.is_trial and self.trial_strategy == "target" and not self.target_files:
            raise ValueError(
                "target_files must be non-empty when is_trial=True and trial_strategy='target'."
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
            raise ValueError(f"seed_plugin_path is not valid Python ({path}): {e}")

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
    seed_records: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Pre-existing experiment records injected into the agent's memory before round 1. "
            "Typically contains the baseline result so the agent knows what benchmark to beat."
        ),
    )

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
    progress_bar: bool = Field(
        default=False,
        description="Stream live tqdm progress bars from training/inference subprocesses.",
    )


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
            "Dominant layer's share of the predicted peak (0.0–1.0). "
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
            "Populated only when the iteration ended without ever training "
            "successfully AND >=1 attempt was rejected by the pre-flight "
            "resource gate. Consumed by the next iteration's proposer via "
            "ProposalInput.prior_iteration_gate_exhaustion. None on healthy "
            "runs (any success) and on all-failure-but-not-budget-related runs."
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
        description="Echo of the input attempts_per_round used for this run.",
    )
    attempts_per_formal_round: int = Field(
        default=5,
        description="Echo of the input attempts_per_formal_round used for this run.",
    )
    max_fail_rounds: int = Field(
        default=3,
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
    termination_reason: Literal["completed", "aborted_fail_rounds"] = Field(
        default="completed",
        description=(
            "Why the loop exited. 'completed' = reached max_rounds successful "
            "rounds; 'aborted_fail_rounds' = max_fail_rounds consecutive "
            "rounds exhausted their attempt budgets."
        ),
    )

    # --- Timing ---
    started_at: str
    finished_at: str
