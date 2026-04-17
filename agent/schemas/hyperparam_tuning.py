# agent/schemas/hyperparam_tuning.py
"""
Input and output schemas for tune_ml_hyperparam_agent.

ExpertAdvice supports two protocols:
  - Plain string  : human-written guidance via CLI or config file
  - ExpertAdvice  : structured object produced by ml_model_proposal_agent

Both are accepted wherever ExpertAdviceInput is used.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.storage import StorageConfig, LocalStorageConfig


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
    focus_areas: List[str] = Field(
        default_factory=list,
        description="Aspects to prioritize during exploration (e.g. 'increase depth before width').",
    )
    constraints: List[str] = Field(
        default_factory=list,
        description="Hard limits that must not be violated (e.g. 'VRAM < 10 GB', 'epochs <= 30').",
    )
    known_failures: List[str] = Field(
        default_factory=list,
        description="Configs or approaches already shown to fail — avoid repeating them.",
    )
    suggested_directions: List[str] = Field(
        default_factory=list,
        description="Concrete things to try (e.g. 'try focal loss with gamma=3', 'reduce batch_size to 4').",
    )
    rationale: str = Field(
        default="",
        description="Why this guidance was given — context for the agent's planning phase.",
    )
    freeform_notes: Optional[str] = Field(
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
    conclusion: Optional[str] = None
    key_factor: Optional[str] = None
    discovery: Optional[str] = None
    memory_update: Optional[str] = None


class ExperimentRecord(BaseModel):
    exp_id: str
    status: Literal[
        "success",
        "error",
        "skipped_oom_risk",
        "skipped_time_risk",
        "error_training",
        "error_training_oom",
        "error_inference",
        "error_inference_oom",
    ]
    model_type: str
    timestamp: str
    file_index: int = Field(default=6, description="Training/validation file index. Defaults to the standard split used in the TIDMAD paper.")
    params: Dict[str, Any]

    # --- Training results ---
    final_loss: Optional[float] = Field(
        default=None,
        description="Final training loss (last epoch). Comparable only across same loss_type.",
    )
    loss_history: Optional[List[float]] = Field(
        default=None,
        description="Training loss per epoch.",
    )
    model_params: Optional[int] = Field(
        default=None,
        description="Number of trainable model parameters.",
    )

    # --- Scoring results ---
    denoising_score: Optional[float] = Field(
        default=None,
        description="Anchor-normalized denoising score (validation).",
    )
    file_vector: Optional[List[Optional[float]]] = Field(
        default=None,
        description="Length-20 score vector. None for files not included in the run.",
    )

    # --- Data volume ---
    training_psd_segments: Optional[int] = Field(
        default=None,
        description="Number of PSD segments used for training.",
    )
    eval_psd_segments: Optional[int] = Field(
        default=None,
        description="Number of PSD segments used for evaluation.",
    )

    timing: Optional[ExperimentTiming] = None
    memory: Optional[ExperimentMemory] = None

    # --- Trial context (optional — absent or default in normal mode) ---
    is_trial: bool = Field(
        default=False,
        description="Whether this experiment ran in trial-explore mode with sparse sampling.",
    )
    trial_strategy: Optional[Literal["snapshot", "anchors", "target"]] = Field(
        default=None,
        description="Sampling strategy used for training.",
    )
    trial_portion: Optional[float] = Field(
        default=None,
        description="Fraction of segments per file for training scope.",
    )
    eval_strategy: Optional[Literal["snapshot", "anchors", "target"]] = Field(
        default=None,
        description="Sampling strategy used for validation.",
    )
    eval_portion: Optional[float] = Field(
        default=None,
        description="Fraction of segments per file for validation scope.",
    )
    train_portion: Optional[float] = Field(
        default=None,
        description="Per-epoch subsample from training scope.",
    )
    target_files: Optional[List[int]] = Field(
        default=None,
        description="File indices sampled (only for 'target' strategy).",
    )
    file_vector: Optional[List[Optional[float]]] = Field(
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
    - In formal mode: ``eval_portion=1.0`` (all segments)

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
    target_files: List[int] = Field(
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
    file_index: Optional[int] = Field(
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
            raise ValueError("target_files required when is_trial=True and trial_strategy='target'.")
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
    model_cfg: Dict[str, Any] = Field(
        default_factory=dict,
        alias="model_config",
        description="Architecture-specific hyperparameters.",
    )
    train_cfg: Dict[str, Any] = Field(
        default_factory=dict,
        alias="train_config",
        description="Training hyperparameters (lr, epochs, batch_size, device).",
    )
    loss_cfg: Dict[str, Any] = Field(
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
    target_files: List[int] = Field(
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
    def with_defaults(cls, raw: Dict[str, Any]) -> "ExperimentPlan":
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
                print("[ExperimentPlan] LLM returned a single-element list — "
                      "unwrapping to dict.")
                raw = raw[0]
            else:
                raise TypeError(
                    f"ExperimentPlan expected a dict, got list of length "
                    f"{len(raw)}. LLM output is malformed."
                )
        if not isinstance(raw, dict):
            raise TypeError(
                f"ExperimentPlan expected a dict, got {type(raw).__name__}."
            )
        try:
            return cls.model_validate(raw)
        except Exception:
            # Keep only experiment fields, let trial fields take defaults.
            # Use alias names (model_config, train_config, loss_config) since
            # that's what the LLM outputs.
            _EXPERIMENT_KEYS = {
                "model_type", "hypothesis", "reasoning",
                "model_config", "train_config", "loss_config",
            }
            safe = {k: v for k, v in raw.items() if k in _EXPERIMENT_KEYS}
            print(f"[ExperimentPlan] LLM returned invalid trial fields — "
                  f"falling back to defaults. Kept keys: {list(safe.keys())}")
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
    target_files: List[int] = Field(
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

    # --- Reproducibility seeds (optional — auto-generated when not provided) ---
    sampling_seed: Optional[int] = Field(
        default=None,
        description=(
            "Seed for build_sample_set() — determines which PSD segments form the "
            "data scope. When None, auto-generated from SHA-256(run_name + attempt). "
            "Set this to replay a previous run's exact data sampling. "
            "Read from a previous trial_config_{exp_id}.json."
        ),
    )
    train_base_seed: Optional[int] = Field(
        default=None,
        description=(
            "Base seed for per-epoch training subsampling. Epoch n uses "
            "train_base_seed + n. When None, auto-generated. "
            "Read from a previous trial_config_{exp_id}.json."
        ),
    )

    # --- Time-budget gate (evaluate_time_skill) ---
    # See docs/time_estimator_implement.md §2.7 + Phase I. The single
    # `time_budget_minutes` field used in Phases D-G was split into two so the
    # per-round gate uses the right ceiling for the mode the round runs in.
    # Both fields originate at the workflow/CLI level and are forwarded through
    # the validator→tuner protocol. Each is independently optional: setting
    # only the trial budget gates trial rounds and skips formal rounds, and
    # vice versa. The tuner picks the right one each round via plan.is_trial.
    trial_time_budget_minutes: Optional[float] = Field(
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
    formal_time_budget_minutes: Optional[float] = Field(
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
    data_dir: Optional[str] = Field(
        default=None,
        description=(
            "Filesystem path to the TIDMAD data directory. Forwarded to "
            "evaluate_time_skill so its real-dataset warmup can read 1 PSD "
            "from the actual disk path the training run will use. When None, "
            "the skill falls back to its static-formula estimate."
        ),
    )

    # --- Hard constraints on LLM plan output (enforced after plan, not by the LLM) ---
    max_epochs: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Hard cap on epochs per round. When set, the tuner clamps the LLM's "
            "planned epochs to min(planned_epochs, max_epochs). Use this to prevent "
            "the LLM from choosing excessively long training in integration tests "
            "or resource-constrained environments."
        ),
    )
    plan_overrides: Dict[str, Any] = Field(
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

    # --- Guidance ---
    expert_advice: ExpertAdviceInput = Field(
        default="",
        description=(
            "Structured guidance from upstream agents (e.g. ml_model_proposal_agent). "
            "Accepts a plain string or a structured ExpertAdvice object. "
            "Populated by the validate→tune protocol; not intended for direct human input."
        ),
    )
    human_advice: Optional[str] = Field(
        default=None,
        description=(
            "Optional human-provided guidance for the tuning agent. "
            "When present, injected into the LLM planner prompt alongside expert_advice "
            "(e.g. 'keep epochs <= 5 for this test run')."
        ),
    )

    # --- Seeding ---
    seed_records: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Pre-existing experiment records injected into the agent's memory before round 1. "
            "Typically contains the baseline result so the agent knows what benchmark to beat."
        ),
    )

    # --- LLM (planner) ---
    llm_provider: Literal["gemini", "openai"] = Field(
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
    reflect_provider: Optional[Literal["gemini", "openai"]] = Field(
        default=None,
        description=(
            "Optional separate provider for the reflector sub-call. "
            "When None, the reflector uses llm_provider. Set to a different "
            "value (e.g. 'openai') to route the reflector to a different "
            "vendor than the planner — the bridge will hold two clients."
        ),
    )
    reflect_model_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional separate model ID for the reflector sub-call. "
            "When None, the reflector uses llm_model_id. Set to a faster / "
            "cheaper / higher-quota model (e.g. 'gemini-2.5-flash') to free "
            "the main provider's quota for the reasoning-heavy planner."
        ),
    )
    max_retries: Optional[int] = Field(
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
    best_exp_id: Optional[str] = Field(
        default=None,
        description="exp_id of the experiment with the highest denoising_score.",
    )
    best_denoising_score: Optional[float] = Field(
        default=None,
        description="Highest denoising_score achieved across all completed rounds.",
    )
    best_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="model_config + train_config + loss_config that produced best_denoising_score.",
    )
    best_file_vector: Optional[List[Optional[float]]] = Field(
        default=None,
        description="Length-20 score vector from the best experiment. None for files not included.",
    )

    # --- Full history ---
    all_records: List[ExperimentRecord] = Field(
        default_factory=list,
        description=(
            "Complete experiment history including successful, failed, and OOM-skipped rounds. "
            "Each record contains params, results, timing, and LLM-generated memory fields."
        ),
    )

    # --- Timing ---
    started_at: str
    finished_at: str
