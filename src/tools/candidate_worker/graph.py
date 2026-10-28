"""Serial typed readiness; each dispatched node runs as one unit process (B3-3)."""

import traceback
from pathlib import Path

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.validator import ValidatorOutput
from core.chain_state import ChainState
from workflows.adaptors import AdaptorOutcome
from workflows.definition.fanout import execution_families
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition
from workflows.termination import infrastructure_abort_reason

from . import readiness, route_phase, unit_runner
from .adaptor_phase import body_outcome, execute_adaptor, expected_adaptors, tuning_branch
from .budget import WorkerBudget
from .fanout_inputs import materialize_fanout
from .graph_evidence import expected_nodes, record_digest
from .graph_models import GraphNodeEvidence, GraphRouteEvidence, GraphTrace
from .models import CandidateRunReceipt, CandidateRunRequest
from .training_admission import admit_training
from .unit_dispatch import node_invocation
from .unit_models import NodeOutput


def execute_fanout(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    *,
    iteration: int = 1,
    history: ChainState | None = None,
    budget: WorkerBudget | None = None,
) -> CandidateRunReceipt:
    definition = request.preview.document.definition
    shape = execution_families(definition, request.preview.execution_profile)
    # Before any effect: a route metric mismatch orphans no native record.
    metric = route_phase.admit_route_metric(definition, composition.metric.spec)
    routing = route_phase.node_routing(definition)
    routes: list[GraphRouteEvidence] = []
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
    results: dict[str, NodeOutput] = {}
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
            readiness.readiness_input(
                slots.values(),
                evidence,
                aborted=aborted,
                decisions=tuple(item.decision for item in routes),
                routing=routing,
            )
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
            # Adaptors are pure worker steps, never unit processes (B3-3).
            evidence[decision.next], outcome = execute_adaptor(
                adaptors[decision.next],
                slots[decision.next],
                evidence,
                workspace=Path(initial.workspace),
                iteration=iteration,
                skips=route_phase.skip_citations(evidence, routes, routing),
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
            output, path = unit_runner.unit_output(
                node_invocation(
                    request,
                    initial,
                    composition,
                    config,
                    node_id=node.id,
                    capability=node.capability,
                    slot_storage=item.storage,
                    selected=selected,
                    shape=shape,
                    results=results,
                    iteration=iteration,
                    admitted=admitted,
                    tuning_branch=tuning_branch(shape, outcomes)
                    if node.id == shape.tuning
                    else None,
                    incumbent=None if history is None else history.chain_formal_incumbent_reference,
                    budget=budget,
                )
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
        except Exception as error:
            if not isinstance(error, unit_runner.NodeUnitRaised):
                traceback.print_exc()  # a raising unit already logged its own traceback
            aborted = True
            evidence[node.id] = item.model_copy(
                update={"state": "failed", "reason": "native_failure"}
            )
        # Outside the node's own failure handling: an unevaluable route fails the body.
        routes += route_phase.decide_routes(
            definition, evidence[node.id], metric, iteration=iteration
        )
    trace = GraphTrace(
        nodes=tuple(evidence[node.id] for node in definition.nodes),
        adaptors=tuple(evidence[adaptor.id] for adaptor in definition.adaptors),
        routes=route_phase.declared_order(definition, routes),
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
