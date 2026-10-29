"""Native phase calls; fixed sequencing and receipt decisions remain in native."""

from pathlib import Path

from agent.schemas.implementor import ImplementorOutput, ImplementorTaskBlocks
from agent.schemas.proposal import ProposalOutput
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.validator import ValidatorOutput
from core.durable_io import publish_bytes_write_once
from core.generated_artifact_name import validate_generated_artifact_name
from nodes.ml_code_validator_agent.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import MLModelProposalAgent
from workflows.candidate_requests import enrich_implementation_request, enrich_validation_request
from workflows.llm_config import WorkflowLLMConfig

from .artifacts import capture_record, verify_artifacts
from .budget import WorkerBudget
from .inputs import NativeInputs
from .invocation import FixedInvocationContext
from .layout import proposal_input_path
from .models import CandidateRunReceipt, CandidateRunRequest
from .record_json import artifact_json


def run_proposal(
    context: FixedInvocationContext,
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    inputs: NativeInputs,
    config: WorkflowLLMConfig,
) -> tuple[ProposalOutput, Path]:
    """Publish the seed, invoke the native proposer, then reconcile its record."""
    context.require_binding(request, initial, inputs, "proposal")
    seed = inputs.proposal
    assert seed.storage.local is not None and seed.task_composition_ref is not None
    proposal_dir = Path(context.storage_workspace)
    proposal_dir.mkdir(parents=True, exist_ok=True)
    input_path = proposal_input_path(
        Path(context.workspace),
        request.preview.execution_profile,
        context.node_id,
        iteration=context.iteration,
    )
    input_path.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes_write_once(
        str(input_path),
        artifact_json(seed, kind="internal", indent=2),
    )

    proposer = MLModelProposalAgent(**config.get("propose"))
    context.bind(proposer)
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
    proposal_path = proposal_dir / f"proposal_{context.run_name}.json"
    capture_record(proposal_path, proposal)
    return proposal, proposal_path


def run_implementation(
    context: FixedInvocationContext,
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    inputs: NativeInputs,
    config: WorkflowLLMConfig,
    proposal: ProposalOutput,
    implementor_blocks: ImplementorTaskBlocks | None,
) -> tuple[ImplementorOutput, Path]:
    """Map and enrich the proposal; invoke and verify the native implementation."""
    context.require_binding(request, initial, inputs, "implementation")
    seed, attempt = inputs.proposal, inputs.attempt
    assert seed.task_composition_ref is not None
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
    context.bind(implementor)
    implemented = implementor.run(implementation)
    verify_artifacts(implemented, attempt, request.read_only, seed.task_composition_ref)
    implementation_path = Path(attempt.impl_dir) / f"implementor_{context.run_name}.json"
    capture_record(implementation_path, implemented)
    return implemented, implementation_path


def run_validation(
    context: FixedInvocationContext,
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    inputs: NativeInputs,
    config: WorkflowLLMConfig,
    proposal: ProposalOutput,
    implemented: ImplementorOutput,
    *,
    budget: WorkerBudget | None = None,
) -> tuple[ValidatorOutput, Path]:
    """Map implementation and lineage; invoke and reconcile native validation.

    The validator's pytest child is bounded by what remains of ``budget``
    (issue #984); without one it stays group-supervised but undeadlined.
    """
    context.require_binding(request, initial, inputs, "validation")
    seed, attempt = inputs.proposal, inputs.attempt
    if request.preview.execution_profile is not None:
        from workflows.candidate_validation_join import proposed_implementation_to_validation

        assert seed.task_composition_ref is not None
        verify_artifacts(implemented, attempt, request.read_only, seed.task_composition_ref)
        validation = proposed_implementation_to_validation(
            proposal,
            implemented,
            attempt.storage,
            inputs.validator_provider,
            inputs.validator_model,
            constraint_context=seed.constraint_context,
            human_advice=request.validation_advice,
        )
    else:
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
    context.bind(validator)
    validated = validator.run(
        validation,
        test_limit=budget.pytest_limit() if budget is not None else None,
    )
    validation_path = Path(attempt.impl_dir) / f"validation_{context.run_name}.json"
    capture_record(validation_path, validated)
    return validated, validation_path
