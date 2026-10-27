"""Bounded authoring requests and projections of the existing declaration."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from workflows.definition import AuthoredLoop, AuthoredWorkflowDocument
from workflows.definition.draft import DraftInspection, WorkflowDraft
from workflows.definition.models import Source
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
    """One inert contract name and its catalog-owned native type label."""

    id: str
    native_type: str


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


class SaveView(Model):
    sha256: Digest
    recovery_ids: tuple[str, ...]
    unchanged: bool = False
    version_name: str | None = Field(default=None, exclude_if=lambda value: value is None)
