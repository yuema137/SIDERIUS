"""Explicit semantic fields for review, without open configuration dumps."""

import json

from pydantic import JsonValue

from tools.setup_review.models import SetupDeclarationReport
from tools.setup_review.route_models import LLMRoute
from tools.setup_review.semantic_models import SavedTaskCheckSnapshot
from tools.setup_review.task_settings_models import TaskSettingsSummary

Snapshot = SetupDeclarationReport | SavedTaskCheckSnapshot

# This is a transmission allowlist, not a second default/configuration owner.
_SETTINGS = frozenset(
    [
        "max_rounds",
        "trial_portion",
        "train_portion",
        "eval_portion",
        "formal_portion",
        "formal_train_portion",
        "formal_eval_portion",
        "trial_max_epochs",
        "formal_max_epochs",
        "trial_time_budget_minutes",
        "formal_time_budget_minutes",
        "trial_vram_budget_gb",
        "formal_vram_budget_gb",
        "data_scope",
        "training_validation_portion",
        "healthgate_mode",
        "result_authority",
        "runtime_watchdog",
        "runtime_watchdog_safety_factor",
        "runtime_watchdog_floor_seconds",
        "validation_max_phase_seconds",
        "execution_regime",
        "validation_max_train_samples",
        "validation_max_portion",
        "validation_max_samples",
        "enable_chain_incumbent_formal_gates",
        "skip_formal_min_delta",
        "bypass_formal_time_budget_min_delta",
        "enable_data_analysis",
        "enable_literature_review",
    ]
)


def _scalars(values: dict[str, JsonValue], names: tuple[str, ...]) -> dict[str, JsonValue]:
    return {
        key: values[key]
        for key in names
        if key in values and not isinstance(values[key], (dict, list))
    }


def declaration_of(snapshot: Snapshot) -> SetupDeclarationReport:
    return snapshot.declaration if isinstance(snapshot, SavedTaskCheckSnapshot) else snapshot


def _parameter_rules(values: dict[str, JsonValue]) -> list[JsonValue]:
    rules = values.get("rules")
    if not isinstance(rules, dict):
        return []
    selected: list[JsonValue] = []
    for path, rule in rules.items():
        if not isinstance(rule, dict):
            continue
        projected: dict[str, JsonValue] = {"path": path, **_scalars(rule, ("exact", "predicate"))}
        interval = rule.get("range")
        if isinstance(interval, dict):
            projected["range"] = _scalars(interval, ("min", "max"))
        allowed = rule.get("allowed")
        if isinstance(allowed, list) and all(
            not isinstance(item, (dict, list)) for item in allowed
        ):
            projected["allowed"] = allowed
        selected.append(projected)
    return selected


def _route_packet(routes: list[LLMRoute]) -> list[JsonValue]:
    return [
        {
            "name": route.name,
            "applicability": route.applicability,
            "transport": route.transport.model_dump(mode="json") if route.transport else None,
            "shares_client_with": route.shares_client_with,
            "issue": route.issue,
        }
        for route in routes
    ]


def _settings_packet(settings: TaskSettingsSummary) -> dict[str, JsonValue]:
    gates = settings.health_config.get("health_gates", []) if settings.health_config else []
    selected: list[JsonValue] = []
    for gate in gates if isinstance(gates, list) else []:
        if not isinstance(gate, dict):
            continue
        item = _scalars(gate, ("id", "gate_role", "after_round", "short_circuit"))
        # Round lists are a declared cadence, not arbitrary plugin configuration.
        cadence = gate.get("after_round")
        if isinstance(cadence, list) and all(isinstance(value, int) for value in cadence):
            item["after_round"] = cadence
        for key in ("on_pass", "on_fail"):
            action = gate.get(key)
            if isinstance(action, dict):
                item[key] = _scalars(action, ("action",))
        selected.append(item)
    return {
        "resolved_data_scope": [value for value in settings.resolved_data_scope],
        "scope_is_partial": settings.scope_is_partial,
        "analysis_enabled": settings.analysis_enabled,
        "formal_policy": settings.formal_policy,
        "health_gate_enabled": settings.health_gate_enabled,
        "health_gates": selected,
        "unresolved": [value for value in settings.unresolved],
    }


def build_packet(snapshot: Snapshot) -> dict[str, JsonValue]:
    """Project facts already saved; never follow a source path or import task code."""
    declaration = declaration_of(snapshot)
    packet: dict[str, JsonValue] = {
        "scope": declaration.scope,
        "settings": [
            {
                "name": row.name,
                "cli_default": row.cli_default,
                "declared_value": row.declared_value,
            }
            for row in declaration.parameters
            if row.name in _SETTINGS
            and not isinstance(row.declared_value, (dict, list))
            and not isinstance(row.cli_default, (dict, list))
        ],
        "routes": _route_packet(declaration.llm_routes),
        "credentials": [item.model_dump(mode="json") for item in declaration.credentials],
        "unresolved": list(declaration.unresolved),
        "deterministic_outcome": declaration.outcome,
        "coverage": (
            "Selected scalar settings and typed routes only. Raw argv, advice, arbitrary nested "
            "configuration, implementation code and original source files are not included. "
            "Missing facts are unknown; do not infer effective defaults from their absence."
        ),
    }
    if isinstance(snapshot, SavedTaskCheckSnapshot):
        packet["deterministic_outcome"] = snapshot.result.outcome
        packet["composition_limitations"] = list(snapshot.limitations)
        if snapshot.result.failure:
            packet["composition_failure"] = {
                "stage": snapshot.result.failure.stage,
                "exception_type": snapshot.result.failure.exception_type,
            }
        settings = snapshot.result.task_settings
        if settings is not None:
            packet["resolved_task_settings"] = _settings_packet(settings)
            packet["routes"] = _route_packet(settings.llm_routes)
        task = snapshot.result.task
        if task:
            packet["task"] = {
                "semantic_fingerprint": task.semantic_fingerprint,
                "task_data_path_id": task.task_data_path_id,
                "primary_metric": _scalars(
                    task.primary_metric, ("id", "direction", "aggregation", "transform")
                ),
                "task_config": _scalars(
                    task.task_config, ("task_name", "task_description", "description", "task_type")
                ),
                "health_declaration": task.task_health_declaration,
                "dataset_profile": _scalars(task.dataset_profile, ("partition_count",)),
                "parameter_rules": _parameter_rules(task.parameter_rules),
                "inference_preflight": _scalars(task.inference_preflight, ("mode", "max_batches")),
            }
            forward = task.task_config.get("forward_contract")
            if isinstance(forward, dict):
                packet["forward_contract"] = _scalars(
                    forward,
                    (
                        "input_shape",
                        "input_description",
                        "output_shape",
                        "output_description",
                        "num_classes",
                        "task_type",
                        "task_note",
                        "embedding_note",
                        "output_head_note",
                        "segmentation_applicability",
                    ),
                )
    return packet


def packet_text(packet: dict[str, JsonValue]) -> str:
    return json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
