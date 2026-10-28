"""Inert public selections and bounded preparation control records."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from agent.schemas.output_types import OutputTypeName
from core.generated_artifact_name import validate_generated_artifact_name
from core.seeding import RunSeed, SeedSource
from tools.workflow_preview.models import FileObservation, PreviewModel


class CandidatePreparationRequest(PreviewModel):
    task_manifest: str
    data_root: str
    llm_config_file: str
    output_dir: str
    candidate_workspace: str
    run_name: str
    preparation_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    candidate_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    task_read_only: tuple[str, ...]
    candidate_network: bool
    candidate_devices: tuple[str, ...]
    candidate_environment_names: tuple[str, ...]
    proposal_advice: str | None = None
    implementation_advice: str | None = None
    validation_advice: str | None = None
    allowed_output_types: tuple[OutputTypeName, ...] | None = Field(default=None, min_length=1)
    #: Issue #983 — the operator's explicit seed for this preparation run; omitted
    #: when ``None`` so seedless request digests are unchanged.
    run_seed: RunSeed | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("run_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        validate_generated_artifact_name(value, field="run_name")
        return value


def require_seed_pair(run_seed: int | None, source: str | None) -> None:
    """A preparation receipt records its run seed and source together, or neither (pre-seed)."""
    if (run_seed is None) != (source is None):
        raise ValueError("run_seed and run_seed_source are recorded together")


class CandidatePreparationReceipt(PreviewModel):
    preparation_id: UUID
    status: Literal["prepared", "failed", "timed_out", "interrupted"]
    output_dir: str
    request_path: str
    log_path: str
    error: str | None = None
    candidate_request_path: str | None = None
    preview_path: str | None = None
    interpretation_path: str | None = None
    proposal_path: str | None = None
    composition_fingerprint: str | None = None
    source_observations: tuple[FileObservation, ...] = ()
    run_seed: RunSeed | None = Field(default=None, exclude_if=lambda value: value is None)
    run_seed_source: SeedSource | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def seed_pair(self):
        require_seed_pair(self.run_seed, self.run_seed_source)
        return self


class PreparationControl(PreviewModel):
    preparation_id: UUID
    request: CandidatePreparationRequest
    sources: tuple[FileObservation, ...]


class PreparedArtifacts(PreviewModel):
    preparation_id: UUID
    control_sha256: str
    composition_fingerprint: str = Field(min_length=1)
    files: tuple[FileObservation, ...]


NATIVE_FILES = (
    "preparation/interpretation_input.json",
    "interpretation.json",
    "proposal.json",
    "storage.json",
    "llm.json",
    "workflow.json",
)


# Narrow parent-side projection, not a replacement native schema. All scientific
# decoding remains in the bound child; this checks its index against saved bytes.


class CompositionIdentity(BaseModel):
    semantic_fingerprint: str
    task_data_path_id: str | None = Field(default=None, exclude_if=lambda value: value is None)


class ProposalIdentity(BaseModel):
    task_composition_ref: CompositionIdentity
