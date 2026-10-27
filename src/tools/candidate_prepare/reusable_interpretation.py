"""Managed native inputs for the reusable interpretation candidate profile."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent.schemas.interpretation import InterpretationInput
from agent.schemas.proposal import ProposalInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tools.candidate_worker.layout import graph_instance_dir
from workflows.definition import ExternalSource, ProtocolRequest, ReusableWorkflowDocument
from workflows.definition.fanout import execution_families

from .models import CandidatePreparationRequest


def external_payloads(
    document: ReusableWorkflowDocument,
    request: CandidatePreparationRequest,
    interpretation: InterpretationInput,
    proposal: ProposalInput,
) -> tuple[tuple[str, bytes], ...]:
    """Project declared external roles from the existing native preparation owners."""
    if document.execution_profile != "native-interpretation-candidate/v1":
        return ()
    shape = execution_families(document.definition, document.execution_profile)
    assert shape.interpretation is not None
    nodes = {node.id: node for node in document.definition.nodes}
    proposal_node = nodes[shape.interpretation.proposal]
    assert isinstance(proposal_node.request, ProtocolRequest)
    values: dict[str, Any] = {
        "storage": proposal.storage,
        "data_dir": request.data_root,
        "task_composition_ref": proposal.task_composition_ref,
        "human_advice": request.proposal_advice,
        "expert_context": None,
        "constraint_context": proposal.constraint_context,
        "workflow_parameter_rules": proposal.workflow_parameter_rules,
    }
    payloads = [(shape.interpretation.input_binding, interpretation)]
    for argument in proposal_node.request.arguments:
        if argument.name in {"output", "storage"}:
            continue
        assert isinstance(argument.source, ExternalSource)
        payloads.append((argument.source.binding, values[argument.name]))
    from .layout import graph_storage_bindings

    storage_files = graph_storage_bindings(document)
    return tuple(
        (
            storage_files.get(binding, f"external.{binding}.json"),
            (
                value.model_dump_json(indent=2) + "\n"
                if isinstance(value, BaseModel)
                else json.dumps(value, indent=2, ensure_ascii=False) + "\n"
            ).encode(),
        )
        for binding, value in payloads
    )


def verify_payloads(
    document: ReusableWorkflowDocument,
    request: CandidatePreparationRequest,
    output: Path,
    read_bytes: Callable[[Path], bytes],
) -> None:
    """Rebuild generated protocol inputs from retained source and parent capture."""
    if document.execution_profile != "native-interpretation-candidate/v1":
        return
    shape = execution_families(document.definition, document.execution_profile)
    assert shape.interpretation is not None
    interpretation_path = output / "preparation/interpretation_input.json"
    interpretation_bytes = read_bytes(interpretation_path)
    interpretation = InterpretationInput.model_validate_json(interpretation_bytes)
    expected_storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(
            workspace=str(
                graph_instance_dir(
                    Path(request.candidate_workspace),
                    request.run_name,
                    shape.interpretation.interpretation,
                )
            ),
            run_name=request.run_name,
        ),
    )
    if interpretation.storage != expected_storage:
        raise ValueError("interpretation storage differs from selected native destination")
    if interpretation.iteration != 1 or not interpretation.cold_start:
        raise ValueError("reusable interpretation input must be the native cold start")
    input_file = output / f"external.{shape.interpretation.input_binding}.json"
    if read_bytes(input_file) != interpretation_bytes:
        raise ValueError("managed interpretation input differs from prepared native input")
    proposal = ProposalInput.model_validate_json(read_bytes(output / "proposal.json"))
    for filename, expected in external_payloads(document, request, interpretation, proposal):
        if read_bytes(output / filename) != expected:
            raise ValueError("managed protocol input differs from captured native preparation")
