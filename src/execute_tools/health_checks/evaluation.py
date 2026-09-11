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

from execute_tools.health_checks._composition import TaskHealthBinding
from execute_tools.health_checks.config import (
    GateConfig,
    load_composed_health_config,
    load_health_gates_config,
)
from execute_tools.health_checks.registry import get as registry_get
from execute_tools.health_checks.runner import evaluate_gate, resolve_action
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    CheckVerdict,
    EvidenceUnit,
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


def _declaration_for(check_name: str) -> CheckInputDeclaration | None:
    """The registered check's declaration, or None if it has none.

    Step 10 / P4. This is a LOOKUP of data the check owns, not a decision:
    nothing here interprets the check's name. ``None`` covers two states that
    behave identically and identically to pre-P4 behaviour — a pre-08a or
    externally supplied check that publishes no declaration, and (per §10,
    unreachable in production because ``runner.evaluate_gate`` already
    resolved the check through the same registry) a name that is not
    registered. Neither invents a declaration, and neither turns evidence
    rendering into a crash for a check that legally executed.
    """
    try:
        skill = registry_get(check_name)
    except KeyError:
        return None
    declaration = getattr(skill, "declaration", None)
    return declaration if isinstance(declaration, CheckInputDeclaration) else None


def _resolve_unit(unit: EvidenceUnit | None, config: dict[str, Any]) -> str | None:
    """A unit's resolved string, or None (R-2).

    A ``literal`` is check-owned and used verbatim. A ``config_key`` is
    TASK-owned (the value scale) and read from the run's composed check
    config; when the task declares no scale the key is absent and NO unit is
    rendered, rather than a default being invented.
    """
    if unit is None:
        return None
    if unit.literal is not None:
        return unit.literal
    if unit.config_key is None:
        # Unreachable: EvidenceUnit validates exactly-one-of at construction.
        # Narrowed explicitly rather than asserted, because a type guarantee
        # enforced in another layer's validator is not one a reader — or a
        # type checker — can see here.
        return None
    return config.get(unit.config_key)


def _threshold(
    declaration: CheckInputDeclaration | None, config: dict[str, Any]
) -> dict[str, Any] | None:
    """The persisted threshold row, rendered from the check's declaration.

    A check declaring no threshold persists no row — the honest shape for a
    recording-only check, unchanged from pre-P4.

    ``PersistedHealthGateResult.threshold`` holds ONE row, so the first
    declared threshold is the one rendered; no shipped check declares more
    than one, and widening the persisted schema is out of scope.

    **Provenance (Step 10 / P4, Q-P4-1).** When the config supplies the value
    it is persisted exactly as today, with NO source label. When the key is
    absent the check did not threshold on nothing — ``run`` fell back to its
    own declared default — so that default is persisted and labelled
    ``source: "check_default"``. Rendering it as absent would misreport a gate
    that ran; failing here would crash on a check that legally executed.

    The value is cast to the type of the declared default, which reproduces
    the per-branch ``int()`` / ``float()`` casts the removed table applied —
    derived from the declaration instead of hardcoded per check name.
    """
    if declaration is None or not declaration.evidence_thresholds:
        return None
    threshold = declaration.evidence_thresholds[0]
    configured = config.get(threshold.config_key)
    if configured is None:
        value: Any = threshold.default
        source: str | None = "check_default"
    else:
        value = type(threshold.default)(configured)
        source = None
    row: dict[str, Any] = {
        "metric": threshold.metric,
        "operator": threshold.operator,
        "value": value,
        "unit": _resolve_unit(threshold.unit, config),
    }
    if source is not None:
        row["source"] = source
    return row


def _per_file_metrics(
    declaration: CheckInputDeclaration | None,
    metrics: dict[str, Any],
    ctx: HealthCheckContext,
    checkpoint_sha256: str | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    # Step 10 / P4: the check declares WHERE its per-file values live. Was an
    # `or` cascade over three TIDMAD metrics keys in generic code.
    per_file_key = declaration.per_file_metrics_key if declaration is not None else "per_file"
    raw: Any = metrics.get(per_file_key)
    metric_name = declaration.per_file_metric_name if declaration is not None else None
    unit = _resolve_unit(
        declaration.per_file_metric_unit if declaration is not None else None, config
    )
    sampling_method = declaration.sampling_method_label if declaration is not None else None

    rows: dict[str, Any] = {}
    if isinstance(raw, list):
        iterable = ((str(item.get("file_index")), item) for item in raw)
    elif isinstance(raw, dict):
        iterable = ((str(key), {"metric_value": value}) for key, value in raw.items())
    else:
        # No per-file values under the declared key: the check has no per-file
        # dimension (it emits scalars), so no rows are fabricated for it.
        iterable = iter(())

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
            # Each check states how IT sampled (Step 10 / P4). Was one
            # TIDMAD-shaped literal applied to every check's rows.
            "sampling_method": sampling_method,
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
    # Step 10 / P4: the check's own declaration is the evidence authority,
    # resolved once here through the SAME registry the runner already used.
    declaration = _declaration_for(check_name)
    check_config = gate_config.checks[0].config
    per_file = _per_file_metrics(declaration, metrics, ctx, checkpoint_sha256, check_config)

    values: list[float] = []
    for row in per_file.values():
        for metric in row["metrics"].values():
            value = metric.get("value")
            if isinstance(value, int | float):
                values.append(float(value))
    metrics["per_file"] = per_file
    metrics["aggregate_statistics"] = _summary(values)

    requested = list(check_config.get("peek_file_indices", []))
    completed = [int(key) for key, row in per_file.items() if row["execution_status"] == "passed"]
    passed = [int(key) for key, row in per_file.items() if row.get("passed") is True]
    failed = [int(key) for key, row in per_file.items() if row.get("passed") is False]
    aggregation: dict[str, Any] = {
        "files_requested": requested or sorted(int(key) for key in per_file),
        "files_completed": completed,
        "files_passed": passed,
        "files_failed": failed,
        "aggregate_passed": result.passed,
    }
    # M cleanup (2026-08-26): ``aggregation_rule`` records the rule the check
    # ACTUALLY APPLIED — the ``peek_and_aggregate`` outcome the consuming
    # checks echo into their result metrics — never the gate config. Reading
    # the config here persisted claims the runtime did not implement: every
    # recording gate got a fabricated ``"recording"`` (not an AggregationMode
    # at all), and a blocking gate whose check ignores the injected policy
    # key (the single-view categorical checks) got the config value as if a
    # per-file rule had run. Absent key = named absence: no per-file
    # aggregation rule was applied to this result.
    applied_rule = metrics.get("aggregation")
    if applied_rule is not None:
        aggregation["aggregation_rule"] = applied_rule
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
        threshold=_threshold(declaration, check_config),
        aggregation=aggregation,
        metrics=metrics,
        gate_runtime_seconds=runtime_seconds,
    )


def evaluate_and_persist_health_gates(
    ctx: HealthCheckContext,
    *,
    config_path: str | None = None,
    production_config_path: str | None = None,
    task_health_binding: TaskHealthBinding | None = None,
    gate_ids: list[str] | None = None,
    healthgate_mode: str | None = None,
    result_authority: str | None = None,
) -> tuple[list[GateResult], list[PersistedHealthGateResult], GateAction]:
    """Run every gate matching ``ctx.round_index`` and build durable results."""
    config = load_health_gates_config(config_path)
    production = None
    if production_config_path:
        production = (
            load_health_gates_config(production_config_path)
            if task_health_binding is None
            else load_composed_health_config(production_config_path, task_health_binding)[0]
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
