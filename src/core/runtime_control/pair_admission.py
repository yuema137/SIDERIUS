"""Aggregate GPU admission from declared limits and measured device capacity.

An explicit operator ceiling overrides the environment operator ceiling. Host
quota and measured physical capacity constrain it independently. There is no
deployment-specific fallback. This module never discovers hardware or reserves
memory; callers supply capacity when making a device-backed decision.

Driver quantities are MiB, allocator quantities are bytes, and operator limits
are GiB. All conversions are binary and explicit.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, model_validator

from core.execution_calibration import MalformedCeilingOverride

#: Exact, 1024-based. Named so no call site has to remember which it is.
BYTES_PER_KIB = 1024
BYTES_PER_MIB = 1024**2
BYTES_PER_GIB = 1024**3
MIB_PER_GIB = 1024

#: The enforced per-user total, when the deployment declares one. A
#: deployment property, so it comes from the environment — never from the
#: checkout. Expressed in MiB because that is what the enforcing
#: components report.
HOST_VRAM_QUOTA_MIB_ENV = "SIDERIUS_GPU_VRAM_QUOTA_MIB"
PAIR_CEILING_GIB_ENV = "SIDERIUS_PAIR_VRAM_CEILING_GIB"


def gib_from_mib(mib: float) -> float:
    """MiB -> GiB. 30,000 MiB is 29.2969 GiB, not 30."""
    return mib / MIB_PER_GIB


def mib_from_gib(gib: float) -> float:
    """GiB -> MiB."""
    return gib * MIB_PER_GIB


def gib_from_bytes(value: int | float) -> float:
    """Bytes (torch) -> GiB."""
    return value / BYTES_PER_GIB


def bytes_from_gib(gib: float) -> float:
    """GiB -> bytes."""
    return gib * BYTES_PER_GIB


def _reject_boolean(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("a GPU limit must be a positive finite number, not a boolean")
    return value


PositiveGpuGiB = Annotated[
    float, BeforeValidator(_reject_boolean), Field(gt=0, allow_inf_nan=False)
]
_positive_limit = TypeAdapter(PositiveGpuGiB)


class ResolvedGpuCeiling(BaseModel):
    """One immutable resolution, consumed without reading the environment again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operator_ceiling_gib: PositiveGpuGiB | None
    operator_source: Literal["caller", "environment", "none"]
    host_quota_gib: PositiveGpuGiB | None
    measured_capacity_gib: PositiveGpuGiB | None

    @model_validator(mode="after")
    def _consistent_sources(self) -> ResolvedGpuCeiling:
        if (self.operator_ceiling_gib is None) != (self.operator_source == "none"):
            raise ValueError("operator ceiling and source must describe the same declaration")
        if all(value is None for value in self._limits()):
            raise ValueError(
                "No aggregate GPU limit is available. Supply measured device capacity, "
                "an explicit ceiling, SIDERIUS_PAIR_VRAM_CEILING_GIB, or a declared "
                "SIDERIUS_GPU_VRAM_QUOTA_MIB. No hardware is inferred."
            )
        return self

    def _limits(self) -> tuple[float | None, ...]:
        return self.operator_ceiling_gib, self.host_quota_gib, self.measured_capacity_gib

    @property
    def effective_gib(self) -> float:
        return min(value for value in self._limits() if value is not None)


def host_quota_gib(*, environ: Mapping[str, str] | None = None) -> float | None:
    """Read an optional positive finite MiB quota; empty still means undeclared.

    F-SCANG-3: a malformed declaration refuses rather than silently disappearing.
    This environment variable has no zero-disables semantics.
    """
    raw = (os.environ if environ is None else environ).get(HOST_VRAM_QUOTA_MIB_ENV)
    if not raw:
        return None
    try:
        mib = _positive_limit.validate_python(raw)
        return _positive_limit.validate_python(gib_from_mib(mib))
    except ValueError:
        raise MalformedCeilingOverride(
            f"{HOST_VRAM_QUOTA_MIB_ENV}={raw!r} must be positive finite MiB. "
            "There is no 0-disables semantics; unset it to mean undeclared."
        ) from None


def resolve_gpu_ceiling(
    *,
    ceiling_gib: float | None = None,
    measured_capacity_gib: float | None = None,
    environ: Mapping[str, str] | None = None,
) -> ResolvedGpuCeiling:
    """Resolve the selected operator declaration, independent quota and capacity."""
    env = dict(os.environ if environ is None else environ)
    source: Literal["caller", "environment", "none"] = "none"
    if ceiling_gib is not None:
        source = "caller"
    else:
        raw = env.get(PAIR_CEILING_GIB_ENV)
        if raw:
            try:
                ceiling_gib = _positive_limit.validate_python(raw)
            except ValueError:
                raise MalformedCeilingOverride(
                    f"{PAIR_CEILING_GIB_ENV}={raw!r} must be positive finite GiB. "
                    "There is no 0-disables semantics; unset it to use measured "
                    "capacity or an independently declared host quota."
                ) from None
            source = "environment"
    return ResolvedGpuCeiling(
        operator_ceiling_gib=ceiling_gib,
        operator_source=source,
        host_quota_gib=host_quota_gib(environ=env),
        measured_capacity_gib=measured_capacity_gib,
    )


def pair_ceiling_gib(*, measured_capacity_gib: float | None = None) -> float:
    """Resolve environment limits and optional capacity; never invent a default."""
    return resolve_gpu_ceiling(measured_capacity_gib=measured_capacity_gib).effective_gib


class PairMember(BaseModel):
    """One concurrent chain and what it is predicted to hold."""

    model_config = ConfigDict(frozen=True)

    run_name: str = Field(min_length=1)
    predicted_peak_vram_gb: PositiveGpuGiB
    #: Where the number came from. A prediction with no provenance is not
    #: evidence, and the decision records it so a later audit can tell a
    #: measured peak from a configured cap.
    provenance: str = Field(min_length=1)


class PairAdmissionDecision(BaseModel):
    """Whether a set of chains may run concurrently, and why."""

    model_config = ConfigDict(frozen=True)

    feasible: bool
    aggregate_gib: float = Field(ge=0.0, allow_inf_nan=False)
    ceiling_gib: PositiveGpuGiB
    headroom_gib: float = Field(allow_inf_nan=False)
    members: tuple[PairMember, ...] = ()
    host_quota_gib: PositiveGpuGiB | None = None
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _headroom_is_consistent(self) -> PairAdmissionDecision:
        expected = self.ceiling_gib - self.aggregate_gib
        if abs(self.headroom_gib - expected) > 1e-6:
            raise ValueError(
                f"headroom {self.headroom_gib} does not follow from "
                f"ceiling {self.ceiling_gib} - aggregate {self.aggregate_gib}"
            )
        if self.feasible != (self.aggregate_gib <= self.ceiling_gib):
            raise ValueError("feasible must follow from aggregate vs ceiling")
        return self


def evaluate_pair_admission(
    members: list[PairMember] | tuple[PairMember, ...],
    *,
    ceiling_gib: float | None = None,
) -> PairAdmissionDecision:
    """Resolve declared limits once, then compare the aggregate requirement."""
    return evaluate_resolved_pair_admission(
        members, limits=resolve_gpu_ceiling(ceiling_gib=ceiling_gib)
    )


def evaluate_resolved_pair_admission(
    members: list[PairMember] | tuple[PairMember, ...],
    *,
    limits: ResolvedGpuCeiling,
) -> PairAdmissionDecision:
    """Pure arithmetic over already resolved limits; no environment or driver I/O."""
    members = tuple(members)
    if not members:
        raise ValueError("a pair admission decision needs at least one member")
    ceiling = limits.effective_gib
    aggregate = sum(m.predicted_peak_vram_gb for m in members)
    if not math.isfinite(aggregate):
        raise ValueError("aggregate GPU requirement overflowed; a finite demand is required")
    feasible = aggregate <= ceiling
    quota = limits.host_quota_gib

    reasons = [
        f"{len(members)} concurrent member(s) predicted to hold "
        f"{aggregate:.2f} GiB against a {ceiling:.2f} GiB aggregate ceiling"
    ]
    for member in members:
        reasons.append(
            f"  {member.run_name}: {member.predicted_peak_vram_gb:.2f} GiB ({member.provenance})"
        )
    if not feasible:
        reasons.append(
            f"INFEASIBLE under the resolved aggregate ceiling: over by "
            f"{aggregate - ceiling:.2f} GiB. Reduce concurrent demand or revise "
            "the declared limits within actual device and deployment constraints."
        )
    if quota is not None:
        reasons.append(
            f"declared host per-user quota: {quota:.2f} GiB ({mib_from_gib(quota):.0f} MiB)"
        )
    else:
        reasons.append(
            "no host quota declared (" + HOST_VRAM_QUOTA_MIB_ENV + " unset): "
            "unknown, which is not the same as unlimited"
        )

    return PairAdmissionDecision(
        feasible=feasible,
        aggregate_gib=aggregate,
        ceiling_gib=ceiling,
        headroom_gib=ceiling - aggregate,
        members=members,
        host_quota_gib=quota,
        reasons=tuple(reasons),
    )


def evaluate_configured_caps(
    caps_gib: dict[str, float],
    *,
    ceiling_gib: float | None = None,
) -> PairAdmissionDecision:
    """The pre-launch check: can this CONFIGURATION exceed the ceiling?

    Before anything is proposed there is no prediction, so the only bound
    available is each chain's own per-attempt admission cap. Summing the
    caps answers a strictly weaker question — "could this pair ever
    exceed the ceiling?" — and that is exactly the question worth asking
    at launch time, because a configuration whose own caps sum above the
    quota can trip the host watchdog no matter what gets proposed.
    """
    return evaluate_pair_admission(
        [
            PairMember(
                run_name=name,
                predicted_peak_vram_gb=cap,
                provenance="configured per-attempt admission cap (not a measurement)",
            )
            for name, cap in sorted(caps_gib.items())
        ],
        ceiling_gib=ceiling_gib,
    )


def _cli(argv: list[str] | None = None) -> int:
    """`python -m core.runtime_control.pair_admission --caps a=16,b=16`

    Exists so the shell launchers can ask the SAME function the Python
    admission path asks — the guard must not be reimplemented in bash,
    where the unit handling this module exists to protect would have to
    be written a second time.

    Exit 0 = feasible, 1 = infeasible, 2 = bad usage.
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--caps",
        required=True,
        help="comma-separated run_name=gib pairs (configured per-attempt caps)",
    )
    parser.add_argument("--ceiling-gib", type=float, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    caps: dict[str, float] = {}
    for item in args.caps.split(","):
        name, _, value = item.partition("=")
        if not name.strip() or not value.strip():
            parser.error(f"malformed --caps entry {item!r}; expected run_name=gib")
        try:
            caps[name.strip()] = float(value)
        except ValueError:
            parser.error(f"non-numeric cap in {item!r}")

    try:
        decision = evaluate_configured_caps(caps, ceiling_gib=args.ceiling_gib)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(decision.model_dump(mode="json"), indent=1))
    else:
        for reason in decision.reasons:
            print(reason)
    return 0 if decision.feasible else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
