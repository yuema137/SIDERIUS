"""Immutable declaration models; external references are not materialized."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
        node_ids = {node.id for node in self.definition.nodes}
        seen = set()
        for position in self.positions:
            if position.node not in node_ids or position.node in seen:
                raise ValueError(f"Unknown or duplicate layout node: {position.node}")
            seen.add(position.node)
        return self


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


def inspect_declaration(document: WorkflowDocument) -> DeclarationReport:
    """Revalidate even an instance made through Pydantic's unchecked copy APIs."""
    WorkflowDocument.model_validate_json(document.model_dump_json())
    return DeclarationReport()
