"""Curated captured-run API; browser selections never contain native requests."""

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from agent.schemas.output_types import OutputTypeName
from tools.candidate_operations.models import OperationFailure
from tools.candidate_prepare import ReusablePreparedSelection
from tools.workflow_preview.models import PreviewModel

from .models import CredentialReadiness, RouteView


class ReusableCaptureChoice(PreviewModel):
    task_id: str
    run_id: UUID


class ReusableCaptureSelection(ReusableCaptureChoice):
    preparation: ReusablePreparedSelection


class ReusableCaptureLaunch(PreviewModel):
    selection: ReusableCaptureSelection
    expected_request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_operation_id: UUID


class ReusableCaptureDescriptor(PreviewModel):
    run_id: UUID
    available: bool
    run_name: str | None = None
    source_sha256: str | None = None
    reason: str | None = None


class ReusableCapturePage(PreviewModel):
    captures: tuple[ReusableCaptureDescriptor, ...]
    next_cursor: UUID | None


class ReusableCaptureReview(PreviewModel):
    execution_profile: (
        Literal[
            "native-proposal-fanout/v1",
            "native-proposal-families/v1",
            "native-literature-candidate/v1",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    literature_settings: dict[str, dict[str, JsonValue]] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    selection: ReusableCaptureSelection
    request_digest: str
    source_path: str
    source_sha256: str
    task_label: str
    task_manifest: str
    data_root: str
    llm_config_file: str
    allowed_output_types: tuple[OutputTypeName, ...] | None
    run_name: str
    envelope: str
    inputs: str
    workspace: str
    nodes: tuple[tuple[str, str], ...]
    routes: tuple[RouteView, ...]
    composition_fingerprint: str
    proposal_advice: str | None
    implementation_advice: str | None
    validation_advice: str | None
    preparation_timeout_seconds: float
    candidate_timeout_seconds: float
    network: bool
    devices: tuple[str, ...]
    environment_names: tuple[str, ...]
    read_only: tuple[str, ...]
    credential_readiness: CredentialReadiness


class ReusableAdmissionNotAttempted(OperationFailure):
    """This dispatch refused before calling submit, not a global UUID absence proof."""
