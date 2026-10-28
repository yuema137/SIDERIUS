"""Canonical JSON bytes and SHA-256 for framework records.

Encoding: ``json.dumps(value, sort_keys=True, separators=(",", ":"))`` with the
default ASCII escaping, the same bytes ``WorkflowDefinition.declaration_digest``
hashes. Pydantic models are dumped with ``mode="json"`` first. Used by the
adaptor record (``workflows.adaptors``) and custom adaptors
(``workflows.custom_adaptors``) so one value has one digest.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel


def canonical_json_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
