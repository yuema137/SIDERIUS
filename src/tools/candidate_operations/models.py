"""Typed local operation records; native requests and receipts retain their owners."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from tools.candidate_prepare.models import CandidatePreparationReceipt, CandidatePreparationRequest
from tools.candidate_worker.models import CandidateRunReceipt, CandidateRunRequest
from tools.workflow_preview.models import FileObservation, PreviewModel


class OperationStoreConfig(PreviewModel):
    state_root: str
    preparation_roots: tuple[str, ...] = Field(min_length=1)
    candidate_roots: tuple[str, ...] = Field(min_length=1)


class PrepareOperation(PreviewModel):
    kind: Literal["prepare"] = "prepare"
    request_id: UUID
    request: CandidatePreparationRequest


class CandidateOperation(PreviewModel):
    kind: Literal["candidate"] = "candidate"
    request_id: UUID
    request: CandidateRunRequest


OperationSubmission = Annotated[PrepareOperation | CandidateOperation, Field(discriminator="kind")]
SUBMISSION = TypeAdapter(OperationSubmission)
NativeReceipt = CandidatePreparationReceipt | CandidateRunReceipt


class RuntimeIdentity(PreviewModel):
    executable: str
    resolved_executable: str
    environment: str
    source: str
    revision: str | None


class OperationRecord(PreviewModel):
    native_id: UUID
    submission: OperationSubmission
    request_digest: str
    config: OperationStoreConfig
    runtime: RuntimeIdentity
    inputs: tuple[FileObservation, ...]
    admitted_at: str


class ActiveOperation(PreviewModel):
    operation_id: UUID


class ProcessIdentity(PreviewModel):
    operation_id: UUID
    request_digest: str
    boot_id: str
    pid: int = Field(gt=0)
    start_ticks: int = Field(ge=0)


class ProcessObservation(PreviewModel):
    status: Literal["alive", "exited", "unknown"]
    reason: str


class SpawnFailure(PreviewModel):
    operation_id: UUID
    request_digest: str
    reason: Literal["spawn_failed"] = "spawn_failed"


class Completion(PreviewModel):
    operation_id: UUID
    request_digest: str
    outcome: Literal["native", "pre_dispatch_failure", "unknown"]
    receipt_digest: str | None = None
    reason: str


class OperationHandle(PreviewModel):
    operation_id: UUID
    kind: Literal["prepare", "candidate"]
    request_digest: str
    observed_at: str
    observation: Literal["starting", "existing", "operation_failed"]


class OperationSnapshot(PreviewModel):
    operation_id: UUID
    kind: Literal["prepare", "candidate"]
    request_digest: str
    observed_at: str
    state: Literal["active", "completed", "operation_failed", "unknown"]
    process: ProcessObservation
    finishing: bool = False
    receipt_available: bool = False
    receipt_digest: str | None = None
    receipt: NativeReceipt | None = None
    reason: str


class LogReadRequest(PreviewModel):
    operation_id: UUID
    kind: Literal["native", "operation"]
    offset: int = Field(default=0, ge=0)
    max_bytes: int = Field(default=65536, gt=0, le=65536)


class LogChunk(PreviewModel):
    operation_id: UUID
    kind: Literal["native", "operation"]
    offset: int
    next_offset: int
    observed_size: int
    missing: bool
    truncated: bool
    text: str


class OperationError(PreviewModel):
    code: str
    message: str


class OperationFailure(ValueError):
    def __init__(self, code: str, message: str):
        self.detail = OperationError(code=code, message=message)
        super().__init__(message)
