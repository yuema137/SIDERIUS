"""Bounded authoring requests and projections of the existing declaration."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, computed_field, model_validator

from workflows.definition import (
    ArgumentBinding,
    AuthoredLoop,
    AuthoredWorkflowDocument,
    ExternalBinding,
    ManagedCandidateBinding,
)
from workflows.definition.catalog import CAPABILITIES, PROTOCOLS
from workflows.definition.contract_names import ContractKind, contract_name
from workflows.definition.draft import BindingPatch, DraftInspection, DraftProblem, WorkflowDraft
from workflows.definition.models import Identifier, Source
from workflows.definition.source import SourceDiagnostic

from .task_models import TaskReferenceAcceptance, TaskReferenceReview, TaskReferenceUpdateProposal
from .training import TrainingInspector

MAX_SOURCE_BYTES = 32 * 1024
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Project(Model):
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    project_root: Path
    source_file: Path
    recovery_directory: Path


def _bounded_source(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("editor source exceeds 32 KiB UTF-8")
    return value


BoundedSource = Annotated[str, AfterValidator(_bounded_source)]


class SourceProposal(Model):
    kind: Literal["source"]
    source: BoundedSource


class LoopProposal(Model):
    """Replace only the authored loop of one complete source declaration.

    Parsing the exact proposal source keeps every other authored value typed as
    written; a browser JSON document cannot distinguish ``2.0`` from ``2``.
    """

    kind: Literal["loop"]
    source: BoundedSource
    loop: AuthoredLoop | None


class PendingNode(Model):
    """One catalog node that is not yet part of the source.

    ``protocol=None`` selects the capability's external request route
    (``binding``); otherwise ``arguments`` bind the protocol's sockets. Unbound
    required inputs are a draft-only state: Review refuses them as
    ``draft_incomplete`` and nothing invalid can reach Save.
    """

    node: Identifier
    capability: str
    protocol: str | None = None
    binding: Identifier | None = None
    arguments: tuple[ArgumentBinding, ...] = ()
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def catalog_route(self) -> Self:
        capability = CAPABILITIES.get(self.capability)
        if capability is None:
            raise ValueError("capability is not in the native catalog")
        if self.protocol is None:
            if self.arguments:
                raise ValueError("an external request route has no protocol arguments")
            return self
        protocol = PROTOCOLS.get(self.protocol)
        if protocol is None or protocol.output != capability.input:
            raise ValueError("protocol does not produce this capability's input")
        if self.binding is not None:
            raise ValueError("a protocol route has no external request binding")
        names = [item.name for item in self.arguments]
        if len(set(names)) != len(names) or not set(names) <= {
            item.name for item in protocol.arguments
        }:
            raise ValueError("arguments must be unique protocol sockets")
        return self

    def missing_problems(self) -> tuple[DraftProblem, ...]:
        """Located problems for each required input that is still unbound."""
        if self.protocol is None:
            fields = () if self.binding else ("request",)
        else:
            bound = {item.name for item in self.arguments}
            fields = tuple(
                item.name
                for item in PROTOCOLS[self.protocol].arguments
                if item.required and item.name not in bound
            )
        return tuple(
            DraftProblem(
                code="required_unbound",
                node=self.node,
                field=field,
                message=f"{self.node}.{field}: required input is unbound",
            )
            for field in fields
        )

    def missing_inputs(self) -> tuple[str, ...]:
        return tuple(item.message for item in self.missing_problems())


class AddNodeProposal(PendingNode):
    """Insert one catalog node into the exact proposal source; other bytes stay."""

    kind: Literal["add_node"]
    source: BoundedSource


NewExternal = ExternalBinding | ManagedCandidateBinding


class NodeDraftsProposal(Model):
    """Any number of pending nodes and new external inputs over one anchor source.

    With ``document`` absent and no ``bindings`` the result is a targeted
    insertion: every anchor byte (comments, formatting) stays and only the new
    externals, nodes, positions and constructor imports are added. ``document``
    carries edits of the existing content (moves, inspector, loop) and
    ``bindings`` patch existing sockets; either one renders the combined
    document canonically, exactly like a document or binding-draft proposal.
    Pending nodes may read each other, new externals and existing results.
    """

    kind: Literal["node_drafts"]
    source: BoundedSource
    nodes: tuple[PendingNode, ...] = ()
    externals: tuple[NewExternal, ...] = ()
    document: AuthoredWorkflowDocument | None = None
    bindings: tuple[BindingPatch, ...] = ()

    @model_validator(mode="after")
    def unique_additions(self) -> Self:
        if not self.nodes and not self.externals:
            raise ValueError("a node draft adds at least one node or external input")
        for values, label in (
            ([item.node for item in self.nodes], "node"),
            ([item.id for item in self.externals], "external input"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"new {label} ids must be unique")
        return self


class RemoveNodeProposal(Model):
    """Remove nodes with their own input bindings and layout positions.

    Any remaining input or loop endpoint that reads a removed node refuses the
    whole proposal with an explanation; nothing is rewired implicitly.
    """

    kind: Literal["remove_node"]
    source: BoundedSource
    nodes: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError("node ids must be unique")
        return self


class NodeEditSummary(Model):
    """Review explanation of a node add/remove; the diff stays the exact authority."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    # Input connections of removed nodes that disappear with them.
    disconnected: tuple[str, ...] = ()
    message: str


class DocumentProposal(Model):
    kind: Literal["document"]
    document: AuthoredWorkflowDocument


class DraftProposal(Model):
    kind: Literal["draft"]
    draft: WorkflowDraft


class DraftRequest(Model):
    expected_sha256: Digest
    draft: WorkflowDraft


class DraftView(Model):
    draft: WorkflowDraft
    inspection: DraftInspection


class ReviewRequest(Model):
    expected_sha256: Digest
    proposal: Annotated[
        SourceProposal
        | LoopProposal
        | DocumentProposal
        | DraftProposal
        | AddNodeProposal
        | NodeDraftsProposal
        | RemoveNodeProposal
        | TaskReferenceUpdateProposal,
        Field(discriminator="kind"),
    ]
    task_reference_selection: TaskReferenceUpdateProposal | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def one_task_selection(self):
        if (
            isinstance(self.proposal, TaskReferenceUpdateProposal)
            and self.task_reference_selection is not None
        ):
            raise ValueError("task-reference proposal already owns its selection")
        return self


# 1-64 characters, no control characters, no leading/trailing whitespace.
VersionName = Annotated[
    str, Field(pattern=r"^[^\s\x00-\x1f\x7f](?:[^\x00-\x1f\x7f]{0,62}[^\s\x00-\x1f\x7f])?$")
]


class SaveRequest(SourceProposal):
    kind: Literal["source"] = "source"
    expected_sha256: Digest
    proposal_sha256: Digest
    # Presentation-only name recorded beside the source; omitted -> next "vN".
    version_name: VersionName | None = Field(default=None, exclude_if=lambda value: value is None)
    task_reference_acceptance: TaskReferenceAcceptance | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class NativeContract(Model):
    """One inert contract id, its catalog-owned native type label and its
    presentation (name, description, kind) from the single ``contract_names`` owner."""

    id: str
    native_type: str

    @computed_field
    @property
    def name(self) -> str:
        return contract_name(self.id).name

    @computed_field
    @property
    def description(self) -> str:
        return contract_name(self.id).description

    @computed_field
    @property
    def kind(self) -> ContractKind:
        return contract_name(self.id).kind


class BindingChoice(Model):
    label: str
    source: Source


class PortChoice(Model):
    label: str
    source: Source
    contract: NativeContract


class ProtocolMapping(Model):
    """Catalog-owned protocol route into a node's native input contract."""

    id: str
    owner: str
    output_contract: NativeContract


class BindingOptions(Model):
    node: str
    argument: str | None
    choices: tuple[BindingChoice, ...]


class PortInventoryEntry(Model):
    node: str
    argument: str | None
    choices: tuple[PortChoice, ...]
    socket_contract: NativeContract
    required: bool
    bound: bool
    source: Source | None
    node_input_contract: NativeContract
    node_output_contract: NativeContract
    protocol_mapping: ProtocolMapping | None


class SourceView(Model):
    training: TrainingInspector | None = None
    loop_template: AuthoredLoop | None = Field(default=None, exclude_if=lambda value: value is None)
    project_id: str
    source_path: str
    source: str
    sha256: Digest
    document: AuthoredWorkflowDocument | None
    diagnostics: tuple[SourceDiagnostic, ...] = ()
    binding_options: tuple[BindingOptions, ...] = ()
    port_inventory: tuple[PortInventoryEntry, ...] = ()
    status: Literal["declaration_only"] = "declaration_only"


class ReviewView(Model):
    task_reference_update: TaskReferenceReview | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    training: TrainingInspector | None = None
    loop_template: AuthoredLoop | None = Field(default=None, exclude_if=lambda value: value is None)
    binding_options: tuple[BindingOptions, ...]
    port_inventory: tuple[PortInventoryEntry, ...] = ()
    source: str
    sha256: Digest
    diff: str
    document: AuthoredWorkflowDocument
    node_edit: NodeEditSummary | None = Field(default=None, exclude_if=lambda value: value is None)


class SaveView(Model):
    sha256: Digest
    recovery_ids: tuple[str, ...]
    unchanged: bool = False
    version_name: str | None = Field(default=None, exclude_if=lambda value: value is None)


class CatalogArgument(Model):
    name: str
    contract: NativeContract
    required: bool
    # Capabilities whose output carries this contract; empty means an external input.
    produced_by: tuple[str, ...] = ()


class CatalogEntry(Model):
    """One addable request route for one capability; ``protocol=None`` is external."""

    capability: str
    protocol: str | None
    owner: str | None
    input_contract: NativeContract
    output_contract: NativeContract
    arguments: tuple[CatalogArgument, ...]


class CapabilityGuide(Model):
    """Palette guidance for one capability, derived from the catalog protocols."""

    capability: str
    stage: int
    description: str
    connects_from: tuple[str, ...]
    connects_to: tuple[str, ...]


class CatalogGuide(Model):
    """Capabilities in stage order; ``chain`` is the build order, ``context`` feeders."""

    capabilities: tuple[CapabilityGuide, ...]
    chain: tuple[str, ...]
    context: tuple[str, ...]


class NodeCatalog(Model):
    entries: tuple[CatalogEntry, ...]
    guide: CatalogGuide


class NodeDraftRequest(Model):
    expected_sha256: Digest
    proposal: AddNodeProposal


class NodeDraftView(Model):
    """Inert inspection of a pending node; ``ports`` use the ordinary inventory shape."""

    proposal: AddNodeProposal
    status: Literal["incomplete", "invalid", "complete"]
    diagnostics: tuple[str, ...] = ()
    ports: tuple[PortInventoryEntry, ...]


class NodeDraftsRequest(Model):
    expected_sha256: Digest
    proposal: NodeDraftsProposal


class NodeDraftsView(Model):
    """Inert inspection of a multi-node draft.

    ``ports`` cover every node of the projected graph (existing and pending);
    existing sockets show their source in ``proposal.document`` (or the anchor)
    without ``proposal.bindings``, which the browser projects itself. Choices
    include pending results and new externals of the matching contract.
    """

    status: Literal["incomplete", "invalid", "complete"]
    diagnostics: tuple[str, ...] = ()
    problems: tuple[DraftProblem, ...] = ()
    ports: tuple[PortInventoryEntry, ...]


class ExternalInputKind(Model):
    """How a new external input of one catalog contract can be declared.

    ``managed`` means a reusable (v2) workflow may leave the value to candidate
    preparation (``ManagedCandidateBinding``); otherwise the author names a
    project-relative JSON file holding a ``native_type`` value. ``summary`` and
    ``example`` are presentation text only; no location is ever defaulted.
    """

    contract: NativeContract
    managed: bool
    summary: str
    example: str


class ExternalInputCatalog(Model):
    entries: tuple[ExternalInputKind, ...]
