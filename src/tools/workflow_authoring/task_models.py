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


FindingCode = Literal[
    "identity_verified",
    "identity_mismatch",
    "inspection_failed",
    "compatibility_unresolved",
    "save_unsupported",
    "reference_mismatch",
    "pin_removal",
    "current_snapshot_adoption",
    "authored_changes",
]


class TaskReferenceAcknowledgement(TaskReferenceModel):
    code: FindingCode
    reference: str


class TaskReferenceAcceptance(TaskReferenceModel):
    selection: TaskReferenceUpdateProposal
    acknowledged_findings: tuple[TaskReferenceAcknowledgement, ...]
    adopt_current_snapshot: bool = False


class TaskReferenceFinding(TaskReferenceAcknowledgement):
    state: Literal["retained", "requires_review", "blocked"]
    message: str


class TaskReferenceReview(TaskReferenceModel):
    selected_choice_id: str
    previous_binding: TaskBinding | None
    target_binding: TaskBinding
    observation: CompositionObservation
    current_observation: CompositionObservation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    findings: tuple[TaskReferenceFinding, ...]
    save_supported: bool = False
    execution_ready: Literal[False] = False
