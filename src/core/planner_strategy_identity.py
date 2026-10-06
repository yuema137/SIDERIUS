"""Portable identity of a planner provider and its framework prompt assembly."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field


class PlannerStrategyIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    version: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assembly_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def source_fingerprint(sources: Mapping[str, bytes]) -> str:
    """Hash labelled source bytes without absolute installation paths."""
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
