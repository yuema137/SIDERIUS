"""One validated fresh candidate delegates to the existing native tuner."""

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_core import to_json

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, HyperparamTuningOutput
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import ValidatorOutput
from core.durable_io import publish_bytes_write_once
from core.sandbox_executor import get_loss_dir, get_plugin_dir
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from workflows.candidate_training_settings import CandidateTrainingSettings
from workflows.construction_admission import admit_generated_model_construction
from workflows.plugin_staging import stage_native_plugins
from workflows.termination import infrastructure_abort_reason
from workflows.tuner_preparation import prepare_native_tuner_input

from .artifacts import capture_record
from .invocation import FixedInvocationContext, invocation_from_storage
from .models import CandidateRunReceipt, tuning_seed_scope
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
    chain_formal_incumbent_reference: float | None,
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
        chain_formal_incumbent_reference=chain_formal_incumbent_reference,
        # Issue #983 — the tuner's seed scope: the global loop iteration (which
        # a resumed segment continues) and the authored tuning node.
        seed_coordinates=tuning_seed_scope(admitted.iteration, admitted.node_id),
    )


def execute_training(
    phases: "CandidatePhaseResult", admitted: TrainingAdmission
) -> CandidateRunReceipt:
    """No retry/round engine, capability publication or global promotion here."""
    receipt = phases.receipt
    if not phases.validation.passed:
        return receipt
    assert receipt.proposal_storage is not None
    directory = Path(receipt.proposal_storage).parent / phases.proposal.model_name
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(directory), run_name=receipt.run_name),
    )
    context = invocation_from_storage(
        receipt, node_id=admitted.node_id, phase="tuning", storage=storage
    )
    output, path = run_training(
        context,
        phases.proposal,
        phases.implementation,
        phases.validation,
        admitted,
        storage=storage,
        chain_formal_incumbent_reference=None,
    )
    abort = infrastructure_abort_reason((output,))
    terminal = receipt.model_copy(
        update={
            "status": "failed" if abort else "completed",
            "error": abort,
            "native_output_paths": (*receipt.native_output_paths, str(path)),
        }
    )
    return capture_training_evidence(terminal, phases.proposal.model_name)


def run_training(
    context: FixedInvocationContext,
    proposal: ProposalOutput,
    implementation: ImplementorOutput,
    validation: ValidatorOutput,
    admitted: TrainingAdmission,
    *,
    storage: StorageConfig,
    chain_formal_incumbent_reference: float | None,
    input_path: Path | None = None,
) -> tuple[HyperparamTuningOutput, Path]:
    """Invoke the existing native tuner for an already admitted, validated lineage."""
    bindings = admitted.bindings
    if (context.workspace, context.run_name, context.run_id, context.node_id) != (
        bindings.workspace,
        bindings.run_name,
        bindings.run_id,
        admitted.node_id,
    ):
        raise ValueError("native tuning invocation run binding disagrees")
    if not validation.passed:
        raise ValueError("native training requires successful validation")
    if (
        storage.local is None
        or context.phase != "tuning"
        or context.storage_workspace != storage.local.workspace
        or context.storage_run_name != storage.local.run_name
    ):
        raise ValueError("native tuning invocation storage binding disagrees")
    model_name = proposal.model_name
    if validation.model_type != model_name or implementation.model_type != model_name:
        raise ValueError("validated candidate model identity disagrees with proposal")
    required = [Path(implementation.model_file_path)]
    if implementation.loss_provenance is not None:
        required.append(Path(implementation.loss_provenance.loss_file_path))
    for source in required:
        if not source.is_file():
            raise ValueError(f"native training source is missing: {source}")
        with source.open("rb") as stream:
            stream.read(1)
    admit_generated_model_construction(implementation, model_name)
    assert storage.local is not None
    directory = Path(storage.local.workspace)
    directory.mkdir(parents=True, exist_ok=True)
    stage_native_plugins(
        implementation,
        model_name,
        get_plugin_dir(str(directory), context.run_name),
        dest_loss_dirs=get_loss_dir(str(directory), context.run_name),
    )
    tune_input = prepare_tuning_request(
        validation,
        proposal,
        admitted.settings,
        admitted=admitted,
        storage=storage,
        chain_formal_incumbent_reference=chain_formal_incumbent_reference,
    )
    if input_path is not None:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        # Evidence rereads this file: keep accepted nonfinite values (#1012)
        # instead of the default inf->null; finite documents are unchanged.
        payload = to_json(tune_input.model_dump(mode="json"), indent=2, inf_nan_mode="strings")
        publish_bytes_write_once(str(input_path), payload)
    agent = HyperparamTuningAgent()
    context.bind(agent)
    output = HyperparamTuningOutput.model_validate(agent.run(tune_input))
    path = directory / f"run_output_{context.run_name}.json"
    capture_record(path, output)
    return output, path
