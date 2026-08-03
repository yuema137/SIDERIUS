"""Whether this environment can measure, and what it would be measuring.

V20 PR C1 / C-C3, design §15.3.

`probe_wiring.probe_runner_availability()` refused unless `TIDMAD_DATA_DIR`
was a readable directory, and the tuner consults it before any bounded live
probe. So on any task other than TIDMAD the whole measured-evidence path
disabled itself, silently, and the run continued on static priors -- the V19
posture the V20 launch gate exists to end.

That is a task assumption expressed by *omission* inside generic
infrastructure, which is harder to find than a hardcoded constant and fails
without saying anything.

This module is generic. It knows that a measurement needs an accelerator, a
dataset root and an identity; it does not know which task, which dataset, or
where that dataset lives. Callers that know the task supply those, and every
one of them already holds the values:

    the tuner        `data_dir` is a parameter of
                     `_resolve_time_check_probe_request`
    the launch guard takes an optional dataset root from its caller
    the bootstrap    resolves the task's dataset itself

An unavailable capability must always say why. `probe_available=False` with
no `unavailability_reason` is refused by a validator: a measurement path
that turns itself off without a reason is exactly what this module replaces.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.phases import RuntimePhase


class ResolvedMeasurementCapability(BaseModel):
    """What this environment can measure, resolved once and passed around.

    Typed rather than a `(bool, str)` tuple because the identity travels
    with the verdict: a capability that says "yes" without saying which task
    and data shape it would be measuring cannot supply a
    `MeasurementIdentity` later, and the identity is the whole point of PR C.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Which task a measurement taken here would describe. Required even
    #: when unavailable -- "we cannot measure task X" is a more useful fact
    #: than "we cannot measure".
    task_identity: str = Field(min_length=1)
    #: Which adapter resolved the data. Names the task-owned component, so a
    #: record can be traced back to what produced it.
    dataset_adapter: str = Field(min_length=1)
    #: The data-shape class a measurement here would be taken under.
    data_shape_class: str = Field(min_length=1)

    probe_available: bool
    #: Required when `probe_available` is False. Never a bare False.
    unavailability_reason: str | None = None

    target_device: str | None = None
    #: Which phases this environment can measure. Empty when unavailable.
    supported_phases: tuple[RuntimePhase, ...] = ()
    #: The resolved dataset root, for the record's provenance. None when the
    #: caller supplied none.
    dataset_root: str | None = None

    @model_validator(mode="after")
    def _unavailable_must_explain(self) -> ResolvedMeasurementCapability:
        if not self.probe_available and not (self.unavailability_reason or "").strip():
            raise ValueError(
                "probe_available=False requires an unavailability_reason: a "
                "measurement path that switches itself off without saying why "
                "is the defect this model exists to prevent"
            )
        if self.probe_available and self.unavailability_reason:
            raise ValueError(
                "unavailability_reason is set while probe_available=True; a "
                "capability cannot be both usable and refused"
            )
        return self

    @property
    def detail(self) -> str:
        """One line for an operator log, available either way."""
        if self.probe_available:
            return (
                f"{self.task_identity}: measurable on {self.target_device} "
                f"({self.data_shape_class}, dataset at {self.dataset_root})"
            )
        return f"{self.task_identity}: not measurable — {self.unavailability_reason}"


def resolve_measurement_capability(
    *,
    task_identity: str,
    dataset_adapter: str,
    data_shape_class: str,
    dataset_root: str | None,
    supported_phases: tuple[RuntimePhase, ...] = ("training", "inference"),
) -> ResolvedMeasurementCapability:
    """Decide whether a real bounded probe can run here.

    Generic: the accelerator check is universal, and everything
    task-specific arrives as an argument. Never raises -- the caller decides
    whether unavailability is fatal (a real formal launch) or expected (a
    CPU or pseudo run), which is the same contract
    `probe_runner_availability` had.

    `dataset_root=None` is refused rather than defaulted. A default here
    would be a task assumption, and this module exists because there was one.
    """
    identity = {
        "task_identity": task_identity,
        "dataset_adapter": dataset_adapter,
        "data_shape_class": data_shape_class,
        "dataset_root": dataset_root,
    }

    def _no(reason: str) -> ResolvedMeasurementCapability:
        return ResolvedMeasurementCapability(
            **identity, probe_available=False, unavailability_reason=reason
        )

    try:
        import torch
    except ImportError:
        return _no("torch is not importable")
    if not torch.cuda.is_available():
        return _no("no CUDA device is visible")
    if not dataset_root:
        return _no("no dataset root was supplied by the caller")
    if not os.path.isdir(dataset_root):
        return _no(f"dataset directory not present at {dataset_root!r}")

    try:
        device_name = torch.cuda.get_device_name(0)
    except Exception:  # pragma: no cover - driver-shape guard
        device_name = "cuda"

    return ResolvedMeasurementCapability(
        **identity,
        probe_available=True,
        target_device=device_name,
        supported_phases=supported_phases,
    )
