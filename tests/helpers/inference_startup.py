"""Checkpoint-bound startup construction with explicit clock and budget injection."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.inference_startup import (
    InferenceStartup,
    InferenceStartupMessage,
    InferenceStartupRequest,
    publish_message,
)

# Real-process success witnesses include durable I/O on slow scratch storage.
OFFLINE_IO_BUDGET_SECONDS = 600.0


def startup_fixture(
    tmp_path: Path,
    spec: GpuMeasurementSpec,
    *,
    clock: Callable[[], float] | None = None,
    child_pid: int = 1234,
    preparation_seconds: float | None = None,
    ack_seconds: float | None = None,
) -> tuple[InferenceStartup, InferenceStartupMessage, list[float]]:
    """Retain small expiry defaults; callers may independently select clock and budgets."""
    if preparation_seconds is None:
        preparation_seconds = 10.0 if clock is not None else OFFLINE_IO_BUDGET_SECONDS
    if ack_seconds is None:
        ack_seconds = 1.0 if clock is not None else OFFLINE_IO_BUDGET_SECONDS
    clock = clock or time.monotonic
    directory = tmp_path / "startup"
    directory.mkdir()
    request = InferenceStartupRequest(
        nonce="attempt",
        spec=spec,
        deadline_at=clock() + preparation_seconds,
        ack_timeout_seconds=ack_seconds,
        poll_seconds=0.01,
        receipt_limit_bytes=1024**2,
    )
    path = directory / "request.json"
    publish_message(path, request, request.receipt_limit_bytes)
    publications: list[float] = []
    startup = InferenceStartup(
        path, request, rss_limit_bytes=1024**3, on_publication=publications.append, clock=clock
    )
    assert spec.inference_checkpoint is not None and spec.inference_binding is not None
    message = InferenceStartupMessage(
        nonce=request.nonce,
        child_pid=child_pid,
        reference=spec.inference_checkpoint,
        binding_sha256=spec.inference_binding.request_sha256,
    )
    return startup, message, publications
