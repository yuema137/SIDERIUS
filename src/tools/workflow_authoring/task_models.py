"""Typed explicit selection/review; trusted target paths never come from a browser."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.setup_review.composition_models import CompositionObservation, TaskCheckSettings
from workflows.definition import TaskBinding


class TaskReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskReferenceTarget(TaskReferenceModel):
    """Projection of one configured task choice, also accepted by code callers."""

    choice_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    binding: TaskBinding
    manifest: Path
    data_root: Path
    llm_config_file: Path
    inspection_root: Path
    read_only: tuple[Path, ...]
    settings: TaskCheckSettings


class TaskReferenceUpdateProposal(TaskReferenceModel):
    kind: Literal["task_references"] = "task_references"
    selected_choice_id: str
    expected_task_binding: TaskBinding


class TaskReferenceFinding(TaskReferenceModel):
    code: Literal[
        "identity_verified",
        "identity_mismatch",
        "inspection_failed",
        "compatibility_unresolved",
        "save_unsupported",
    ]
    state: Literal["retained", "blocked"]
    reference: str
    message: str


class TaskReferenceReview(TaskReferenceModel):
    selected_choice_id: str
    previous_binding: TaskBinding | None
    target_binding: TaskBinding
    observation: CompositionObservation
    findings: tuple[TaskReferenceFinding, ...]
    save_supported: Literal[False] = False
    execution_ready: Literal[False] = False
