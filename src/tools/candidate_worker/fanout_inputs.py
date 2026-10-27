"""Materialize declared branch slots through the existing native input owners."""

from pathlib import Path
from typing import TYPE_CHECKING

from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.chain_state import ChainState
from workflows.attempt_storage import impl_attempt_storage
from workflows.definition import ExternalRequest, ExternalSource, ProtocolRequest
from workflows.definition.fanout import execution_families
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition

from .inputs import (
    NativeInputs,
    materialize_proposal,
    reconcile_protocol_inputs,
    validator_settings,
)
from .interpretation import prepare_interpretation
from .layout import candidate_control_dir, graph_instance_dir, proposal_debug_dir
from .literature_inputs import materialize_literature
from .models import CandidateRunRequest

if TYPE_CHECKING:
    from .training_admission import TrainingAdmission


def materialize_fanout(
    request: CandidateRunRequest,
    workspace: Path,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    *,
    iteration: int = 1,
    interpretation_output: InterpretationOutput | None = None,
    admitted: "TrainingAdmission | None" = None,
    history: ChainState | None = None,
) -> dict[str, NativeInputs | LiteratureReviewInput | InterpretationInput]:
    definition = request.preview.document.definition
    shape = execution_families(definition, request.preview.execution_profile)
    nodes = {node.id: node for node in definition.nodes}
    control = candidate_control_dir(workspace, iteration=iteration)
    contents = captured_contents(request, workspace, iteration=iteration)
    provider, model = validator_settings(config)
    externals = {item.id: item for item in definition.externals}
    used: set[str] = set()
    if shape.tuning is not None:
        protocol = nodes[shape.tuning].request
        assert isinstance(protocol, ProtocolRequest)
        used.update(
            arg.source.binding
            for arg in protocol.arguments
            if isinstance(arg.source, ExternalSource)
        )
    result: dict[str, NativeInputs | LiteratureReviewInput | InterpretationInput] = {}
    interpreted_payload = None
    if shape.interpretation is not None:
        edge = shape.interpretation
        selected, arguments = prepare_interpretation(
            request,
            workspace,
            edge,
            contents,
            composition,
            iteration=iteration,
            admitted=admitted,
            history=history,
        )
        result[edge.interpretation] = selected
        used.add(edge.input_binding)
        protocol = nodes[edge.proposal].request
        assert isinstance(protocol, ProtocolRequest)
        used.update(
            arg.source.binding
            for arg in protocol.arguments
            if isinstance(arg.source, ExternalSource)
        )
        if interpretation_output is None:
            declared = used | {
                arg.source.binding
                for node in definition.nodes
                if isinstance(node.request, ProtocolRequest)
                for arg in node.request.arguments
                if isinstance(arg.source, ExternalSource)
            }
            if declared != set(externals):
                raise ValueError("unused external inputs are unsupported by the candidate worker")
            return result
        proposal = arguments.apply(
            interpretation_output, history=history, feedback=selected.recent_formal_validity
        )
        # Composition owns these task facts, as in the fixed native workflow.
        proposal.task_description = composition.task_description
        proposal.forward_contract = composition.forward_contract
        proposal.proposal_blocks = composition.proposal_blocks
        interpreted_payload = proposal.model_dump_json(exclude_unset=True).encode()
    for family in shape.families:
        proposal_request = nodes[family.proposal].request
        if interpreted_payload is not None:
            seed_binding = None
        elif shape.literature is not None:
            seed_binding = shape.literature.seed_binding
        else:
            assert isinstance(proposal_request, ExternalRequest)
            seed_binding = proposal_request.binding
        seed, ref = materialize_proposal(
            interpreted_payload
            if interpreted_payload is not None
            else contents[f"external.{seed_binding}"],
            proposal_storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(
                    workspace=str(
                        graph_instance_dir(
                            workspace, request.run_name, family.proposal, iteration=iteration
                        )
                    ),
                    run_name=request.run_name,
                ),
            ),
            composition=composition,
            admitted=admitted,
            data_root=(Path(request.preview.project_root) / definition.task.data_root).resolve(),
            control=control,
            debug_root=proposal_debug_dir(
                workspace, request.preview.execution_profile, family.proposal, iteration=iteration
            ),
        )
        if seed_binding is not None:
            used.add(seed_binding)
        for implementation, validation in family.branches:
            attempt = impl_attempt_storage(
                str(
                    graph_instance_dir(
                        workspace, request.run_name, implementation, iteration=iteration
                    )
                ),
                request.run_name,
                1,
            )
            protocols = (nodes[implementation].request, nodes[validation].request)
            assert all(isinstance(item, ProtocolRequest) for item in protocols)
            used.update(
                reconcile_protocol_inputs(
                    tuple(item for item in protocols if isinstance(item, ProtocolRequest)),
                    contents=contents,
                    externals=externals,
                    seed=seed,
                    admitted=admitted,
                    ref=ref,
                    attempt=attempt,
                    provider=provider,
                    model=model,
                )
            )
            inputs = NativeInputs(seed, attempt, provider, model)
            result[implementation] = result[validation] = inputs
        result[family.proposal] = result[family.branches[0][0]]
    if shape.literature is not None:
        edge = shape.literature
        candidate = result[edge.proposal]
        assert isinstance(candidate, NativeInputs)
        result[edge.review] = materialize_literature(
            contents[f"external.{edge.review_binding}"],
            request=request,
            workspace=workspace,
            node_id=edge.review,
            seed=candidate.proposal,
            config=config,
            iteration=iteration,
        )
        used.add(edge.review_binding)
    if used != set(externals):
        raise ValueError("unused external inputs are unsupported by the candidate worker")
    return result


def captured_contents(
    request: CandidateRunRequest, workspace: Path, *, iteration: int, verify: bool = False
) -> dict[str, bytes]:
    """Read immutable capture; only a declared loop may rebind managed body slots."""
    import hashlib

    from .graph_evidence import expected_nodes, read_graph_control
    from .models import CandidateRunReceipt

    loop = request.preview.document.definition.loop
    control = candidate_control_dir(workspace, iteration=1 if loop else iteration)
    if loop is None and not verify:
        return {
            item.reference: (control / f"input_{index:03}.snapshot").read_bytes()
            for index, item in enumerate(request.files)
        }
    contents = {}
    for index, observation in enumerate(request.files):
        payload = read_graph_control(control / f"input_{index:03}.snapshot")
        if hashlib.sha256(payload).hexdigest() != observation.sha256:
            raise ValueError("captured input identity changed")
        contents[observation.reference] = payload
    if loop is None or iteration == 1:
        return contents
    initial = CandidateRunReceipt.model_validate_json(read_graph_control(control / "launch.json"))
    before = expected_nodes(request, initial)
    after = expected_nodes(request, initial, iteration=iteration)
    slots = {old.storage: new.storage for old, new in zip(before, after, strict=True)}
    for binding in request.preview.document.definition.externals:
        key = f"external.{binding.id}"
        if binding.contract == "storage":
            value = StorageConfig.model_validate_json(contents[key])
            if value.local is None or value.local.workspace not in slots:
                raise ValueError("loop storage is not an initial managed body slot")
            value.local.workspace = slots[value.local.workspace]
            contents[key] = value.model_dump_json().encode()
    return contents
