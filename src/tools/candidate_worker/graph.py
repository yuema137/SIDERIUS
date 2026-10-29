"""Typed readiness; each dispatched node runs as one unit process (B3-3).

Serial by default. A run with ``CandidateRunRequest.parallel`` and an admitted
host budget dispatches independent units concurrently (``parallel_dispatch``,
B3-4b); both loops share the per-node steps of ``GraphBody``.
"""

import traceback
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.validator import ValidatorOutput
from core.chain_state import ChainState
from core.runtime_control.scheduling import HostBudget
from execute_tools.evaluation_metric import MetricSpec
from workflows.adaptors import AdaptorOutcome
from workflows.definition.fanout import ProposalFamilies, execution_families
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition
from workflows.termination import infrastructure_abort_reason

from . import readiness, route_phase, unit_runner
from .adaptor_llm import JudgeAdaptorContext, judge_adaptor_context
from .adaptor_phase import (
    body_outcome,
    execute_adaptor,
    expected_adaptors,
    judged_proposal,
    skipped_inputs,
    tuning_branch,
)
from .budget import WorkerBudget
from .fanout_inputs import materialize_fanout
from .graph_evidence import expected_nodes, record_digest
from .graph_models import GraphNodeEvidence, GraphRouteEvidence, GraphTrace
from .inputs import NativeInputs
from .loop_models import ResumeAdvice
from .models import CandidateRunReceipt, CandidateRunRequest
from .readiness import NodeRouting
from .training_admission import TrainingAdmission, admit_training
from .unit_dispatch import SelectedInput, node_invocation
from .unit_models import NodeInvocation, NodeOutput


def execute_fanout(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    *,
    iteration: int = 1,
    history: ChainState | None = None,
    budget: WorkerBudget | None = None,
    host_budget: HostBudget | None = None,
    operator_advice: ResumeAdvice | None = None,
) -> CandidateRunReceipt:
    """Run one body; ``host_budget`` is the admitted parallel budget (``None``: serial).

    ``operator_advice`` is the Resume advice of the segment dispatching this body.
    """
    body = GraphBody.admit(
        request,
        initial,
        composition,
        config,
        iteration,
        history,
        budget,
        host_budget,
        operator_advice=operator_advice,
    )
    if host_budget is None:
        dispatch_serial(body)
        return body.terminal()
    from .parallel_dispatch import dispatch_parallel

    dispatch_parallel(body, host_budget)
    return body.terminal(scheduling="parallel-v1")


def dispatch_serial(body: "GraphBody") -> None:
    """Exactly one node at a time, in readiness order (the reference behaviour)."""
    while not body.done():
        node_id = body.next_node()
        if node_id is None:
            continue
        if body.run_adaptor(node_id):
            continue
        item = body.running_item(node_id)
        try:
            output, path = unit_runner.unit_output(body.invocation(node_id))
            body.finish(node_id, item, output, path)
        except Exception as error:
            body.fail(node_id, item, error)
        body.decide_routes(node_id)


@dataclass
class GraphBody:
    """One body's typed state: declared slots, recorded evidence and node results."""

    request: CandidateRunRequest
    initial: CandidateRunReceipt
    composition: RunTaskComposition
    config: WorkflowLLMConfig
    iteration: int
    history: ChainState | None
    budget: WorkerBudget | None
    shape: ProposalFamilies
    metric: MetricSpec | None
    routing: dict[str, NodeRouting]
    admitted: TrainingAdmission | None
    inputs: dict[str, SelectedInput]
    slots: dict[str, GraphNodeEvidence]
    #: LLM COMBINE adaptors' admitted routes, rubrics and judge budget (B6-8a).
    judge: JudgeAdaptorContext | None
    #: The dispatching segment's Resume advice, composed into the proposal input only.
    operator_advice: ResumeAdvice | None = None
    results: dict[str, NodeOutput] = field(default_factory=dict)
    evidence: dict[str, GraphNodeEvidence] = field(default_factory=dict)
    outcomes: dict[str, AdaptorOutcome] = field(default_factory=dict)
    routes: list[GraphRouteEvidence] = field(default_factory=list)
    aborted: bool = False

    @classmethod
    def admit(
        cls,
        request: CandidateRunRequest,
        initial: CandidateRunReceipt,
        composition: RunTaskComposition,
        config: WorkflowLLMConfig,
        iteration: int,
        history: ChainState | None,
        budget: WorkerBudget | None,
        host_budget: HostBudget | None = None,
        *,
        operator_advice: ResumeAdvice | None = None,
    ) -> "GraphBody":
        definition = request.preview.document.definition
        shape = execution_families(definition, request.preview.execution_profile)
        # Before any effect: a route metric mismatch orphans no native record.
        metric = route_phase.admit_route_metric(definition, composition.metric.spec)
        routing = route_phase.node_routing(definition)
        admitted = (
            admit_training(
                request, initial, composition, config, iteration=iteration, host_budget=host_budget
            )
            if shape.tuning
            else None
        )
        # Before any effect: LLM COMBINE adaptors' routes, rubrics, guidance and the run's
        # static judge call sum against max_judge_calls (B6-8a; D3, D4).
        judge = judge_adaptor_context(request, initial, composition.judge_task)
        inputs = materialize_fanout(
            request,
            Path(initial.workspace),
            composition,
            config,
            iteration=iteration,
            admitted=admitted,
            history=history,
        )
        slots = {
            item.node_id: item
            for item in (
                *expected_nodes(request, initial, iteration=iteration),
                *expected_adaptors(request, initial, iteration=iteration),
            )
        }
        return cls(
            request,
            initial,
            composition,
            config,
            iteration,
            history,
            budget,
            shape,
            metric,
            routing,
            admitted,
            inputs,
            slots,
            judge,
            operator_advice,
        )

    @property
    def definition(self):
        return self.request.preview.document.definition

    def done(self) -> bool:
        return len(self.evidence) >= len(self.slots)

    def next_node(self, running: frozenset[str] = frozenset()) -> str | None:
        """Close what readiness closes; return the next dispatchable node, if any.

        ``running`` nodes are already dispatched (parallel mode): readiness sees
        them as ``running``, so it neither returns them nor anything waiting on them.
        """
        decided = dict(self.evidence)
        for node_id in running:
            decided[node_id] = self.running_item(node_id)
        decision = readiness.next_dispatch(
            readiness.readiness_input(
                self.slots.values(),
                decided,
                aborted=self.aborted,
                decisions=tuple(item.decision for item in self.routes),
                routing=self.routing,
                skipped_inputs=skipped_inputs(self.definition, self.outcomes),
            )
        )
        for node_id, state, reason in decision.terminal:
            self.evidence[node_id] = self.slots[node_id].model_copy(
                update={"state": state, "reason": reason, "record_path": None}
            )
        if decision.next is None and not decision.terminal and not running:
            raise RuntimeError("graph readiness found no dispatchable node")
        return decision.next

    def run_adaptor(self, node_id: str) -> bool:
        """Adaptors are pure worker steps, never unit processes (B3-3)."""
        adaptors = {adaptor.id: adaptor for adaptor in self.definition.adaptors}
        if node_id not in adaptors:
            return False
        self.evidence[node_id], outcome = execute_adaptor(
            adaptors[node_id],
            self.slots[node_id],
            self.evidence,
            workspace=Path(self.initial.workspace),
            iteration=self.iteration,
            skips=route_phase.skip_citations(self.evidence, self.routes, self.routing),
            judge=self.judge,
        )
        if outcome is not None:
            self.outcomes[node_id] = outcome
        self.aborted = self.aborted or self.evidence[node_id].state == "failed"
        return True

    def capability(self, node_id: str) -> str:
        return next(node.capability for node in self.definition.nodes if node.id == node_id)

    def running_item(self, node_id: str) -> GraphNodeEvidence:
        return self.slots[node_id].model_copy(update={"state": "running", "record_path": None})

    def invocation(self, node_id: str) -> NodeInvocation:
        """Select the node's typed input from completed predecessors (parent side)."""
        shape = self.shape
        if shape.interpretation is not None and node_id == shape.interpretation.proposal:
            interpreted = self.results[shape.interpretation.interpretation]
            assert isinstance(interpreted, InterpretationOutput)
            self.inputs.update(
                materialize_fanout(
                    self.request,
                    Path(self.initial.workspace),
                    self.composition,
                    self.config,
                    iteration=self.iteration,
                    interpretation_output=interpreted,
                    admitted=self.admitted,
                    history=self.history,
                    operator_advice=self.operator_advice,
                )
            )
        selected = self.inputs[shape.families[0].proposal if node_id == shape.tuning else node_id]
        judged = judged_proposal(shape, self.outcomes, node_id)
        if judged is not None:
            # B6-8b: the branch's task facts come from the selected proposal's seed.
            owner = self.inputs[judged[1]]
            assert isinstance(selected, NativeInputs) and isinstance(owner, NativeInputs)
            selected = replace(selected, proposal=owner.proposal)
        return node_invocation(
            self.request,
            self.initial,
            self.composition,
            self.config,
            node_id=node_id,
            capability=self.capability(node_id),
            slot_storage=self.slots[node_id].storage,
            selected=selected,
            shape=shape,
            results=self.results,
            outcomes=self.outcomes,
            iteration=self.iteration,
            admitted=self.admitted,
            tuning_branch=tuning_branch(shape, self.outcomes) if node_id == shape.tuning else None,
            incumbent=None
            if self.history is None
            else self.history.chain_formal_incumbent_reference,
            budget=self.budget,
        )

    def finish(self, node_id: str, item: GraphNodeEvidence, output: NodeOutput, path: str) -> None:
        rejected = isinstance(output, ValidatorOutput) and not output.passed
        failed = (
            isinstance(output, HyperparamTuningOutput)
            and infrastructure_abort_reason((output,)) is not None
        )
        self.aborted = self.aborted or failed
        self.evidence[node_id] = item.model_copy(
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
        self.results[node_id] = output

    def fail(self, node_id: str, item: GraphNodeEvidence, error: BaseException) -> None:
        if not isinstance(error, unit_runner.NodeUnitRaised):
            traceback.print_exception(error)  # a raising unit already logged its own
        self.aborted = True
        self.evidence[node_id] = item.model_copy(
            update={"state": "failed", "reason": "native_failure"}
        )

    def decide_routes(self, node_id: str) -> None:
        # Outside the node's own failure handling: an unevaluable route fails the body.
        self.routes += route_phase.decide_routes(
            self.definition, self.evidence[node_id], self.metric, iteration=self.iteration
        )

    def terminal(
        self, *, scheduling: Literal["serial", "parallel-v1"] = "serial"
    ) -> CandidateRunReceipt:
        definition = self.definition
        trace = GraphTrace(
            nodes=tuple(self.evidence[node.id] for node in definition.nodes),
            adaptors=tuple(self.evidence[adaptor.id] for adaptor in definition.adaptors),
            routes=route_phase.declared_order(definition, self.routes),
            scheduling=scheduling,
        )
        status, validation_passed = body_outcome(self.shape, definition, trace)
        return self.initial.model_copy(
            update={
                "status": status,
                "graph_trace": trace,
                "native_output_paths": tuple(
                    item.record_path for item in trace.nodes if item.record_path is not None
                ),
                "validation_passed": validation_passed,
            }
        )
