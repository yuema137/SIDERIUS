"""Native inference checkpoint loading shared by production and measurement."""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable
from typing import Any, BinaryIO

from core.file_identity import (
    FileIdentityError,
    FileSnapshot,
    open_identity_file,
    path_matches_snapshot,
    regular_file_snapshot,
)
from core.runtime_control.inference_checkpoint_reference import InferenceCheckpointReference
from core.stream_identity import stream_file_identity


def assert_training_sentinel(model_path: str, exp_id: str) -> None:
    """Keep the trainer's completion marker and existing failure classification."""
    sentinel_path = os.path.join(os.path.dirname(model_path), f"_OK_{exp_id}")
    if not os.path.exists(sentinel_path):
        raise RuntimeError(
            f"error_training: checkpoint never written: {model_path} "
            f"(missing sentinel: {sentinel_path})"
        )


def load_inference_checkpoint(
    model: Any,
    model_path: str,
    exp_id: str,
    *,
    checkpoint_file: BinaryIO | None = None,
) -> Any:
    """Load on CPU into the resident model, preserving strictness and output units."""
    import torch

    from ml_models.target_standardization import load_trained_state

    assert_training_sentinel(model_path, exp_id)
    state_dict = torch.load(
        checkpoint_file if checkpoint_file is not None else model_path, map_location="cpu"
    )
    try:
        return load_trained_state(model, state_dict)
    finally:
        del state_dict


def load_bound_inference_checkpoint(
    model: Any,
    reference: InferenceCheckpointReference,
    *,
    deadline_at: float,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[Any, InferenceCheckpointReference]:
    """Verify and load one open file within the caller's existing worker budget.

    Two streaming checks detect ordinary concurrent changes, not hostile writers
    that can change and restore bytes during reads. The parent worker deadline
    and RSS bound remain responsible for blocked IO and native deserialization.
    """

    if not math.isfinite(deadline_at):
        raise ValueError("checkpoint measurement requires a finite deadline")

    def check_budget() -> None:
        if clock() >= deadline_at:
            raise TimeoutError("checkpoint verification exhausted the measurement deadline")

    def metadata(handle: BinaryIO) -> FileSnapshot:
        try:
            return regular_file_snapshot(handle, expected_size=reference.checkpoint_byte_size)
        except FileIdentityError as exc:
            if exc.reason == "not_regular":
                raise ValueError("inference checkpoint is not a regular file") from exc
            raise ValueError("inference checkpoint byte size differs from its reference") from exc

    def verify(handle: BinaryIO) -> None:
        handle.seek(0)
        digest, size = stream_file_identity(
            handle, byte_limit=reference.checkpoint_byte_size, check_budget=check_budget
        )
        if digest != reference.checkpoint_sha256 or size != reference.checkpoint_byte_size:
            raise ValueError("inference checkpoint bytes differ from their reference")

    check_budget()
    assert_training_sentinel(reference.checkpoint_path, reference.experiment_id)
    with open_identity_file(reference.checkpoint_path) as handle:
        before = metadata(handle)
        verify(handle)
        if metadata(handle) != before:
            raise ValueError("inference checkpoint changed during verification")
        handle.seek(0)
        check_budget()
        loaded = load_inference_checkpoint(
            model,
            reference.checkpoint_path,
            reference.experiment_id,
            checkpoint_file=handle,
        )
        check_budget()
        verify(handle)
        path_matches = path_matches_snapshot(reference.checkpoint_path, before)
        if metadata(handle) != before or not path_matches:
            raise ValueError("inference checkpoint changed during loading")
        check_budget()
    return loaded, reference
