"""One validated fresh candidate delegates to the existing native tuner."""

from pathlib import Path
from typing import TYPE_CHECKING

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import ValidatorOutput
from core.sandbox_executor import get_loss_dir, get_plugin_dir
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from workflows.candidate_training_settings import CandidateTrainingSettings
from workflows.construction_admission import admit_generated_model_construction
from workflows.plugin_staging import stage_native_plugins
from workflows.run_context import bind_agent_run_context
from workflows.termination import infrastructure_abort_reason
from workflows.tuner_preparation import prepare_native_tuner_input

from .artifacts import capture_record
from .models import CandidateRunReceipt
from .training_admission import TrainingAdmission
from .training_evidence import capture_training_evidence

if TYPE_CHECKING:
    from .native import CandidatePhaseResult


def prepare_tuning_request(
    validation: ValidatorOutput,
    proposal: ProposalOutput,
    settings: CandidateTrainingSettings,
    *,
    admitted: TrainingAdmission,
    storage: StorageConfig,
) -> HyperparamTuningInput:
    """The closed graph fan-in; runtime bindings remain managed context."""
    if settings is not admitted.settings:
        raise ValueError("tuning settings must be the admitted instance")
    invariants = admitted.bindings.run_invariants
    assert invariants is not None
    return prepare_native_tuner_input(
        validation=validation,
        proposal=proposal,
        storage=storage,
        launch=settings.launch,
        bindings=admitted.bindings,
        run_invariants=invariants,
        constraint_context=admitted.constraints,
        chain_formal_incumbent_reference=None,
    )


def execute_training(
    phases: "CandidatePhaseResult", admitted: TrainingAdmission
) -> CandidateRunReceipt:
    """No retry/round engine, capability publication or global promotion here."""
    receipt = phases.receipt
    if not phases.validation.passed:
        return receipt
    model_name = phases.proposal.model_name
    if phases.validation.model_type != model_name or phases.implementation.model_type != model_name:
        raise ValueError("validated candidate model identity disagrees with proposal")
    required = [Path(phases.implementation.model_file_path)]
    if phases.implementation.loss_provenance is not None:
        required.append(Path(phases.implementation.loss_provenance.loss_file_path))
    for source in required:
        if not source.is_file():
            raise ValueError(f"native training source is missing: {source}")
        with source.open("rb") as stream:
            stream.read(1)
    admit_generated_model_construction(phases.implementation, model_name)
    assert receipt.proposal_storage is not None
    directory = Path(receipt.proposal_storage).parent / model_name
    directory.mkdir(parents=True, exist_ok=True)
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(directory), run_name=receipt.run_name),
    )
    stage_native_plugins(
        phases.implementation,
        model_name,
        get_plugin_dir(str(directory), receipt.run_name),
        dest_loss_dirs=get_loss_dir(str(directory), receipt.run_name),
    )
    tune_input = prepare_tuning_request(
        phases.validation, phases.proposal, admitted.settings, admitted=admitted, storage=storage
    )
    agent = HyperparamTuningAgent()
    bind_agent_run_context(
        agent,
        workspace=receipt.workspace,
        iteration=1,
        run_name=receipt.run_name,
        run_id=receipt.run_id,
    )
    output = agent.run(tune_input)
    path = directory / f"run_output_{receipt.run_name}.json"
    capture_record(path, output)
    abort = infrastructure_abort_reason((output,))
    terminal = receipt.model_copy(
        update={
            "status": "failed" if abort else "completed",
            "error": abort,
            "native_output_paths": (*receipt.native_output_paths, str(path)),
        }
    )
    return capture_training_evidence(terminal, model_name)
