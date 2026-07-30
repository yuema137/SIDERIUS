"""
core/runtime_control/observation_store.py

Append-only observation store + derived historical priors (RT2-F).

Design: docs/design/runtime_estimation_and_watchdog.md §6 — raw
observations are the source of truth; calibration is a derived view.
Pipeline: append-only observations → eligibility filtering (§6c) →
aggregation → historical prior, with §6b invalidation (environment
mismatch, drift eviction, age staleness) applied at LOOKUP time so a
prior can never silently outlive the conditions it was measured under.

Concurrency (§6.3): one JSONL file PER WRITER
(``observations_{writer_id}.jsonl``); a writer only ever appends to its
own file, so concurrent chains cannot interleave partial lines. Reads
merge every ``observations_*.jsonl`` in the root; malformed lines are
skipped and reported — store corruption fails safely and never yields a
formal-eligible estimate (§6.3).

Raw observations are NEVER deleted or overwritten; there is no update
or delete API on purpose.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.phases import RuntimePhase
from core.runtime_control.records import RuntimeObservation

_WRITER_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

#: final_status values whose observations may feed calibration (§6c).
_CALIBRATION_ELIGIBLE_STATUSES: frozenset[str] = frozenset({"completed", "inference_complete"})


class PriorPolicy(BaseModel):
    """§6b invalidation / §2.10 contract parameters (provisional defaults)."""

    model_config = ConfigDict(frozen=True)

    contract_factor: float = Field(
        default=1.5,
        gt=1.0,
        description="§2.10 acceptance factor F for the drift criterion.",
    )
    drift_consecutive: int = Field(
        default=3,
        ge=1,
        description="Consecutive contract violations that evict a prior (§6b rule 4).",
    )
    max_age_days: float = Field(
        default=90.0,
        gt=0.0,
        description="Entries older than this are STALE — reusable only with an elevated safety factor (§6b rule 5).",
    )


class PriorLookup(BaseModel):
    """Outcome of a historical-prior lookup for one calibration key."""

    model_config = ConfigDict(frozen=True)

    status: Literal["valid", "stale", "absent", "evicted_drift", "env_mismatch"]
    prior_unit_ms: float | None = Field(default=None, gt=0.0)
    n_observations: int = Field(default=0, ge=0)
    newest_timestamp: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


def calibration_key(
    phase: RuntimePhase,
    *,
    gpu_name: str | None,
    torch_version: str | None,
    precision: str,
    optimizer_type: str,
    model_family: str,
    param_count: int,
    seg_size: int,
    batch_size: int,
) -> str:
    """§6a calibration key — every factor demonstrably moves unit time.

    ``param_count`` collapses to a log2 bucket; ``seg_size`` stays exact
    (operator-chosen discrete values — bucketing would alias
    meaningfully different sizes, e.g. 1250 vs 2500).
    """
    torch_major = (torch_version or "unknown").split(".")[0]
    log2_bucket = int(math.log2(param_count)) if param_count > 0 else 0
    return "|".join(
        [
            f"phase={phase}",
            f"gpu={gpu_name or 'unknown'}",
            f"torch{torch_major}",
            f"prec={precision}",
            f"opt={optimizer_type}",
            f"family={model_family}",
            f"p2^{log2_bucket}",
            f"seg={seg_size}",
            f"bs={batch_size}",
        ]
    )


def observation_calibration_key(obs: RuntimeObservation, phase: RuntimePhase) -> str | None:
    """Key for one observation's phase, from its recorded calibration context.

    Returns ``None`` when the observation lacks the context — such
    observations remain evidence but never feed calibration.
    """
    ctx = obs.calibration_context
    required = ("precision", "optimizer_type", "model_family", "param_count", "seg_size")
    if not ctx or any(k not in ctx for k in required):
        return None
    return calibration_key(
        phase,
        gpu_name=obs.hardware.get("gpu_name"),
        torch_version=obs.software.get("torch_version"),
        precision=str(ctx["precision"]),
        optimizer_type=str(ctx["optimizer_type"]),
        model_family=str(ctx["model_family"]),
        param_count=int(ctx["param_count"]),
        seg_size=int(ctx["seg_size"]),
        batch_size=int(ctx.get("batch_size", 0)),
    )


def component_calibration_eligible(obs: RuntimeObservation, phase: RuntimePhase) -> bool:
    """§6c: only clean, representative observations update calibration.

    Requires: an eligible terminal status, no watchdog involvement, no
    rejected admission, and a phase component with BOTH a steady
    measurement and a positive realized workload/actual.
    """
    if obs.final_status not in _CALIBRATION_ELIGIBLE_STATUSES:
        return False
    if obs.watchdog_status is not None:
        return False
    if obs.admission is not None and obs.admission.decision != "admitted":
        # C9c: BOTH failure classes are excluded, and so is a legacy record
        # that carries no class at all — an unclassified refusal is not a
        # claim that the run was clean. Checking `!= "admitted"` rather than
        # `== "rejected"` keeps that true for any future decision value.
        return False
    component = obs.components.get(phase)
    if component is None or component.measurement is None:
        return False
    return component.measurement.steady_state_reached


def realized_unit_ms(obs: RuntimeObservation, phase: RuntimePhase) -> float | None:
    """The phase's REALIZED unit time: actual ÷ unit_count (preferred),
    falling back to the steady measurement median.

    The realized value includes everything the phase actually paid
    (reconstructions, allocator behavior) — strictly better calibration
    evidence than the verification-window median when available.
    """
    component = obs.components.get(phase)
    if component is None:
        return None
    if (
        component.actual_seconds is not None
        and component.workload is not None
        and component.workload.unit_count > 0
    ):
        return component.actual_seconds * 1000.0 / component.workload.unit_count
    if component.measurement is not None:
        return component.measurement.unit_time_ms_median
    return None


class ObservationStore:
    """Append-only per-writer JSONL store with merged reads (§6.3)."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        os.makedirs(root_dir, exist_ok=True)

    def _writer_path(self, writer_id: str) -> str:
        if not _WRITER_ID_RE.match(writer_id):
            raise ValueError(
                f"writer_id {writer_id!r} invalid: must match {_WRITER_ID_RE.pattern} "
                "(it names this writer's private JSONL file)."
            )
        return os.path.join(self.root_dir, f"observations_{writer_id}.jsonl")

    def append(self, observation: RuntimeObservation, *, writer_id: str) -> str:
        """Append one observation to this writer's file. Returns the path.

        Single ``write()`` of one newline-terminated line in append mode
        — a writer's own lines can never interleave, and no other
        process writes this file (§6.3 one-file-per-chain contract).
        """
        path = self._writer_path(writer_id)
        line = json.dumps(observation.model_dump(mode="json")) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        return path

    def read_all(self) -> list[RuntimeObservation]:
        """Merge every writer's file; malformed lines skipped + reported."""
        observations: list[RuntimeObservation] = []
        try:
            names = sorted(os.listdir(self.root_dir))
        except OSError:
            return []
        for name in names:
            if not (name.startswith("observations_") and name.endswith(".jsonl")):
                continue
            path = os.path.join(self.root_dir, name)
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError as exc:
                print(f"[observation_store] unreadable {path}: {exc}")
                continue
            for lineno, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                try:
                    observations.append(RuntimeObservation.model_validate(json.loads(line)))
                except Exception as exc:
                    print(f"[observation_store] skipping {name}:{lineno}: {exc}")
        return observations

    # ── Derived priors ───────────────────────────────────────────────────

    def lookup_prior(
        self,
        key: str,
        phase: RuntimePhase,
        *,
        policy: PriorPolicy | None = None,
        current_gpu_name: str | None = None,
        current_torch_version: str | None = None,
        now: float | None = None,
    ) -> PriorLookup:
        """Derive the historical prior for ``key`` with §6b invalidation.

        Environment mismatch is structurally impossible for gpu/torch
        (they are part of the key), but the CALLER's current environment
        is still checked against the key so a stale key from another
        host is never cross-applied (§6b rules 1-2).

        Args:
            key:    ``calibration_key(...)`` string.
            phase:  Phase whose unit time is being derived.
            policy: §6b parameters.
            current_gpu_name / current_torch_version: the environment
                    about to CONSUME the prior.
            now:    Override for age computation (tests).
        """
        policy = policy or PriorPolicy()
        if current_gpu_name is not None and f"gpu={current_gpu_name}|" not in key + "|":
            return PriorLookup(status="env_mismatch")
        if current_torch_version is not None:
            major = current_torch_version.split(".")[0]
            if f"|torch{major}|" not in f"|{key}|":
                return PriorLookup(status="env_mismatch")

        matching: list[tuple[str, float, float | None]] = []
        for obs in self.read_all():
            if observation_calibration_key(obs, phase) != key:
                continue
            if not component_calibration_eligible(obs, phase):
                continue
            unit_ms = realized_unit_ms(obs, phase)
            if unit_ms is None or unit_ms <= 0:
                continue
            component = obs.components.get(phase)
            log_error = (
                component.prediction_error.log_error
                if component is not None and component.prediction_error is not None
                else None
            )
            matching.append((obs.timestamp, unit_ms, log_error))
        if not matching:
            return PriorLookup(status="absent")

        matching.sort(key=lambda t: t[0])  # ISO timestamps sort lexically

        # §6b rule 4 — drift eviction: N consecutive newest observations
        # violating the §2.10 contract evict the prior entirely.
        recent_errors = [e for _, _, e in matching if e is not None][-policy.drift_consecutive :]
        if len(recent_errors) >= policy.drift_consecutive and all(
            e > math.log(policy.contract_factor) for e in recent_errors
        ):
            return PriorLookup(status="evicted_drift", n_observations=len(matching))

        values = sorted(v for _, v, _ in matching)
        median = values[len(values) // 2]
        newest_ts = matching[-1][0]
        status: Literal["valid", "stale"] = "valid"
        age_seconds = _age_seconds(newest_ts, now=now)
        if age_seconds is None or age_seconds > policy.max_age_days * 86400.0:
            status = "stale"  # §6b rule 5 — elevated safety factor until refreshed
        return PriorLookup(
            status=status,
            prior_unit_ms=median,
            n_observations=len(matching),
            newest_timestamp=newest_ts,
            provenance={
                "key": key,
                "aggregation": "median_of_realized_unit_ms",
                "observation_count": len(matching),
            },
        )


def _age_seconds(timestamp: str, *, now: float | None = None) -> float | None:
    """Age of an observation timestamp (``%Y-%m-%dT%H:%M:%S%z``); None if unparseable."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            then = time.mktime(time.strptime(timestamp, fmt))
            return (now if now is not None else time.time()) - then
        except ValueError:
            continue
    return None
