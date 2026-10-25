"""Configured native requests and browser selections; execution policy is host-owned."""

from uuid import UUID

from pydantic import Field

from tools.candidate_operations.native_chain_models import (
    Digest,
    NativeChainAdmission,
    NativeChainOperationRequest,
)
from tools.workflow_preview.models import PreviewModel

from .readiness_models import CredentialReadiness


class NativeChainChoice(PreviewModel):
    choice_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    label: str = Field(min_length=1, max_length=160)
    request: NativeChainOperationRequest


class NativeChainChoiceSelection(PreviewModel):
    choice_id: str


class NativeChainLaunchSelection(NativeChainChoiceSelection):
    operation_id: UUID
    expected_request_digest: Digest


class NativeChainChoiceView(PreviewModel):
    choice_id: str
    label: str


class NativeChainReviewView(PreviewModel):
    choice_id: str
    label: str
    request_digest: Digest
    admission: NativeChainAdmission
    capture_path: str
    envelope: str
    read_only: tuple[str, ...]
    network: bool
    devices: tuple[str, ...]
    environment_names: tuple[str, ...]
    timeout_seconds: float
    input_max_bytes: int
    max_iterations_observed: int
    max_observation_bytes: int
    max_evidence_read_bytes: int | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    credential_readiness: CredentialReadiness
