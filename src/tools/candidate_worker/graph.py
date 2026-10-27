"""Serial typed readiness within the existing native candidate worker."""

import traceback
from dataclasses import replace
from pathlib import Path
from typing import cast

from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import local_typed_evidence
from agent.schemas.validator import ValidatorOutput
from workflows.definition.fanout import execution_families
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition

from . import phases
from .fanout_inputs import materialize_fanout
from .graph_evidence import expected_nodes, record_digest
from .graph_models import GraphNodeEvidence, GraphTrace
from .inputs import NativeInputs
from .interpretation import run_interpretation
from .invocation import NativePhase, invocation_from_storage
from .literature_phase import run_literature
from .models import CandidateRunReceipt, CandidateRunRequest


def execute_fanout(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    *,
    iteration: int = 1,
) -> CandidateRunReceipt:
    definition = request.preview.document.definition
    shape = execution_families(definition, request.preview.execution_profile)
    dependencies = dict(shape.predecessors)
    inputs = materialize_fanout(
        request, Path(initial.workspace), composition, config, iteration=iteration
    )
    results: dict[
        str,
        ProposalOutput
        | ImplementorOutput
        | ValidatorOutput
        | LiteratureReviewOutput
        | InterpretationOutput,
    ] = {}
    slots = {item.node_id: item for item in expected_nodes(request, initial, iteration=iteration)}
    evidence: dict[str, GraphNodeEvidence] = {}
    aborted = False
    while len(evidence) < len(definition.nodes):
        for node in definition.nodes:
            if node.id in evidence or not dependencies[node.id].issubset(evidence):
                continue
            item = slots[node.id].model_copy(update={"state": "running", "record_path": None})
            if aborted or any(evidence[key].state != "succeeded" for key in dependencies[node.id]):
                evidence[node.id] = item.model_copy(
                    update={
                        "state": "blocked",
                        "reason": "dependency_not_successful",
                    }
                )
                break
            try:
                if shape.interpretation is not None and node.id == shape.interpretation.proposal:
                    interpreted = results[shape.interpretation.interpretation]
                    assert isinstance(interpreted, InterpretationOutput)
                    inputs.update(
                        materialize_fanout(
                            request,
                            Path(initial.workspace),
                            composition,
                            config,
                            iteration=iteration,
                            interpretation_output=interpreted,
                        )
                    )
                selected = inputs[node.id]
                storage = (
                    selected.storage
                    if isinstance(selected, (LiteratureReviewInput, InterpretationInput))
                    else selected.proposal.storage
                    if node.capability == "proposal"
                    else selected.attempt.storage
                )
                phase = cast(NativePhase, node.capability)
                context = invocation_from_storage(
                    initial, node_id=node.id, phase=phase, storage=storage, iteration=iteration
                )
                if phase == "interpretation":
                    assert isinstance(selected, InterpretationInput)
                    output, path = run_interpretation(context, initial, selected, config)
                elif phase == "literature":
                    assert isinstance(selected, LiteratureReviewInput)
                    output, path = run_literature(context, request, initial, selected)
                elif phase == "proposal":
                    assert isinstance(selected, NativeInputs)
                    if shape.literature is not None:
                        review = results[shape.literature.review]
                        assert isinstance(review, LiteratureReviewOutput)
                        selected = replace(
                            selected,
                            proposal=local_typed_evidence(review, proposal_input=selected.proposal),
                        )
                    output, path = phases.run_proposal(context, request, initial, selected, config)
                else:
                    assert isinstance(selected, NativeInputs)
                    proposal = results[shape.proposal_for(node.id)]
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
