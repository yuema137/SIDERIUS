"""Canonical sorted-key, compact, ASCII JSON and SHA-256 for framework values.

Finite values retain their historical bytes. Non-finite values use the strict,
versioned typed-path encoding owned by core.record_encoding. Only replay of
unversioned evidence may reproduce historical bare JSON constants.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from core.record_encoding import (
    ENCODING_VERSION,
    EncodingVersion,
    canonical_value,
    model_record_value,
)


def canonical_json_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = model_record_value(value)
    return json.dumps(
        canonical_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def replay_json_bytes(
    value: BaseModel | dict[str, Any], *, version: EncodingVersion | None
) -> bytes:
    """Recompute recorded bytes, using legacy tokens only for unversioned evidence."""
    if version == ENCODING_VERSION:
        return canonical_json_bytes(value)
    if version is not None:
        raise ValueError("unsupported record encoding")
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
