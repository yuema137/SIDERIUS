"""Serial typed readiness within the existing native candidate worker."""

import traceback
from dataclasses import replace
from pathlib import Path
from typing import cast

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import local_typed_evidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import ValidatorOutput
from core.chain_state import ChainState
from workflows.adaptors import AdaptorOutcome
from workflows.definition.fanout import execution_families
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition
from workflows.termination import infrastructure_abort_reason

from . import phases, readiness
from .adaptor_phase import body_outcome, execute_adaptor, expected_adaptors, tuning_branch
from .fanout_inputs import materialize_fanout
from .graph_evidence import expected_nodes, record_digest
from .graph_models import GraphNodeEvidence, GraphTrace
from .inputs import NativeInputs
from .interpretation import run_interpretation
from .invocation import NativePhase, invocation_from_storage
from .layout import tuning_input_path
from .literature_phase import run_literature
from .models import CandidateRunReceipt, CandidateRunRequest
from .training import run_training
from .training_admission import admit_training


def execute_fanout(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    *,
    iteration: int = 1,
    history: ChainState | None = None,
) -> CandidateRunReceipt:
    definition = request.preview.document.definition
    shape = execution_families(definition, request.preview.execution_profile)
    admitted = (
        admit_training(request, initial, composition, config, iteration=iteration)
        if shape.tuning
        else None
    )
    inputs = materialize_fanout(
        request,
        Path(initial.workspace),
        composition,
        config,
        iteration=iteration,
        admitted=admitted,
        history=history,
    )
    results: dict[
        str,
        ProposalOutput
        | ImplementorOutput
        | ValidatorOutput
        | LiteratureReviewOutput
        | InterpretationOutput
        | HyperparamTuningOutput,
    ] = {}
    slots = {
        item.node_id: item
        for item in (
            *expected_nodes(request, initial, iteration=iteration),
            *expected_adaptors(request, initial, iteration=iteration),
        )
    }
    evidence: dict[str, GraphNodeEvidence] = {}
    outcomes: dict[str, AdaptorOutcome] = {}
    aborted = False
    nodes = {node.id: node for node in definition.nodes}
    adaptors = {adaptor.id: adaptor for adaptor in definition.adaptors}
    while len(evidence) < len(slots):
        decision = readiness.next_dispatch(
            readiness.readiness_input(slots.values(), evidence, aborted=aborted)
        )
        for node_id, state, reason in decision.terminal:
            evidence[node_id] = slots[node_id].model_copy(
                update={"state": state, "reason": reason, "record_path": None}
            )
        if decision.next is None:
            if not decision.terminal:
                raise RuntimeError("graph readiness found no dispatchable node")
            continue
        if decision.next in adaptors:
            evidence[decision.next], outcome = execute_adaptor(
                adaptors[decision.next],
                slots[decision.next],
                evidence,
                workspace=Path(initial.workspace),
                iteration=iteration,
            )
            if outcome is not None:
                outcomes[decision.next] = outcome
            aborted = aborted or evidence[decision.next].state == "failed"
            continue
        node = nodes[decision.next]
        item = slots[node.id].model_copy(update={"state": "running", "record_path": None})
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
                        admitted=admitted,
                        history=history,
                    )
                )
            selected = inputs[shape.families[0].proposal if node.id == shape.tuning else node.id]
            if node.id == shape.tuning:
                storage = StorageConfig(
                    backend="local",
                    local=LocalStorageConfig(workspace=item.storage, run_name=initial.run_name),
                )
            elif isinstance(selected, (LiteratureReviewInput, InterpretationInput)):
                storage = selected.storage
            elif node.capability == "proposal":
                storage = selected.proposal.storage
            else:
                storage = selected.attempt.storage
            phase = cast(NativePhase, node.capability)
            context = invocation_from_storage(
                initial, node_id=node.id, phase=phase, storage=storage, iteration=iteration
            )
            if phase == "tuning":
                assert admitted is not None
                context.require_resolved_binding(
                    initial,
                    run_name=request.run_name,
                    node_id=node.id,
                    phase="tuning",
                    storage=storage,
                    implementation_directory="",
                )
                proposal = results[shape.families[0].proposal]
                implementation, validation = (
                    results[key] for key in tuning_branch(shape, outcomes)
                )
                assert isinstance(proposal, ProposalOutput)
                assert isinstance(implementation, ImplementorOutput)
                assert isinstance(validation, ValidatorOutput)
                output, path = run_training(
                    context,
                    proposal,
                    implementation,
                    validation,
                    admitted,
                    storage=storage,
                    chain_formal_incumbent_reference=(
                        None if history is None else history.chain_formal_incumbent_reference
                    ),
                    input_path=tuning_input_path(
                        Path(initial.workspace), node.id, iteration=iteration
                    ),
                )
            elif phase == "interpretation":
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
            failed = (
                isinstance(output, HyperparamTuningOutput)
                and infrastructure_abort_reason((output,)) is not None
            )
            aborted = aborted or failed
            evidence[node.id] = item.model_copy(
                update={
                    "state": "failed" if failed else "rejected" if rejected else "succeeded",
                    "record_path": str(path),
                    "record_sha256": record_digest(str(path)),
                    "reason": "native_failure"
                    if failed
                    else "validation_rejected"
                    if rejected
                    else None,
                }
            )
            results[node.id] = output
        except Exception:
            traceback.print_exc()
            aborted = True
            evidence[node.id] = item.model_copy(
                update={"state": "failed", "reason": "native_failure"}
            )
    trace = GraphTrace(
        nodes=tuple(evidence[node.id] for node in definition.nodes),
        adaptors=tuple(evidence[adaptor.id] for adaptor in definition.adaptors),
    )
    status, validation_passed = body_outcome(shape, definition, trace)
    return initial.model_copy(
        update={
            "status": status,
            "graph_trace": trace,
            "native_output_paths": tuple(
                item.record_path for item in trace.nodes if item.record_path is not None
            ),
            "validation_passed": validation_passed,
        }
    )
