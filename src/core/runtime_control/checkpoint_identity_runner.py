"""Prepare an explicit checkpoint identity through the existing CPU supervisor."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from core.runtime_control.checkpoint_identity import (
    CheckpointIdentityReceipt,
    CheckpointIdentityRequest,
    CheckpointPreparationResult,
    CheckpointPreparationTiming,
)
from core.runtime_control.observed_subprocess import (
    ObservedProcessResult,
    ProcessLifecycle,
    ProcessLimits,
    ProcessSupervisionError,
    remaining_process_limits,
    supervise_subprocess,
)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate checkpoint receipt field")
        result[key] = value
    return result


def _read_receipt(observed: ObservedProcessResult) -> CheckpointIdentityReceipt:
    if observed.completed is None:
        raise ValueError("checkpoint identity worker produced no completed result")
    return CheckpointIdentityReceipt.model_validate(
        json.loads(observed.completed.stdout, object_pairs_hook=_unique_fields)
    )


def _validate_receipt(
    request: CheckpointIdentityRequest,
    observed: ObservedProcessResult,
    receipt: CheckpointIdentityReceipt,
) -> None:
    lifecycle = observed.lifecycle
    group = lifecycle.group_cleanup
    if (
        observed.completed is None
        or observed.timeout is not None
        or observed.completed.returncode != 0
        or not lifecycle.child_reaped
        or lifecycle.returncode != 0
        or lifecycle.stop_reason is not None
        or lifecycle.cleanup_errors
        or lifecycle.owned_pgid != lifecycle.child_pid
        or group is None
        or group.required
        or group.term is not None
        or group.kill is not None
        or group.final.status != "absent"
    ):
        raise ValueError("checkpoint identity worker lifecycle is not clean")
    if receipt.request_nonce != request.request_nonce or receipt.child_pid != lifecycle.child_pid:
        raise ValueError("checkpoint identity receipt differs from its request or child")
    if receipt.reference is not None:
        receipt.reference.validate_native_path(request.model_type)
        if (
            receipt.reference.checkpoint_path != request.checkpoint_path
            or receipt.reference.experiment_id != request.experiment_id
        ):
            raise ValueError("checkpoint identity receipt differs from its native reference")


def prepare_checkpoint_identity(
    request: CheckpointIdentityRequest,
    *,
    limits: ProcessLimits,
    request_directory: Path,
    env: dict[str, str],
) -> CheckpointPreparationResult:
    """Charge preparation before launch and reject late results after cleanup.

    Parent IO cannot be interrupted here. On return from each preparation stage,
    spent time is deducted instead of granting a fresh worker allowance. Only the
    fixed child reads checkpoint contents; the parent handles small protocol data.
    """
    started = time.perf_counter()
    request_elapsed = supervised_elapsed = 0.0
    finalization_started: float | None = None
    lifecycle: ProcessLifecycle | None = None
    receipt: CheckpointIdentityReceipt | None = None
    accepted = None
    detail = "checkpoint identity unavailable"
    temporary: tempfile.TemporaryDirectory | None = None
    try:
        if not request_directory.is_absolute():
            raise ValueError("checkpoint request directory must be absolute")
        if request.cooperative_seconds != limits.deadline_seconds:
            raise ValueError(
                "checkpoint cooperative ceiling must equal the supplied work allowance"
            )
        temporary = tempfile.TemporaryDirectory(
            prefix="checkpoint-identity-", dir=request_directory
        )
        request_path = Path(temporary.name) / "request.json"
        request_path.write_text(request.model_dump_json())
        supervised_at = time.perf_counter()
        request_elapsed = supervised_at - started
        remaining = remaining_process_limits(limits, request_elapsed)
        try:
            observed = supervise_subprocess(
                [
                    sys.executable,
                    "-m",
                    "core.runtime_control.checkpoint_identity_worker_main",
                    str(request_path),
                ],
                env=env,
                preexec_fn=None,
                capture_stdout=True,
                limits=remaining,
            )
        finally:
            finalization_started = time.perf_counter()
            supervised_elapsed = finalization_started - supervised_at
        lifecycle = observed.lifecycle
        receipt = _read_receipt(observed)
        _validate_receipt(request, observed, receipt)
        if receipt.reference is None:
            detail = receipt.unavailable_reason or detail
        else:
            accepted = receipt.reference
            detail = "native checkpoint identity verified in bounded CPU worker"
    except Exception as exc:
        accepted = None
        detail = f"checkpoint identity unavailable: {type(exc).__name__}: {exc}"
        evidence = (
            exc.lifecycle
            if isinstance(exc, ProcessSupervisionError)
            else getattr(exc, "process_lifecycle", None)
        )
        if isinstance(evidence, ProcessLifecycle):
            lifecycle = evidence
    finally:
        if finalization_started is None:
            finalization_started = time.perf_counter()
            request_elapsed = finalization_started - started
        if temporary is not None:
            try:
                temporary.cleanup()
            except Exception as exc:
                accepted = None
                detail += f"; request cleanup unavailable: {type(exc).__name__}: {exc}"
    finished = time.perf_counter()
    elapsed = finished - started
    if elapsed >= limits.deadline_seconds:
        accepted = None
        detail = "checkpoint identity preparation exceeded its total allowance, including result checks and cleanup"
    return CheckpointPreparationResult(
        status="available" if accepted is not None else "unavailable",
        reference=accepted,
        detail=detail,
        worker_receipt=receipt,
        lifecycle=lifecycle,
        timing=CheckpointPreparationTiming(
            request_seconds=request_elapsed,
            supervised_seconds=supervised_elapsed,
            finalization_seconds=finished - finalization_started,
            elapsed_seconds=elapsed,
        ),
    )
