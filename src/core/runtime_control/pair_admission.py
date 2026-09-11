"""Host-aware aggregate VRAM admission for concurrently-running chains.

Per-chain admission answers "does THIS attempt fit the device?". On a
shared host that is not the binding constraint: this machine enforces a
per-user quota over the SUM of every process the user owns, and when the
sum is exceeded a root watchdog picks a process and signals it. During
C12 that watchdog reaped a probe holding 31,266 MiB against a 30,000 MiB
quota — the first component to notice was the watchdog, and what it
produced was a kill, not a rejection.

This module makes the pair the unit of admission, so the aggregate is
checked BEFORE anything is launched or admitted:

    Σ predicted peak VRAM over concurrent members  ≤  aggregate ceiling

The ceiling is deliberately below the host quota. The gap absorbs what a
prediction cannot see — allocator fragmentation, the CUDA context of each
process, and the fact that a peak is an instant rather than a plateau.

Units are the whole point of the exercise here, so they are explicit
everywhere and never inferred:

* the host watchdog and `nvidia-smi` report **MiB** while calling it MB;
* torch reports **bytes**;
* operator-facing configuration is in **GiB**.

Every conversion goes through the helpers below, which are 1024-based and
tested against exact values, so a factor-of-1000 error cannot survive.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.execution_calibration import MalformedCeilingOverride

#: Exact, 1024-based. Named so no call site has to remember which it is.
BYTES_PER_KIB = 1024
BYTES_PER_MIB = 1024**2
BYTES_PER_GIB = 1024**3
MIB_PER_GIB = 1024

#: Operator-set aggregate ceiling for one concurrent pair, in GiB
#: (operator decision 2026-07-31). Below the host quota on purpose.
DEFAULT_PAIR_CEILING_GIB = 28.0

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


def host_quota_gib() -> float | None:
    """The declared per-user total quota in GiB, or None if undeclared.

    Undeclared means unknown, not unlimited: callers must not treat None
    as headroom.

    F-SCANG-3: a value that is SET but unusable — non-numeric, zero, or
    negative — is REFUSED via :class:`MalformedCeilingOverride` instead of
    silently resolving to "undeclared". The silent shape let a typo'd
    quota vanish, so every admission decision ran as if the host had
    never declared one, with no diagnostic anywhere. There is no
    0-disables semantics here (unlike ``SIDERIUS_SUBPROCESS_RSS_GB``):
    unset the variable to mean undeclared.

    An EMPTY string ("") still behaves as unset — a deliberate,
    preserved-behavior DIVERGENCE from ``SIDERIUS_SUBPROCESS_RSS_GB``,
    which refuses "". An empty value is the shell-wrapper pass-through
    pattern (``VAR="${VAR:-}"``), not a typo'd number; the class this
    refusal repairs is silently-consumed TYPOS.

    Raises:
        MalformedCeilingOverride: the variable is set to a non-numeric
            or non-positive value.
    """
    raw = os.environ.get(HOST_VRAM_QUOTA_MIB_ENV)
    if not raw:
        return None
    try:
        mib = float(raw)
    except ValueError:
        raise MalformedCeilingOverride(
            f"{HOST_VRAM_QUOTA_MIB_ENV}={raw!r} is not a number of MiB. "
            f"Set a positive number of MiB, or unset it to mean "
            f"undeclared. It is NOT ignored: a silently-ignored override "
            f"is how a run comes to execute under limits nobody chose."
        ) from None
    if mib <= 0:
        raise MalformedCeilingOverride(
            f"{HOST_VRAM_QUOTA_MIB_ENV}={raw!r} is not positive. There is "
            f"NO 0-disables semantics for this variable (unlike "
            f"SIDERIUS_SUBPROCESS_RSS_GB); unset it to mean "
            f"undeclared/default."
        )
    return gib_from_mib(mib)


def pair_ceiling_gib() -> float:
    """The aggregate ceiling actually in force.

    The operator ceiling stands unless the deployment declares a quota
    that is tighter still, in which case the quota wins — a ceiling above
    the enforced limit would be no ceiling at all.

    F-SCANG-3: an override that is SET but unusable — non-numeric, zero,
    or negative — is REFUSED via :class:`MalformedCeilingOverride`. The
    silent shape was the named incident: a typo'd value silently capped
    the arm at :data:`DEFAULT_PAIR_CEILING_GIB` (28.0 — the operator
    default calibrated on the lilab RTX 5090 host) with no diagnostic —
    no log line, no lock entry, no preflight row.
    There is no 0-disables semantics here (unlike
    ``SIDERIUS_SUBPROCESS_RSS_GB``): unset the variable to use the
    operator default.

    An EMPTY string ("") still behaves as unset — a deliberate,
    preserved-behavior DIVERGENCE from ``SIDERIUS_SUBPROCESS_RSS_GB``,
    which refuses "". An empty value is the shell-wrapper pass-through
    pattern (``VAR="${VAR:-}"``), not a typo'd number; the class this
    refusal repairs is silently-consumed TYPOS.

    Raises:
        MalformedCeilingOverride: this variable — or, transitively,
            ``SIDERIUS_GPU_VRAM_QUOTA_MIB`` via :func:`host_quota_gib` —
            is set to a non-numeric or non-positive value.
    """
    ceiling = DEFAULT_PAIR_CEILING_GIB
    raw = os.environ.get(PAIR_CEILING_GIB_ENV)
    if raw:
        try:
            configured = float(raw)
        except ValueError:
            raise MalformedCeilingOverride(
                f"{PAIR_CEILING_GIB_ENV}={raw!r} is not a number of GiB. "
                f"Set a positive number of GiB, or unset it to use the "
                f"operator default ({DEFAULT_PAIR_CEILING_GIB} GiB). It "
                f"is NOT ignored: before this refusal, a typo here "
                f"silently capped the arm at the "
                f"{DEFAULT_PAIR_CEILING_GIB} GiB default with no "
                f"diagnostic."
            ) from None
        if configured <= 0:
            raise MalformedCeilingOverride(
                f"{PAIR_CEILING_GIB_ENV}={raw!r} is not positive. There "
                f"is NO 0-disables semantics for this variable (unlike "
                f"SIDERIUS_SUBPROCESS_RSS_GB); unset it to use the "
                f"operator default ({DEFAULT_PAIR_CEILING_GIB} GiB)."
            )
        ceiling = configured
    quota = host_quota_gib()
    return min(ceiling, quota) if quota is not None else ceiling


class PairMember(BaseModel):
    """One concurrent chain and what it is predicted to hold."""

    model_config = ConfigDict(frozen=True)

    run_name: str = Field(min_length=1)
    predicted_peak_vram_gb: float = Field(gt=0.0)
    #: Where the number came from. A prediction with no provenance is not
    #: evidence, and the decision records it so a later audit can tell a
    #: measured peak from a configured cap.
    provenance: str = Field(min_length=1)


class PairAdmissionDecision(BaseModel):
    """Whether a set of chains may run concurrently, and why."""

    model_config = ConfigDict(frozen=True)

    feasible: bool
    aggregate_gib: float = Field(ge=0.0)
    ceiling_gib: float = Field(gt=0.0)
    headroom_gib: float
    members: tuple[PairMember, ...] = ()
    host_quota_gib: float | None = None
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
    """Decide whether these members may hold the device at the same time.

    Pure: every input is explicit, so the same inputs always give the
    same decision and the decision can be recorded and re-checked.
    """
    members = tuple(members)
    if not members:
        raise ValueError("a pair admission decision needs at least one member")
    ceiling = ceiling_gib if ceiling_gib is not None else pair_ceiling_gib()
    if ceiling <= 0:
        raise ValueError(f"aggregate ceiling must be positive, got {ceiling}")

    aggregate = sum(m.predicted_peak_vram_gb for m in members)
    feasible = aggregate <= ceiling
    quota = host_quota_gib()

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
            f"INFEASIBLE under the host quota: over the ceiling by "
            f"{aggregate - ceiling:.2f} GiB. Do not run these concurrently — "
            "the alternative is letting the host watchdog discover it and "
            "signal one of them."
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

    decision = evaluate_configured_caps(caps, ceiling_gib=args.ceiling_gib)
    if args.json:
        print(json.dumps(decision.model_dump(mode="json"), indent=1))
    else:
        for reason in decision.reasons:
            print(reason)
    return 0 if decision.feasible else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
