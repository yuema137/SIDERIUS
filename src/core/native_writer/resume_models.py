"""Bounded coordination identities for explicitly admitted native successors."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from core.native_observation import EvidenceReadBytes, ObservationPolicy, observation_policy

from .models import Claim, Digest, Participation, Registration, Unresolved, WriterModel


class WriterSnapshot(WriterModel):
    registration: Registration
    claim: Claim | None
    participant: Participation | None
    unresolved: Unresolved | None
    registration_digest: Digest
    claim_digest: Digest | None
    participant_digest: Digest | None
    unresolved_digest: Digest | None
    lock_device: int
    lock_inode: int


class ResumeReservation(WriterModel):
    version: Literal[1] = 1
    state_root: str
    store_digest: Digest
    root_operation_id: UUID
    predecessor_operation_id: UUID
    successor_operation_id: UUID
    successor_request_digest: Digest
    claim_id: UUID
    predecessor_completion_digest: Digest
    baseline_operation_id: UUID
    baseline_terminal_digest: Digest
    capture_sha256: Digest
    snapshot_digest: Digest
    evidence_digest: Digest
    observation_policy: ObservationPolicy = 2
    start_iteration: int = Field(ge=2, le=1000, strict=True)
    final_iteration: int = Field(ge=2, le=1000, strict=True)
    input_max_bytes: int = Field(gt=0, le=16777216, strict=True)
    max_observation_bytes: int = Field(gt=0, le=1048576, strict=True)
    max_evidence_read_bytes: EvidenceReadBytes | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def consistent_observation_budget(self):
        if self.observation_policy != observation_policy(self.max_evidence_read_bytes):
            raise ValueError("observation policy disagrees with evidence-read budget")
        return self


class ResumeAdoption(WriterModel):
    reservation_digest: Digest
    operation_id: UUID
    claim_id: UUID
