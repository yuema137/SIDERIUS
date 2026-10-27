"""Immutable declaration models; external references are not materialized."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

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


class LoopFeedback(DeclarationModel):
    """Explicit cross-body edge; it is not a cycle inside the body's DAG."""

    source: ResultSource
    target: Identifier
    protocol: Literal["tuning-to-interpretation"]
    history: Literal["native-research/v1"]


class AuthoredLoop(DeclarationModel):
    final_iteration: Annotated[int, Field(gt=0)]
    feedback: LoopFeedback


class WorkflowDefinition(DeclarationModel):
    schema_version: Literal[1] = 1
    task: TaskReferences
    externals: tuple[ExternalBinding, ...] = ()
    nodes: tuple[NodeInstance, ...] = Field(min_length=1)
    loop: AuthoredLoop | None = Field(default=None, exclude_if=lambda value: value is None)

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
    contract: Literal["proposal.input", "storage", "native-training.settings", "literature.input"]
    kind: Literal["managed_candidate"] = "managed_candidate"
    literature_settings: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_literature_settings(self) -> Self:
        if self.contract == "literature.input":
            if self.literature_settings is None:
                raise ValueError("Managed literature requires explicit literature_settings")
        elif self.literature_settings is not None:
            raise ValueError("literature_settings requires a literature.input binding")
        return self


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
    loop: AuthoredLoop | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_connections(self) -> Self:
        from .validation import validate_definition

        validate_definition(self)
        return self


class TaskBinding(DeclarationModel):
    """Accepted native identity and readable labels; never a resolver or new hash."""

    schema_version: Literal["siderius.task-binding/v1"] = "siderius.task-binding/v1"
    package_id: str = Field(min_length=1, max_length=160)
    revision: str = Field(min_length=1, max_length=160)
    task_data_path_id: str = Field(min_length=1, max_length=160)
    semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReusableWorkflowDocument(DeclarationModel):
    definition: ReusableWorkflowDefinition
    positions: tuple[NodePosition, ...] = ()
    preparation_options: CandidatePreparationOptions = Field(
        default_factory=CandidatePreparationOptions
    )

    execution_profile: (
        Literal[
            "native-proposal-fanout/v1",
            "native-proposal-families/v1",
            "native-literature-candidate/v1",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    training_settings: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    task_binding: TaskBinding | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_training(self) -> Self:
        if self.execution_profile is not None and self.training_settings is not None:
            raise ValueError("Fanout does not support training_settings")
        settings_bindings = [
            item
            for item in self.definition.externals
            if item.contract == "native-training.settings"
        ]
        tuning = any(node.capability == "tuning" for node in self.definition.nodes)
        if self.training_settings is None:
            if settings_bindings or tuning:
                raise ValueError("Reusable tuning requires source-owned training_settings")
            return self
        if (
            not tuning
            or len(settings_bindings) != 1
            or not isinstance(settings_bindings[0], ManagedCandidateBinding)
        ):
            raise ValueError(
                "training_settings requires one tuning node and managed settings binding"
            )
        from workflows.candidate_training_settings import (
            effective_training_settings,
            parse_training_settings,
        )

        from .candidate import candidate_nodes

        candidate_nodes(self.definition)
        settings = parse_training_settings(
            effective_training_settings(
                self.training_settings, self.preparation_options.allowed_output_types
            )
        )
        if settings.health_checks_config is not None:
            raise ValueError("Reusable training does not capture external health_checks_config")
        return self

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
