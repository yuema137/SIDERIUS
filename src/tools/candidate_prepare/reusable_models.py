"""Inert reusable preparation selections and parent-owned publication records."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from core.generated_artifact_name import validate_generated_artifact_name
from tools.candidate_worker.models import CandidateRunRequest
from tools.workflow_preview.models import FileObservation, PreviewModel
from workflows.definition import ReusableWorkflowDocument, WorkflowDocument

from .models import NATIVE_FILES, CandidatePreparationRequest, PreparationControl
from .resolution import ReusableCandidateLocations


class ReusableCandidatePreparationRequest(PreviewModel):
    source_path: str
    project_root: str
    expected_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runs_root: str
    run_id: UUID
    run_name: str
    llm_config_file: str
    preparation_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    candidate_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    task_read_only: tuple[str, ...]
    candidate_network: bool
    candidate_devices: tuple[str, ...]
    candidate_environment_names: tuple[str, ...]

    @field_validator("run_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        validate_generated_artifact_name(value, field="run_name")
        return value


class ReusableBindingCapture(PreviewModel):
    schema_version: Literal[1] = 1
    run_id: UUID
    envelope: str
    project_root: str
    original_source: FileObservation
    snapshot_path: str
    reusable_semantic_digest: str
    request: CandidatePreparationRequest
    locations: ReusableCandidateLocations
    sources: tuple[FileObservation, ...]


class ReusablePreparationPlan(PreviewModel):
    binding: ReusableBindingCapture
    document: ReusableWorkflowDocument
    resolved_document: WorkflowDocument


class ReusablePreparationControl(PreparationControl):
    kind: Literal["reusable"] = "reusable"
    binding_path: str
    binding_sha256: str


class ReusablePreparationReceipt(PreviewModel):
    run_id: UUID
    envelope: str
    status: Literal["prepared", "failed", "timed_out", "interrupted"]
    binding_path: str
    binding_sha256: str
    preparation_receipt_path: str | None = None
    candidate_request_path: str | None = None
    candidate_request_sha256: str | None = None
    preview_sha256: str | None = None
    error: str | None = None


REUSABLE_FILES = (*NATIVE_FILES, "workflow.resolved.py")


class ReusablePreparedSelection(PreviewModel):
    """Caller-retained identity of exact published receipt bytes, not a live lookup."""

    envelope: str
    expected_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerifiedReusablePreparation(PreviewModel):
    selection: ReusablePreparedSelection
    request: CandidateRunRequest
    binding: ReusableBindingCapture
    receipt: ReusablePreparationReceipt
    preparation_id: UUID
    composition_fingerprint: str
