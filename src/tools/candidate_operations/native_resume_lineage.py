"""Bounded immutable successor traversal; never scans stores or grants cleanup."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from core.native_writer.resume import adoption_name, reservation_name
from core.native_writer.resume_models import ResumeAdoption, ResumeReservation
from core.native_writer.state import WriterState

from .files import JSON_LIMIT, encode, open_file
from .models import (
    Completion,
    OperationRecord,
    OperationStoreConfig,
    ProcessIdentity,
    ProcessObservation,
    SpawnFailure,
)
from .native_chain_models import NativeChainFence, NativeChainTerminal
from .native_chain_read import chain_context, validated_terminal
from .native_resume_models import reservation_for
from .process import observe
from .store import operation_path, validate_record


class ControlBudget:
    def __init__(self):
        # The caller already loaded one <=4 MiB selected record. Charge its full cap.
        self.remaining = 12 * 1024 * 1024

    def read(self, path: Path) -> bytes | None:
        try:
            with open_file(path, private_file=True) as fd:
                limit = min(JSON_LIMIT, self.remaining)
                if os.fstat(fd).st_size > limit:
                    raise ValueError("resume_control_limit")
                raw = os.read(fd, limit + 1)
                if len(raw) > limit:
                    raise ValueError("resume_control_limit")
                self.remaining -= len(raw)
                return raw
        except FileNotFoundError:
            return None


@dataclass(frozen=True)
class ChainNode:
    record: OperationRecord
    process: ProcessObservation
    completion: Completion | None
    completion_digest: str | None
    terminal: NativeChainTerminal | None
    spawn_failure: SpawnFailure | None

    @property
    def id(self) -> UUID:
        return self.record.submission.request_id


def _optional[Model: BaseModel](raw: bytes | None, model: type[Model]) -> Model | None:
    return model.model_validate_json(raw) if raw is not None else None


def load_node(
    config: OperationStoreConfig,
    operation_id: UUID,
    budget: ControlBudget,
    *,
    record: OperationRecord | None = None,
) -> ChainNode:
    path = operation_path(config, operation_id)
    if record is None:
        raw = budget.read(path / "request.json")
        if raw is None:
            raise ValueError("resume_request_missing")
        record = validate_record(config, operation_id, OperationRecord.model_validate_json(raw))
    chain_context(record)
    identity = _optional(budget.read(path / "process.json"), ProcessIdentity)
    raw = budget.read(path / "completion.json")
    completion = _optional(raw, Completion)
    failure = _optional(budget.read(path / "spawn_failure.json"), SpawnFailure)
    for marker in (identity, completion, failure):
        if marker is not None and (
            marker.operation_id != operation_id or marker.request_digest != record.request_digest
        ):
            raise ValueError("resume_marker_identity")
    terminal_raw = budget.read(path / "native-chain-terminal.json")
    if failure is not None and (
        identity is not None or completion is not None or terminal_raw is not None
    ):
        raise ValueError("resume_spawn_failure_contradiction")
    terminal = None
    if completion is not None and completion.outcome == "native_chain":
        if terminal_raw is None:
            raise ValueError("resume_terminal_missing")
        terminal = validated_terminal(record, completion, terminal_raw)
    elif terminal_raw is not None:
        # A child may have published terminal before Completion. It is not trusted yet.
        if completion is not None:
            raise ValueError("resume_terminal_contradiction")
    return ChainNode(
        record,
        observe(identity)
        if identity is not None
        else ProcessObservation(status="unknown", reason="missing_identity"),
        completion,
        hashlib.sha256(raw).hexdigest() if raw is not None else None,
        terminal,
        failure,
    )


@dataclass(frozen=True)
class ChainLineage:
    selected: ChainNode
    nodes: tuple[ChainNode, ...]
    reservations: tuple[ResumeReservation, ...]
    adoptions: tuple[ResumeAdoption | None, ...]

    @property
    def head(self) -> ChainNode:
        return self.nodes[-1]


def require_closed(node: ChainNode, adoption: ResumeAdoption | None) -> None:
    if node.process.status != "exited" or node.completion is None:
        raise ValueError("resume_operation_active_or_unknown")
    if node.terminal is not None:
        supervision = node.terminal.supervision
        if not supervision.direct_child_reaped or supervision.cleanup.final.status != "absent":
            raise ValueError("resume_cleanup_unresolved")
        return
    if (
        node.record.native_resume_admission is None
        or adoption is not None
        or node.completion.outcome != "pre_dispatch_failure"
        or node.completion.reason != "native_resume_spawn_failed"
    ):
        raise ValueError("resume_no_trusted_terminal")


def read_lineage(selected: OperationRecord, *, allow_unlinked: bool = False) -> ChainLineage:
    config = selected.config
    request, admission = chain_context(selected)
    root_id = (
        selected.native_resume_admission.root_operation_id
        if selected.native_resume_admission is not None
        else selected.submission.request_id
    )
    budget = ControlBudget()
    selected_node = load_node(config, selected.submission.request_id, budget, record=selected)
    root = selected_node if root_id == selected_node.id else load_node(config, root_id, budget)
    if root.record.submission.kind != "native_chain" or chain_context(root.record) != (
        request,
        admission,
    ):
        raise ValueError("resume_root_changed")
    fence_raw = budget.read(Path(request.envelope) / ".native-chain-operation/binding.json")
    if fence_raw is None:
        raise ValueError("resume_root_fence_missing")
    fence = NativeChainFence.model_validate_json(fence_raw)
    if fence != NativeChainFence(
        operation_id=root.id,
        request_digest=root.record.request_digest,
        capture_sha256=request.capture_sha256,
        envelope=request.envelope,
    ):
        raise ValueError("resume_root_fence_changed")
    nodes, links, adoptions = [root], [], []
    state = WriterState(Path(admission.workspace), create=False)
    try:
        for _ in range(65):
            raw = state.read_bytes(reservation_name(nodes[-1].id))
            if raw is None:
                break
            if len(links) == 64:
                raise ValueError("resume_lineage_limit")
            require_closed(nodes[-1], adoptions[-1] if adoptions else None)
            value = ResumeReservation.model_validate_json(raw)
            if value.successor_operation_id in {node.id for node in nodes}:
                raise ValueError("resume_lineage_cycle")
            child = (
                selected_node
                if value.successor_operation_id == selected_node.id
                else load_node(config, value.successor_operation_id, budget)
            )
            admitted = child.record.native_resume_admission
            if admitted is None or chain_context(child.record) != (request, admission):
                raise ValueError("resume_child_binding_changed")
            if nodes[-1].terminal is None:
                prior = nodes[-1].record.native_resume_admission
                if prior is None or admitted.owner != prior.owner:
                    raise ValueError("resume_no_child_owner_changed")
            if (
                value
                != reservation_for(
                    admitted, child.id, child.record.native_id, child.record.request_digest
                )
                or value.root_operation_id != root.id
                or value.predecessor_operation_id != nodes[-1].id
                or value.state_root != config.state_root
                or value.store_digest != hashlib.sha256(encode(config)).hexdigest()
                or value.predecessor_completion_digest != nodes[-1].completion_digest
            ):
                raise ValueError("resume_link_changed")
            baseline = next(
                (node for node in nodes if node.id == value.baseline_operation_id), None
            )
            if (
                baseline is None
                or baseline.terminal is None
                or baseline.completion is None
                or (
                    baseline.completion.terminal_digest != value.baseline_terminal_digest
                    or admitted.evidence != baseline.terminal.evidence
                )
            ):
                raise ValueError("resume_baseline_changed")
            adopted = state.read(adoption_name(child.id), ResumeAdoption)
            if adopted is not None and adopted != ResumeAdoption(
                reservation_digest=hashlib.sha256(raw).hexdigest(),
                operation_id=child.id,
                claim_id=child.record.native_id,
            ):
                raise ValueError("resume_adoption_changed")
            nodes.append(child)
            links.append(value)
            adoptions.append(adopted)
        if not allow_unlinked and selected.submission.request_id not in {node.id for node in nodes}:
            raise ValueError("resume_unlinked_operation")
        return ChainLineage(selected_node, tuple(nodes), tuple(links), tuple(adoptions))
    finally:
        state.close()
