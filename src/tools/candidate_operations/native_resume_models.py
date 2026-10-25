"""Inert resume requests and the immutable, inherited admission projection."""

import hashlib
from typing import Literal
from uuid import UUID

from pydantic import Field

from core.native_observation import observation_policy
from core.native_writer.resume_models import ResumeReservation, WriterSnapshot
from tools.native_chain.observation import NativeChainEvidence
from tools.workflow_preview.models import PreviewModel

from .native_chain_models import Digest, NativeChainAdmission, NativeChainOperationRequest


class NativeChainResumeRequest(PreviewModel):
    predecessor_operation_id: UUID
    expected_review_digest: Digest


class NativeChainResumeOperation(PreviewModel):
    kind: Literal["native_chain_resume"] = "native_chain_resume"
    request_id: UUID
    request: NativeChainResumeRequest


class NativeResumeAdmission(PreviewModel):
    state_root: str
    root_operation_id: UUID
    predecessor_operation_id: UUID
    predecessor_completion_digest: Digest
    baseline_operation_id: UUID
    baseline_terminal_digest: Digest
    root_request: NativeChainOperationRequest
    root_admission: NativeChainAdmission
    owner: WriterSnapshot
    evidence: NativeChainEvidence
    start_iteration: int = Field(ge=2, le=1001, strict=True)
    store_digest: Digest


class NativeResumeReview(PreviewModel):
    eligibility: Literal["ready", "not_needed"]
    review_digest: Digest
    admission: NativeResumeAdmission
    whole_iterations_repeated: tuple[int, ...] = ()


def review_digest(admission: NativeResumeAdmission) -> str:
    return hashlib.sha256(admission.model_dump_json().encode()).hexdigest()


def reservation_for(
    admission: NativeResumeAdmission, operation_id: UUID, claim_id: UUID, request_digest: str
) -> ResumeReservation:
    return ResumeReservation(
        state_root=admission.state_root,
        store_digest=admission.store_digest,
        root_operation_id=admission.root_operation_id,
        predecessor_operation_id=admission.predecessor_operation_id,
        successor_operation_id=operation_id,
        successor_request_digest=request_digest,
        claim_id=claim_id,
        predecessor_completion_digest=admission.predecessor_completion_digest,
        baseline_operation_id=admission.baseline_operation_id,
        baseline_terminal_digest=admission.baseline_terminal_digest,
        capture_sha256=admission.root_request.capture_sha256,
        snapshot_digest=hashlib.sha256(admission.owner.model_dump_json().encode()).hexdigest(),
        evidence_digest=hashlib.sha256(admission.evidence.model_dump_json().encode()).hexdigest(),
        start_iteration=admission.start_iteration,
        final_iteration=admission.root_admission.final_iteration,
        input_max_bytes=admission.root_request.input_max_bytes,
        max_observation_bytes=admission.root_request.max_observation_bytes,
        max_evidence_read_bytes=admission.root_request.max_evidence_read_bytes,
        observation_policy=observation_policy(admission.root_request.max_evidence_read_bytes),
    )
