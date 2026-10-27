"""Derive and verify final graph evidence without importing native node consumers."""

import hashlib
import json
from pathlib import Path
from typing import cast

from core.control_json import JSON_LIMIT, encode_control
from core.file_identity import open_identity_file, regular_file_snapshot
from execute_tools.impl_attempts import impl_attempt_dir
from workflows.definition.fanout import execution_families

from .graph_models import GraphCapability, GraphNodeEvidence, GraphTrace
from .layout import candidate_control_dir, graph_instance_dir
from .models import CandidateRunReceipt, CandidateRunRequest


def expected_nodes(
    request: CandidateRunRequest, initial: CandidateRunReceipt, *, iteration: int = 1
) -> tuple[GraphNodeEvidence, ...]:
    definition = request.preview.document.definition
    shape = execution_families(definition, request.preview.execution_profile)
    parents = {validation: impl for impl, validation in shape.branches}
    predecessors = dict(shape.predecessors)
    evidence = []
    for node in definition.nodes:
        directory = graph_instance_dir(
            Path(initial.workspace),
            request.run_name,
            parents.get(node.id, node.id),
            iteration=iteration,
        )
        if node.capability in ("implementation", "validation"):
            directory = Path(impl_attempt_dir(str(directory), 1))
        prefix = {
            "literature": "ml_literature_review",
            "interpretation": "interpretation",
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


def admit_graph_control(
    request: CandidateRunRequest, initial: CandidateRunReceipt, *, iteration: int = 1
) -> None:
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
        for item in expected_nodes(request, initial, iteration=iteration)
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
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    receipt: CandidateRunReceipt,
    *,
    iteration: int = 1,
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
    expected = expected_nodes(request, initial, iteration=iteration)
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
    if (
        execution_families(
            request.preview.document.definition, request.preview.execution_profile
        ).literature
        is not None
    ):
        verify_literature_evidence(request, initial, trace, iteration=iteration)
    if (
        execution_families(
            request.preview.document.definition, request.preview.execution_profile
        ).interpretation
        is not None
    ):
        verify_interpretation_evidence(request, initial, trace, iteration=iteration)


def verify_literature_evidence(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    trace: GraphTrace,
    *,
    iteration: int = 1,
) -> None:
    """Reconstruct the typed edge from captured source inputs, not child claims."""
    from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput
    from agent.schemas.proposal import ProposalInput
    from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import (
        local_typed_evidence,
    )
    from agent.schemas.storage import LocalStorageConfig, StorageConfig

    from .inputs import require_storage
    from .layout import literature_input_path, proposal_input_path

    edge = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    ).literature
    assert edge is not None
    nodes = {node.node_id: node for node in trace.nodes}
    if nodes[edge.review].state != "succeeded":
        return
    workspace = Path(initial.workspace)

    def captured(binding: str) -> bytes:
        index, observation = next(
            (index, item)
            for index, item in enumerate(request.files)
            if item.reference == f"external.{binding}"
        )
        payload = read_graph_control(
            candidate_control_dir(workspace, iteration=iteration) / f"input_{index:03}.snapshot"
        )
        if hashlib.sha256(payload).hexdigest() != observation.sha256:
            raise ValueError("literature captured input digest mismatch")
        return payload

    selected = LiteratureReviewInput.model_validate_json(captured(edge.review_binding))
    managed = StorageConfig(
        backend="local",
        local=LocalStorageConfig(
            workspace=nodes[edge.review].storage,
            run_name=request.run_name,
        ),
    )
    require_storage(selected.storage, managed)
    selected.storage = managed
    actual = LiteratureReviewInput.model_validate_json(
        read_graph_control(literature_input_path(workspace, edge.review, iteration=iteration))
    )
    seed_payload = json.loads(captured(edge.seed_binding))
    seed_storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(
            workspace=nodes[edge.proposal].storage,
            run_name=request.run_name,
        ),
    )
    seed_payload.setdefault("storage", seed_storage.model_dump(mode="json"))
    seed = ProposalInput.model_validate(seed_payload)
    require_storage(seed.storage, seed_storage)
    seed.storage = seed_storage
    if (
        actual != selected
        or selected.run_name != request.run_name
        or (selected.task_description, selected.constraint_context)
        != (seed.task_description, seed.constraint_context)
    ):
        raise ValueError("literature diagnostic/task binding mismatch")
    path = nodes[edge.review].record_path
    assert path is not None
    with open_identity_file(path, require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        payload = handle.read()
        if (
            regular_file_snapshot(handle) != before
            or hashlib.sha256(payload).hexdigest() != nodes[edge.review].record_sha256
        ):
            raise ValueError("literature native record changed while verifying")
    output = LiteratureReviewOutput.model_validate_json(payload)
    if output.run_name != request.run_name:
        raise ValueError("literature native record run binding mismatch")
    if nodes[edge.proposal].state == "succeeded":
        proposal = ProposalInput.model_validate_json(
            read_graph_control(
                proposal_input_path(
                    workspace, request.preview.execution_profile, edge.proposal, iteration=iteration
                )
            )
        )
        if proposal != local_typed_evidence(output, proposal_input=seed):
            raise ValueError("proposal input does not match the declared literature edge")


def verify_interpretation_evidence(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    trace: GraphTrace,
    *,
    iteration: int = 1,
) -> None:
    """Replay the directed protocol, not task composition or native execution."""
    from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
    from agent.schemas.proposal import ProposalInput
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from workflows.definition import ProtocolRequest

    from .inputs import require_storage
    from .interpretation import read_arguments
    from .layout import interpretation_input_path, proposal_input_path

    edge = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    ).interpretation
    assert edge is not None
    nodes = {item.node_id: item for item in trace.nodes}
    if nodes[edge.interpretation].state != "succeeded":
        return
    workspace = Path(initial.workspace)
    contents = {}
    for index, observation in enumerate(request.files):
        payload = read_graph_control(
            candidate_control_dir(workspace, iteration=iteration) / f"input_{index:03}.snapshot"
        )
        if hashlib.sha256(payload).hexdigest() != observation.sha256:
            raise ValueError("interpretation captured input digest mismatch")
        contents[observation.reference] = payload
    selected = InterpretationInput.model_validate_json(contents[f"external.{edge.input_binding}"])
    actual = InterpretationInput.model_validate_json(
        read_graph_control(
            interpretation_input_path(workspace, edge.interpretation, iteration=iteration)
        )
    )
    if actual != selected or actual.iteration != iteration:
        raise ValueError("interpretation input capture mismatch")
    protocol = next(
        node.request
        for node in request.preview.document.definition.nodes
        if node.id == edge.proposal
    )
    assert isinstance(protocol, ProtocolRequest)
    arguments = read_arguments(protocol, contents)
    for node_id, storage in (
        (edge.interpretation, selected.storage),
        (edge.proposal, arguments.storage),
    ):
        require_storage(
            storage,
            StorageConfig(
                backend="local",
                local=LocalStorageConfig(
                    workspace=nodes[node_id].storage,
                    run_name=request.run_name,
                ),
            ),
        )
    path = nodes[edge.interpretation].record_path
    assert path is not None
    with open_identity_file(path, require_no_follow=True) as handle:
        payload = handle.read()
    if hashlib.sha256(payload).hexdigest() != nodes[edge.interpretation].record_sha256:
        raise ValueError("interpretation record changed while verifying")
    output = InterpretationOutput.model_validate_json(payload)
    if nodes[edge.proposal].state == "succeeded":
        proposal = ProposalInput.model_validate_json(
            read_graph_control(
                proposal_input_path(
                    workspace, request.preview.execution_profile, edge.proposal, iteration=iteration
                )
            )
        )
        expected = arguments.apply(output)
        # These task facts are checked by child composition/materialize_proposal.
        # Parent never executes task plugins or infers expectations from child fields.
        composed_fields = {"task_description", "forward_contract", "proposal_blocks"}
        if (
            proposal.model_dump(exclude=composed_fields)
            != expected.model_dump(exclude=composed_fields)
            or proposal.task_description != selected.task_description
        ):
            raise ValueError("proposal input does not match the declared interpretation edge")
