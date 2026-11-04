"""Builtin checkpoint measurements in a separate supervised worker.

The scoring interpreter reads only typed results; candidate construction and
forward execution cannot patch its aggregation or emission. Latency follows a
dedicated timed-forward protocol, never inference-phase wall time.
"""

from __future__ import annotations

import json
import math
import os
import stat
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from execute_tools.evaluation_spec import LatencyProtocol, MeasurementComponent
from execute_tools.measurement_results import (
    MEASUREMENT_UNITS,
    MeasurementNoise,
    MeasurementResult,
)


class MeasurementRequest(BaseModel):
    """Parent-written reconstruction inputs for the attempt's serialized checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_type: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    model_configuration: dict[str, JsonValue]
    loss_type: str = Field(min_length=1)
    checkpoint_path: str = Field(min_length=1)
    model_io_json: str | None = None


def active_measurement_components() -> tuple[MeasurementComponent, ...]:
    """The bound run's declared measurement components, in declaration order.

    Reads the declaration snapshot that ``bind_run_task_composition`` binds once
    (checked by the composition verification guard); no manifest reload and no
    second binding. Without a binding nothing is measured, and a
    measurement-declaring scoring child then refuses rather than skipping.
    """
    from agent.evaluation_context import active_evaluation_prompt_context

    context = active_evaluation_prompt_context()
    if context is None:
        return ()
    return tuple(c for c in context.spec.components if isinstance(c, MeasurementComponent))


def read_measurement_request(path: str) -> MeasurementRequest:
    with open(path, encoding="utf-8") as handle:
        return MeasurementRequest.model_validate(json.load(handle))


def _percentile(ordered: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of an ascending sequence."""
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def time_forward(
    forward: Callable[[], Any],
    protocol: LatencyProtocol,
    *,
    synchronize: Callable[[], None] = lambda: None,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[float, MeasurementNoise]:
    """Median and IQR (ms) of ``repeats`` timed forwards after ``warmup`` untimed ones."""
    deadline = clock() + protocol.timeout_seconds
    for _ in range(protocol.warmup):
        forward()
        if clock() > deadline:
            raise TimeoutError("latency warm-up exceeded timeout_seconds")
    synchronize()
    samples: list[float] = []
    for _ in range(protocol.repeats):
        started = clock()
        forward()
        synchronize()
        ended = clock()
        samples.append((ended - started) * 1000.0)
        if ended > deadline:
            raise TimeoutError("latency repeats exceeded timeout_seconds")
    ordered = sorted(samples)
    iqr = _percentile(ordered, 0.75) - _percentile(ordered, 0.25)
    return _percentile(ordered, 0.5), MeasurementNoise(repeats=len(ordered), iqr=iqr)


class _LoadedCandidate:
    """Lazily load the checkpoint once for every component that needs the model."""

    def __init__(self, request: MeasurementRequest):
        self.request = request
        self._model: Any = None
        self.contract: Any = None
        self.device = "cpu"

    def model(self) -> Any:
        if self._model is None:
            import torch

            from agent.schemas.model_io_contract import ModelIOContract
            from execute_tools.inference_checkpoint import load_inference_checkpoint
            from execute_tools.inference_model import construct_inference_model

            request = self.request
            contract = None
            if request.model_io_json is not None:
                with open(request.model_io_json, encoding="utf-8") as handle:
                    contract = ModelIOContract.model_validate(json.load(handle))
            self.contract = contract
            model, _config = construct_inference_model(
                request.model_type,
                dict(request.model_configuration),
                model_io_contract=contract,
                loss_type=request.loss_type,
            )
            model = load_inference_checkpoint(model, request.checkpoint_path, request.experiment_id)
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = model.to(self.device).eval()
        return self._model


def _input_tensor(loaded: _LoadedCandidate, shape: Sequence[int]) -> Any:
    import torch

    from execute_tools.model_input_dtype import resolve_inference_input_dtype

    dtype = resolve_inference_input_dtype(loaded.request.model_type, loaded.contract)
    generator = torch.Generator().manual_seed(0)
    if dtype is not None and not dtype.is_floating_point:
        tensor = torch.zeros(tuple(shape), dtype=dtype)
    else:
        tensor = torch.randn(tuple(shape), generator=generator, dtype=dtype or torch.float32)
    return tensor.to(loaded.device)


def _measure(
    component: MeasurementComponent, loaded: _LoadedCandidate
) -> tuple[float, MeasurementNoise]:
    exact = MeasurementNoise(repeats=1, iqr=0.0)
    if component.measurement == "model_bytes":
        return float(os.path.getsize(loaded.request.checkpoint_path)), exact
    model = loaded.model()
    if component.measurement == "trainable_parameter_count":
        return float(sum(p.numel() for p in model.parameters() if p.requires_grad)), exact
    if component.measurement == "total_parameter_count":
        return float(sum(p.numel() for p in model.parameters())), exact
    import torch

    assert component.protocol is not None
    batch = _input_tensor(loaded, component.protocol.input_shape)
    synchronize = torch.cuda.synchronize if loaded.device == "cuda" else (lambda: None)

    def forward() -> None:
        with torch.inference_mode():
            model(batch)

    return time_forward(forward, component.protocol, synchronize=synchronize)


def _checkpoint_sha256(path: str) -> str | None:
    from core.stream_identity import stream_file_identity

    try:
        with open(path, "rb") as handle:
            digest, _size = stream_file_identity(handle)
        return digest
    except OSError:
        return None


def measure_components(
    components: Sequence[MeasurementComponent], request: MeasurementRequest
) -> list[MeasurementResult]:
    """One result per component, in declaration order; failures are recorded, not raised."""
    if not components:
        return []
    loaded = _LoadedCandidate(request)
    checkpoint = _checkpoint_sha256(request.checkpoint_path)
    results: list[MeasurementResult] = []
    for component in components:
        unit = MEASUREMENT_UNITS[component.measurement]
        try:
            value, noise = _measure(component, loaded)
            if not math.isfinite(value):
                raise ValueError("measurement produced a nonfinite value")
            result = MeasurementResult(
                component_id=component.id,
                measurement=component.measurement,
                unit=unit,
                value=value,
                noise=noise,
                device=loaded.device,
                checkpoint_sha256=checkpoint,
            )
        except Exception as error:  # every failure is typed evidence, never a crash
            from core.local_code.failure import raise_if_code_package_failure

            raise_if_code_package_failure(error)
            result = MeasurementResult(
                component_id=component.id,
                measurement=component.measurement,
                unit=unit,
                device=loaded.device,
                checkpoint_sha256=checkpoint,
                failure=f"{type(error).__name__}: {error}",
            )
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Isolated worker (#1296 F3): candidate model code never runs in the scoring
# child. The parent launches this worker under explicit process
# limits before scoring and transports only validated MeasurementResult JSON.
# ---------------------------------------------------------------------------

#: Framework allowance for interpreter start, model construction and checkpoint
#: load, added to the declared latency timeouts to form the worker deadline.
MEASUREMENT_LOAD_ALLOWANCE_SECONDS = 300.0


class MeasurementWorkerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: MeasurementRequest
    components: tuple[MeasurementComponent, ...] = Field(min_length=1, strict=False)
    output_path: str = Field(min_length=1)


def worker_deadline_seconds(components: Sequence[MeasurementComponent]) -> float:
    return MEASUREMENT_LOAD_ALLOWANCE_SECONDS + sum(
        c.protocol.timeout_seconds for c in components if c.protocol is not None
    )


def failed_results(
    components: Sequence[MeasurementComponent], reason: str
) -> list[MeasurementResult]:
    """Every component fails with one worker-level reason (timeout, crash, RSS)."""
    return [
        MeasurementResult(
            component_id=c.id,
            measurement=c.measurement,
            unit=MEASUREMENT_UNITS[c.measurement],
            failure=reason,
        )
        for c in components
    ]


def validate_measurement_roster(
    results: Sequence[MeasurementResult], declared: Mapping[str, str]
) -> None:
    """Results must cover exactly the declared components with their declared kinds."""
    reported = [r.component_id for r in results]
    if len(reported) != len(set(reported)) or set(reported) != set(declared):
        raise ValueError("measurement results omit, duplicate or add components")
    for result in results:
        if result.measurement != declared[result.component_id]:
            raise ValueError(
                f"measurement {result.component_id!r} reports kind {result.measurement!r}, "
                f"declared {declared[result.component_id]!r}"
            )


MAX_RESULTS_BYTES = 1 << 20
MAX_LOG_TAIL_BYTES = 500


def worker_log_path(output_path: str) -> str:
    return os.path.join(os.path.dirname(output_path), "measurement_worker.log")


def _read_regular_file(path: str, limit: int, *, tail: bool = False) -> bytes:
    """Read at most ``limit`` bytes from a worker-written regular file.

    The worker controls the path, so never follow a symlink, never block on a
    FIFO or device, and never load an unbounded payload into the parent.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{os.path.basename(path)} is not a regular file")
        if tail:
            os.lseek(fd, max(0, info.st_size - limit), os.SEEK_SET)
        elif info.st_size > limit:
            raise ValueError(f"{os.path.basename(path)} exceeds {limit} bytes")
        chunks, remaining = [], limit
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _log_tail(output_path: str) -> str:
    try:
        data = _read_regular_file(worker_log_path(output_path), MAX_LOG_TAIL_BYTES, tail=True)
    except (OSError, ValueError):
        return ""
    return data.decode("utf-8", errors="replace").strip()


def read_measurement_results(path: str, declared: Mapping[str, str]) -> list[MeasurementResult]:
    raw = json.loads(_read_regular_file(path, MAX_RESULTS_BYTES).decode("utf-8"))
    if not isinstance(raw, list):
        raise ValueError("measurement results must be a JSON list")
    results = [MeasurementResult.model_validate(item) for item in raw]
    validate_measurement_roster(results, declared)
    return results


def run_measurement_worker(
    request: MeasurementRequest,
    components: Sequence[MeasurementComponent],
    *,
    directory: str,
    env: dict[str, str],
    preexec_fn: Callable[[], None] | None,
    rss_limit_bytes: int,
) -> list[MeasurementResult]:
    """Run the worker under a hard deadline and RSS limit; failures become results.

    The worker inherits ``env`` (the same ``CUDA_VISIBLE_DEVICES`` and plugin
    roots as the training/inference children) and ``preexec_fn`` (address
    space cap). On deadline, RSS excess, crash or malformed output every
    component is a failure result naming the cause.
    """
    import sys

    from core.runtime_control.observed_subprocess import (
        ProcessLimits,
        ProcessSupervisionError,
        supervise_subprocess,
    )

    if not components:
        return []
    declared = {c.id: c.measurement for c in components}
    os.makedirs(directory, exist_ok=True)
    output = os.path.join(directory, "measurement_results.json")
    request_path = os.path.join(directory, "measurement_worker_request.json")
    worker = MeasurementWorkerRequest(
        request=request, components=tuple(components), output_path=output
    )
    with open(request_path, "w", encoding="utf-8") as handle:
        json.dump(worker.model_dump(mode="json"), handle)
    for stale in (output, worker_log_path(output)):
        if os.path.lexists(stale):
            os.remove(stale)
    deadline = worker_deadline_seconds(components)
    limits = ProcessLimits(
        deadline_seconds=deadline,
        rss_limit_bytes=rss_limit_bytes,
        poll_seconds=0.2,
        grace_seconds=5.0,
        reap_seconds=5.0,
    )
    try:
        observed = supervise_subprocess(
            [sys.executable, "-m", "execute_tools.candidate_measurement_worker", request_path],
            env=env,
            preexec_fn=preexec_fn,
            capture_stdout=True,
            limits=limits,
        )
    except ProcessSupervisionError as error:
        reason = error.lifecycle.stop_reason or str(error)
        if reason == "work_deadline_exceeded":
            reason = f"measurement worker exceeded its {deadline:g} s deadline and was killed"
        return failed_results(components, f"measurement worker stopped: {reason}")
    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        # ValueError covers undecodable bytes the worker wrote before redirecting its output.
        detail = _log_tail(output) or str(error)
        return failed_results(components, f"measurement worker failed: {detail}")
    completed = observed.completed
    if completed is None or completed.returncode != 0:
        tail = _log_tail(output) or (
            "" if completed is None else (completed.stderr or "")[-MAX_LOG_TAIL_BYTES:]
        )
        return failed_results(components, f"measurement worker failed: {tail.strip()}")
    try:
        return read_measurement_results(output, declared)
    except (OSError, ValueError, RecursionError) as error:
        # RecursionError: deeply nested JSON below the size cap.
        return failed_results(components, f"measurement worker output invalid: {error}")
