"""Shared, dependency-light values for Data Analysis contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class FrozenModel(BaseModel):
    """Default boundary posture for new Data Analysis schemas."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class CertifiedArtifactRef(FrozenModel):
    """Host-independent artifact identity plus a caller-resolvable logical ref."""

    logical_ref: NonEmptyStr
    sha256: Sha256
    media_type: NonEmptyStr
    byte_size: int | None = Field(default=None, ge=0)


class CallerIdentity(FrozenModel):
    caller_id: NonEmptyStr
    caller_type: Annotated[
        str,
        StringConstraints(pattern=r"^(human|workflow|orchestrator|capability)$"),
    ]
    request_source: str | None = None
