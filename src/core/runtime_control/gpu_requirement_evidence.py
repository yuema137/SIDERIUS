"""Explicit ownership of a measured requirement, independent of admission policy.

A provenance category alone cannot distinguish an additional worker from an
already-live process tree. These inert records retain that distinction and the
measurement process's original lifecycle facts without discovering hardware.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.runtime_control.process_group import GroupObservation

if TYPE_CHECKING:
    from core.runtime_control.gpu_accounting import GpuAccountingSnapshot


class ProcessEvidence(BaseModel):
    """How the worker process ended. Facts, not a verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    worker_pid: int = Field(gt=0)
    worker_pgid: int = Field(gt=0)
    exit_code: int | None = None
    signal_number: int | None = None
    term_sent: bool = False
    kill_sent: bool = False
    #: Something in the group outlived the reap. It may still hold the
    #: device, so this is never silently ignored.
    orphans_remaining: bool = False
    group_cleanup_required: bool = False
    final_group_observation: GroupObservation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class GpuRequirementOwnership(BaseModel):
    """A completed isolated measurement used to size a *new* process tree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: Literal["new_worker_process_tree"]
    # A failed run may never observe a UUID. Keep its lifecycle facts without
    # inventing an identity; admission cannot use that missing device.
    device_uuid: str | None = Field(min_length=1)
    process: ProcessEvidence
    owned_pids: tuple[int, ...] = ()

    @property
    def completion_refusal(self) -> str | None:
        process = self.process
        if (
            process.exit_code != 0
            or process.signal_number is not None
            or process.term_sent
            or process.kill_sent
            or process.group_cleanup_required
            or process.orphans_remaining
            or (
                process.final_group_observation is not None
                and process.final_group_observation.status != "absent"
            )
        ):
            return "measurement worker did not establish a clean completed lifecycle"
        return None

    def applicability_refusal(self, snapshot: GpuAccountingSnapshot) -> str | None:
        """Refuse overlap, including conservative refusal on possible PID reuse."""
        if self.completion_refusal is not None:
            return self.completion_refusal
        measured_pids = {self.process.worker_pid, *self.owned_pids}
        current_pids = {p.pid for p in (*snapshot.own_processes, *snapshot.other_processes)}
        if measured_pids & current_pids:
            return "a measured worker PID is still present in current device occupancy"
        return None


class AdmissionRequirementEvidence(BaseModel):
    """One validated projection shared by typed tables and explicit dict callers."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    requirement_mib: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    provenance: str | None = None
    ownership: GpuRequirementOwnership | None = None
    validation_error: str | None = None

    @classmethod
    def from_entry(cls, entry: object) -> AdmissionRequirementEvidence:
        if entry is None:
            return cls()
        if not isinstance(entry, Mapping):
            return cls(validation_error="requirement entry is not a mapping")
        try:
            return cls.model_validate(entry)
        except ValidationError as error:
            # Field paths/types are sufficient diagnostics; do not echo arbitrary
            # values from a malformed external entry into an operator message.
            problems = ", ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in error.errors()
            )
            return cls(validation_error=f"invalid requirement evidence ({problems})")
