"""Shared, dependency-light values for Data Analysis contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from core.record_encoding import (
    ENCODING_VERSION,
    EncodingVersion,
    RecordModel,
    canonical_value,
    model_record_value,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class FrozenModel(RecordModel):
    """Default boundary posture for new Data Analysis schemas."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    """Strict UTF-8 identities; finite bytes retain their historical spelling."""
    if isinstance(value, BaseModel):
        value = model_record_value(value)
    return json.dumps(
        canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def replay_json_bytes(value: Any, *, version: EncodingVersion | None) -> bytes:
    """Reproduce UTF-8 archive bytes under an explicitly selected encoding.

    The caller must verify the archive's trusted byte/digest anchor. A legacy
    null is irrecoverable and must never be interpreted as a non-finite float.
    """
    if version == ENCODING_VERSION:
        return canonical_json_bytes(value)
    if version is not None:
        raise ValueError("unsupported record encoding")
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


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
