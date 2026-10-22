"""The single supported candidate declaration; native payloads remain separate."""

from workflows.definition import (
    ArgumentBinding,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    NodeInstance,
    ProtocolRequest,
    ResultSource,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
)

from .models import CandidatePreparationRequest


def candidate_document(request: CandidatePreparationRequest) -> WorkflowDocument:
    nodes = [
        NodeInstance(id="propose", capability="proposal", request=ExternalRequest(binding="seed"))
    ]
    for name, capability, source, protocol in (
        ("implement", "implementation", "propose", "proposal-to-implementation"),
        ("validate", "validation", "implement", "implementation-to-validation"),
    ):
        nodes.append(
            NodeInstance(
                id=name,
                capability=capability,
                request=ProtocolRequest(
                    protocol=protocol,
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node=source)),
                        ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
                    ),
                ),
            )
        )
    return WorkflowDocument(
        definition=WorkflowDefinition(
            task=TaskReferences(
                manifest=request.task_manifest,
                data_root=request.data_root,
                workspace=request.candidate_workspace,
            ),
            externals=(
                ExternalBinding(id="seed", contract="proposal.input", location="proposal.json"),
                ExternalBinding(id="storage", contract="storage", location="storage.json"),
            ),
            nodes=tuple(nodes),
        )
    )
