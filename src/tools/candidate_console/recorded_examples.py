"""Read configured candidate records as validation evidence, never live operations."""

from pathlib import Path

from agent.schemas.implementor import ImplementorOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.validator import ValidatorOutput
from execute_tools.impl_attempts import impl_attempt_dir
from tools.candidate_operations.files import read_model
from tools.candidate_operations.models import OperationFailure, OperationStoreConfig
from tools.candidate_worker import CandidateTokenReadRequest, read_candidate_tokens
from tools.candidate_worker.layout import candidate_proposal_dir
from tools.candidate_worker.models import CandidateRunReceipt, CandidateRunRequest
from tools.candidate_worker.records import verify_candidate_records

from .models import RecordedExampleChoice, RecordedExampleView, RecordedStage


def read_recorded_example(
    store: OperationStoreConfig, choice: RecordedExampleChoice
) -> RecordedExampleView:
    """Validate one fixed, allowlisted three-stage candidate record set."""
    workspace = Path(choice.workspace)
    root = next(
        (
            Path(value)
            for value in store.candidate_roots
            if workspace != Path(value) and workspace.is_relative_to(Path(value))
        ),
        None,
    )
    if root is None:
        raise OperationFailure("example_path", "recorded example is unavailable")

    control = workspace / "candidate_run"
    try:
        request = read_model(control / "request.json", CandidateRunRequest)
        initial = read_model(control / "launch.json", CandidateRunReceipt)
        receipt = read_model(control / "receipt.json", CandidateRunReceipt)
    except (OSError, ValueError) as error:
        raise OperationFailure("integrity", "recorded candidate evidence is incomplete") from error

    try:
        declaration_workspace = Path(
            request.preview.project_root,
            request.preview.document.definition.task.workspace,
        ).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise OperationFailure(
            "integrity", "recorded example workspace identity is invalid"
        ) from error
    if receipt.status == "accepted":
        candidate_status = "accepted"
    elif receipt.status == "rejected":
        candidate_status = "rejected"
    else:
        raise OperationFailure(
            "integrity", "recorded example is outside the supported candidate flow"
        )
    candidate_id = receipt.candidate_id
    if (
        declaration_workspace != workspace
        or request.preview.execution_profile is not None
        or tuple(node.capability for node in request.preview.document.definition.nodes)
        != ("proposal", "implementation", "validation")
        or candidate_id is None
        or receipt.validation_passed is None
        or receipt.validation_passed != (candidate_status == "accepted")
        or receipt.training_output is not None
        or receipt.graph_trace is not None
    ):
        raise OperationFailure(
            "integrity", "recorded example is outside the supported candidate flow"
        )

    try:
        verify_candidate_records(
            request,
            initial,
            expected_request=request,
            expected_run_id=choice.expected_run_id,
            workspace=workspace,
            receipt=receipt,
        )
        proposal_dir = candidate_proposal_dir(workspace, request.run_name)
        implementation_dir = Path(impl_attempt_dir(str(proposal_dir), 1))
        expected_paths = (
            proposal_dir / f"proposal_{request.run_name}.json",
            implementation_dir / f"implementor_{request.run_name}.json",
            implementation_dir / f"validation_{request.run_name}.json",
        )
        if tuple(Path(value) for value in receipt.native_output_paths) != expected_paths:
            raise ValueError("candidate output locations differ from the native layout")
        proposal = read_model(expected_paths[0], ProposalOutput)
        implementation = read_model(expected_paths[1], ImplementorOutput)
        validation = read_model(expected_paths[2], ValidatorOutput)
        if (
            proposal.candidate_id != candidate_id
            or implementation.candidate_id != candidate_id
            or validation.candidate_id != candidate_id
            or proposal.model_name != implementation.model_type
            or implementation.model_type != validation.model_type
            or validation.passed != receipt.validation_passed
        ):
            raise ValueError("candidate stage identities do not agree")
        tokens = read_candidate_tokens(
            CandidateTokenReadRequest(
                allowed_workspace_root=str(root),
                workspace=str(workspace),
                expected_run_id=choice.expected_run_id,
            )
        )
    except (OSError, ValueError) as error:
        raise OperationFailure(
            "integrity", "recorded candidate evidence could not be verified"
        ) from error

    return RecordedExampleView(
        example_id=choice.example_id,
        label=choice.label,
        run_id=receipt.run_id,
        candidate_id=candidate_id,
        run_name=receipt.run_name,
        declaration_digest=receipt.declaration_digest,
        declaration=request.preview.document.definition,
        source_snapshot_available=request.workflow_source is not None,
        candidate_status=candidate_status,
        validation_passed=receipt.validation_passed,
        stages=(
            RecordedStage(capability="proposal", model_type=proposal.model_name),
            RecordedStage(capability="implementation", model_type=implementation.model_type),
            RecordedStage(
                capability="validation",
                model_type=validation.model_type,
                passed=validation.passed,
            ),
        ),
        tokens=tokens,
    )
