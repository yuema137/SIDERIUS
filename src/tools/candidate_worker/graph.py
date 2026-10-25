"""Serial typed readiness within the existing native candidate worker."""

import traceback
from pathlib import Path
from typing import cast

from agent.schemas.implementor import ImplementorOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.validator import ValidatorOutput
from workflows.definition.fanout import proposal_fanout
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition

from . import phases
from .fanout_inputs import materialize_fanout
from .graph_evidence import record_digest
from .graph_models import GraphCapability, GraphNodeEvidence, GraphTrace
from .invocation import NativePhase, invocation_from_storage
from .models import CandidateRunReceipt, CandidateRunRequest


def execute_fanout(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
) -> CandidateRunReceipt:
    definition = request.preview.document.definition
    shape = proposal_fanout(definition)
    dependencies = dict(shape.predecessors)
    inputs = materialize_fanout(request, Path(initial.workspace), composition, config)
    results: dict[str, ProposalOutput | ImplementorOutput | ValidatorOutput] = {}
    evidence: dict[str, GraphNodeEvidence] = {}
    aborted = False
    while len(evidence) < len(definition.nodes):
        for node in definition.nodes:
            if node.id in evidence or not dependencies[node.id].issubset(evidence):
                continue
            selected = inputs[node.id]
            storage = (
                selected.proposal.storage
                if node.capability == "proposal"
                else selected.attempt.storage
            )
            assert storage.local is not None
            item = GraphNodeEvidence(
                node_id=node.id,
                capability=cast(GraphCapability, node.capability),
                predecessors=tuple(sorted(dependencies[node.id])),
                storage=storage.local.workspace,
                state="running",
            )
            if aborted or any(evidence[key].state != "succeeded" for key in dependencies[node.id]):
                evidence[node.id] = item.model_copy(
                    update={
                        "state": "blocked",
                        "reason": "dependency_not_successful",
                    }
                )
                break
            try:
                phase: NativePhase
                if node.capability == "proposal":
                    phase = "proposal"
                elif node.capability == "implementation":
                    phase = "implementation"
                else:
                    phase = "validation"
                context = invocation_from_storage(
                    initial, node_id=node.id, phase=phase, storage=storage
                )
                if phase == "proposal":
                    output, path = phases.run_proposal(context, request, initial, selected, config)
                else:
                    proposal = results[shape.proposal]
                    assert isinstance(proposal, ProposalOutput)
                    if phase == "implementation":
                        output, path = phases.run_implementation(
                            context,
                            request,
                            initial,
                            selected,
                            config,
                            proposal,
                            composition.implementor_blocks,
                        )
                    else:
                        parent = next(impl for impl, valid in shape.branches if valid == node.id)
                        implemented = results[parent]
                        assert isinstance(implemented, ImplementorOutput)
                        output, path = phases.run_validation(
                            context,
                            request,
                            initial,
                            selected,
                            config,
                            proposal,
                            implemented,
                        )
                rejected = isinstance(output, ValidatorOutput) and not output.passed
                evidence[node.id] = item.model_copy(
                    update={
                        "state": "rejected" if rejected else "succeeded",
                        "record_path": str(path),
                        "record_sha256": record_digest(str(path)),
                        "reason": "validation_rejected" if rejected else None,
                    }
                )
                results[node.id] = output
            except Exception:
                traceback.print_exc()
                aborted = True
                evidence[node.id] = item.model_copy(
                    update={"state": "failed", "reason": "native_failure"}
                )
            break
    trace = GraphTrace(nodes=tuple(evidence[node.id] for node in definition.nodes))
    status = (
        "failed"
        if aborted
        else ("rejected" if any(item.state == "rejected" for item in trace.nodes) else "accepted")
    )
    return initial.model_copy(
        update={
            "status": status,
            "graph_trace": trace,
            "native_output_paths": tuple(
                item.record_path for item in trace.nodes if item.record_path is not None
            ),
            "validation_passed": status == "accepted",
        }
    )
