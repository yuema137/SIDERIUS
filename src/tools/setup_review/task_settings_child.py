"""Task-dependent settings, called only inside the explicit sandbox check."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tools.setup_review.routes import standard_llm_routes
from tools.setup_review.task_settings_models import (
    TaskSettingsInputs,
    TaskSettingsSummary,
    decode_formal_delta,
)

if TYPE_CHECKING:
    from workflows.task_composition import RunTaskComposition


def resolve_task_settings(
    inputs: TaskSettingsInputs, composition: RunTaskComposition, scratch: str
) -> TaskSettingsSummary:
    """Use production policy owners without binding a fabricated dataset root."""
    from execute_tools.dataset_config import DataScope, bind_dataset_profile
    from execute_tools.health_checks.config import (
        load_health_gates_config,
        materialize_effective_config,
    )
    from execute_tools.health_checks.launch_policy import validate_formal_launch
    from workflows.task_settings import resolve_analysis_binding, validate_scope_settings

    validate_formal_launch(
        healthgate_mode=inputs.healthgate_mode,
        result_authority=inputs.result_authority,
        health_checks_config=inputs.health_checks_config,
        gates_enabled=inputs.enable_chain_incumbent_formal_gates,
        skip_formal_min_delta=decode_formal_delta(inputs.skip_formal_min_delta),
        bypass_formal_time_budget_min_delta=decode_formal_delta(
            inputs.bypass_formal_time_budget_min_delta
        ),
        task_health_binding=composition.task_health_binding,
    )
    scope = inputs.data_scope if inputs.data_scope is not None else DataScope.default()
    count = composition.dataset_profile.partition_count
    resolved = scope.resolve(count)
    partial = resolved != list(range(count))
    with bind_dataset_profile(composition.dataset_profile):
        validate_scope_settings(
            scope_is_partial=partial,
            formal_strategy=inputs.formal_strategy,
            task_composition=composition,
            health_gate_enabled=inputs.health_gate_enabled,
            health_gate_files=inputs.health_gate_files,
        )
    analysis_enabled = resolve_analysis_binding(composition, inputs.analysis_enabled) is not None
    config = None
    digest = None
    if inputs.health_gate_enabled:
        health_output = Path(scratch) / "task-settings"
        health_output.mkdir()
        path, digest = materialize_effective_config(
            inputs.health_checks_config,
            inputs.health_gate_files,
            str(health_output),
            resolved_scope=resolved,
            task_health_binding=composition.task_health_binding,
            dataset_partition_count=count,
        )
        effective = load_health_gates_config(path)
        config = {
            **effective.model_dump(mode="json"),
            "task_health_binding": effective.task_health_binding,
            "resolved_plugins": [
                item.model_dump(mode="json") for item in effective.resolved_plugins
            ],
        }
    return TaskSettingsSummary(
        resolved_data_scope=resolved,
        scope_is_partial=partial,
        analysis_enabled=analysis_enabled,
        llm_routes=standard_llm_routes(
            inputs.llm_config,
            literature_enabled=inputs.literature_enabled,
            analysis_enabled=analysis_enabled,
            pseudo_llm=inputs.pseudo_llm,
        ),
        formal_policy="passed",
        health_gate_enabled=inputs.health_gate_enabled,
        health_config=config,
        health_config_sha256=digest,
        unresolved=(
            "Hardware availability, effective watchdog profiles, memory and timing remain unchecked.",
            "Dataset contents, split integrity, models and actual Health evaluations were not tested.",
            "Agent-selected training values and which conditional routes execute remain unknown.",
            "This snapshot is not bound to a later launch; recheck after changing inputs.",
        ),
    )
