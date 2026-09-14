"""Attempt-scoped task Health coverage validation.

This module is intentionally small: planning acquires an opaque evaluation
scope, and this boundary asks the same bound task to confirm that scope covers
the output-dependent Health demand before any execution admission occurs.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from execute_tools.task_data_path import (
    HealthCoverageRequest,
    HealthCoverageResult,
    TaskDataPath,
    TaskHealthCoverageError,
    resolve_task_health_coverage_capability,
)


def validate_attempt_health_coverage(
    *,
    data_path: TaskDataPath,
    evaluation_scope: object,
    round_kind: str,
    health_binding: Any,
    health_gate_files: list[int] | tuple[int, ...] | None = None,
    composed: bool,
    health_enabled: bool,
) -> HealthCoverageResult | None:
    """Require coverage only for a composed Health-enabled attempt.

    Non-composed, Health-disabled and legacy ``single_file`` paths return
    without resolving the optional capability. The helper does not inspect
    either opaque value, expand the scope, or invoke any execution effect.
    """
    if not composed or not health_enabled or round_kind not in ("trial", "formal"):
        return None
    capability = resolve_task_health_coverage_capability(data_path)
    try:
        request = HealthCoverageRequest(
            evaluation_scope=evaluation_scope,
            round_kind=round_kind,
            health_binding=health_binding,
            health_gate_files=(
                tuple(health_gate_files) if health_gate_files is not None else None
            ),
        )
        raw_result = capability.validate_health_coverage(request)
        result = HealthCoverageResult.model_validate(raw_result)
    except TaskHealthCoverageError:
        raise
    except (ValidationError, TypeError, ValueError) as exc:
        task_id = getattr(data_path, "task_data_path_id", "<unknown>")
        raise TaskHealthCoverageError(
            f"task data path {task_id!r} returned malformed Health coverage "
            f"for {round_kind!r} attempt: {exc}"
        ) from exc
    except Exception as exc:
        task_id = getattr(data_path, "task_data_path_id", "<unknown>")
        raise TaskHealthCoverageError(
            f"task data path {task_id!r} failed Health coverage validation "
            f"for {round_kind!r} attempt: {exc}"
        ) from exc

    if result.applicable and not result.covered:
        task_id = getattr(data_path, "task_data_path_id", "<unknown>")
        raise TaskHealthCoverageError(
            f"task data path {task_id!r} reports uncovered Health demand for "
            f"{round_kind!r} attempt: {result.reason}"
        )
    return result
