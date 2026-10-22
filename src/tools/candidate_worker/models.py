"""Inert public launch contract: no native node or task imports."""

from typing import Literal

from pydantic import Field, field_validator

from core.generated_artifact_name import validate_generated_artifact_name
from tools.setup_review.route_models import LLMRoute
from tools.workflow_preview.models import FileObservation, PreviewModel, WorkflowPreviewRequest


class CandidateRunRequest(PreviewModel):
    preview: WorkflowPreviewRequest
    declaration_digest: str
    files: tuple[FileObservation, ...]
    selected_constructor_routes: tuple[LLMRoute, ...]
    storage_policy: Literal["managed_fresh"]
    run_name: str
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    network: bool
    devices: tuple[str, ...]
    read_only: tuple[str, ...]
    environment_names: tuple[str, ...]
    implementation_advice: str | None = None
    validation_advice: str | None = None

    @field_validator("run_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        validate_generated_artifact_name(value, field="run_name")
        return value


class CandidateRunReceipt(PreviewModel):
    """Execution index; native records remain the authority for node data."""

    run_id: str
    run_name: str
    workspace: str
    declaration_digest: str
    status: Literal["launched", "accepted", "rejected", "failed", "timed_out", "interrupted"]
    node_ids: tuple[str, ...]
    selected_constructor_routes: tuple[LLMRoute, ...]
    ledger_path: str
    log_path: str
    candidate_id: str | None = None
    composition_fingerprint: str | None = None
    proposal_storage: str | None = None
    implementation_storage: str | None = None
    native_output_paths: tuple[str, ...] = ()
    validation_passed: bool | None = None
    error: str | None = None
