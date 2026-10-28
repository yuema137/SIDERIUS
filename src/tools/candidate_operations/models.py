"""Typed local operation records; native requests and receipts retain their owners."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from core.runtime_control.pair_admission import PositiveGpuGiB
from core.runtime_control.scheduling import PositiveCount, PositiveQuantity, ResourceRequest
from core.seeding import RunSeed, RunSeedBinding, admitted_run_seed
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
    "prepare",
    "prepare_reusable",
    "candidate",
    "native_chain",
    "native_chain_resume",
    "candidate_loop_resume",
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


class OperationResources(PreviewModel):
    """The operator's explicit reservation for one candidate operation; nothing is guessed.

    Consulted only by a budgeted host ledger. Wall time is not declared here: it is
    the request's ``timeout_seconds``. ``time_budgeted`` states whether the run uses
    a measured time budget (decision B3-Q6). ``ResourceRequest`` owns the field rules.
    """

    gpu_count: Literal[0, 1]
    vram_gib: PositiveGpuGiB | None = None
    vram_source: Literal["measured", "configured_cap"] | None = None
    host_memory_gib: PositiveQuantity
    cpu_slots: PositiveCount
    time_budgeted: bool

    @model_validator(mode="after")
    def scheduling_rules(self):
        self.request(unit_id="declaration", dispatch_ordinal=0, wall_seconds=1.0)
        return self

    def request(
        self, *, unit_id: str, dispatch_ordinal: int, wall_seconds: float
    ) -> ResourceRequest:
        return ResourceRequest(
            unit_id=unit_id,
            dispatch_ordinal=dispatch_ordinal,
            gpu_count=self.gpu_count,
            vram_gib=self.vram_gib,
            vram_source=self.vram_source,
            host_memory_gib=self.host_memory_gib,
            cpu_slots=self.cpu_slots,
            wall_seconds=wall_seconds,
        )


class CandidateOperation(PreviewModel):
    kind: Literal["candidate"] = "candidate"
    request_id: UUID
    request: CandidateRunRequest
    reusable_preparation: ReusablePreparedSelection | None = None
    resources: OperationResources | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class CandidateLoopResumeRequest(PreviewModel):
    predecessor_operation_id: UUID
    expected_receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateLoopResumeOperation(PreviewModel):
    kind: Literal["candidate_loop_resume"] = "candidate_loop_resume"
    request_id: UUID
    request: CandidateLoopResumeRequest


OperationSubmission = Annotated[
    PrepareOperation
    | ReusablePrepareOperation
    | CandidateOperation
    | NativeChainOperation
    | NativeChainResumeOperation
    | CandidateLoopResumeOperation,
    Field(discriminator="kind"),
]
SUBMISSION = TypeAdapter(OperationSubmission)
#: Submissions whose admission binds a run seed (issue #983). A loop resume
#: inherits its root's; native chains resolve theirs at chain startup.
SEEDED_SUBMISSIONS = (PrepareOperation, ReusablePrepareOperation, CandidateOperation)
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
    #: Issue #983 — the run seed bound at admission, before claim and spawn; a
    #: loop resume copies its root's. ``None`` only on records that predate the
    #: seed contract (and on native chains, whose seed lives in the chain lock).
    run_seed: RunSeedBinding | None = Field(default=None, exclude_if=lambda value: value is None)
    #: Provenance: the run seed of the reusable preparation a candidate was built
    #: from. The candidate never derives from it; it keeps its own ``run_seed``.
    preparation_run_seed: RunSeed | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def admitted_seed_matches_request(self):
        submission = self.submission
        if isinstance(submission, SEEDED_SUBMISSIONS):
            if self.run_seed is not None:
                # Raises when the binding is not what admission binds for this request.
                admitted_run_seed(submission.request.run_seed, self.run_seed)
        elif self.run_seed is not None and submission.kind != "candidate_loop_resume":
            raise ValueError(f"{submission.kind} operation records no run seed")
        if self.preparation_run_seed is not None and (
            not isinstance(submission, CandidateOperation)
            or submission.reusable_preparation is None
        ):
            raise ValueError("preparation_run_seed requires a reusable-preparation candidate")
        return self

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


class CancelRequest(PreviewModel):
    """Durable, write-once operator intent to cancel one live candidate operation.

    The operation child polls for it while the sandbox runs (``cancel.py``).
    """

    operation_id: UUID
    request_digest: str
    requested_at: str


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
    successor_operation_id: UUID | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    finishing: bool = False
    # Omitted unless a CancelRequest is recorded; existing snapshot bytes are unchanged.
    cancel_requested: bool = Field(default=False, exclude_if=lambda value: not value)
    # A new cancel would be recorded (cancel.cancellable); omitted when false.
    cancellable: bool = Field(default=False, exclude_if=lambda value: not value)
    receipt_available: bool = False
    receipt_digest: str | None = None
    receipt: NativeReceipt | None = None
    native_chain: NativeChainObservation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    #: The admitted record's run seed (issue #983), readable before any receipt.
    run_seed: RunSeedBinding | None = Field(default=None, exclude_if=lambda value: value is None)
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


class OperationListEntry(PreviewModel):
    """One verified record: admission time, generated names and its read snapshot."""

    admitted_at: str
    run_name: str | None
    project_id: str | None
    snapshot: OperationSnapshot


class OperationListing(PreviewModel):
    entries: tuple[OperationListEntry, ...]
    unreadable: int = Field(ge=0)
    examined: int = Field(ge=0)
    incomplete: bool
