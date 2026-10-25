"""Fresh native candidate sequencing; optional tuning delegates to its native owner."""

from dataclasses import dataclass
from pathlib import Path

from agent.schemas.implementor import ImplementorOutput, ImplementorTaskBlocks
from agent.schemas.proposal import ProposalOutput
from agent.schemas.validator import ValidatorOutput
from tools.workflow_preview.config import parse_config
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

from . import phases
from .inputs import NativeInputs, materialize
from .invocation import fixed_invocations
from .models import CandidateRunReceipt, CandidateRunRequest


@dataclass(frozen=True)
class CandidatePhaseResult:
    proposal: ProposalOutput
    implementation: ImplementorOutput
    validation: ValidatorOutput
    receipt: CandidateRunReceipt


def run_candidate_phases(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    inputs: NativeInputs,
    config: WorkflowLLMConfig,
    implementor_blocks: ImplementorTaskBlocks | None,
) -> CandidatePhaseResult:
    proposal_context, implementation_context, validation_context = fixed_invocations(
        request, initial, inputs
    )
    proposal, proposal_path = phases.run_proposal(
        proposal_context, request, initial, inputs, config
    )
    implemented, implementation_path = phases.run_implementation(
        implementation_context, request, initial, inputs, config, proposal, implementor_blocks
    )
    validated, validation_path = phases.run_validation(
        validation_context, request, initial, inputs, config, proposal, implemented
    )
    seed, attempt = inputs.proposal, inputs.attempt
    assert seed.storage.local is not None and seed.task_composition_ref is not None
    proposal_dir = Path(seed.storage.local.workspace)
    receipt = initial.model_copy(
        update={
            "status": "accepted" if validated.passed else "rejected",
            "validation_passed": validated.passed,
            "candidate_id": proposal.candidate_id,
            "composition_fingerprint": seed.task_composition_ref.semantic_fingerprint,
            "proposal_storage": str(proposal_dir),
            "implementation_storage": attempt.impl_dir,
            "native_output_paths": (
                str(proposal_path),
                str(implementation_path),
                str(validation_path),
            ),
        }
    )

    return CandidatePhaseResult(proposal, implemented, validated, receipt)


def sequence(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    inputs: NativeInputs,
    config: WorkflowLLMConfig,
    implementor_blocks: ImplementorTaskBlocks | None,
) -> CandidateRunReceipt:
    """Preserve the legacy three-stage receipt surface."""
    return run_candidate_phases(request, initial, inputs, config, implementor_blocks).receipt


def execute_native(
    request: CandidateRunRequest, initial: CandidateRunReceipt
) -> CandidateRunReceipt:
    config = WorkflowLLMConfig.default()
    for index, observation in enumerate(request.files):
        if observation.reference == "llm_config":
            config = parse_config(
                (
                    Path(initial.workspace) / "candidate_run" / f"input_{index:03}.snapshot"
                ).read_bytes()
            )
    manifest = next(item.path for item in request.files if item.reference == "task.manifest")
    composition = compose_run_task_bindings(manifest)
    data = (
        Path(request.preview.project_root) / request.preview.document.definition.task.data_root
    ).resolve()
    with bind_run_task_composition(composition, physical_data_root=str(data)):
        if any(node.capability == "tuning" for node in request.preview.document.definition.nodes):
            from .training import execute_training
            from .training_admission import admit_training

            admitted = admit_training(request, initial, composition, config)
            inputs = materialize(request, Path(initial.workspace), composition, config, admitted)
            phases = run_candidate_phases(
                request, initial, inputs, config, composition.implementor_blocks
            )
            return execute_training(phases, admitted)
        inputs = materialize(request, Path(initial.workspace), composition, config)
        return sequence(request, initial, inputs, config, composition.implementor_blocks)
