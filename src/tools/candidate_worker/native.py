"""Fresh native candidate sequencing; optional tuning delegates to its native owner."""

from dataclasses import dataclass
from pathlib import Path

from agent.schemas.implementor import ImplementorOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.validator import ValidatorOutput
from core.durable_io import publish_bytes_write_once
from core.generated_artifact_name import validate_generated_artifact_name
from nodes.ml_code_validator_agent.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import MLModelProposalAgent
from tools.workflow_preview.config import parse_config
from workflows.candidate_requests import enrich_implementation_request, enrich_validation_request
from workflows.llm_config import WorkflowLLMConfig
from workflows.run_context import bind_agent_run_context
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

from .artifacts import capture_record, verify_artifacts
from .inputs import NativeInputs, materialize
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
    implementor_blocks,
) -> CandidatePhaseResult:
    seed = inputs.proposal
    attempt = inputs.attempt
    assert seed.storage.local is not None and seed.task_composition_ref is not None
    proposal_dir = Path(seed.storage.local.workspace)
    proposal_dir.mkdir(parents=True, exist_ok=True)
    publish_bytes_write_once(
        str(Path(initial.workspace) / "candidate_run" / "proposal_input.json"),
        seed.model_dump_json(indent=2).encode(),
    )

    def bind(agent) -> None:
        bind_agent_run_context(
            agent,
            workspace=initial.workspace,
            iteration=1,
            run_name=initial.run_name,
            run_id=initial.run_id,
        )

    proposer = MLModelProposalAgent(**config.get("propose"))
    bind(proposer)
    proposal = proposer.run(seed)
    proposal = ProposalOutput.model_validate(
        proposal.model_dump(),
        context={"implementation_bound": True, "allowed_output_types": seed.allowed_output_types},
    )
    validate_generated_artifact_name(proposal.model_name, field="model_name")
    if seed.baseline_isolation:
        from workflows.model_exploration import refuse_builtin_proposal_under_isolation

        refuse_builtin_proposal_under_isolation(proposal, baseline_isolation=True)
    if any(item.source_type == "experiment" for item in proposal.inherited_components):
        raise ValueError("fresh candidate worker cannot restore inherited experiment source")
    proposal_path = proposal_dir / f"proposal_{request.run_name}.json"
    capture_record(proposal_path, proposal)
    implementation = local_full_spec(
        proposal,
        attempt.storage,
        constraint_context=seed.constraint_context,
        task_composition_ref=seed.task_composition_ref,
    )
    implementation.plugin_dir, implementation.test_dir, implementation.loss_dir = (
        attempt.plugin_dir,
        attempt.test_dir,
        attempt.loss_dir,
    )
    enrich_implementation_request(
        implementation,
        task_description=seed.task_description,
        forward_contract=seed.forward_contract,
        implementor_blocks=implementor_blocks,
        hardware_context=seed.hardware_context,
        vram_budget_gb=seed.vram_budget_gb,
        human_advice=request.implementation_advice,
        reference_code={},
        previous_validation_failure=None,
    )
    implementor = MLModelImplementor(**config.get("implement"))
    bind(implementor)
    implemented = implementor.run(implementation)
    verify_artifacts(implemented, attempt, request.read_only, seed.task_composition_ref)
    implementation_path = Path(attempt.impl_dir) / f"implementor_{request.run_name}.json"
    capture_record(implementation_path, implemented)
    validation = local_all_fields(
        implemented,
        attempt.storage,
        inputs.validator_provider,
        inputs.validator_model,
        constraint_context=seed.constraint_context,
    )
    enrich_validation_request(
        validation,
        human_advice=request.validation_advice,
        inherited_components=proposal.inherited_components,
    )
    validator = MLCodeValidatorAgent(**config.get("validate"))
    bind(validator)
    validated = validator.run(validation)
    validation_path = Path(attempt.impl_dir) / f"validation_{request.run_name}.json"
    capture_record(validation_path, validated)
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


def sequence(request, initial, inputs, config, implementor_blocks) -> CandidateRunReceipt:
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
