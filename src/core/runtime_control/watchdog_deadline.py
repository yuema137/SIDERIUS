"""Watchdog deadline authority for explicit ceilings or opted-in forecast tightening."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any

from core.runtime_control.records import MEASUREMENT_BACKED_SOURCES, RuntimeObservation
from core.runtime_control.session import RuntimeControlPolicy


def _read_observation(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as stream:
            raw = json.load(stream)
        return RuntimeObservation.model_validate(raw).model_dump(mode="json")
    except Exception as exc:
        print(f"[Executor] runtime-verification sidecar unreadable ({path}): {exc}")
        return None


def watchdog_deadline_provider(
    policy: RuntimeControlPolicy,
    rv_sidecar_path: str,
    *,
    phase: str = "training",
    observation_reader: Callable[[str], dict[str, Any] | None] = _read_observation,
) -> Callable[[], tuple[float | None, str]]:
    """Return a deadline measured from subprocess start, plus its source.

    Native policy ignores point forecasts and never raises a declared ceiling.
    Legacy forecast tightening is an explicit policy choice. The supervisor's
    polling and termination grace remain separate from this deadline selection.
    """
    if policy.watchdog.deadline_policy == "budget-ceiling-v1":
        ceilings = (
            (policy.operator_budget_seconds, "operator_budget"),
            (policy.watchdog.budget_seconds, "watchdog_budget"),
            (policy.watchdog.max_phase_seconds, "validation_max_phase"),
        )
        supplied = [(value, source) for value, source in ceilings if value is not None]
        deadline = min(supplied, key=lambda item: item[0]) if supplied else (None, "none")
        return lambda: deadline

    watchdog_factor = (
        policy.watchdog.safety_factor
        if policy.watchdog.safety_factor is not None
        else policy.safety_factor
    )

    def provider() -> tuple[float | None, str]:
        candidates: list[tuple[float, str]] = []
        if policy.operator_budget_seconds is not None:
            candidates.append((policy.operator_budget_seconds, "operator_budget"))
        if policy.watchdog.max_phase_seconds is not None:
            candidates.append((policy.watchdog.max_phase_seconds, "validation_max_phase"))

        block = observation_reader(rv_sidecar_path)
        if block:
            component_map = block.get("components") or {}

            def has_measured_prediction(component: Mapping[str, Any]) -> bool:
                prediction = component.get("prediction") or {}
                return (
                    prediction.get("predicted_seconds") is not None
                    and prediction.get("source") in MEASUREMENT_BACKED_SOURCES
                )

            predicted = [
                component["prediction"]["predicted_seconds"]
                for component in component_map.values()
                if has_measured_prediction(component)
            ]
            complete = has_measured_prediction(component_map.get(phase) or {})
            if phase == "training" and "validation" in component_map:
                validation = component_map["validation"]
                workload = validation.get("workload") or {}
                validation_required = workload.get("unit_count") != 0
                complete = complete and (
                    not validation_required or has_measured_prediction(validation)
                )
            if predicted and (policy.operator_budget_seconds is None or complete):
                candidates.append((sum(predicted) * watchdog_factor, "verified_components"))

        if not candidates:
            return None, "none"
        deadline, source = min(candidates, key=lambda candidate: candidate[0])
        return max(deadline, policy.watchdog.floor_seconds), source

    return provider
