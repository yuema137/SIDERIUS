"""Admit one fresh native training run before any candidate node is constructed."""

import json
from dataclasses import dataclass, replace
from pathlib import Path

from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.ordering import resolve_ordering
from agent.schemas.proposal import ProposalInput
from agent.utils.proposer_preflight import UNCONSTRAINED_TRAIN_PORTION, UNCONSTRAINED_TRIAL_PORTION
from core.durable_io import publish_bytes_write_once
from core.hardware_context import get_or_create as get_hardware_context
from core.run_invariants import ensure_run_invariants
from core.runtime_control.launch_guard import run_launch_self_test
from execute_tools.dataset_config import DataScope
from execute_tools.evaluation_execution import candidate_evaluation_executor
from execute_tools.health_checks.launch_policy import validate_formal_launch
from execute_tools.model_output_retention import require_local_output_inventory
from workflows.candidate_training_settings import CandidateTrainingSettings
from workflows.constraint_disclosure import workflow_constraint_context
from workflows.definition import ExternalSource, ProtocolRequest
from workflows.llm_config import WorkflowLLMConfig
from workflows.run_bindings import WorkflowRunBindings
from workflows.run_config import active_vram_budget, bind_runtime_verifier_launch
from workflows.task_composition import RunTaskComposition, resolve_composed_measurement_capability
from workflows.training_startup import prepare_training_run

from .models import CandidateRunReceipt, CandidateRunRequest


@dataclass(frozen=True)
class TrainingAdmission:
    settings: CandidateTrainingSettings
    bindings: WorkflowRunBindings
    constraints: ConstraintContext | None


def reconcile_constraints(
    actual: ConstraintContext | None, expected: ConstraintContext | None
) -> None:
    """Accept incomplete evidence, but refuse each already known conflicting section."""
    if actual is None:
        return
    if expected is None:
        raise ValueError("constraint_context conflicts with disabled disclosure")
    for name in type(actual).model_fields:
        if name == "known_sections":
            continue
        value = getattr(actual, name)
        if (name in actual.known_sections or value is not None) and value != getattr(
            expected, name
        ):
            raise ValueError(f"constraint_context.{name} disagrees with native training")


def reconcile_proposal(seed: ProposalInput, admitted: TrainingAdmission) -> ProposalInput:
    """Preserve explicit values, filling only omitted native launch facts."""
    launch = admitted.settings.launch
    bindings = admitted.bindings
    values = {
        name: getattr(launch, name)
        for name in (
            "trial_time_budget_minutes",
            "formal_time_budget_minutes",
            "workflow_parameter_rules",
            "sampling_seed",
            "is_trial",
            "allowed_output_types",
            "baseline_isolation",
        )
    }
    values.update(
        data_scope=bindings.data_scope if bindings.data_scope is not None else DataScope.default(),
        trial_portion=UNCONSTRAINED_TRIAL_PORTION
        if launch.trial_portion is None
        else launch.trial_portion,
        train_portion=UNCONSTRAINED_TRAIN_PORTION
        if launch.train_portion is None
        else launch.train_portion,
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


def admit_training(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
) -> TrainingAdmission:
    """Resolve actual scope, Health, hardware and measurement using native owners."""
    definition = request.preview.document.definition
    tuning = next(node.request for node in definition.nodes if node.capability == "tuning")
    assert isinstance(tuning, ProtocolRequest)
    source = next(arg.source for arg in tuning.arguments if arg.name == "settings")
    assert isinstance(source, ExternalSource)
    binding = next(item for item in definition.externals if item.id == source.binding)
    index = next(
        i for i, item in enumerate(request.files) if item.reference == f"external.{binding.id}"
    )
    control = Path(initial.workspace) / "candidate_run"
    payload = (control / f"input_{index:03}.snapshot").read_bytes()
    settings = CandidateTrainingSettings.model_validate_json(payload)
    # Dataclass omission remains distinguishable here: false cannot disable a real launch.
    if (
        "require_probe_runner" in json.loads(payload).get("launch", {})
        and not settings.launch.require_probe_runner
    ):
        raise ValueError("require_probe_runner cannot be disabled for native training")
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
    preparation = prepare_training_run(
        launch=launch,
        workspace=initial.workspace,
        llm_config=config,
        task_composition=composition,
        **{
            name: getattr(settings, name)
            for name in type(settings).model_fields
            if name != "launch"
        },
    )
    resolve_ordering(
        resolved_scope=list(preparation.resolved_scope),
        override_strategy=settings.order_strategy_override,
        override_file_order=settings.file_order_override,
    )
    capability = resolve_composed_measurement_capability(composition, dataset_root=root)
    run_launch_self_test(require_probe_runner=launch.require_probe_runner, capability=capability)
    ensure_run_invariants(initial.workspace, preparation.invariants)
    hardware = get_hardware_context(Path(initial.workspace), initial.run_name)
    bindings = WorkflowRunBindings(
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
        task_composition=composition,
        llm_config=config,
        measurement_capability=capability,
        hardware_context=hardware,
        active_vram_budget_gb=active_vram_budget(launch),
    )
    publish_bytes_write_once(
        str(control / "training_settings.json"), settings.model_dump_json(indent=2).encode()
    )
    return TrainingAdmission(settings, bindings, workflow_constraint_context(launch, composition))
