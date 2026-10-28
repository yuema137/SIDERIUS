"""Derive and verify final graph evidence without importing native node consumers."""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from core.chain_state import ChainState
from core.control_json import JSON_LIMIT, encode_control
from core.file_identity import open_identity_file, regular_file_snapshot
from execute_tools.impl_attempts import impl_attempt_dir
from workflows.definition.fanout import execution_families

from . import readiness
from .graph_models import GraphCapability, GraphNodeEvidence, GraphReason, GraphState, GraphTrace
from .layout import candidate_control_dir, graph_instance_dir
from .models import CandidateRunReceipt, CandidateRunRequest
from .route_eval import RouteEvaluationOutput

if TYPE_CHECKING:
    from workflows.adaptors import AdaptorOutcome


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
            "tuning": "run_output",
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
    from .adaptor_phase import expected_adaptors

    encode_control(request)
    encode_control(initial)
    nodes, adaptors = (
        tuple(
            item.model_copy(
                update={
                    "state": "succeeded",
                    "record_sha256": "f" * 64,
                    "reason": "dependency_not_successful",
                }
            )
            for item in slots
        )
        for slots in (
            expected_nodes(request, initial, iteration=iteration),
            expected_adaptors(request, initial, iteration=iteration),
        )
    )
    encode_control(
        initial.model_copy(
            update={
                "status": "rejected",
                "validation_passed": False,
                "graph_trace": GraphTrace(nodes=nodes, adaptors=adaptors),
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


# Reasons a node closed without a native record may carry, by terminal state.
_UNDISPATCHED_REASONS: dict[GraphState, frozenset[GraphReason]] = {
    "failed": frozenset(("native_failure",)),
    "blocked": frozenset(("dependency_not_successful",)),
    "skipped": readiness.SKIP_REASONS,
}


def replay_readiness(
    nodes: tuple[GraphNodeEvidence, ...],
    *,
    decisions: tuple[RouteEvaluationOutput, ...] = (),
    routing: Mapping[str, readiness.NodeRouting] | None = None,
) -> None:
    """Replay readiness only, never native execution, over recorded terminal states.

    Every node readiness closes must carry exactly the closing state and reason;
    every node it dispatches must have been dispatched (succeeded, rejected or
    failed), so a node run inside a non-selected arm or a skip readiness would not
    produce is refused. Uncertainty (a failure) stops later effects.
    """
    recorded = {item.node_id: item for item in nodes}
    complete: dict[str, GraphNodeEvidence] = {}
    aborted = False
    while len(complete) < len(nodes):
        step = readiness.next_dispatch(
            readiness.readiness_input(
                nodes, complete, aborted=aborted, decisions=decisions, routing=routing
            )
        )
        if step.next is not None:
            item = recorded[step.next]
            valid = item.state in ("succeeded", "rejected", "failed")
        elif step.terminal:
            node_id, state, reason = step.terminal[0]
            item = recorded[node_id]
            valid = (item.state, item.reason) == (state, reason)
        else:
            raise ValueError("graph trace violates serial readiness or failure stop")
        if not valid:
            raise ValueError("graph trace violates serial readiness or failure stop")
        aborted = aborted or item.state == "failed"
        complete[item.node_id] = item


def verify_graph_trace(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    receipt: CandidateRunReceipt,
    *,
    iteration: int = 1,
    history: ChainState | None = None,
) -> None:
    if receipt.loop_trace is not None:
        raise ValueError("one-body graph receipt cannot contain loop aggregate evidence")
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
    from .adaptor_phase import expected_adaptors, verify_adaptors

    expected = expected_nodes(request, initial, iteration=iteration)
    expected_adaptor = expected_adaptors(request, initial, iteration=iteration)
    if len(trace.nodes) != len(expected) or len(trace.adaptors) != len(expected_adaptor):
        raise ValueError("graph trace membership mismatch")
    shape = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    )
    states: dict[str, GraphState] = {
        item.node_id: item.state for item in (*trace.nodes, *trace.adaptors)
    }
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
        native_abort = (
            item.capability == "tuning" and item.state == "failed" and item.record_path is not None
        )
        if item.state in ("succeeded", "rejected") or native_abort:
            if any(states[key] != "succeeded" for key in item.predecessors):
                raise ValueError("graph invocation ran before all predecessors succeeded")
            if (
                item.record_path is None
                or item.record_path != slot.record_path
                or item.record_sha256 != record_digest(item.record_path)
            ):
                raise ValueError("graph native record mismatch")
            if item.reason != (
                "native_failure"
                if native_abort
                else "validation_rejected"
                if item.state == "rejected"
                else None
            ) or (item.state == "rejected" and item.capability != "validation"):
                raise ValueError("graph terminal reason mismatch")
        elif (
            item.record_path is not None
            or item.record_sha256 is not None
            or item.reason not in _UNDISPATCHED_REASONS[item.state]
        ):
            raise ValueError("graph incomplete invocation claims output")
    for item, slot in zip(trace.adaptors, expected_adaptor, strict=True):
        _check_adaptor_entry(item, slot, states)
    replay_readiness((*trace.nodes, *trace.adaptors))
    status = readiness.body_status(states.values(), tuning=shape.tuning is not None)
    if (
        ("blocked" in states.values() and status in ("accepted", "completed"))
        or receipt.status != status
        or receipt.validation_passed
        != (
            all(
                item.state == "succeeded" for item in trace.nodes if item.capability == "validation"
            )
            if shape.tuning
            else status == "accepted"
        )
    ):
        raise ValueError("graph aggregate outcome mismatch")
    if (
        receipt.native_output_paths
        != tuple(item.record_path for item in trace.nodes if item.record_path is not None)
        or receipt.training_output is not None
    ):
        raise ValueError("graph output index mismatch")
    outcomes = verify_adaptors(
        request, trace.nodes, trace.adaptors, workspace=Path(initial.workspace), iteration=iteration
    )
    if shape.tuning is not None:
        verify_graph_training(
            request,
            initial,
            trace,
            iteration=iteration,
            incumbent=None if history is None else history.chain_formal_incumbent_reference,
            outcomes=outcomes,
        )
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
        verify_interpretation_evidence(
            request, initial, trace, iteration=iteration, history=history
        )


def _check_adaptor_entry(
    item: GraphNodeEvidence, slot: GraphNodeEvidence, states: Mapping[str, GraphState]
) -> None:
    """Binding, record and readiness facts of one adaptor entry; its content is recomputed."""
    if (item.node_id, item.capability, item.predecessors, item.storage) != (
        slot.node_id,
        slot.capability,
        slot.predecessors,
        slot.storage,
    ):
        raise ValueError("graph trace binding mismatch")
    if item.state in ("pending", "running"):
        raise ValueError("graph terminal contains unfinished invocation")
    if item.record_path is None:
        if item.record_sha256 is not None or item.reason not in _UNDISPATCHED_REASONS.get(
            item.state, frozenset()
        ):
            raise ValueError("graph incomplete invocation claims output")
        return
    if item.state not in ("succeeded", "rejected", "failed") or any(
        states[key] in ("pending", "running", "failed", "blocked") for key in item.predecessors
    ):
        raise ValueError("graph adaptor ran before its inputs were terminal")
    if item.record_path != slot.record_path or item.record_sha256 != record_digest(
        item.record_path
    ):
        raise ValueError("graph adaptor record mismatch")


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
    history: ChainState | None = None,
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
    from .fanout_inputs import captured_contents

    contents = captured_contents(request, workspace, iteration=iteration, verify=True)
    selected = InterpretationInput.model_validate_json(contents[f"external.{edge.input_binding}"])
    if history is not None and iteration > 1:
        from workflows.research_history import interpretation_history

        selected = selected.model_copy(
            update={
                **interpretation_history(history, selected),
                "iteration": iteration,
                "storage": StorageConfig(
                    backend="local",
                    local=LocalStorageConfig(
                        workspace=nodes[edge.interpretation].storage,
                        run_name=request.run_name,
                    ),
                ),
            }
        )
    actual = InterpretationInput.model_validate_json(
        read_graph_control(
            interpretation_input_path(workspace, edge.interpretation, iteration=iteration)
        )
    )
    shape = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    )
    settings = None
    if shape.tuning is not None:
        from workflows.candidate_training_settings import (
            parse_training_settings,
            reconcile_constraints,
        )

        tuning = next(
            node.request
            for node in request.preview.document.definition.nodes
            if node.id == shape.tuning
        )
        assert isinstance(tuning, ProtocolRequest)
        source = next(arg.source for arg in tuning.arguments if arg.name == "settings")
        from workflows.definition import ExternalSource

        assert isinstance(source, ExternalSource)
        settings = parse_training_settings(contents[f"external.{source.binding}"])
        reconcile_constraints(selected.constraint_context, actual.constraint_context)
        if (
            "enable_structured_health_feedback" in selected.model_fields_set
            and selected.enable_structured_health_feedback
            != settings.enable_structured_health_feedback
        ):
            raise ValueError("interpretation health feedback conflicts with training settings")
        selected = selected.model_copy(
            update={
                "constraint_context": actual.constraint_context,
                "enable_structured_health_feedback": settings.enable_structured_health_feedback,
            }
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
        from tools.workflow_preview.config import parse_config
        from workflows.llm_config import WorkflowLLMConfig

        config = (
            parse_config(contents["llm_config"])
            if "llm_config" in contents
            else WorkflowLLMConfig.default()
        )
        expected = arguments.apply(
            output, config=config, history=history, feedback=selected.recent_formal_validity
        )
        if settings is not None:
            from workflows.candidate_training_settings import (
                proposal_training_values,
                reconcile_constraints,
            )

            reconcile_constraints(arguments.constraint_context, actual.constraint_context)
            values = proposal_training_values(settings)
            for name, value in values.items():
                if name in expected.model_fields_set and getattr(expected, name) != value:
                    raise ValueError(
                        "declared interpretation edge conflicts with training settings"
                    )
            expected = expected.model_copy(
                update=values | {"constraint_context": actual.constraint_context}
            )
        # These task facts are checked by child composition/materialize_proposal.
        # Parent never executes task plugins or infers expectations from child fields.
        composed_fields = {"task_description", "forward_contract", "proposal_blocks"}
        if settings is not None:
            # Child native admission owns actual hardware and full task constraints.
            # Preparation-known launch values and all authored advice remain compared.
            composed_fields.add("hardware_context")
        if (
            proposal.model_dump(exclude=composed_fields)
            != expected.model_dump(exclude=composed_fields)
            or proposal.task_description != selected.task_description
        ):
            raise ValueError("proposal input does not match the declared interpretation edge")


def verify_graph_training(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    trace: GraphTrace,
    *,
    iteration: int,
    incumbent: float | None = None,
    outcomes: "Mapping[str, AdaptorOutcome] | None" = None,
) -> None:
    """Verify native identity/transport without running task plugins or training admission.

    ``outcomes`` are the verified adaptor outcomes; under a selection adaptor the
    trained validation is the one it emitted, otherwise the profile's only branch.
    """
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from agent.schemas.proposal import ProposalInput, ProposalOutput
    from agent.schemas.validator import ValidatorOutput

    from .layout import proposal_input_path, tuning_input_path
    from .training_evidence import NativeOutputIdentity

    shape = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    )
    nodes = {item.node_id: item for item in trace.nodes}
    assert shape.tuning is not None
    tuner = nodes[shape.tuning]
    if tuner.record_path is None:
        if tuner.state == "succeeded":
            raise ValueError("successful tuning lacks native output")
        return
    from .adaptor_phase import tuning_branch

    proposal_path = nodes[shape.families[0].proposal].record_path
    validation_path = nodes[tuning_branch(shape, outcomes or {})[1]].record_path
    assert proposal_path is not None and validation_path is not None
    proposal = ProposalOutput.model_validate_json(Path(proposal_path).read_bytes())
    validation = ValidatorOutput.model_validate_json(Path(validation_path).read_bytes())
    value = HyperparamTuningInput.model_validate_json(
        read_graph_control(
            tuning_input_path(Path(initial.workspace), shape.tuning, iteration=iteration)
        )
    )
    seed = ProposalInput.model_validate_json(
        read_graph_control(
            proposal_input_path(
                Path(initial.workspace),
                request.preview.execution_profile,
                shape.families[0].proposal,
                iteration=iteration,
            )
        )
    )
    output = NativeOutputIdentity.model_validate_json(Path(tuner.record_path).read_bytes())
    if (
        not validation.passed
        or value.storage.local is None
        or value.storage.local.workspace != tuner.storage
        or value.storage.local.run_name != initial.run_name
        or value.model_type != proposal.model_name
        or value.candidate_id != proposal.candidate_id
        or value.task_composition_ref is None
        or value.task_composition_ref != seed.task_composition_ref
        or validation.candidate_id != proposal.candidate_id
        or value.constraint_context != seed.constraint_context
        or value.current_run_best_formal_score != incumbent
        or output.run_name != initial.run_name
        or output.model_type != proposal.model_name
        or output.candidate_id != proposal.candidate_id
        or output.task_composition_fingerprint != value.task_composition_ref.semantic_fingerprint
        or tuner.state
        != ("failed" if output.termination_reason == "infrastructure_abort" else "succeeded")
    ):
        raise ValueError("graph native training identity/termination mismatch")
