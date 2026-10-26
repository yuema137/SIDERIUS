"""Typed local operation records; native requests and receipts retain their owners."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from tools.candidate_prepare.models import CandidatePreparationReceipt, CandidatePreparationRequest
from tools.candidate_prepare.reusable_models import (
    ReusableCandidatePreparationRequest,
    ReusablePreparationObservations,
    ReusablePreparationReceipt,
    ReusablePreparedSelection,
)
from tools.candidate_worker.models import CandidateRunReceipt, CandidateRunRequest
from tools.workflow_preview.models import FileObservation, PreviewModel

from .native_chain_models import NativeChainAdmission, NativeChainObservation, NativeChainOperation
from .native_resume_models import NativeChainResumeOperation, NativeResumeAdmission, review_digest

OperationKind = Literal[
    "prepare", "prepare_reusable", "candidate", "native_chain", "native_chain_resume"
]


class OperationStoreConfig(PreviewModel):
    state_root: str
    preparation_roots: tuple[str, ...] = Field(min_length=1)
    candidate_roots: tuple[str, ...] = Field(min_length=1)


class PrepareOperation(PreviewModel):
    kind: Literal["prepare"] = "prepare"
    request_id: UUID
    request: CandidatePreparationRequest


class ReusablePrepareOperation(PreviewModel):
    kind: Literal["prepare_reusable"] = "prepare_reusable"
    request_id: UUID
    request: ReusableCandidatePreparationRequest


class ReusablePreparationExpectation(PreviewModel):
    """Reviewed request identity plus native observations, separate from request parameters."""

    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    observations: ReusablePreparationObservations


class CandidateOperation(PreviewModel):
    kind: Literal["candidate"] = "candidate"
    request_id: UUID
    request: CandidateRunRequest
    reusable_preparation: ReusablePreparedSelection | None = None


OperationSubmission = Annotated[
    PrepareOperation
    | ReusablePrepareOperation
    | CandidateOperation
    | NativeChainOperation
    | NativeChainResumeOperation,
    Field(discriminator="kind"),
]
SUBMISSION = TypeAdapter(OperationSubmission)
NativeReceipt = CandidatePreparationReceipt | ReusablePreparationReceipt | CandidateRunReceipt


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
    native_chain_admission: NativeChainAdmission | None = None
    native_resume_admission: NativeResumeAdmission | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def chain_binding(self):
        admission = self.native_chain_admission
        resume = self.native_resume_admission
        if self.submission.kind == "native_chain_resume":
            if (
                admission is not None
                or resume is None
                or resume.predecessor_operation_id
                != self.submission.request.predecessor_operation_id
                or resume.root_admission.input_files != self.inputs
                or resume.root_admission.checkout != self.runtime.source
                or resume.root_admission.workspace != resume.root_request.envelope + "/workspace"
                or resume.root_admission.capture_sha256 != resume.root_request.capture_sha256
                or resume.state_root != self.config.state_root
                or review_digest(resume) != self.submission.request.expected_review_digest
            ):
                raise ValueError("resume admission identity mismatch")
            return self
        if resume is not None:
            raise ValueError("resume admission on another operation kind")
        if self.submission.kind != "native_chain":
            if admission is not None:
                raise ValueError("chain admission on another operation kind")
            return self
        request = self.submission.request
        if (
            admission is None
            or admission.request_digest != self.request_digest
            or admission.capture_sha256 != request.capture_sha256
            or admission.workspace != request.envelope + "/workspace"
            or admission.checkout != self.runtime.source
            or admission.input_files != self.inputs
            or admission.final_iteration > request.max_iterations_observed
        ):
            raise ValueError("chain admission identity mismatch")
        return self


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
    outcome: Literal["native", "native_chain", "pre_dispatch_failure", "unknown"]
    receipt_digest: str | None = None
    terminal_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def terminal_kind(self):
        if self.outcome == "native_chain":
            if self.terminal_digest is None or self.receipt_digest is not None:
                raise ValueError("chain completion requires only terminal digest")
        elif self.terminal_digest is not None:
            raise ValueError("terminal digest requires chain completion")
        return self

    reason: str


class OperationHandle(PreviewModel):
    operation_id: UUID
    kind: OperationKind
    request_digest: str
    observed_at: str
    observation: Literal["starting", "existing", "operation_failed"]


class OperationSnapshot(PreviewModel):
    operation_id: UUID
    kind: OperationKind
    request_digest: str
    observed_at: str
    state: Literal["active", "completed", "operation_failed", "unknown"]
    process: ProcessObservation
    finishing: bool = False
    receipt_available: bool = False
    receipt_digest: str | None = None
    receipt: NativeReceipt | None = None
    native_chain: NativeChainObservation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
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


class PreparedCandidate(PreviewModel):
    prepare_operation_id: UUID
    preparation_request: CandidatePreparationRequest
    request: CandidateRunRequest
    request_sha256: str
    preparation_id: UUID
    receipt_sha256: str | None
    composition_fingerprint: str
