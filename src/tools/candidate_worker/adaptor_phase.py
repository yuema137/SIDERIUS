"""Execute and verify declared deterministic adaptors inside one graph body (B6-3).

The strategy itself is the pure ``workflows.adaptors`` core. This module only
builds its typed items from verified native records, publishes the adaptor's own
write-once record and output values, and recomputes both for the verifier.
Worker and verifier call the same ``decide``, so they cannot drift.
"""

import hashlib
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from core.canonical_json import canonical_json_bytes
from core.durable_io import publish_bytes_write_once
from workflows.adaptors import (
    AdaptorInputRef,
    AdaptorItem,
    AdaptorOutcome,
    AdaptorRecord,
    build_adaptor_record,
    run_deterministic_adaptor,
)
from workflows.adaptors.record import PORT
from workflows.adaptors.run import AdaptorReason
from workflows.custom_adaptors.contracts import native_type
from workflows.definition import (
    AdaptorInstance,
    AdaptorRequest,
    AdaptorSource,
    ProtocolRequest,
    ResultSource,
    ReusableWorkflowDefinition,
    WorkflowDefinition,
)
from workflows.definition.catalog import VALIDITY_GATED_CONTRACTS
from workflows.definition.fanout import ProposalFamilies, execution_families
from workflows.definition.llm_strategies import LLM_STRATEGY_TYPES

from . import readiness
from .graph_evidence import read_graph_control, record_digest
from .graph_models import GraphNodeEvidence, GraphReason, GraphState, GraphTrace
from .layout import adaptor_dir, adaptor_output_path, adaptor_record_path
from .models import CandidateRunReceipt, CandidateRunRequest

if TYPE_CHECKING:
    from .adaptor_llm import JudgeAdaptorContext

AdaptorDefinition = WorkflowDefinition | ReusableWorkflowDefinition


class SkippedAdaptorInputError(ValueError):
    """A skipped source reached an adaptor, but no skip record exists to cite.

    Unreachable for route skips: routed execution (B1-PR5) cites the deciding
    route evidence (``route_phase.skip_citations``). A skip with another reason
    (``insufficient_items``, a non-emitted adaptor output index) still needs its own
    record before it may reach an adaptor; no admitted profile binds one.
    """


def expected_adaptors(
    request: CandidateRunRequest, initial: CandidateRunReceipt, *, iteration: int = 1
) -> tuple[GraphNodeEvidence, ...]:
    """One pending trace slot per declared adaptor, in declaration order."""
    definition = request.preview.document.definition
    if not definition.adaptors:
        return ()
    shape = execution_families(definition, request.preview.execution_profile)
    predecessors = dict(shape.predecessors)
    workspace = Path(initial.workspace)
    return tuple(
        GraphNodeEvidence(
            node_id=adaptor.id,
            capability="adaptor",
            predecessors=tuple(sorted(predecessors[adaptor.id])),
            storage=str(adaptor_dir(workspace, iteration=iteration)),
            state="pending",
            record_path=str(adaptor_record_path(workspace, adaptor.id, iteration=iteration)),
        )
        for adaptor in definition.adaptors
    )


def adaptor_items(
    adaptor: AdaptorInstance,
    entries: Mapping[str, GraphNodeEvidence],
    skips: Mapping[str, str] | None = None,
) -> tuple[AdaptorItem, ...]:
    """Typed items in declared order (port order, then binding position).

    Completion order never enters: the tuple follows the declaration, and a
    succeeded value is re-read from its digest-checked native record, so the
    worker and the verifier see the same bytes. A route-skipped source cites its
    skip record digest from ``skips`` (``route_phase.skip_citations``).
    """
    citations = skips or {}
    bindings = {binding.port: binding for binding in adaptor.bindings}
    items = []
    for port in adaptor.inputs:
        for position, source in enumerate(bindings[port.name].sources):
            if not isinstance(source, ResultSource):
                raise ValueError(f"adaptor {adaptor.id}: only result sources are executable")
            entry = entries[source.node]
            if entry.state == "skipped" and source.node in citations:
                items.append(
                    AdaptorItem(
                        ref=AdaptorInputRef(
                            port=port.name,
                            position=position,
                            source=source,
                            record_sha256=citations[source.node],
                        ),
                        contract=port.contract,
                        state="skipped",
                        value=None,
                    )
                )
                continue
            if entry.state == "skipped":
                raise SkippedAdaptorInputError(
                    f"adaptor {adaptor.id}: input {source.node} was skipped; skipped adaptor "
                    "inputs need a skip record to cite"
                )
            if (
                entry.state not in ("succeeded", "rejected")
                or entry.record_path is None
                or entry.record_sha256 is None
            ):
                raise ValueError(f"adaptor {adaptor.id}: input {source.node} has no native record")
            # Rejected sources are read too: their state must be the record's verdict.
            value = _native_value(port.contract, entry)
            if entry.state == "rejected":
                if not _rejected_by_record(port.contract, value):
                    raise ValueError(
                        f"adaptor {adaptor.id}: input {source.node} is rejected "
                        "but its native record does not reject it"
                    )
                value = None
            items.append(
                AdaptorItem(
                    ref=AdaptorInputRef(
                        port=port.name,
                        position=position,
                        source=source,
                        record_sha256=entry.record_sha256,
                    ),
                    contract=port.contract,
                    state=entry.state,
                    value=value,
                )
            )
    return tuple(items)


def _native_value(contract: str, entry: GraphNodeEvidence) -> BaseModel:
    assert entry.record_path is not None
    payload = read_graph_control(Path(entry.record_path))
    if hashlib.sha256(payload).hexdigest() != entry.record_sha256:
        raise ValueError(f"native record of {entry.node_id} changed before adaptor admission")
    value_type = native_type(contract)
    if not (isinstance(value_type, type) and issubclass(value_type, BaseModel)):
        raise ValueError(f"contract {contract} has no native record model")
    return value_type.model_validate_json(payload)


def _rejected_by_record(contract: str, value: BaseModel) -> bool:
    """Only a validity-gated record can carry a rejection (``passed=False``)."""
    if contract not in VALIDITY_GATED_CONTRACTS:
        return False
    return getattr(value, "passed", True) is False


def decide(
    adaptor: AdaptorInstance,
    entries: Mapping[str, GraphNodeEvidence],
    *,
    iteration: int,
    skips: Mapping[str, str] | None = None,
    judge: "JudgeAdaptorContext | None" = None,
) -> tuple[AdaptorOutcome, AdaptorRecord]:
    """The adaptor's decision and its record; no metric-ranking kind is admitted.

    A deterministic COMBINE is pure. An LLM COMBINE (B6-8a) runs through
    ``adaptor_llm.decide_llm`` with ``judge``: the worker's context runs the strategy,
    the verifier's replays it from the recorded anchor.
    """
    items = adaptor_items(adaptor, entries, skips)
    combine = adaptor.combine
    if isinstance(combine, LLM_STRATEGY_TYPES):
        if judge is None:
            raise ValueError(f"adaptor {adaptor.id}: an LLM COMBINE requires the judge context")
        from .adaptor_llm import decide_llm

        return decide_llm(adaptor, items, iteration=iteration, context=judge)
    outcome = run_deterministic_adaptor(
        items,
        combine_strategy=combine,
        select_strategy=adaptor.select,
        distribute_strategy=adaptor.distribute,
        metric=None,
    )
    record = build_adaptor_record(
        adaptor_id=adaptor.id,
        iteration=iteration,
        combine=combine,
        select=adaptor.select,
        distribute=adaptor.distribute,
        outcome=outcome,
    )
    return outcome, record


def graph_closure(outcome: AdaptorOutcome) -> tuple[GraphState, GraphReason | None]:
    """The trace state and reason of a decided adaptor."""
    return outcome.status, _graph_reason(outcome.reason)


def _graph_reason(reason: AdaptorReason | None) -> GraphReason | None:
    match reason:
        case (
            None | "no_admissible_input" | "insufficient_items" | "too_many_items" | "judge_failure"
        ):
            return reason
        case _:  # a new AdaptorReason must be mapped to a graph reason explicitly
            raise ValueError(f"adaptor reason {reason!r} has no graph reason")


def _adaptor_sources(definition: AdaptorDefinition) -> tuple[tuple[str, AdaptorSource], ...]:
    """Every (consumer node, adaptor output) data edge, in declaration order."""
    edges: list[tuple[str, AdaptorSource]] = []
    for node in definition.nodes:
        if isinstance(node.request, AdaptorRequest):
            edges.append((node.id, node.request.source))
        elif isinstance(node.request, ProtocolRequest):
            edges.extend(
                (node.id, arg.source)
                for arg in node.request.arguments
                if isinstance(arg.source, AdaptorSource)
            )
    return tuple(edges)


def adaptor_value(outcome: AdaptorOutcome, source: AdaptorSource) -> BaseModel:
    """The emitted value an adaptor source names; a skipped or absent output raises."""
    output = next((item for item in outcome.outputs if item.index == source.index), None)
    if output is None or output.value is None:
        raise ValueError(f"adaptor {source.adaptor} emitted no output at index {source.index}")
    return output.value


def skipped_inputs(
    definition: AdaptorDefinition, outcomes: Mapping[str, AdaptorOutcome]
) -> dict[str, GraphReason]:
    """Consumers of an output index a succeeded adaptor skipped (per-index skip).

    The pure core skips an index only for a shortfall, so the reason is
    ``insufficient_items``; readiness closes the consumer ``skipped`` with it and
    generic skip propagation carries it to the consumer's dependants.
    """
    skipped: dict[str, GraphReason] = {}
    for node_id, source in _adaptor_sources(definition):
        outcome = outcomes.get(source.adaptor)
        if outcome is None or outcome.status != "succeeded":
            continue  # a non-succeeded adaptor blocks its consumers instead
        if any(item.index == source.index and item.status == "skipped" for item in outcome.outputs):
            skipped[node_id] = "insufficient_items"
    return skipped


def execute_adaptor(
    adaptor: AdaptorInstance,
    slot: GraphNodeEvidence,
    entries: Mapping[str, GraphNodeEvidence],
    *,
    workspace: Path,
    iteration: int,
    skips: Mapping[str, str] | None = None,
    judge: "JudgeAdaptorContext | None" = None,
) -> tuple[GraphNodeEvidence, AdaptorOutcome | None]:
    """Decide, publish outputs then the record (write-once), and close the trace slot.

    Any exception is an uncertain failure: the slot fails without a record and
    the caller stops later effects, as for a native node. A skipped input without
    a skip record is a contract gap, never a run outcome, so it propagates.
    """
    try:
        outcome, record = decide(adaptor, entries, iteration=iteration, skips=skips, judge=judge)
        state, reason = graph_closure(outcome)
        adaptor_dir(workspace, iteration=iteration).mkdir(parents=True, exist_ok=True)
        for output in outcome.outputs:
            if output.value is not None:
                path = adaptor_output_path(
                    workspace, adaptor.id, PORT, output.index, iteration=iteration
                )
                publish_bytes_write_once(str(path), canonical_json_bytes(output.value))
        path = adaptor_record_path(workspace, adaptor.id, iteration=iteration)
        publish_bytes_write_once(str(path), canonical_json_bytes(record))
        closed = slot.model_copy(
            update={
                "state": state,
                "reason": reason,
                "record_path": str(path),
                "record_sha256": record_digest(str(path)),
            }
        )
    except SkippedAdaptorInputError:
        raise
    except Exception:
        traceback.print_exc()
        failed = slot.model_copy(
            update={"state": "failed", "reason": "native_failure", "record_path": None}
        )
        return failed, None
    return closed, outcome


def verify_adaptors(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    nodes: tuple[GraphNodeEvidence, ...],
    adaptors: tuple[GraphNodeEvidence, ...],
    *,
    workspace: Path,
    iteration: int,
    skips: Mapping[str, str] | None = None,
) -> dict[str, AdaptorOutcome]:
    """Recompute every recorded adaptor from the native records it names.

    The record and every emitted output must equal the recomputation byte for
    byte, and the trace closure must equal the recomputed outcome. An LLM COMBINE
    is replayed from the strategy evidence its recorded record anchors (never run):
    readback contacts no provider.
    """
    entries = {item.node_id: item for item in (*nodes, *adaptors)}
    outcomes: dict[str, AdaptorOutcome] = {}
    judge = _replay_context(request, initial, entries)
    for adaptor in request.preview.document.definition.adaptors:
        entry = entries[adaptor.id]
        if entry.record_path is None:
            continue
        outcome, record = decide(adaptor, entries, iteration=iteration, skips=skips, judge=judge)
        if isinstance(adaptor.combine, LLM_STRATEGY_TYPES) and record.strategy_evidence is None:
            from .adaptor_llm import judge_evidence_dir

            if judge_evidence_dir(workspace, adaptor.id, iteration).exists():
                raise ValueError(f"adaptor {adaptor.id} has judge evidence its record never ran")
        if read_graph_control(Path(entry.record_path)) != canonical_json_bytes(record):
            raise ValueError(f"adaptor {adaptor.id} record does not match its recomputation")
        if (entry.state, entry.reason) != graph_closure(outcome):
            raise ValueError(f"adaptor {adaptor.id} terminal state does not match its record")
        emitted = set()
        for output in outcome.outputs:
            if output.value is None:
                continue
            path = adaptor_output_path(
                workspace, adaptor.id, PORT, output.index, iteration=iteration
            )
            emitted.add(path.name)
            if read_graph_control(path) != canonical_json_bytes(output.value):
                raise ValueError(f"adaptor {adaptor.id} output does not match its recomputation")
        published = {
            path.name
            for path in adaptor_dir(workspace, iteration=iteration).iterdir()
            if path.name.startswith(f"{adaptor.id}.out.")
        }
        if published != emitted:
            raise ValueError(f"adaptor {adaptor.id} published outputs its record does not derive")
        outcomes[adaptor.id] = outcome
    return outcomes


def _replay_context(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    entries: Mapping[str, GraphNodeEvidence],
) -> "JudgeAdaptorContext | None":
    """Replay context with each recorded LLM adaptor's strategy evidence anchor."""
    from .adaptor_llm import llm_adaptors, replay_context

    anchors: dict[str, str] = {}
    for adaptor in llm_adaptors(request.preview.document.definition.adaptors):
        path = entries[adaptor.id].record_path
        if path is None:
            continue
        recorded = AdaptorRecord.model_validate_json(read_graph_control(Path(path)))
        if recorded.strategy_evidence is not None:
            anchors[adaptor.id] = recorded.strategy_evidence.sha256
    return replay_context(request, initial, anchors)


def judged_proposal(
    shape: ProposalFamilies, outcomes: Mapping[str, AdaptorOutcome], node_id: str
) -> tuple[BaseModel, str] | None:
    """B6-8b: (proposal value, owning proposal node) a judged branch node consumes.

    The value is the adaptor output its branch reads; the owner is the first input
    that output cites (the ranked proposal, or a synthesized value's first parent),
    whose seed supplies the branch's task facts. ``None`` outside a judged branch.
    """
    source = shape.judged_source(node_id)
    if source is None:
        return None
    outcome = outcomes[source.adaptor]
    output = next(item for item in outcome.outputs if item.index == source.index)
    owner = output.inputs[0].source
    if not isinstance(owner, ResultSource):
        raise ValueError("a judged branch's proposal has no producing node")
    return adaptor_value(outcome, source), owner.node


def tuning_branch(
    shape: ProposalFamilies, outcomes: Mapping[str, AdaptorOutcome]
) -> tuple[str, str]:
    """The (implementation, validation) pair the tuner trains.

    Without a selection adaptor the profile has one branch; with one, the branch
    whose validator the adaptor emitted (its contribution, never a re-derivation).
    """
    if shape.selection is None:
        return shape.branches[0]
    outcome = outcomes.get(shape.selection.adaptor)
    if outcome is None or len(outcome.outputs) != 1:
        raise ValueError("training requires exactly one selected validation result")
    source = outcome.outputs[0].inputs[0].source
    if not isinstance(source, ResultSource):
        raise ValueError("the selected validation result has no producing node")
    return next(branch for branch in shape.branches if branch[1] == source.node)


def body_outcome(
    shape: ProposalFamilies, definition: AdaptorDefinition, trace: GraphTrace
) -> tuple[readiness.BodyStatus, bool]:
    """Body status and ``validation_passed``, shared by the worker and the verifier.

    A rejection a succeeded adaptor absorbed is neutral, like a skip: it was an
    inadmissible input, not the body's outcome. Under a selection adaptor,
    ``validation_passed`` is the selected candidate's validation, i.e. whether the
    adaptor selected one. Every node keeps its own state in the trace.
    """
    entries = (*trace.nodes, *trace.adaptors)
    absorbed = {
        source.node
        for adaptor, item in zip(definition.adaptors, trace.adaptors, strict=True)
        if item.state == "succeeded"
        for binding in adaptor.bindings
        for source in binding.sources
        if isinstance(source, ResultSource)
    }
    status = readiness.body_status(
        (
            item.state
            for item in entries
            if not (item.state == "rejected" and item.node_id in absorbed)
        ),
        tuning=shape.tuning is not None,
    )
    if shape.selection is not None:
        selected = next(item for item in trace.adaptors if item.node_id == shape.selection.adaptor)
        return status, selected.state == "succeeded"
    if shape.tuning is None:
        return status, status == "accepted"
    passed = all(
        item.state == "succeeded" for item in trace.nodes if item.capability == "validation"
    )
    return status, passed
