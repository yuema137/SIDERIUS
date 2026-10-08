"""Explicit optional reviewed-launch request; no credentials or runtime objects."""

from pathlib import Path
from typing import Literal

from pydantic import Field

from tools.setup_review.semantic_models import Digest, ReviewModel, SnapshotOperation


class FindingDisposition(ReviewModel):
    index: int = Field(ge=0, strict=True)
    finding_sha256: Digest
    action: Literal["acknowledge"] = "acknowledge"
    reason: str = Field(min_length=1)


class ReviewedLaunchRequest(SnapshotOperation):
    receipt: Path
    receipt_sha256: Digest
    dispositions: tuple[FindingDisposition, ...] = ()
