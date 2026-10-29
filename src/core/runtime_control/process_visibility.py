"""Explicit GPU process visibility and its execution-condition precedence.

An absent declaration preserves historical behavior; it does not certify a
global process view. A private PID namespace declares its limitation at launch.
This provenance is inherited by ordinary subprocesses, not discovered from PID
numbers or repaired by exposing a host process filesystem.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

PROCESS_VISIBILITY_ENV = "SIDERIUS_GPU_PROCESS_VISIBILITY"
ProcessVisibility = Literal["namespace_limited"]


class IsolatedHeadroomPolicy(BaseModel):
    """Selected isolation requires headroom evidence even in observe-only mode."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    headroom_policy: Literal["require_conservative_bound"] = "require_conservative_bound"
    refusal_enforcement: Literal["all_phase_modes"] = "all_phase_modes"


class GpuExecutionConditions(IsolatedHeadroomPolicy):
    process_visibility: ProcessVisibility


def declared_visibility(environ: Mapping[str, str] | None = None) -> ProcessVisibility | None:
    """Reject malformed explicit declarations rather than silently dropping them."""
    environment = os.environ if environ is None else environ
    if PROCESS_VISIBILITY_ENV not in environment:
        return None
    return GpuExecutionConditions.model_validate(
        {"process_visibility": environment[PROCESS_VISIBILITY_ENV]}
    ).process_visibility


def requires_isolated_admission(snapshot: object = None) -> bool:
    """Presence also covers malformed declarations and failed sampling."""
    return (
        PROCESS_VISIBILITY_ENV in os.environ
        or getattr(snapshot, "process_visibility", None) is not None
    )


class DeviceAvailability(BaseModel):
    """A transported hardware fact; neither an identity nor device discovery."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_available: StrictBool | None = None
