"""Pure source-owned native destinations; no task composition or publication."""

from pathlib import Path

from agent.schemas.storage import StorageConfig
from tools.candidate_worker.layout import candidate_proposal_dir, graph_instance_dir
from workflows.attempt_storage import impl_attempt_storage
from workflows.definition import ExternalSource, ProtocolRequest, ReusableWorkflowDocument
from workflows.definition.fanout import proposal_fanout
from workflows.definition.models import DeclarationModel


class StorageRecord(DeclarationModel):
    filename: str
    owner: str
    storage: StorageConfig


class PreparationLayout(DeclarationModel):
    proposal_dir: str
    storage_records: tuple[StorageRecord, ...]


def storage_filename(implementation: str) -> str:
    """One filename owner for source-derived storage and artifact census."""
    return f"storage.{implementation}.json"


def graph_storage_bindings(document: ReusableWorkflowDocument) -> dict[str, str]:
    """Assign aliases by admitted implementation edges, never node adjacency."""
    shape = proposal_fanout(document.definition)
    nodes = {node.id: node for node in document.definition.nodes}
    owners: dict[str, str] = {}
    for implementation, validator in shape.branches:
        for node_id in (implementation, validator):
            request = nodes[node_id].request
            assert isinstance(request, ProtocolRequest)
            for argument in request.arguments:
                if argument.name != "storage":
                    continue
                if not isinstance(argument.source, ExternalSource):
                    raise ValueError("Graph storage requires a managed external")
                alias = argument.source.binding
                if alias in owners and owners[alias] != implementation:
                    raise ValueError("Graph storage binding is shared across implementation owners")
                owners[alias] = implementation
    return {alias: storage_filename(owner) for alias, owner in owners.items()}


def preparation_layout(
    document: ReusableWorkflowDocument | None, workspace: Path, run_name: str
) -> PreparationLayout:
    """Use existing native slot owners for fixed and explicitly admitted graph paths."""
    if document is None or document.execution_profile is None:
        proposal = candidate_proposal_dir(workspace, run_name)
        return PreparationLayout(
            proposal_dir=str(proposal),
            storage_records=(
                StorageRecord(
                    filename="storage.json",
                    owner="implementation",
                    storage=impl_attempt_storage(str(proposal), run_name, 1).storage,
                ),
            ),
        )
    shape = proposal_fanout(document.definition)
    graph_storage_bindings(document)
    return PreparationLayout(
        proposal_dir=str(graph_instance_dir(workspace, run_name, shape.proposal)),
        storage_records=tuple(
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
