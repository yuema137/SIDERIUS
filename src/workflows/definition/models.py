"""Immutable declaration models; external references are not materialized."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from agent.schemas.output_types import OutputTypeName

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$", max_length=100)]
Location = Annotated[str, StringConstraints(min_length=1, pattern=r"^[^\x00]+$")]


class DeclarationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TaskReferences(DeclarationModel):
    """Locations only: no existence, content or task identity verification."""

    manifest: Location
    data_root: Location
    workspace: Location


class ExternalBinding(DeclarationModel):
    id: Identifier
    contract: str
    location: Location


class ExternalSource(DeclarationModel):
    kind: Literal["external"] = "external"
    binding: Identifier


class ResultSource(DeclarationModel):
    kind: Literal["result"] = "result"
    node: Identifier
    port: Literal["result"] = "result"


Source = Annotated[ExternalSource | ResultSource, Field(discriminator="kind")]


class ArgumentBinding(DeclarationModel):
    name: str
    source: Source


class ExternalRequest(DeclarationModel):
    kind: Literal["external"] = "external"
    binding: Identifier


class ProtocolRequest(DeclarationModel):
    kind: Literal["protocol"] = "protocol"
    protocol: str
    arguments: tuple[ArgumentBinding, ...]


Request = Annotated[ExternalRequest | ProtocolRequest, Field(discriminator="kind")]


class NodeInstance(DeclarationModel):
    id: Identifier
    capability: str
    request: Request


class WorkflowDefinition(DeclarationModel):
    schema_version: Literal[1] = 1
    task: TaskReferences
    externals: tuple[ExternalBinding, ...] = ()
    nodes: tuple[NodeInstance, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_connections(self) -> Self:
        from .validation import validate_definition

        validate_definition(self)
        return self

    def declaration_digest(self) -> str:
        """Hash declared values, not external bytes, runtime defaults or run identity."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class NodePosition(DeclarationModel):
    node: Identifier
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class WorkflowDocument(DeclarationModel):
    definition: WorkflowDefinition
    positions: tuple[NodePosition, ...] = ()

    @model_validator(mode="after")
    def validate_positions(self) -> Self:
        from .validation import validate_positions

        validate_positions(self.definition.nodes, self.positions)
        return self


class ReusableTaskReferences(DeclarationModel):
    """Authored locations only; a reusable declaration owns no workspace."""

    manifest: Location
    data_root: Location


class ManagedCandidateBinding(DeclarationModel):
    id: Identifier
    contract: Literal["proposal.input", "storage"]
    kind: Literal["managed_candidate"] = "managed_candidate"


class CandidatePreparationOptions(DeclarationModel):
    """Inert preparation selections; no native payloads or execution defaults."""

    proposal_advice: str | None = None
    implementation_advice: str | None = None
    validation_advice: str | None = None
    allowed_output_types: tuple[OutputTypeName, ...] | None = Field(default=None, min_length=1)


class ReusableWorkflowDefinition(DeclarationModel):
    """Version 2 describes reusable declarations, not arbitrary executable graphs."""

    schema_version: Literal[2] = 2
    task: ReusableTaskReferences
    externals: tuple[ExternalBinding | ManagedCandidateBinding, ...] = ()
    nodes: tuple[NodeInstance, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_connections(self) -> Self:
        from .validation import validate_definition

        validate_definition(self)
        return self


class ReusableWorkflowDocument(DeclarationModel):
    definition: ReusableWorkflowDefinition
    positions: tuple[NodePosition, ...] = ()
    preparation_options: CandidatePreparationOptions = Field(
        default_factory=CandidatePreparationOptions
    )

    @model_validator(mode="after")
    def validate_positions(self) -> Self:
        from .validation import validate_positions

        validate_positions(self.definition.nodes, self.positions)
        return self

    def declaration_digest(self) -> str:
        """Semantic identity includes options but excludes layout and source bytes."""
        canonical = json.dumps(
            self.model_dump(mode="json", exclude={"positions"}),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


AuthoredWorkflowDocument = WorkflowDocument | ReusableWorkflowDocument


def revalidate_document(document: AuthoredWorkflowDocument) -> AuthoredWorkflowDocument:
    """Revalidate by the explicit variant, including unchecked copied instances."""
    if isinstance(document, ReusableWorkflowDocument):
        return ReusableWorkflowDocument.model_validate_json(
            document.model_dump_json(warnings=False)
        )
    return WorkflowDocument.model_validate_json(document.model_dump_json(warnings=False))


class DeclarationReport(DeclarationModel):
    """A successful structural check never certifies execution readiness."""

    status: Literal["declaration_validated"] = "declaration_validated"
    execution_ready: Literal[False] = False
    unresolved: tuple[str, ...] = (
        "External payload contents and native request validation",
        "Task manifest identity, data availability and workspace isolation",
        "Capability constructors, model routing and effective native defaults",
        "Environment, resource admission and execution lifecycle",
    )


def inspect_declaration(document: AuthoredWorkflowDocument) -> DeclarationReport:
    """Revalidate even an instance made through Pydantic's unchecked copy APIs."""
    revalidate_document(document)
    return DeclarationReport()
