"""Read-only review projections from the prepared request's pinned native inputs."""

import hashlib
from pathlib import Path

from pydantic import TypeAdapter

from agent.schemas.hyperparam_tuning import TaskCompositionRef
from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.proposal import ProposalInput
from tools.candidate_operations.models import OperationFailure
from tools.candidate_prepare.reusable_admission import safe_bytes
from tools.candidate_worker.models import CandidateRunRequest
from tools.workflow_preview.models import PreviewModel
from workflows.candidate_training_settings import parse_training_settings


class TrainingReview(PreviewModel):
    healthgate_mode: str | None
    trial_time_budget_minutes: float | None
    formal_time_budget_minutes: float | None
    max_epochs: int | None
    trial_max_epochs: int | None
    formal_max_epochs: int | None
    workflow_parameter_rules: ParameterRules | None


class CaptureFacts(PreviewModel):
    training: TrainingReview | None = None
    task_parameter_rules: ParameterRules | None = None


def capture_facts(request: CandidateRunRequest) -> CaptureFacts:
    """Use captured bytes, checking their digest again before projecting them.

    Native schemas resolve defaults. No task plugin is loaded and no current editor
    or console setting can replace the selected preparation's facts.
    """
    training = None
    rules = None
    for binding in request.preview.document.definition.externals:
        if binding.contract not in {
            "proposal.input",
            "native-training.settings",
            "optional.task-composition-ref",
        }:
            continue
        observation = next(
            item for item in request.files if item.reference == f"external.{binding.id}"
        )
        payload = safe_bytes(Path(observation.path))
        if hashlib.sha256(payload).hexdigest() != observation.sha256:
            raise OperationFailure("reusable_preparation", "captured review input changed")
        if binding.contract == "proposal.input":
            proposal = ProposalInput.model_validate_json(payload)
            if proposal.task_composition_ref is not None:
                rules = proposal.task_composition_ref.parameter_rules
        elif binding.contract == "optional.task-composition-ref":
            reference = TypeAdapter(TaskCompositionRef | None).validate_json(payload)
            if reference is not None:
                rules = reference.parameter_rules
        else:
            launch = parse_training_settings(payload).launch
            training = TrainingReview.model_validate(
                {name: getattr(launch, name) for name in TrainingReview.model_fields}
            )
    return CaptureFacts(training=training, task_parameter_rules=rules)
