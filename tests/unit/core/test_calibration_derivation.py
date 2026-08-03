"""System A's measurement, derived — never re-measured.

V20 PR C1 / C-C3c. Operator architecture, 2026-08-03 UTC: System A stays the
single source of truth for measured runtime duration; System B receives a
typed deterministic derivative of the `RuntimeObservation` System A already
writes after a successful phase.

These tests drive REAL preserved production records —
`docs/design/pregate_evidence/runtime_observations/*.jsonl`, H100 evidence
from the pre-gate campaign — rather than hand-built observations. The whole
class of defect this PR keeps finding is a converter that is correct against
a shape its producer never emits.

THREE OUTCOMES, NOT TWO. The converter returns exactly one of:

    DerivedDurationRecord   eligible; identity complete, measurement clean
    QuarantinedDerivation   the measurement is real, the identity is not
                            complete enough to bucket it (O-2)
    NotDerivable            this is not calibration evidence at all

The third is the one worth being careful about. A rejected attempt, a
watchdog kill or a non-steady measurement is not an incomplete identity that
might later be repaired -- it is an event that must never reach throughput
calibration, and nothing is persisted for it. Collapsing it into quarantine
would leave failure evidence sitting in a namespace whose purpose is
"salvageable".
"""

from __future__ import annotations

import json
import pathlib

import pytest

from core.runtime_control.calibration_derivation import (
    SUPPORTED_UNITS,
    DerivedDurationRecord,
    IdentityContext,
    NotDerivable,
    QuarantinedDerivation,
    derive_duration_calibration_record,
)
from core.runtime_control.records import RuntimeObservation

EVIDENCE = pathlib.Path("docs/design/pregate_evidence/runtime_observations")

CONTEXT = IdentityContext(
    task_identity="tidmad_denoise",
    data_shape_class="psd10000000_seg200_files20",
    hardware_uuid="GPU-1111-aaaa",
    runtime_stack_identity="stack:cb380df61b90",
)


def _raw() -> dict:
    """One real persisted System A record."""
    path = sorted(EVIDENCE.glob("*.jsonl"))[0]
    return json.loads(path.read_text().splitlines()[0])


def _observation(**mutations) -> RuntimeObservation:
    payload = json.loads(json.dumps(_raw()))
    for key, value in mutations.items():
        payload[key] = value
    return RuntimeObservation.model_validate(payload)


class TestTheMeasurementIsCarriedNotRecomputed:
    def test_the_duration_is_system_a_s_own_number(self):
        """The architectural constraint. If this ever differs from System A's
        median, System B has started measuring, which it must not."""
        obs = _observation()
        result = derive_duration_calibration_record(obs, "training", identity=CONTEXT)
        assert isinstance(result, DerivedDurationRecord)

        source = obs.components["training"].measurement
        assert source is not None
        assert result.measured_value_ms == source.unit_time_ms_median
        assert result.n_measured_units == source.n_measured_units
        assert result.measurement_unit == source.unit

    def test_it_is_always_a_duration_and_never_a_requirement(self):
        """A promoted millisecond must never be able to answer a memory
        query. `measurement_kind` is an identity dimension precisely so the
        two cannot meet."""
        result = derive_duration_calibration_record(_observation(), "training", identity=CONTEXT)
        assert isinstance(result, DerivedDurationRecord)
        assert result.identity.measurement_kind == "duration"

    def test_identity_comes_from_the_context_and_the_recorded_family(self):
        result = derive_duration_calibration_record(_observation(), "training", identity=CONTEXT)
        assert isinstance(result, DerivedDurationRecord)
        identity = result.identity
        assert identity.task_identity == CONTEXT.task_identity
        assert identity.hardware_uuid == CONTEXT.hardware_uuid
        assert identity.runtime_stack_identity == CONTEXT.runtime_stack_identity
        # The family is the trainer's own, not the context's -- System A and
        # System B must share one family namespace.
        assert identity.model_family == _raw()["calibration_context"]["model_family"]

    def test_the_envelope_inputs_are_what_actually_ran(self):
        result = derive_duration_calibration_record(_observation(), "training", identity=CONTEXT)
        assert isinstance(result, DerivedDurationRecord)
        context = _raw()["calibration_context"]
        assert result.workload["batch_size"] == context["batch_size"]
        assert result.workload["seg_size"] == context["seg_size"]

    def test_training_and_inference_derive_to_different_identities(self):
        train = derive_duration_calibration_record(_observation(), "training", identity=CONTEXT)
        infer = derive_duration_calibration_record(_observation(), "inference", identity=CONTEXT)
        assert isinstance(train, DerivedDurationRecord)
        assert isinstance(infer, DerivedDurationRecord)
        assert train.identity.identity_key != infer.identity.identity_key


class TestFailureEvidenceIsNotCalibrationEvidence:
    """The D4 rule, enforced at the converter.

    `calibration_policy.py:279-285` records it: "measured OOM, wall-cap hits
    and abnormal termination are valuable failure evidence but must not
    update throughput calibration", and anticipates "another producer" doing
    exactly that. This converter would be that producer if it did not gate.
    """

    @pytest.mark.parametrize(
        "label,mutation",
        [
            ("watchdog fired", {"watchdog_status": "killed"}),
            ("failed terminal status", {"final_status": "error"}),
        ],
    )
    def test_a_failed_attempt_yields_nothing(self, label, mutation):
        result = derive_duration_calibration_record(
            _observation(**mutation), "training", identity=CONTEXT
        )
        assert isinstance(result, NotDerivable), label
        assert result.reason

    def test_a_rejected_admission_yields_nothing(self):
        payload = json.loads(json.dumps(_raw()))
        payload["admission"]["decision"] = "rejected"
        obs = RuntimeObservation.model_validate(payload)
        assert isinstance(
            derive_duration_calibration_record(obs, "training", identity=CONTEXT), NotDerivable
        )

    def test_a_non_steady_measurement_yields_nothing(self):
        """A rate that had not stabilised is not a rate."""
        payload = json.loads(json.dumps(_raw()))
        payload["components"]["training"]["measurement"]["steady_state_reached"] = False
        obs = RuntimeObservation.model_validate(payload)
        assert isinstance(
            derive_duration_calibration_record(obs, "training", identity=CONTEXT), NotDerivable
        )

    def test_not_derivable_is_distinct_from_quarantine(self):
        """Failure evidence must not land in the salvageable namespace. A
        rejected attempt is not an identity that might later be repaired."""
        failed = derive_duration_calibration_record(
            _observation(final_status="error"), "training", identity=CONTEXT
        )
        incomplete = derive_duration_calibration_record(_observation(), "training", identity=None)
        assert isinstance(failed, NotDerivable)
        assert isinstance(incomplete, QuarantinedDerivation)

    @pytest.mark.parametrize("phase", ["setup", "scoring", "orchestration"])
    def test_a_non_throughput_phase_is_not_derivable(self, phase):
        """`setup` IS measured by System A, but it is not a throughput rate;
        scoring and orchestration have no production measurement. None may be
        reinterpreted as one."""
        result = derive_duration_calibration_record(_observation(), phase, identity=CONTEXT)
        assert isinstance(result, NotDerivable)


class TestIncompleteIdentityQuarantines:
    def test_a_missing_identity_context_quarantines_with_the_fact_kept(self):
        result = derive_duration_calibration_record(_observation(), "training", identity=None)
        assert isinstance(result, QuarantinedDerivation)
        assert "identity_context" in result.missing_identity_fields
        # The measurement is preserved: it really happened.
        assert result.observation_payload["measured_value_ms"] > 0

    def test_a_missing_model_family_quarantines(self):
        payload = json.loads(json.dumps(_raw()))
        payload["calibration_context"]["model_family"] = ""
        obs = RuntimeObservation.model_validate(payload)
        result = derive_duration_calibration_record(obs, "training", identity=CONTEXT)
        assert isinstance(result, QuarantinedDerivation)
        assert "model_family" in result.missing_identity_fields

    def test_no_fabricated_default_reaches_an_eligible_record(self):
        """ "unknown" is never substituted for a family that was not
        recorded. That is the whole point of the quarantine namespace."""
        payload = json.loads(json.dumps(_raw()))
        payload["calibration_context"]["model_family"] = "   "
        obs = RuntimeObservation.model_validate(payload)
        result = derive_duration_calibration_record(obs, "training", identity=CONTEXT)
        assert not isinstance(result, DerivedDurationRecord)

    def test_an_unmapped_unit_quarantines_rather_than_guessing(self):
        payload = json.loads(json.dumps(_raw()))
        payload["components"]["training"]["measurement"]["unit"] = "furlongs"
        obs = RuntimeObservation.model_validate(payload)
        result = derive_duration_calibration_record(obs, "training", identity=CONTEXT)
        assert isinstance(result, QuarantinedDerivation)
        assert "furlongs" in result.reason

    def test_every_supported_unit_names_its_phase_explicitly(self):
        """No unchecked cast. An unrecognised unit means we do not know what
        was measured, and a guess would enter a bucket other measurements
        are averaged into."""
        assert set(SUPPORTED_UNITS.values()) <= {"training", "inference"}
        assert "optimizer_step" in SUPPORTED_UNITS


class TestIdempotency:
    def test_the_same_event_derives_to_the_same_identity(self):
        """Content addressing is the idempotency mechanism: an identical
        derivation hashes to the identical registry id and dedups, so
        reprocessing cannot advance a promotion sample count twice."""
        a = derive_duration_calibration_record(_observation(), "training", identity=CONTEXT)
        b = derive_duration_calibration_record(_observation(), "training", identity=CONTEXT)
        assert isinstance(a, DerivedDurationRecord)
        assert isinstance(b, DerivedDurationRecord)
        assert a.identity.identity_key == b.identity.identity_key
        assert a.source_reference == b.source_reference

    def test_the_source_reference_links_back_to_system_a(self):
        result = derive_duration_calibration_record(_observation(), "training", identity=CONTEXT)
        assert isinstance(result, DerivedDurationRecord)
        assert result.source_reference["derived_from"] == "runtime_observation"
        assert result.source_reference["system_a_timestamp"] == _raw()["timestamp"]

    def test_two_different_phases_of_one_event_are_not_one_record(self):
        train = derive_duration_calibration_record(_observation(), "training", identity=CONTEXT)
        infer = derive_duration_calibration_record(_observation(), "inference", identity=CONTEXT)
        assert isinstance(train, DerivedDurationRecord)
        assert isinstance(infer, DerivedDurationRecord)
        assert train.source_reference != infer.source_reference


class TestThePureBoundary:
    def test_the_converter_performs_no_io(self):
        """Pure by construction: no registry, no filesystem, no clock. A
        converter that wrote would make failure isolation impossible to
        reason about."""
        import ast
        from pathlib import Path

        import core.runtime_control.calibration_derivation as mod

        tree = ast.parse(Path(mod.__file__).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)

        forbidden = {"os", "pathlib", "time", "datetime"}
        assert not (imported & forbidden), (
            f"the pure converter imports I/O or clock modules: {imported & forbidden}"
        )
        assert not any("calibration_registry" in name for name in imported), (
            "the converter must not reach the registry; persistence is a separate responsibility"
        )
