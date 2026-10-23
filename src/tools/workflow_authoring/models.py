"""Bounded authoring requests and projections of the existing declaration."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from workflows.definition import WorkflowDocument
from workflows.definition.models import Source
from workflows.definition.source import SourceDiagnostic

MAX_SOURCE_BYTES = 32 * 1024
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Project(Model):
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    project_root: Path
    source_file: Path
    recovery_directory: Path


class SourceProposal(Model):
    kind: Literal["source"]
    source: str

    @field_validator("source")
    @classmethod
    def bounded(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("editor source exceeds 32 KiB UTF-8")
        return value


class DocumentProposal(Model):
    kind: Literal["document"]
    document: WorkflowDocument


class ReviewRequest(Model):
    expected_sha256: Digest
    proposal: Annotated[SourceProposal | DocumentProposal, Field(discriminator="kind")]


class SaveRequest(SourceProposal):
    kind: Literal["source"] = "source"
    expected_sha256: Digest
    proposal_sha256: Digest


class BindingChoice(Model):
    label: str
    source: Source


class BindingOptions(Model):
    node: str
    argument: str | None
    choices: tuple[BindingChoice, ...]


class SourceView(Model):
    project_id: str
    source_path: str
    source: str
    sha256: Digest
    document: WorkflowDocument | None
    diagnostics: tuple[SourceDiagnostic, ...] = ()
    binding_options: tuple[BindingOptions, ...] = ()
    status: Literal["declaration_only"] = "declaration_only"


class ReviewView(Model):
    source: str
    sha256: Digest
    diff: str
    document: WorkflowDocument


class SaveView(Model):
    sha256: Digest
    recovery_ids: tuple[str, ...]
    unchanged: bool = False
