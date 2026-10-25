"""Materialize declared branch slots through the existing native input owners."""

from pathlib import Path

from agent.schemas.storage import LocalStorageConfig, StorageConfig
from workflows.attempt_storage import impl_attempt_storage
from workflows.definition import ExternalRequest, ProtocolRequest
from workflows.definition.fanout import proposal_fanout
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition

from .inputs import (
    NativeInputs,
    materialize_proposal,
    reconcile_protocol_inputs,
    validator_settings,
)
from .layout import graph_instance_dir
from .models import CandidateRunRequest


def materialize_fanout(
    request: CandidateRunRequest,
    workspace: Path,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
) -> dict[str, NativeInputs]:
    definition = request.preview.document.definition
    shape = proposal_fanout(definition)
    nodes = {node.id: node for node in definition.nodes}
    proposal_request = nodes[shape.proposal].request
    assert isinstance(proposal_request, ExternalRequest)
    control = workspace / "candidate_run"
    contents = {
        item.reference: (control / f"input_{index:03}.snapshot").read_bytes()
        for index, item in enumerate(request.files)
    }
    seed, ref = materialize_proposal(
        contents[f"external.{proposal_request.binding}"],
        proposal_storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=str(graph_instance_dir(workspace, request.run_name, shape.proposal)),
                run_name=request.run_name,
            ),
        ),
        composition=composition,
        data_root=(Path(request.preview.project_root) / definition.task.data_root).resolve(),
        control=control,
    )
    provider, model = validator_settings(config)
    externals = {item.id: item for item in definition.externals}
    used = {proposal_request.binding}
    result: dict[str, NativeInputs] = {}
    for implementation, validation in shape.branches:
        attempt = impl_attempt_storage(
            str(graph_instance_dir(workspace, request.run_name, implementation)),
            request.run_name,
            1,
        )
        protocols = (nodes[implementation].request, nodes[validation].request)
        assert all(isinstance(item, ProtocolRequest) for item in protocols)
        used.update(
            reconcile_protocol_inputs(
                tuple(item for item in protocols if isinstance(item, ProtocolRequest)),
                contents=contents,
                externals=externals,
                seed=seed,
                ref=ref,
                attempt=attempt,
                provider=provider,
                model=model,
            )
        )
        inputs = NativeInputs(seed, attempt, provider, model)
        result[implementation] = result[validation] = inputs
    if used != set(externals):
        raise ValueError("unused external inputs are unsupported by the candidate worker")
    result[shape.proposal] = result[shape.branches[0][0]]
    return result
