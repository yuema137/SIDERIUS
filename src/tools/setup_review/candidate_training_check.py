"""Native declaration checks for retained training settings on a fresh task."""

from pathlib import Path

from agent.schemas.ordering import resolve_ordering
from execute_tools.dataset_config import DataScope, bind_dataset_profile
from execute_tools.health_checks.config import materialize_effective_config
from execute_tools.health_checks.launch_policy import validate_formal_launch
from workflows.candidate_training_settings import CandidateTrainingSettings
from workflows.task_composition import RunTaskComposition
from workflows.task_settings import validate_scope_settings

from .composition_models import CandidateTrainingFacts


def check_training_settings(
    settings: CandidateTrainingSettings, composition: RunTaskComposition, scratch: str
) -> CandidateTrainingFacts:
    """Validate only target-known training declarations using native policy owners."""
    if settings.launch.data_dir is not None:
        raise ValueError(
            "Changed task review requires managed training data_dir to be absent or null"
        )

    launch = settings.launch
    validate_formal_launch(
        healthgate_mode=launch.healthgate_mode,
        result_authority=launch.result_authority,
        health_checks_config=settings.health_checks_config,
        gates_enabled=launch.enable_chain_incumbent_formal_gates,
        skip_formal_min_delta=launch.skip_formal_min_delta,
        bypass_formal_time_budget_min_delta=launch.bypass_formal_time_budget_min_delta,
        task_health_binding=composition.task_health_binding,
    )

    scope = settings.data_scope if settings.data_scope is not None else DataScope.default()
    count = composition.dataset_profile.partition_count
    resolved = scope.resolve(count)
    partial = resolved != list(range(count))
    with bind_dataset_profile(composition.dataset_profile):
        validate_scope_settings(
            scope_is_partial=partial,
            formal_strategy=launch.formal_strategy,
            task_composition=composition,
            health_gate_enabled=settings.health_gate_enabled,
            health_gate_files=settings.health_gate_files,
        )

    if settings.health_gate_enabled:
        output = Path(scratch) / "candidate-training-health"
        output.mkdir()
        materialize_effective_config(
            settings.health_checks_config,
            settings.health_gate_files,
            str(output),
            resolved_scope=resolved,
            task_health_binding=composition.task_health_binding,
            dataset_partition_count=count,
        )

    ordering = resolve_ordering(
        resolved_scope=resolved,
        override_strategy=settings.order_strategy_override,
        override_file_order=settings.file_order_override,
    )
    return CandidateTrainingFacts(
        resolved_scope=tuple(resolved),
        scope_is_partial=partial,
        ordering=ordering,
        health_gate_enabled=settings.health_gate_enabled,
    )
