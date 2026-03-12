# dashboard/api/models.py
"""
Pydantic v2 response models for the dashboard REST API.

These models define the wire format returned by all API endpoints.
They are populated from raw dicts returned by the DataSource ABC —
the API layer is the only place that touches these models.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Experiment record — mirrors the schema written by ml_hyperparameter_tune_agent.py
# ---------------------------------------------------------------------------

class TrainConfig(BaseModel):
    lr: Optional[float] = None
    epochs: Optional[int] = None
    batch_size: Optional[int] = None
    device: Optional[str] = None

    model_config = ConfigDict(extra="allow")   # forward-compatible with new fields


class LossConfig(BaseModel):
    loss_type: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class ExperimentParams(BaseModel):
    # "model_config" is reserved by Pydantic v2; alias bridges the wire name
    model_cfg: dict = Field(default_factory=dict, alias="model_config")
    train_config: TrainConfig = Field(default_factory=TrainConfig)
    loss_config: LossConfig = Field(default_factory=LossConfig)

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ExperimentResults(BaseModel):
    final_loss: Optional[float] = None
    model_params: Optional[int] = None

    model_config = ConfigDict(extra="allow")


class MemoryRecord(BaseModel):
    hypothesis: Optional[str] = None
    conclusion: Optional[str] = None
    key_factor: Optional[str] = None
    discovery: Optional[str] = None
    memory_update: Optional[str] = None
    expert_advice_followed: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class ExperimentRecord(BaseModel):
    """
    Full experiment record as stored by the pipeline.
    Optional fields throughout — baseline and skipped records omit some.
    """
    exp_id: str
    status: Literal["success", "skipped_oom_risk", "error"]
    model_type: str
    timestamp: Optional[str] = None
    denoising_score: Optional[float] = None
    params: ExperimentParams = Field(default_factory=ExperimentParams)
    results: ExperimentResults = Field(default_factory=ExperimentResults)
    memory: MemoryRecord = Field(default_factory=MemoryRecord)

    model_config = ConfigDict(extra="ignore")  # drop internal keys like _run_name


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
    baseline_score: Optional[float] = None
    best_agent_score: Optional[float] = None
    best_run_name: Optional[str] = None
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
    denoising_score: Optional[float] = None
    final_loss: Optional[float] = None
    model_params: Optional[int] = None
    loss_type: Optional[str] = None
    epochs: Optional[int] = None
    timestamp: Optional[str] = None


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
