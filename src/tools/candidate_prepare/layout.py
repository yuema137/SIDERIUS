"""Pure source-owned native destinations; no task composition or publication."""

from pathlib import Path

from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tools.candidate_worker.layout import candidate_proposal_dir, graph_instance_dir
from workflows.attempt_storage import impl_attempt_storage
from workflows.definition import (
    ExternalRequest,
    ExternalSource,
    ProtocolRequest,
    ReusableWorkflowDocument,
)
from workflows.definition.fanout import execution_families
from workflows.definition.models import DeclarationModel


class StorageRecord(DeclarationModel):
    filename: str
    owner: str
    storage: StorageConfig


class ProposalRecord(DeclarationModel):
    """Declared graph owner, or None for the fixed native slot."""

    filename: str
    owner: str | None
    directory: str


class PreparationLayout(DeclarationModel):
    proposal_records: tuple[ProposalRecord, ...]
    storage_records: tuple[StorageRecord, ...]


def storage_filename(implementation: str) -> str:
    """One filename owner for source-derived storage and artifact census."""
    return f"storage.{implementation}.json"


def graph_storage_filenames(document: ReusableWorkflowDocument) -> tuple[str, ...]:
    """Return each generated storage artifact once, in preparation order."""
    shape = execution_families(document.definition, document.execution_profile)
    owners = ((shape.interpretation.proposal,) if shape.interpretation is not None else ()) + tuple(
        implementation for implementation, _ in shape.branches
    )
    return tuple(storage_filename(owner) for owner in owners)


def proposal_filename(profile: str | None, owner: str) -> str:
    return f"proposal.{owner}.json" if profile == "native-proposal-families/v1" else "proposal.json"


def proposal_receipt_path(document: ReusableWorkflowDocument, output: Path) -> str | None:
    """The explicit family profile has an indexed inventory, no singular proposal."""
    return (
        None
        if document.execution_profile == "native-proposal-families/v1"
        else str(output / "proposal.json")
    )


def graph_proposal_bindings(document: ReusableWorkflowDocument) -> dict[str, str]:
    """Every prepared family owns one seed; shared aliases cannot name two files."""
    shape = execution_families(document.definition, document.execution_profile)
    nodes = {node.id: node for node in document.definition.nodes}
    bindings: dict[str, str] = {}
    if shape.interpretation is not None:
        return bindings
    for family in shape.families:
        request = nodes[family.proposal].request
        if shape.literature is not None:
            binding = shape.literature.seed_binding
        else:
            assert isinstance(request, ExternalRequest)
            binding = request.binding
        if binding in bindings:
            raise ValueError("Graph proposal binding is shared across proposal owners")
        bindings[binding] = proposal_filename(document.execution_profile, family.proposal)
    return bindings


def graph_literature_bindings(document: ReusableWorkflowDocument) -> dict[str, str]:
    """The admitted review owns its one generated native input."""
    if document.execution_profile != "native-literature-candidate/v1":
        return {}
    edge = execution_families(document.definition, document.execution_profile).literature
    assert edge is not None
    return {edge.review_binding: f"literature.{edge.review}.json"}


def graph_storage_bindings(document: ReusableWorkflowDocument) -> dict[str, str]:
    """Assign aliases by admitted implementation edges, never node adjacency."""
    shape = execution_families(document.definition, document.execution_profile)
    nodes = {node.id: node for node in document.definition.nodes}
    owners: dict[str, str] = {}
    selected = [(implementation, validator) for implementation, validator in shape.branches]
    if shape.interpretation is not None:
        selected.append((shape.interpretation.proposal, ""))
    for implementation, validator in selected:
        for node_id in (implementation, validator):
            if not node_id:
                continue
            request = nodes[node_id].request
            assert isinstance(request, ProtocolRequest)
            for argument in request.arguments:
                if argument.name != "storage":
                    continue
                if not isinstance(argument.source, ExternalSource):
                    raise ValueError("Graph storage requires a managed external")
                alias = argument.source.binding
                if alias in owners and owners[alias] != implementation:
                    raise ValueError("Graph storage binding is shared across owners")
                owners[alias] = implementation
    return {alias: storage_filename(owner) for alias, owner in owners.items()}


def interpretation_external_bindings(document: ReusableWorkflowDocument) -> dict[str, str]:
    """Name managed protocol payloads generated from the existing native preparation."""
    if document.execution_profile != "native-interpretation-candidate/v1":
        return {}
    shape = execution_families(document.definition, document.execution_profile)
    assert shape.interpretation is not None
    nodes = {node.id: node for node in document.definition.nodes}
    bindings = {
        shape.interpretation.input_binding: f"external.{shape.interpretation.input_binding}.json"
    }
    proposal = nodes[shape.interpretation.proposal]
    assert isinstance(proposal.request, ProtocolRequest)
    for argument in proposal.request.arguments:
        if argument.name == "output" or argument.name == "storage":
            continue
        assert isinstance(argument.source, ExternalSource)
        bindings[argument.source.binding] = f"external.{argument.source.binding}.json"
    return bindings


def preparation_layout(
    document: ReusableWorkflowDocument | None, workspace: Path, run_name: str
) -> PreparationLayout:
    """Use existing native slot owners for fixed and explicitly admitted graph paths."""
    if document is None or document.execution_profile is None:
        proposal = candidate_proposal_dir(workspace, run_name)
        return PreparationLayout(
            proposal_records=(
                ProposalRecord(filename="proposal.json", owner=None, directory=str(proposal)),
            ),
            storage_records=(
                StorageRecord(
                    filename="storage.json",
                    owner="implementation",
                    storage=impl_attempt_storage(str(proposal), run_name, 1).storage,
                ),
            ),
        )
    shape = execution_families(document.definition, document.execution_profile)
    graph_storage_bindings(document)
    graph_proposal_bindings(document)
    proposal_storage = (
        (
            StorageRecord(
                filename=storage_filename(shape.interpretation.proposal),
                owner=shape.interpretation.proposal,
                storage=StorageConfig(
                    backend="local",
                    local=LocalStorageConfig(
                        workspace=str(
                            graph_instance_dir(workspace, run_name, shape.interpretation.proposal)
                        ),
                        run_name=run_name,
                    ),
                ),
            ),
        )
        if shape.interpretation is not None
        else ()
    )
    return PreparationLayout(
        proposal_records=tuple(
            ProposalRecord(
                filename=proposal_filename(document.execution_profile, family.proposal),
                owner=family.proposal,
                directory=str(graph_instance_dir(workspace, run_name, family.proposal)),
            )
            for family in shape.families
        ),
        storage_records=proposal_storage
        + tuple(
            StorageRecord(
                filename=storage_filename(implementation),
                owner=implementation,
                storage=impl_attempt_storage(
                    str(graph_instance_dir(workspace, run_name, implementation)), run_name, 1
                ).storage,
            )
            for implementation, _ in shape.branches
        ),
    )
