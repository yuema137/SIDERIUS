"""Captured-chain operation boundaries, distinct from scientific receipts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from core.native_observation import EvidenceReadBytes
from tools.native_chain.observation import NativeChainEvidence, ObservationPolicy
from tools.workflow_preview.models import FileObservation, PreviewModel
from tools.workspace_sandbox.runner import ObservedExecutionResult

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class NativeChainOperationRequest(PreviewModel):
    capture_path: str
    capture_sha256: Digest
    envelope: str
    read_only: tuple[str, ...]
    network: bool
    devices: tuple[str, ...]
    environment_names: tuple[str, ...]
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    input_max_bytes: int = Field(gt=0, le=16 * 1024 * 1024, strict=True)
    max_iterations_observed: int = Field(gt=0, le=1000, strict=True)
    max_observation_bytes: int = Field(gt=0, le=1024 * 1024, strict=True)
    max_evidence_read_bytes: EvidenceReadBytes | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class NativeChainOperation(PreviewModel):
    kind: Literal["native_chain"] = "native_chain"
    request_id: UUID
    request: NativeChainOperationRequest


class NativeChainAdmission(PreviewModel):
    request_digest: Digest
    capture_sha256: Digest
    workspace: str
    final_iteration: int = Field(gt=0, le=1000)
    run_name: str
    recipe: Literal["native-standard-chain/v1"]
    checkout: str
    git_directory: str
    git_common_directory: str
    required_environment_names: tuple[str, ...]
    input_files: tuple[FileObservation, ...]


class NativeChainFence(PreviewModel):
    operation_id: UUID
    request_digest: Digest
    capture_sha256: Digest
    envelope: str


class NativeChainTerminal(PreviewModel):
    operation_id: UUID
    request_digest: Digest
    capture_sha256: Digest
    envelope: str
    workspace: str
    runtime_digest: Digest
    supervision: ObservedExecutionResult
    observation_policy: ObservationPolicy = 1
    evidence: NativeChainEvidence = Field(
        default_factory=lambda: NativeChainEvidence(availability="unavailable")
    )


class NativeChainContinuation(PreviewModel):
    root_operation_id: UUID
    head_operation_id: UUID
    head_state: Literal["active", "completed", "operation_failed", "unknown"]
    lifecycle: Literal["reserved", "adopted", "no_child", "terminal"]


class NativeChainObservation(PreviewModel):
    admission: NativeChainAdmission
    terminal: NativeChainTerminal | None = None
    continuation: NativeChainContinuation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    evidence: NativeChainEvidence = Field(
        default_factory=lambda: NativeChainEvidence(availability="unavailable")
    )
