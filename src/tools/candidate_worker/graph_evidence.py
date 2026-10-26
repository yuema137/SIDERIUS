"""Derive and verify final graph evidence without importing native node consumers."""

import hashlib
from pathlib import Path
from typing import cast

from core.control_json import JSON_LIMIT, encode_control
from core.file_identity import open_identity_file, regular_file_snapshot
from execute_tools.impl_attempts import impl_attempt_dir
from workflows.definition.fanout import execution_families

from .graph_models import GraphCapability, GraphNodeEvidence, GraphTrace
from .layout import graph_instance_dir
from .models import CandidateRunReceipt, CandidateRunRequest


def expected_nodes(
    request: CandidateRunRequest, initial: CandidateRunReceipt
) -> tuple[GraphNodeEvidence, ...]:
    definition = request.preview.document.definition
    shape = execution_families(definition, request.preview.execution_profile)
    parents = {validation: impl for impl, validation in shape.branches}
    predecessors = dict(shape.predecessors)
    evidence = []
    for node in definition.nodes:
        directory = graph_instance_dir(
            Path(initial.workspace), request.run_name, parents.get(node.id, node.id)
        )
        if node.capability != "proposal":
            directory = Path(impl_attempt_dir(str(directory), 1))
        prefix = {
            "proposal": "proposal",
            "implementation": "implementor",
            "validation": "validation",
        }[node.capability]
        evidence.append(
            GraphNodeEvidence(
                node_id=node.id,
                capability=cast(GraphCapability, node.capability),
                predecessors=tuple(sorted(predecessors[node.id])),
                storage=str(directory),
                state="pending",
                record_path=str(directory / f"{prefix}_{request.run_name}.json"),
            )
        )
    return tuple(evidence)


def admit_graph_control(request: CandidateRunRequest, initial: CandidateRunReceipt) -> None:
    """Reserve actual encoded space for every node's largest terminal representation."""
    encode_control(request)
    encode_control(initial)
    nodes = tuple(
        item.model_copy(
            update={
                "state": "succeeded",
                "record_sha256": "f" * 64,
                "reason": "dependency_not_successful",
            }
        )
        for item in expected_nodes(request, initial)
    )
    encode_control(
        initial.model_copy(
            update={
                "status": "rejected",
                "validation_passed": False,
                "graph_trace": GraphTrace(nodes=nodes),
                "native_output_paths": tuple(item.record_path for item in nodes),
                "error": "graph_control_overflow",
            }
        )
    )


def read_graph_control(path: Path) -> bytes:
    with open_identity_file(str(path), require_no_follow=True) as handle:
        if regular_file_snapshot(handle).size > JSON_LIMIT:
            raise ValueError("JSON record exceeds 4 MiB")
        payload = handle.read(JSON_LIMIT + 1)
        if len(payload) > JSON_LIMIT:
            raise ValueError("JSON record exceeds 4 MiB")
        return payload


def record_digest(path: str) -> str:
    """Hash native bytes incrementally; their scientific format has its own owner."""
    with open_identity_file(path, require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        digest = hashlib.sha256()
        while block := handle.read(65536):
            digest.update(block)
        if regular_file_snapshot(handle) != before:
            raise ValueError("native record changed while verifying")
        return digest.hexdigest()


def verify_graph_trace(
    request: CandidateRunRequest, initial: CandidateRunReceipt, receipt: CandidateRunReceipt
) -> None:
    if any(
        value is not None
        for value in (
            receipt.candidate_id,
            receipt.composition_fingerprint,
            receipt.proposal_storage,
            receipt.implementation_storage,
            receipt.training_output,
        )
    ):
        raise ValueError("graph receipt cannot claim fixed scientific output fields")
    trace = receipt.graph_trace
    if trace is None:
        if (
            receipt.status not in ("failed", "interrupted", "timed_out")
            or receipt.native_output_paths
            or receipt.validation_passed is not None
        ):
            raise ValueError("graph receipt lacks terminal trace")
        return
    expected = expected_nodes(request, initial)
    if len(trace.nodes) != len(expected):
        raise ValueError("graph trace membership mismatch")
    states = {item.node_id: item.state for item in trace.nodes}
    for item, slot in zip(trace.nodes, expected, strict=True):
        if (item.node_id, item.capability, item.predecessors, item.storage) != (
            slot.node_id,
            slot.capability,
            slot.predecessors,
            slot.storage,
        ):
            raise ValueError("graph trace binding mismatch")
        if item.state in ("pending", "running"):
            raise ValueError("graph terminal contains unfinished invocation")
        if item.state in ("succeeded", "rejected"):
            if any(states[key] != "succeeded" for key in item.predecessors):
                raise ValueError("graph invocation ran before all predecessors succeeded")
            if (
                item.record_path is None
                or item.record_path != slot.record_path
                or item.record_sha256 != record_digest(item.record_path)
            ):
                raise ValueError("graph native record mismatch")
            if item.reason != ("validation_rejected" if item.state == "rejected" else None) or (
                item.state == "rejected" and item.capability != "validation"
            ):
                raise ValueError("graph terminal reason mismatch")
        elif (
            item.record_path is not None
            or item.record_sha256 is not None
            or item.reason
            != ("native_failure" if item.state == "failed" else "dependency_not_successful")
        ):
            raise ValueError("graph incomplete invocation claims output")
    # Replay readiness only, never native execution: uncertainty stops later effects.
    pending = {item.node_id: item for item in trace.nodes}
    complete: dict[str, str] = {}
    aborted = False
    while pending:
        item = next(item for item in pending.values() if set(item.predecessors).issubset(complete))
        blocked = aborted or any(complete[key] != "succeeded" for key in item.predecessors)
        if (item.state == "blocked") != blocked:
            raise ValueError("graph trace violates serial readiness or failure stop")
        aborted = aborted or item.state == "failed"
        complete[item.node_id] = item.state
        del pending[item.node_id]
    status = (
        "failed"
        if "failed" in states.values()
        else ("rejected" if "rejected" in states.values() else "accepted")
    )
    if (
        ("blocked" in states.values() and status == "accepted")
        or receipt.status != status
        or receipt.validation_passed != (status == "accepted")
    ):
        raise ValueError("graph aggregate outcome mismatch")
    if (
        receipt.native_output_paths
        != tuple(item.record_path for item in trace.nodes if item.record_path is not None)
        or receipt.training_output is not None
    ):
        raise ValueError("graph output index mismatch")
