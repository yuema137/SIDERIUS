"""Authorize a verified native checkpoint before the first inference operation.

Only the existing subprocess supervisor owns termination. These bounded file
messages identify one child and attempt; they are not an adversarial sandbox.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.durable_io import publish_bytes_write_once
from core.file_identity import open_identity_file, regular_file_snapshot
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.inference_checkpoint_reference import InferenceCheckpointReference
from core.runtime_control.inference_measurement_binding import inference_measurement_binding
from core.runtime_control.process_control import ProcessControl


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate startup field: {key}")
        result[key] = value
    return result


def read_message[T: BaseModel](path: Path, model: type[T], byte_limit: int) -> T:
    with open_identity_file(str(path), require_no_follow=True) as stream:
        before = regular_file_snapshot(stream)
        if before.size > byte_limit:
            raise ValueError("startup receipt exceeds startup_receipt_limit_bytes")
        payload = stream.read(byte_limit + 1)
        if len(payload) > byte_limit or regular_file_snapshot(stream) != before:
            raise ValueError("startup receipt changed or exceeded its declared byte limit")
    return model.model_validate(json.loads(payload, object_pairs_hook=_unique_fields))


def publish_message(path: Path, message: BaseModel, byte_limit: int) -> None:
    payload = message.model_dump_json().encode()
    if len(payload) > byte_limit:
        raise ValueError("startup message exceeds startup_receipt_limit_bytes")
    publish_bytes_write_once(str(path), payload)


class InferenceStartupRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    nonce: str = Field(min_length=1)
    spec: GpuMeasurementSpec
    deadline_at: float = Field(allow_inf_nan=False)
    ack_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    poll_seconds: float = Field(gt=0, allow_inf_nan=False)
    receipt_limit_bytes: int = Field(gt=0, strict=True)


class InferenceStartupMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    nonce: str
    child_pid: int = Field(gt=0, strict=True)
    reference: InferenceCheckpointReference
    binding_sha256: str


class InferenceStartupReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    nonce: str
    loaded: InferenceStartupMessage | None = None
    consumed: InferenceStartupMessage | None = None
    published_at: float | None = None
    error: str | None = None


def load_and_wait_for_authorization(model, request_path: str, *, checkpoint_path: str, exp_id: str):
    """Child-only boundary: no forward or dataset iteration occurs in this function."""
    from execute_tools.inference_checkpoint import load_bound_inference_checkpoint

    path = Path(request_path)
    # The small fixed request envelope carries the explicit message bound. It is
    # parent-authored and is not a child-returned path or result.
    request = InferenceStartupRequest.model_validate_json(path.read_bytes())
    spec = request.spec
    reference = spec.inference_checkpoint
    if reference is None or spec.inference_binding is None:
        raise ValueError("native protected inference requires a bound checkpoint")
    if reference.checkpoint_path != checkpoint_path or reference.experiment_id != exp_id:
        raise ValueError("actual inference checkpoint differs from the startup request")
    if inference_measurement_binding(spec) != spec.inference_binding:
        raise ValueError("inference sources changed before checkpoint loading")
    loaded, verified = load_bound_inference_checkpoint(
        model, reference, deadline_at=request.deadline_at
    )
    if inference_measurement_binding(spec) != spec.inference_binding:
        raise ValueError("inference sources changed during checkpoint loading")
    message = InferenceStartupMessage(
        nonce=request.nonce,
        child_pid=os.getpid(),
        reference=verified,
        binding_sha256=spec.inference_binding.request_sha256,
    )
    publish_message(path.parent / "loaded.json", message, request.receipt_limit_bytes)
    while True:
        try:
            authorization = read_message(
                path.parent / "authorized.json",
                InferenceStartupMessage,
                request.receipt_limit_bytes,
            )
        except FileNotFoundError:
            if time.monotonic() >= request.deadline_at:
                raise TimeoutError(
                    "inference startup authorization was not published in time"
                ) from None
            time.sleep(request.poll_seconds)
            continue
        if authorization != message:
            raise ValueError("inference startup authorization does not match this loaded child")
        publish_message(path.parent / "consumed.json", message, request.receipt_limit_bytes)
        return loaded


class InferenceStartup:
    """One attempt's parent handshake, polled by the existing process owner."""

    def __init__(
        self,
        request_path: Path,
        request: InferenceStartupRequest,
        *,
        rss_limit_bytes: int,
        on_publication: Callable[[float], None],
        clock: Callable[[], float] = time.monotonic,
        environment: Mapping[str, str] | None = None,
        control: ProcessControl | None = None,
    ):
        self.path, self.request = request_path, request
        self.rss_limit_bytes = rss_limit_bytes
        self.on_publication, self.clock = on_publication, clock
        self.environment = environment
        self.control = control
        self.receipt = InferenceStartupReceipt(nonce=request.nonce)

    @property
    def published_at(self) -> float | None:
        return self.receipt.published_at

    def check(self, child_pid: int | None, *, terminal: bool = False) -> None:
        try:
            self._check(child_pid, terminal=terminal)
        except BaseException as error:
            self.receipt = self.receipt.model_copy(
                update={"error": f"{type(error).__name__}: {error}"}
            )
            raise

    def _check(self, child_pid: int | None, *, terminal: bool) -> None:
        now = self.clock()
        if self.published_at is None:
            if now >= self.request.deadline_at:
                raise TimeoutError("inference startup exhausted the shared measurement allowance")
            if child_pid is None:
                return
            try:
                loaded = read_message(
                    self.path.parent / "loaded.json",
                    InferenceStartupMessage,
                    self.request.receipt_limit_bytes,
                )
            except FileNotFoundError:
                if terminal:
                    raise ValueError(
                        "inference exited without a verified checkpoint receipt"
                    ) from None
                return
            spec = self.request.spec
            if spec.inference_checkpoint is None or spec.inference_binding is None:
                raise ValueError("startup requires checkpoint-bound inference")
            expected = InferenceStartupMessage(
                nonce=self.request.nonce,
                child_pid=child_pid,
                reference=spec.inference_checkpoint,
                binding_sha256=spec.inference_binding.request_sha256,
            )
            if loaded != expected:
                raise ValueError("loaded checkpoint receipt differs from the current child/request")
            if (
                inference_measurement_binding(spec, environ=self.environment)
                != spec.inference_binding
            ):
                raise ValueError("inference sources changed before authorization")
            if self.clock() >= self.request.deadline_at:
                raise TimeoutError("inference authorization preparation exhausted its allowance")
            if self.control is not None:
                decision = self.control.check_control()
                if decision.status == "stop":
                    raise RuntimeError(f"inference authorization refused: {decision.reason}")
            publish_message(
                self.path.parent / "authorized.json", loaded, self.request.receipt_limit_bytes
            )
            published = self.clock()
            self.receipt = self.receipt.model_copy(
                update={"loaded": loaded, "published_at": published}
            )
            self.on_publication(published)
            if published >= self.request.deadline_at:
                raise TimeoutError("inference authorization publication exhausted its allowance")
        published_at = self.published_at
        assert published_at is not None
        if self.receipt.consumed is None:
            if self.clock() - published_at >= self.request.ack_timeout_seconds:
                raise TimeoutError("inference authorization consumption observation was late")
            try:
                consumed = read_message(
                    self.path.parent / "consumed.json",
                    InferenceStartupMessage,
                    self.request.receipt_limit_bytes,
                )
            except FileNotFoundError:
                if terminal or self.clock() - published_at >= self.request.ack_timeout_seconds:
                    raise TimeoutError(
                        "inference authorization consumption was not confirmed"
                    ) from None
                return
            if consumed != self.receipt.loaded:
                raise ValueError("inference consumption receipt differs from its authorization")
            self.receipt = self.receipt.model_copy(update={"consumed": consumed})
