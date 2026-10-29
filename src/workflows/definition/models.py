"""Immutable declaration models; external references are not materialized."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, StringConstraints, model_validator

from agent.schemas.output_types import OutputTypeName

from .adaptor_strategies import DistributeStrategy, SelectStrategy
from .base import DeclarationModel, Identifier, Location
from .llm_strategies import AdaptorCombine


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


class SelectedSource(DeclarationModel):
    """Merge: the result of the one candidate whose arm ``branch`` selected.

    A deterministic select keyed by the recorded route decision, never an OR/race join.
    """

    kind: Literal["selected"] = "selected"
    branch: Identifier
    candidates: tuple[ResultSource, ...] = Field(min_length=2)


class AdaptorSource(DeclarationModel):
    """One output of a declared adaptor; ``index`` names one of its distributed outputs."""

    kind: Literal["adaptor"] = "adaptor"
    adaptor: Identifier
    port: Literal["result"] = "result"
    index: Annotated[int, Field(ge=0)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


Source = Annotated[
    ExternalSource | ResultSource | SelectedSource | AdaptorSource, Field(discriminator="kind")
]


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


class AdaptorRequest(DeclarationModel):
    """A whole capability request taken from an adaptor output of exactly that contract."""

    kind: Literal["adaptor"] = "adaptor"
    source: AdaptorSource


Request = Annotated[ExternalRequest | ProtocolRequest | AdaptorRequest, Field(discriminator="kind")]


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


class MetricThresholdStop(DeclarationModel):
    """Stop once the loop incumbent reaches ``threshold`` under the run metric's direction.

    Direction is never declared here: it comes from the run's ``MetricSpec``.
    """

    kind: Literal["metric_threshold"] = "metric_threshold"
    metric_id: str = Field(min_length=1)
    threshold: float = Field(allow_inf_nan=False)


class NoImprovementStop(DeclarationModel):
    """Stop after this many consecutive completed bodies leave the incumbent unimproved."""

    kind: Literal["no_improvement"] = "no_improvement"
    completed_bodies: Annotated[int, Field(gt=0)]


class JudgeStop(DeclarationModel):
    """Stop when the LLM stop judge decides so at a completed-body boundary.

    Consulted only after every deterministic condition continued, never at the final
    boundary and never before ``min_completed_bodies``. The route is operator-owned
    (``WorkflowLLMConfig.judge.stop``), never declared here. ``on_failure="continue"``
    records a failed call as an abstention; ``"fail"`` ends the loop ``failed``.
    """

    kind: Literal["judge"] = "judge"
    criterion: str = Field(min_length=1, max_length=2000)
    min_completed_bodies: Annotated[int, Field(gt=0)] = 1
    on_failure: Literal["fail", "continue"] = "fail"


StopCondition = Annotated[
    MetricThresholdStop | NoImprovementStop | JudgeStop, Field(discriminator="kind")
]


MAX_ROUTE_BRANCHES = 32
MAX_ROUTE_CASES = 8
MAX_ROUTE_LEAVES = 8
ObservableId = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class BoolIs(DeclarationModel):
    """True when a catalogued boolean observable equals ``value``."""

    kind: Literal["bool_is"] = "bool_is"
    observable: ObservableId
    value: bool


class EnumIn(DeclarationModel):
    """True when a catalogued enum observable is one of ``values``."""

    kind: Literal["enum_in"] = "enum_in"
    observable: ObservableId
    values: tuple[str, ...] = Field(min_length=1)


class MetricAtLeast(DeclarationModel):
    """True when a present metric observable is at least ``threshold`` under the run metric.

    Direction comes only from the run's ``MetricSpec``; an absent value is false.
    """

    kind: Literal["metric_at_least"] = "metric_at_least"
    observable: ObservableId
    metric_id: str = Field(min_length=1)
    threshold: float = Field(allow_inf_nan=False)


class IsMissing(DeclarationModel):
    """True when a catalogued metric observable has no value."""

    kind: Literal["is_missing"] = "is_missing"
    observable: ObservableId


RouteLeaf = Annotated[BoolIs | EnumIn | MetricAtLeast | IsMissing, Field(discriminator="kind")]


class AllOf(DeclarationModel):
    kind: Literal["all_of"] = "all_of"
    terms: tuple[RouteLeaf, ...] = Field(min_length=2, max_length=MAX_ROUTE_LEAVES)


class AnyOf(DeclarationModel):
    kind: Literal["any_of"] = "any_of"
    terms: tuple[RouteLeaf, ...] = Field(min_length=2, max_length=MAX_ROUTE_LEAVES)


class Not(DeclarationModel):
    kind: Literal["not"] = "not"
    term: RouteLeaf


# One combinator level over leaves only: combinators never nest.
RoutePredicate = Annotated[
    BoolIs | EnumIn | MetricAtLeast | IsMissing | AllOf | AnyOf | Not,
    Field(discriminator="kind"),
]


class RouteCase(DeclarationModel):
    when: RoutePredicate
    targets: tuple[Identifier, ...] = Field(min_length=1)


class Branch(DeclarationModel):
    """Exclusive route over one upstream result; the first matching case wins.

    ``default=None`` means no arm runs when no case matches, so a single-case
    branch without a default is a guard (conditional edge). Branch ids form
    their own namespace. Declaration only: execution admission is separate.
    """

    id: Identifier
    source: ResultSource
    cases: tuple[RouteCase, ...] = Field(min_length=1, max_length=MAX_ROUTE_CASES)
    default: tuple[Identifier, ...] | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )


AdaptorFormat = Literal["siderius.adaptors/v1"]


class InputPort(DeclarationModel):
    """A typed adaptor input; a ``one`` port takes exactly one source."""

    name: Identifier
    contract: str
    cardinality: Literal["one", "many"]
    min_items: Annotated[int, Field(ge=0)] = 1
    max_items: Annotated[int, Field(gt=0)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if self.cardinality == "one" and (self.min_items != 1 or self.max_items is not None):
            raise ValueError("a 'one' port takes exactly one item; it declares no item bounds")
        if self.max_items is not None and self.min_items > self.max_items:
            raise ValueError("min_items must not exceed max_items")
        return self


class PortBinding(DeclarationModel):
    """Sources of one port; their declared order is every tie-break order."""

    port: Identifier
    sources: tuple[Source, ...]


class AdaptorInstance(DeclarationModel):
    """A declared COMBINE -> SELECT -> DISTRIBUTE step; its output contract is derived.

    Declaration only: no execution profile admits an adaptor yet.
    """

    id: Identifier
    kind: Literal["adaptor"] = "adaptor"
    inputs: tuple[InputPort, ...] = Field(min_length=1)
    bindings: tuple[PortBinding, ...]
    combine: AdaptorCombine  # LLM kinds run only under native-literature-judged/v1
    select: SelectStrategy
    distribute: DistributeStrategy


class AuthoredLoop(DeclarationModel):
    final_iteration: Annotated[int, Field(gt=0)]
    feedback: LoopFeedback
    # Any-of, evaluated in declared order at each completed-body boundary.
    stop_conditions: tuple[StopCondition, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )


class WorkflowDefinition(DeclarationModel):
    schema_version: Literal[1] = 1
    task: TaskReferences
    externals: tuple[ExternalBinding, ...] = ()
    nodes: tuple[NodeInstance, ...] = Field(min_length=1)
    loop: AuthoredLoop | None = Field(default=None, exclude_if=lambda value: value is None)
    routes: tuple[Branch, ...] = Field(
        default=(), max_length=MAX_ROUTE_BRANCHES, exclude_if=lambda value: not value
    )
    adaptor_format: AdaptorFormat | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    adaptors: tuple[AdaptorInstance, ...] = Field(default=(), exclude_if=lambda value: not value)

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
    contract: Literal[
        "proposal.input",
        "storage",
        "native-training.settings",
        "literature.input",
        "interpretation.input",
        "optional.text",
        "optional.expert-advice",
        "optional.expert-context",
        "optional.parameter-rules",
        "optional.constraint-context",
        "optional.task-composition-ref",
    ]
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
    routes: tuple[Branch, ...] = Field(
        default=(), max_length=MAX_ROUTE_BRANCHES, exclude_if=lambda value: not value
    )
    adaptor_format: AdaptorFormat | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    adaptors: tuple[AdaptorInstance, ...] = Field(default=(), exclude_if=lambda value: not value)

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
            "native-interpretation-candidate/v1",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    training_settings: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    task_binding: TaskBinding | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_training(self) -> Self:
        if (
            self.execution_profile is not None
            and self.execution_profile != "native-interpretation-candidate/v1"
            and self.training_settings is not None
        ):
            raise ValueError("This reusable graph profile does not support training_settings")
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

        if self.execution_profile == "native-interpretation-candidate/v1":
            from .fanout import execution_families

            execution_families(self.definition, self.execution_profile)
        else:
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
