"""Curated captured-run API; browser selections never contain native requests."""

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from agent.schemas.output_types import OutputTypeName
from core.seeding import RunSeed
from tools.candidate_operations.models import OperationFailure
from tools.candidate_prepare import ReusablePreparedSelection
from tools.workflow_preview.models import PreviewModel
from workflows.definition import AuthoredLoop

from .models import CredentialReadiness, RouteView, RunResourcesSelection


class ReusableCaptureChoice(PreviewModel):
    task_id: str
    run_id: UUID


class ReusableCaptureSelection(ReusableCaptureChoice, RunResourcesSelection):
    """The reviewed capture plus the operator's scheduling inputs (B3-4c)."""

    preparation: ReusablePreparedSelection
    #: Optional operator seed for the candidate run (issue #983); omitted means
    #: the operation generates and records one at admission. The reviewed
    #: request digest binds it.
    run_seed: RunSeed | None = Field(default=None, exclude_if=lambda value: value is None)


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
            "native-interpretation-candidate/v1",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    literature_settings: dict[str, dict[str, JsonValue]] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    # The executed request's authored loop; absent means one body per launch.
    loop: AuthoredLoop | None = Field(default=None, exclude_if=lambda value: value is None)
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
    #: ``package_mounts.device_warnings`` for ``devices``/``read_only``, the same
    #: wording ``check`` prints; display only, Launch stays enabled.
    device_warnings: tuple[str, ...] = ()
    credential_readiness: CredentialReadiness
    # Display-only Save name of source_sha256 in the project's version record (B8-3); the
    # SHA-256 stays the bound identity. Absent when the bytes were never saved here.
    source_version_name: str | None = Field(default=None, exclude_if=lambda value: value is None)
    #: ``seed_labels.review_label`` wording of the selection's seed.
    seed: str


class ReusableAdmissionNotAttempted(OperationFailure):
    """This dispatch refused before calling submit, not a global UUID absence proof."""
