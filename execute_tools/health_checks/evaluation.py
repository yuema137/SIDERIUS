"""Shared HealthGate evaluation and persistence adapter.

Both Phase 1 baselines and tuner rounds call this module.  It deliberately
wraps the existing gate runner instead of duplicating check calculations.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import suppress
from typing import Any, Literal

import numpy as np

from execute_tools.health_checks.config import GateConfig, load_health_gates_config
from execute_tools.health_checks.runner import evaluate_gate, resolve_action
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    GateAction,
    GateResult,
    HealthCheckContext,
    PersistedHealthGateResult,
)


def _sha256(path: str | None) -> str | None:
    if not path or not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(path: str | None) -> dict[str, Any]:
    if not path:
        return {"path": None, "exists": False, "stable_inventory_id": None}
    absolute = os.path.abspath(path)
    if not os.path.isfile(absolute):
        return {"path": absolute, "exists": False, "stable_inventory_id": None}
    stat = os.stat(absolute)
    identity = f"{absolute}:{stat.st_size}:{stat.st_mtime_ns}"
    return {
        "path": absolute,
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "stable_inventory_id": hashlib.sha256(identity.encode()).hexdigest(),
    }


def _decode_json_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Normalise legacy ``*_json`` values at the persistence boundary."""
    normalised: dict[str, Any] = {}
    for key, value in metrics.items():
        target_key = key[:-5] if key.endswith("_json") else key
        if key.endswith("_json") and isinstance(value, str):
            with suppress(json.JSONDecodeError):
                value = json.loads(value)
        normalised[target_key] = value
    return normalised


def _summary(values: list[float]) -> dict[str, float | int]:
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=np.float64)
    if finite.size == 0:
        return {"count": 0}
    return {
        "count": int(finite.size),
        "minimum": float(np.min(finite)),
        "q25": float(np.quantile(finite, 0.25)),
        "median": float(np.median(finite)),
        "q75": float(np.quantile(finite, 0.75)),
        "maximum": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "standard_deviation": float(np.std(finite, ddof=1)) if finite.size > 1 else 0.0,
    }


def _threshold(check_name: str, config: dict[str, Any]) -> dict[str, Any] | None:
    if check_name == "output_diversity":
        return {
            "metric": "n_unique_int8_values",
            "operator": ">",
            "value": int(config.get("min_unique_int8_values", 5)),
            "unit": "count",
        }
    if check_name == "output_std":
        return {
            "metric": "output_std_mv",
            "operator": ">=",
            "value": float(config.get("min_std_mv", 1.0)),
            "unit": "mV",
        }
    if check_name == "amplitude_collapse":
        return {
            "metric": "dominant_mode_fraction",
            "operator": "<=",
            "value": float(config.get("collapse_threshold", 0.95)),
            "unit": "fraction",
        }
    return None


def _per_file_metrics(
    check_name: str,
    metrics: dict[str, Any],
    ctx: HealthCheckContext,
    checkpoint_sha256: str | None,
) -> dict[str, Any]:
    raw: Any = metrics.get("per_file")
    metric_name = {
        "output_diversity": "n_unique_int8_values",
        "output_std": "output_std_mv",
        "amplitude_collapse": "dominant_mode_fraction",
        "pearson_dispersion": "pearson_correlation",
        "spectral_peak_ratio": "spectral_peak_ratio",
        "per_file_output_std": "output_std_mv",
    }.get(check_name)
    unit = {
        "output_diversity": "count",
        "output_std": "mV",
        "amplitude_collapse": "fraction",
        "pearson_dispersion": "correlation",
        "spectral_peak_ratio": "ratio",
        "per_file_output_std": "mV",
    }.get(check_name)

    rows: dict[str, Any] = {}
    if isinstance(raw, list):
        iterable = ((str(item.get("file_index")), item) for item in raw)
    elif isinstance(raw, dict):
        iterable = ((str(key), {"metric_value": value}) for key, value in raw.items())
    else:
        named = (
            metrics.get("pearson_per_file")
            or metrics.get("ratio_per_file")
            or metrics.get("std_mv_per_file")
            or {}
        )
        iterable = ((str(key), {"metric_value": value}) for key, value in named.items())

    for key, item in iterable:
        index = int(key)
        path = ctx.get_denoised_path(index)
        value = item.get("metric_value")
        io_warning = item.get("io_error")
        rows[key] = {
            "file_index": index,
            "file": _inventory(path),
            "passed": item.get("passed"),
            "execution_status": "not_run" if io_warning else "passed",
            "sample_count_inspected": metrics.get("peek_samples_requested"),
            "sampling_method": "channel0001_prefix_peek",
            "metrics": ({metric_name: {"value": value, "unit": unit}} if metric_name else {}),
            "checkpoint_sha256": checkpoint_sha256,
            "io_warning": io_warning,
        }
    return rows


def _execution_status(
    result: GateResult, metrics: dict[str, Any]
) -> Literal["passed", "failed", "not_run", "error"]:
    """Persisted execution state for one gate — now derived from TYPED verdicts.

    Step 08a replaced the ``"not applicable" in reasons`` string sniff: this
    function used to reverse-engineer an honest verdict out of prose that a
    check happened to emit, which meant a reworded reason silently changed a
    persisted status.

    The VALUES are unchanged, deliberately and byte-for-byte. Rule order is
    load-bearing and matches the pre-08a function exactly:

    1. an exception inside a check → ``"error"``;
    2. every attempted file having failed I/O → ``"not_run"``, **kept ahead
       of any verdict-derived error** because that is what the pre-08a rule
       produced for this input class. Such a result also carries
       ``CheckVerdict.ERROR`` in ``check_verdicts``, which is where the
       four-way truth now lives; ``execution_status`` keeps its legacy
       meaning so no existing reader changes behaviour;
    3. every check inapplicable → ``"not_run"`` (the sniff's replacement,
       now typed);
    4. otherwise the gate's routing verdict.
    """
    if any("exception_type" in check.metrics for check in result.check_results):
        return "error"
    attempted = metrics.get("n_files_attempted")
    io_failed = metrics.get("n_files_io_failed")
    if attempted and io_failed == attempted:
        return "not_run"
    if result.check_results and all(
        check.verdict is CheckVerdict.INAPPLICABLE for check in result.check_results
    ):
        return "not_run"
    return "passed" if result.passed else "failed"


def _persist(
    result: GateResult,
    gate_config: GateConfig,
    production_gate: GateConfig | None,
    ctx: HealthCheckContext,
    runtime_seconds: float,
    checkpoint_sha256: str | None,
    healthgate_mode: str | None = None,
    result_authority: str | None = None,
) -> PersistedHealthGateResult:
    check = result.check_results[0] if result.check_results else None
    metrics = _decode_json_metrics(check.metrics if check else {})
    check_name = check.check_name if check else gate_config.checks[0].name
    per_file = _per_file_metrics(check_name, metrics, ctx, checkpoint_sha256)

    values: list[float] = []
    for row in per_file.values():
        for metric in row["metrics"].values():
            value = metric.get("value")
            if isinstance(value, int | float):
                values.append(float(value))
    metrics["per_file"] = per_file
    metrics["aggregate_statistics"] = _summary(values)

    requested = list(gate_config.checks[0].config.get("peek_file_indices", []))
    completed = [int(key) for key, row in per_file.items() if row["execution_status"] == "passed"]
    passed = [int(key) for key, row in per_file.items() if row.get("passed") is True]
    failed = [int(key) for key, row in per_file.items() if row.get("passed") is False]
    aggregation = {
        "aggregation_rule": gate_config.checks[0].config.get("aggregation", "recording"),
        "files_requested": requested or sorted(int(key) for key in per_file),
        "files_completed": completed,
        "files_passed": passed,
        "files_failed": failed,
        "aggregate_passed": result.passed,
    }
    would_invalidate = bool(
        not result.passed
        and production_gate is not None
        and production_gate.on_fail.action is not GateAction.CONTINUE
    )
    return PersistedHealthGateResult(
        gate_name=result.gate_id,
        # D-C7b: what this gate WAS, recorded beside what it did. The id is
        # never rewritten — it is the join key for archived artifacts — so
        # the honest label is derived from these instead.
        gate_role=getattr(gate_config, "gate_role", None),
        configured_action=gate_config.on_fail.action,
        healthgate_mode=healthgate_mode,
        result_authority=result_authority,
        execution_status=_execution_status(result, metrics),
        # Step 08a: what each check actually WAS, beside what the gate did.
        # Built from the checks that produced a result, so a short-circuited
        # gate reports the checks that ran rather than inventing entries for
        # the ones that never did.
        check_verdicts={check.check_name: check.verdict.value for check in result.check_results},
        check_passed=result.passed,
        would_invalidate_under_production_policy=would_invalidate,
        resolved_action=result.action,
        failure_reason=result.failure_reason or None,
        threshold=_threshold(check_name, gate_config.checks[0].config),
        aggregation=aggregation,
        metrics=metrics,
        gate_runtime_seconds=runtime_seconds,
    )


def evaluate_and_persist_health_gates(
    ctx: HealthCheckContext,
    *,
    config_path: str | None = None,
    production_config_path: str | None = None,
    gate_ids: list[str] | None = None,
    healthgate_mode: str | None = None,
    result_authority: str | None = None,
) -> tuple[list[GateResult], list[PersistedHealthGateResult], GateAction]:
    """Run every gate matching ``ctx.round_index`` and build durable results."""
    config = load_health_gates_config(config_path)
    production = (
        load_health_gates_config(production_config_path) if production_config_path else None
    )
    production_by_id = {gate.id: gate for gate in production.health_gates} if production else {}
    checkpoint_sha256 = _sha256(ctx.checkpoint_path)
    runtime_results: list[GateResult] = []
    persisted: list[PersistedHealthGateResult] = []
    for gate in config.health_gates:
        if not gate.matches_round(ctx.round_index) or (
            gate_ids is not None and gate.id not in gate_ids
        ):
            continue
        started = time.perf_counter()
        result = evaluate_gate(gate.id, ctx, config_path=config_path)
        elapsed = time.perf_counter() - started
        runtime_results.append(result)
        persisted.append(
            _persist(
                result,
                gate,
                production_by_id.get(gate.id),
                ctx,
                elapsed,
                checkpoint_sha256,
                healthgate_mode=healthgate_mode,
                result_authority=result_authority,
            )
        )
    return runtime_results, persisted, resolve_action(runtime_results)
