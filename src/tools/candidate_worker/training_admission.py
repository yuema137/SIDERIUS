"""Admit one fresh native training run before any candidate node is constructed."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TypedDict, Unpack

from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.ordering import OrderStrategy, resolve_ordering
from agent.schemas.proposal import ProposalInput
from core.durable_io import publish_bytes_write_once
from core.hardware_context import get_or_create as get_hardware_context
from core.hardware_models import HardwareContext
from core.retired_seed_pins import refuse_set_pins
from core.run_invariants import RunInvariants, ensure_run_invariants
from core.run_seed_lock import WorkspaceRunSeed, adopt_bound_run_seed
from core.runtime_control.launch_guard import run_launch_self_test
from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
from core.runtime_control.scheduling import HostBudget
from core.seeding import MissingRunSeed
from execute_tools.dataset_config import DataScope, single_file_mode_refusal
from execute_tools.evaluation_execution import candidate_evaluation_executor
from execute_tools.health_checks.launch_policy import validate_formal_launch
from execute_tools.model_output_retention import require_local_output_inventory
from workflows.candidate_training_settings import (
    CandidateTrainingSettings,
    parse_training_settings,
    proposal_training_values,
    reconcile_constraints,
)
from workflows.constraint_disclosure import workflow_constraint_context
from workflows.definition import ExternalSource, ProtocolRequest
from workflows.llm_config import WorkflowLLMConfig
from workflows.run_bindings import WorkflowRunBindings
from workflows.run_config import (
    WorkflowLaunchConfig,
    active_vram_budget,
    bind_runtime_verifier_launch,
)
from workflows.task_composition import RunTaskComposition, resolve_composed_measurement_capability
from workflows.training_startup import prepare_training_run

from .layout import candidate_control_dir
from .models import CandidateRunReceipt, CandidateRunRequest


@dataclass(frozen=True)
class TrainingAdmission:
    settings: CandidateTrainingSettings
    bindings: WorkflowRunBindings
    constraints: ConstraintContext | None
    node_id: str
    #: The global loop iteration this body trains in (1 outside a loop); with
    #: ``node_id`` it is the tuner's seed scope (issue #983).
    iteration: int
    #: B3-4b — the run's parallel scheduling budget, locked as ``parallel-v1``;
    #: ``None`` for a serial run.
    host_budget: HostBudget | None = None


def admitted_workspace_seed(initial: CandidateRunReceipt) -> WorkspaceRunSeed:
    """The launch receipt's run seed, checked against the workspace lock.

    Raises:
        MissingRunSeed: the receipt predates the seed contract.
        RunInvariantsViolation: the lock records a different seed.
    """
    binding = initial.seed_binding()
    if binding is None:
        raise MissingRunSeed(
            "candidate launch receipt records no run_seed: it predates the seed "
            "contract and cannot train on this build; start a fresh candidate"
        )
    return adopt_bound_run_seed(initial.workspace, binding)


class AdmittedRunFacts(TypedDict):
    """Every binding admission establishes besides the composition and LLM config."""

    workspace: str
    run_name: str
    run_dir: str
    run_id: str | None
    data_scope: DataScope | None
    resolved_data_scope: tuple[int, ...]
    scope_is_partial: bool
    run_invariants: RunInvariants | None
    health_gate_enabled: bool
    health_gate_files: tuple[int, ...] | None
    health_checks_config: str | None
    order_strategy_override: OrderStrategy | None
    file_order_override: tuple[int, ...] | None
    enable_structured_health_feedback: bool
    measurement_capability: ResolvedMeasurementCapability | None
    hardware_context: HardwareContext | None
    active_vram_budget_gb: float | None


def admitted_run_bindings(
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    **admitted: Unpack[AdmittedRunFacts],
) -> WorkflowRunBindings:
    """The candidate worker's one `WorkflowRunBindings` construction.

    Admission supplies the facts it established; a graph unit process rebuilds
    the same admission from its transported facts and its own re-bound
    composition and LLM config (`unit_models.AdmittedTraining.restore`).
    """
    return WorkflowRunBindings(**admitted, task_composition=composition, llm_config=config)


def reconcile_proposal(seed: ProposalInput, admitted: TrainingAdmission) -> ProposalInput:
    """Preserve explicit values, filling only omitted native launch facts."""
    bindings = admitted.bindings
    values = proposal_training_values(admitted.settings)
    values.update(
        data_scope=bindings.data_scope if bindings.data_scope is not None else DataScope.default(),
        enable_structured_health_feedback=bindings.enable_structured_health_feedback,
        vram_budget_gb=bindings.active_vram_budget_gb,
    )
    for name, value in values.items():
        if name in seed.model_fields_set and getattr(seed, name) != value:
            raise ValueError(f"proposal seed {name} disagrees with native training")
    if seed.hardware_context is not None and seed.hardware_context != bindings.hardware_context:
        raise ValueError("proposal seed hardware_context disagrees with actual hardware")
    reconcile_constraints(seed.constraint_context, admitted.constraints)
    values.update(
        hardware_context=bindings.hardware_context, constraint_context=admitted.constraints
    )
    return ProposalInput.model_validate(seed.model_dump() | values)


def refuse_untrainable_launch(
    launch: WorkflowLaunchConfig, composition: RunTaskComposition
) -> None:
    """Launch backstop for the Run review refusal, before any candidate node exists.

    Raises ``ValueError`` when ``is_trial`` is false for a dataset profile without
    TIDMAD topology: every round would be ``single_file`` and none could train.
    """
    reason = single_file_mode_refusal(composition.dataset_profile, is_trial=launch.is_trial)
    if reason is not None:
        raise ValueError(reason)


def admit_training(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    *,
    iteration: int = 1,
    host_budget: HostBudget | None = None,
) -> TrainingAdmission:
    """Resolve actual scope, Health, hardware and measurement using native owners."""
    definition = request.preview.document.definition
    node = next(node for node in definition.nodes if node.capability == "tuning")
    tuning = node.request
    assert isinstance(tuning, ProtocolRequest)
    source = next(arg.source for arg in tuning.arguments if arg.name == "settings")
    assert isinstance(source, ExternalSource)
    binding = next(item for item in definition.externals if item.id == source.binding)
    index = next(
        i for i, item in enumerate(request.files) if item.reference == f"external.{binding.id}"
    )
    control = candidate_control_dir(Path(initial.workspace), iteration=iteration)
    capture = candidate_control_dir(
        Path(initial.workspace), iteration=1 if definition.loop else iteration
    )
    payload = (capture / f"input_{index:03}.snapshot").read_bytes()
    settings = parse_training_settings(payload)
    root = str((Path(request.preview.project_root) / definition.task.data_root).resolve())
    if settings.launch.data_dir is not None and Path(settings.launch.data_dir).resolve() != Path(
        root
    ):
        raise ValueError("training data_dir disagrees with selected physical root")
    health_source = settings.health_checks_config
    if health_source is not None:
        health_source = next(
            item.path for item in request.files if item.reference == "training.health_checks_config"
        )
    launch = bind_runtime_verifier_launch(
        replace(settings.launch, data_dir=root, require_probe_runner=True)
    )
    settings = CandidateTrainingSettings.model_validate_json(
        settings.model_copy(
            update={"launch": launch, "health_checks_config": health_source}
        ).model_dump_json()
    )
    launch = settings.launch
    validate_formal_launch(
        healthgate_mode=launch.healthgate_mode,
        result_authority=launch.result_authority,
        health_checks_config=health_source,
        gates_enabled=launch.enable_chain_incumbent_formal_gates,
        skip_formal_min_delta=launch.skip_formal_min_delta,
        bypass_formal_time_budget_min_delta=launch.bypass_formal_time_budget_min_delta,
        task_health_binding=composition.task_health_binding,
    )
    require_local_output_inventory(
        task=composition.task_data_path,
        composed=True,
        external_evaluation=candidate_evaluation_executor() is not None,
    )
    # Issue #983 — a settings document that recorded a retired pin is readable
    # but never executed. Admission never generates a seed: it executes the one
    # the launch receipt bound, and later bodies find it locked.
    refuse_set_pins(settings.retired_seed_pins, "candidate training settings")
    run_seed = admitted_workspace_seed(initial)
    print(run_seed.log_line(), flush=True)
    preparation = prepare_training_run(
        launch=launch,
        workspace=initial.workspace,
        llm_config=config,
        task_composition=composition,
        run_seed=run_seed,
        host_budget=host_budget,
        **{
            name: getattr(settings, name)
            for name in type(settings).model_fields
            if name not in {"launch", "retired_seed_pins"}
        },
    )
    resolve_ordering(
        resolved_scope=list(preparation.resolved_scope),
        override_strategy=settings.order_strategy_override,
        override_file_order=settings.file_order_override,
    )
    capability = resolve_composed_measurement_capability(composition, dataset_root=root)
    run_launch_self_test(require_probe_runner=launch.require_probe_runner, capability=capability)
    refuse_untrainable_launch(launch, composition)
    ensure_run_invariants(initial.workspace, preparation.invariants)
    hardware = get_hardware_context(Path(initial.workspace), initial.run_name)
    bindings = admitted_run_bindings(
        composition,
        config,
        workspace=initial.workspace,
        run_name=initial.run_name,
        run_id=initial.run_id,
        run_dir=str(Path(initial.workspace) / initial.run_name),
        data_scope=settings.data_scope,
        resolved_data_scope=preparation.resolved_scope,
        scope_is_partial=preparation.scope_is_partial,
        run_invariants=preparation.invariants,
        health_gate_enabled=settings.health_gate_enabled,
        health_gate_files=None
        if settings.health_gate_files is None
        else tuple(settings.health_gate_files),
        health_checks_config=preparation.tuner_health_source,
        order_strategy_override=settings.order_strategy_override,
        file_order_override=None
        if settings.file_order_override is None
        else tuple(settings.file_order_override),
        enable_structured_health_feedback=settings.enable_structured_health_feedback,
        measurement_capability=capability,
        hardware_context=hardware,
        active_vram_budget_gb=active_vram_budget(launch),
    )
    publish_bytes_write_once(
        str(control / "training_settings.json"), settings.model_dump_json(indent=2).encode()
    )
    return TrainingAdmission(
        settings,
        bindings,
        workflow_constraint_context(launch, composition),
        node.id,
        iteration,
        host_budget,
    )
