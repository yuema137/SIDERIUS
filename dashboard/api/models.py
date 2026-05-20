# dashboard/api/models.py
"""
Pydantic v2 response models for the dashboard REST API.

These models define the wire format returned by all API endpoints.
They are populated from raw dicts returned by the DataSource ABC —
the API layer is the only place that touches these models.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Experiment record — mirrors the schema written by ml_hyperparameter_tune_agent.py
# ---------------------------------------------------------------------------


class TrainConfig(BaseModel):
    lr: float | None = None
    epochs: int | None = None
    batch_size: int | None = None
    device: str | None = None

    model_config = ConfigDict(extra="allow")  # forward-compatible with new fields


class LossConfig(BaseModel):
    loss_type: str | None = None

    model_config = ConfigDict(extra="allow")


class ExperimentParams(BaseModel):
    # "model_config" is reserved by Pydantic v2; alias bridges the wire name
    model_cfg: dict = Field(default_factory=dict, alias="model_config")
    train_config: TrainConfig = Field(default_factory=TrainConfig)
    loss_config: LossConfig = Field(default_factory=LossConfig)

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ExperimentResults(BaseModel):
    final_loss: float | None = None
    model_params: int | None = None

    model_config = ConfigDict(extra="allow")


class MemoryRecord(BaseModel):
    hypothesis: str | None = None
    conclusion: str | None = None
    key_factor: str | None = None
    discovery: str | None = None
    memory_update: str | None = None
    expert_advice_followed: str | None = None

    model_config = ConfigDict(extra="allow")


class TimingRecord(BaseModel):
    train_time_s: float | None = None
    inference_time_s: float | None = None
    scoring_time_s: float | None = None

    model_config = ConfigDict(extra="allow")


class ExperimentRecord(BaseModel):
    """
    Full experiment record as stored by the pipeline.
    Optional fields throughout — baseline and skipped records omit some.
    """

    exp_id: str
    status: Literal["success", "skipped_oom_risk", "error"]
    model_type: str
    timestamp: str | None = None
    denoising_score: float | None = None
    params: ExperimentParams = Field(default_factory=ExperimentParams)
    results: ExperimentResults = Field(default_factory=ExperimentResults)
    timing: TimingRecord = Field(default_factory=TimingRecord)
    memory: MemoryRecord = Field(default_factory=MemoryRecord)

    # Training results (new typed fields)
    final_loss: float | None = None
    model_params: int | None = None

    # Trial context
    is_trial: bool | None = None
    trial_strategy: str | None = None
    trial_portion: float | None = None
    eval_strategy: str | None = None
    eval_portion: float | None = None
    train_portion: float | None = None
    training_psd_segments: int | None = None
    eval_psd_segments: int | None = None
    # Inner Optional: per-file scores can be None for files that were
    # not scored in this round (e.g. trial mode skipped them, or the
    # file failed). Matches agent/schemas/hyperparam_tuning.py.
    file_vector: list[float | None] | None = None

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Run summary (paginated list of records)
# ---------------------------------------------------------------------------


class RunSummary(BaseModel):
    model: str
    run_name: str
    total_count: int
    offset: int
    limit: int
    records: list[ExperimentRecord]


# ---------------------------------------------------------------------------
# Model overview (aggregated stats across all runs)
# ---------------------------------------------------------------------------


class StatusCounts(BaseModel):
    success: int = 0
    skipped_oom_risk: int = 0

    model_config = ConfigDict(extra="allow")  # allow unknown future statuses


class ModelOverview(BaseModel):
    model: str
    baseline_score: float | None = None
    best_agent_score: float | None = None
    best_run_name: str | None = None
    total_experiments: int = 0
    status_counts: StatusCounts = Field(default_factory=StatusCounts)
    runs: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


class LeaderboardEntry(BaseModel):
    rank: int
    exp_id: str
    run_name: str
    denoising_score: float | None = None
    final_loss: float | None = None
    model_params: int | None = None
    loss_type: str | None = None
    epochs: int | None = None
    timestamp: str | None = None


class LeaderboardResponse(BaseModel):
    model: str
    top_n: int
    status_filter: str
    entries: list[LeaderboardEntry]


# ---------------------------------------------------------------------------
# Health + config (bootstrap for frontend)
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    data_source_type: str
    readable: bool


class FrontendConfig(BaseModel):
    """
    Served once on page load so the JS never has hardcoded settings.
    """

    refresh_interval_seconds: int
    data_source_type: str
    models: list[str]
    default_run_name: str
    theme: str = "dark"


# ---------------------------------------------------------------------------
# Generic list responses
# ---------------------------------------------------------------------------


class ModelListResponse(BaseModel):
    models: list[str]


class RunListResponse(BaseModel):
    model: str
    runs: list[str]


# ---------------------------------------------------------------------------
# Exploration iteration table — one row per explore-loop iteration,
# summarising the best record found by the hyperparam tuner for that iteration.
# ---------------------------------------------------------------------------


class IterationRound(BaseModel):
    """One round-block for the iteration table — corresponds to one
    actually-executed record in the iteration's ``all_records`` (skipped
    attempts are filtered out by the endpoint before rounds are emitted).
    """

    exp_id: str
    is_trial: bool | None = None
    trial_portion: float | None = None
    train_portion: float | None = None
    final_loss: float | None = None
    denoising_score: float | None = None


class IterationTableRow(BaseModel):
    """One row of the exploration iteration-summary table.

    Each row is one new-model-explore iteration. ``rounds`` holds only the
    records that actually ran (status == ``success``); skipped/error
    attempts are filtered out before reaching the wire. The frontend pads
    each row with em-dash blocks up to ``IterationTableResponse.max_rounds``
    so the columns align across the whole run.
    """

    iteration: str  # "iteration_001" or "iter_001"
    model_name: str | None = None  # discovered model dir (or attempt fallback)
    status: str | None = None  # run_output top-level status
    termination_reason: str | None = None
    completed_rounds: int | None = None
    total_attempts: int | None = None
    rounds: list[IterationRound] = Field(default_factory=list)


class IterationTableResponse(BaseModel):
    run_name: str
    max_rounds: int  # widest rounds[] across rows; drives column count
    rows: list[IterationTableRow]
