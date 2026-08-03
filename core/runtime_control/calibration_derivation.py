"""One measurement, two views: System A's record derived into System B's.

V20 PR C1 / C-C3c. Operator architecture, 2026-08-03 UTC:

    System A remains the single source of truth for measured runtime
    duration. System B must not perform or invent a second duration
    measurement. It receives a typed, deterministic derivative of the
    `RuntimeObservation` System A already writes after a successful phase.

So this module is a PURE CONVERTER. It performs no I/O, runs no probe, and
recomputes no timing: the duration it emits is the one System A measured,
carried across unchanged.

WHY A DERIVATION AND NOT A SECOND PROBE. The audit that produced this
checkpoint found the calibration registry was written only through the
REQUEST_PROBE gate, which the happy path cannot open -- 20 records on the
one live machine, all from a path that fires on failure. Meanwhile System A
writes a real, steady-state duration on every successful attempt, at a
HIGHER evidence tier (`real_training_verification`, tier 4) than a bounded
probe (tier 2). Running a probe to populate the registry would spend GPU
time measuring with a worse instrument while a better one is already
running.

WHICH OBSERVATIONS QUALIFY IS NOT A NEW QUESTION. `observation_store.
component_calibration_eligible` already answers it -- eligible terminal
status, no watchdog involvement, no rejected admission, and a phase
component carrying a steady-state measurement. This module reuses that gate
rather than inventing a second notion of "clean enough to calibrate", which
would drift from it.

WHAT THIS MODULE MUST NOT DO. The tuner's shared
`_append_runtime_observation` helper has four production call sites, and
three of them record failures -- a subprocess rejection, an evidence-channel
failure and a wall-clock timeout. Deriving calibration there would feed
failure evidence into throughput calibration, which `calibration_policy`
forbids at `:279-285` and explicitly anticipates ("should another producer
ever record failure evidence as an observation"). The production hook is the
SUCCESS call site only.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.observation_store import component_calibration_eligible
from core.runtime_control.phases import RuntimePhase
from core.runtime_control.records import RuntimeObservation
from core.runtime_control.registry_schemas import (
    CalibrationObservation,
    MeasurementIdentity,
)

#: System A's measurement units, mapped to the phase they describe. Explicit
#: rather than a cast: an unrecognised unit means we do not know what was
#: measured, and guessing would put an unknown quantity in a bucket other
#: measurements are averaged into.
SUPPORTED_UNITS: dict[str, RuntimePhase] = {
    "optimizer_step": "training",
    "inference_batch": "inference",
    "segment": "inference",
}

#: Phases this converter will derive from. `setup` is measured by System A
#: but is not a throughput rate, and `scoring`/`orchestration` have no
#: production measurement yet. Anything outside this set quarantines rather
#: than being reinterpreted.
DERIVABLE_PHASES: tuple[RuntimePhase, ...] = ("training", "inference")


class IdentityContext(BaseModel):
    """The identity System A's record does not carry.

    `RuntimeObservation.hardware` holds `gpu_name` and `hostname` -- a model
    of card, not the card -- so the device INSTANCE has to be supplied. Task
    and data-shape class come from the resolved measurement capability, and
    the stack from the shared capture helper.

    Every field is required and non-blank: a caller that cannot supply one
    should not be constructing this, and the derivation will quarantine.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_identity: str = Field(min_length=1)
    data_shape_class: str = Field(min_length=1)
    hardware_uuid: str = Field(min_length=1)
    runtime_stack_identity: str = Field(min_length=1)


class DerivedDurationRecord(BaseModel):
    """An eligible derivation: identity, the measured fact, and its source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: MeasurementIdentity
    measurement_unit: str = Field(min_length=1)
    measured_value_ms: float = Field(gt=0.0)
    n_measured_units: int = Field(ge=1)
    #: Envelope inputs, read from what was actually run.
    workload: dict[str, Any] = Field(default_factory=dict)
    #: Links the derivative to the System A event it came from, so the same
    #: event reprocessed is recognisable rather than duplicated.
    source_reference: dict[str, Any] = Field(default_factory=dict)


class QuarantinedDerivation(BaseModel):
    """The measurement happened; the identity is not complete enough to use.

    Carries the measured fact anyway (O-2): refusing to record it would
    destroy evidence and tell the operator nothing about how often identity
    is incomplete.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(min_length=1)
    missing_identity_fields: tuple[str, ...] = ()
    observation_payload: dict[str, Any] = Field(default_factory=dict)
    source_reference: dict[str, Any] = Field(default_factory=dict)


class NotDerivable(BaseModel):
    """This observation is not calibration evidence at all.

    Distinct from quarantine: a rejected, watchdog-killed or non-steady
    attempt is not an incomplete identity, it is an event that must never
    reach throughput calibration. Nothing is persisted for it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(min_length=1)


DerivationResult = DerivedDurationRecord | QuarantinedDerivation | NotDerivable
DerivationKind = Literal["eligible", "quarantined", "not_derivable"]


def _source_reference(obs: RuntimeObservation, phase: RuntimePhase) -> dict[str, Any]:
    """Stable link back to the System A event.

    Deterministic, so the same event derives to the same content id and the
    registry's content addressing dedups it -- that is the idempotency
    mechanism, not a separate ledger.
    """
    return {
        "system_a_timestamp": obs.timestamp,
        "chain_id": obs.chain_id,
        "attempt_id": obs.attempt_id,
        "phase": phase,
        "derived_from": "runtime_observation",
    }


def derive_duration_calibration_record(
    obs: RuntimeObservation,
    phase: RuntimePhase,
    *,
    identity: IdentityContext | None,
) -> DerivationResult:
    """Convert one phase of a System A observation into a v2 derivation.

    Pure: no filesystem, no registry, no clock. Returns exactly one of
    eligible / quarantined / not-derivable, so the caller never has to infer
    which happened from a None.
    """
    if phase not in DERIVABLE_PHASES:
        return NotDerivable(reason=f"phase {phase!r} is not a derivable throughput phase")

    # The existing production gate. Reusing it keeps one definition of
    # "clean enough to calibrate" instead of two that can drift.
    if not component_calibration_eligible(obs, phase):
        return NotDerivable(
            reason=(
                f"{phase}: not calibration-eligible under the existing rule "
                "(terminal status, watchdog, admission, or no steady-state "
                "measurement)"
            )
        )

    component = obs.components.get(phase)
    measurement = component.measurement if component else None
    if measurement is None:  # pragma: no cover - the gate above implies it
        return NotDerivable(reason=f"{phase}: no measurement present")

    unit = measurement.unit
    expected_phase = SUPPORTED_UNITS.get(unit)
    if expected_phase is None:
        return QuarantinedDerivation(
            reason=f"unit {unit!r} has no explicit phase mapping; refusing to guess",
            missing_identity_fields=("measurement_unit",),
            observation_payload={"unit": unit, "phase": phase},
            source_reference=_source_reference(obs, phase),
        )

    context = obs.calibration_context or {}
    model_family = str(context.get("model_family") or "").strip()

    missing: list[str] = []
    if identity is None:
        missing.append("identity_context")
    if not model_family:
        missing.append("model_family")

    measured_ms = float(measurement.unit_time_ms_median)
    payload = {
        "unit": unit,
        "phase": phase,
        "measured_value_ms": measured_ms,
        "n_measured_units": measurement.n_measured_units,
        "calibration_context": dict(context),
    }

    if missing:
        return QuarantinedDerivation(
            reason=(
                "the measurement is real but its identity is incomplete: " + ", ".join(missing)
            ),
            missing_identity_fields=tuple(missing),
            observation_payload=payload,
            source_reference=_source_reference(obs, phase),
        )

    assert identity is not None  # narrowed by `missing` above
    return DerivedDurationRecord(
        identity=MeasurementIdentity(
            measurement_kind="duration",
            task_identity=identity.task_identity,
            data_shape_class=identity.data_shape_class,
            model_family=model_family,
            candidate_config_hash=_config_hash(context),
            phase=phase,
            hardware_uuid=identity.hardware_uuid,
            runtime_stack_identity=identity.runtime_stack_identity,
        ),
        measurement_unit=unit,
        measured_value_ms=measured_ms,
        n_measured_units=measurement.n_measured_units,
        workload={
            k: context[k]
            for k in ("batch_size", "seg_size", "param_count")
            if isinstance(context.get(k), (int, float))
        },
        source_reference=_source_reference(obs, phase),
    )


def _config_hash(context: dict[str, Any]) -> str:
    """Deterministic identity for the candidate configuration.

    Built from the calibration context the trainer already records
    (precision, optimizer, family, params, segment, batch), so two
    materially different configurations of one family do not share a
    bucket.
    """
    from core.runtime_control.identity import config_hash12

    return f"cfg:{config_hash12(context)}"


# ── Persistence: the second responsibility, deliberately separate ───────────
#
# Derivation is pure; this writes. Keeping them apart is what makes the
# failure-isolation contract statable: a persistence failure cannot corrupt a
# derivation, and a derivation cannot half-write.


class PersistOutcome(BaseModel):
    """What persistence did, in a form the caller can record.

    Never raises for a storage problem. System A is already durable by the
    time this runs, and the operator rule for C-C3c is explicit: fail-open
    for the scientific workflow, fail-closed for calibration authority. A
    registry that is full, locked or absent must cost this run its
    calibration sample and nothing else.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["eligible", "quarantined", "not_derivable", "failed"]
    record_id: str | None = None
    #: Present for "failed" and "not_derivable"; the reason is always
    #: recordable, so a missing calibration sample is never silent.
    detail: str | None = None


def persist_duration_calibration_record(
    result: DerivationResult,
    *,
    registry: Any,
    hardware_compatibility_id: str,
    execution_environment_id: str,
    concurrency_identity: str,
    producer_identity: str,
    provenance: str,
    software_stack: dict[str, Any],
) -> PersistOutcome:
    """Write a derivation to the v2 registry, or explain why it did not.

    Idempotent through content addressing: an identical derivation produces
    an identical record id, which `record_observation` dedups. Reprocessing
    one System A event therefore cannot advance a promotion sample count
    twice -- there is no separate ledger to keep in step.
    """
    if isinstance(result, NotDerivable):
        return PersistOutcome(kind="not_derivable", detail=result.reason)

    try:
        if isinstance(result, QuarantinedDerivation):
            qid = registry.quarantine_observation(
                {**result.observation_payload, "source": result.source_reference},
                reason=result.reason,
                missing_identity_fields=result.missing_identity_fields,
            )
            return PersistOutcome(kind="quarantined", record_id=qid, detail=result.reason)

        observation = CalibrationObservation(
            operation=result.identity.phase,  # type: ignore[arg-type]
            measurement_unit=result.measurement_unit,
            measured_value_ms=result.measured_value_ms,
            workload=dict(result.workload),
            model_family=result.identity.model_family,
            identity=result.identity,
            hardware_compatibility_id=hardware_compatibility_id,
            execution_environment_id=execution_environment_id,
            concurrency_identity=concurrency_identity,  # type: ignore[arg-type]
            software_stack=dict(software_stack),
            producer_identity=producer_identity,
            provenance=provenance,  # type: ignore[arg-type]
            source_run=dict(result.source_reference),
            uncertainty_inputs={"n_measured_units": result.n_measured_units},
        )
        oid = registry.record_observation(observation)
        return PersistOutcome(kind="eligible", record_id=oid)
    except Exception as exc:
        # Explicit, not silent: the caller records this so an operator can
        # see that a sample was lost and why.
        return PersistOutcome(kind="failed", detail=f"{type(exc).__name__}: {exc}")
