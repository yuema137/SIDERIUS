"""Inert source capture binding; origin paths never supply execution bytes."""

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from workflows.definition import parse_workflow_source

if TYPE_CHECKING:
    from .models import CandidateRunRequest


def validate_source(request: "CandidateRunRequest") -> None:
    capture = request.workflow_source
    if capture is None:
        return
    if hashlib.sha256(capture.source.encode("utf-8")).hexdigest() != capture.sha256:
        raise ValueError("workflow source hash mismatch")
    if parse_workflow_source(capture.source) != request.preview.document:
        raise ValueError("workflow source differs from preview document")


def verify_snapshot(request: "CandidateRunRequest", control: Path) -> None:
    if request.workflow_source is None:
        return
    # Match native observation nonblocking regular-file admission, and bound the
    # fixed snapshot read to the captured source size. Never follow an alias.
    import os
    import stat

    expected = request.workflow_source.source.encode("utf-8")
    descriptor = os.open(
        control / "workflow.py.snapshot", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    )
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("workflow source snapshot must be a regular file")
        if stream.read(len(expected) + 1) != expected:
            raise ValueError("workflow source snapshot mismatch")
