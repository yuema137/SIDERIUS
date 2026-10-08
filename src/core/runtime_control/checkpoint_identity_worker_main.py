"""Fixed CPU-only identity reader; no model imports or checkpoint deserialization."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

from core.file_identity import open_identity_file, path_matches_snapshot, regular_file_snapshot
from core.runtime_control.checkpoint_identity import (
    CheckpointIdentityReceipt,
    CheckpointIdentityRequest,
)
from core.runtime_control.inference_checkpoint_reference import InferenceCheckpointReference
from core.stream_identity import stream_file_identity
from execute_tools.inference_checkpoint import assert_training_sentinel


def identify_checkpoint(
    request: CheckpointIdentityRequest, *, clock: Callable[[], float] = time.monotonic
) -> InferenceCheckpointReference:
    """Two same-fd checks detect ordinary mutation within the parent-owned bound."""
    deadline = clock() + request.cooperative_seconds

    def check_budget() -> None:
        if clock() >= deadline:
            raise TimeoutError("checkpoint identity preparation deadline exhausted")

    check_budget()
    assert_training_sentinel(request.checkpoint_path, request.experiment_id)
    with open_identity_file(request.checkpoint_path, require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        first = stream_file_identity(handle, byte_limit=before.size, check_budget=check_budget)
        if regular_file_snapshot(handle) != before:
            raise ValueError("checkpoint changed during identity preparation")
        handle.seek(0)
        second = stream_file_identity(handle, byte_limit=before.size, check_budget=check_budget)
        if (
            first != second
            or first[1] != before.size
            or regular_file_snapshot(handle) != before
            or not path_matches_snapshot(request.checkpoint_path, before)
        ):
            raise ValueError("checkpoint changed during identity preparation")
        check_budget()
    return InferenceCheckpointReference(
        checkpoint_path=request.checkpoint_path,
        experiment_id=request.experiment_id,
        checkpoint_sha256=first[0],
        checkpoint_byte_size=first[1],
    )


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("checkpoint identity requires one request file", file=sys.stderr)
        return 2
    try:
        request = CheckpointIdentityRequest.model_validate_json(Path(arguments[0]).read_text())
    except (OSError, ValueError) as exc:
        print(f"checkpoint identity request unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2
    try:
        reference = identify_checkpoint(request)
        receipt = CheckpointIdentityReceipt(
            request_nonce=request.request_nonce, child_pid=os.getpid(), reference=reference
        )
    except (OSError, ValueError, RuntimeError) as exc:
        receipt = CheckpointIdentityReceipt(
            request_nonce=request.request_nonce,
            child_pid=os.getpid(),
            unavailable_reason=f"{type(exc).__name__}: {exc}",
        )
    print(receipt.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
