"""Known-path result reads through the shared regular-file identity owner."""

from __future__ import annotations

import hashlib
from io import FileIO
from pathlib import Path
from typing import cast

from core.file_identity import open_identity_file, path_matches_snapshot, regular_file_snapshot
from tools.setup_review.composition_models import (
    CHILD_RESULT_NAME,
    CompositionJob,
    CompositionResult,
)


def manifest_digest(path: str) -> str:
    """Observe the caller-selected manifest, detecting ordinary concurrent mutation."""
    with open_identity_file(path, require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        # The shared owner opens an unbuffered binary file descriptor (FileIO).
        digest = hashlib.file_digest(cast(FileIO, handle), "sha256").hexdigest()
        if regular_file_snapshot(handle) != before or not path_matches_snapshot(path, before):
            raise ValueError(
                "Selected manifest changed while being read; retry with unchanged inputs"
            )
    return digest


def read_composition_result(job: CompositionJob) -> CompositionResult:
    """Never open a child-returned path, follow a link or wait for a FIFO writer."""
    path = str(Path(job.scratch) / CHILD_RESULT_NAME)
    limit = job.settings.result_max_bytes
    overflow = (
        f"Child result exceeds result_max_bytes={limit}. Inspect the cause; if the expected "
        "task summary requires more space, explicitly raise --result-max-bytes and rerun."
    )
    with open_identity_file(path, require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        if before.size > limit:
            raise ValueError(overflow)
        payload = handle.read(limit + 1)
        if len(payload) > limit:
            raise ValueError(overflow)
        if regular_file_snapshot(handle) != before or not path_matches_snapshot(path, before):
            raise ValueError("Child result changed while being read")
    result = CompositionResult.model_validate_json(payload)
    if result.request_sha256 != job.digest or result.manifest_sha256 != job.manifest_sha256:
        raise ValueError("Child result does not match the selected check request/manifest")
    if result.outcome == "passed" and (result.task_settings is not None) != (
        job.task_settings is not None
    ):
        raise ValueError("Child result does not match the requested task-settings checks")
    return result
