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
from pydantic import BaseModel, Field

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


# Union type accepted wherever expert advice is expected
ExpertAdviceInput = Union[str, ExpertAdvice]


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
    status: Literal["success", "error", "skipped_oom_risk"]
    model_type: str
    timestamp: str
    file_index: int = Field(default=6, description="Training/validation file index. Defaults to the standard split used in the TIDMAD paper.")
    params: Dict[str, Any]
    results: Dict[str, Any]
    denoising_score: Optional[float] = None
    timing: Optional[ExperimentTiming] = None
    memory: Optional[ExperimentMemory] = None


# ---------------------------------------------------------------------------
# Agent input
# ---------------------------------------------------------------------------

class HyperparamTuningInput(BaseModel):
    """
    Full specification for a tune_ml_hyperparam_agent run.

    Fields are grouped by concern:
      - Research:  what to explore and how hard to push
      - Guidance:  expert advice steering the LLM planner
      - Seeding:   pre-existing records the agent should treat as prior knowledge
      - LLM:       which model drives the planning and reflection steps
      - Infra:     storage paths (managed by the communication interface in production)
    """

    # --- Research ---
    model_type: str = Field(
        description="Architecture to tune. One of the registered model keys, or 'auto' to let the agent decide.",
    )
    file_index: int = Field(
        default=6,
        ge=0,
        description="Validation/training file index (0-39). Default 6 matches the paper's standard split.",
    )
    max_rounds: int = Field(
        default=50,
        ge=1,
        description="Maximum number of completed experiment rounds (OOM-skipped attempts do not count).",
    )

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

    # --- LLM ---
    llm_provider: Literal["gemini", "openai"] = Field(
        default="gemini",
        description="LLM provider for planning and reflection.",
    )
    llm_model_id: str = Field(
        default="gemini-3.1-flash-lite-preview",
        description="Specific model ID passed to the provider.",
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
