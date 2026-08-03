"""Identity, applicability and policy kept apart.

V20 PR C1 / C-C2a.

The v1 bucket key put all three into one seven-part string
(`calibration_policy.bucket_components`). Three consequences, each measured
on the live registry during the PR C audit:

  * a matching bucket READ as applicability, when it is only a candidate set
    that still has to be checked;
  * `task` and `data_shape_class` were absent entirely, while the registry
    lives at one per-user root -- so two tasks with the same family, hardware
    and stack shared a bucket;
  * the device INSTANCE was absent. `hardware_compatibility_id` describes a
    model of card, not the card, so one 5090's measurement could speak for
    another.

`MeasurementIdentity` is exact-match: who a measurement is about.
`ApplicabilityEnvelope` is bounded-range: who else it may speak for. This
module tests that the split holds, because the frozen invariants in the PR C
design (§8.A) are only enforceable if they are expressible -- "cross-task
reuse fails" is a property of an identity comparison, not of a similarity
heuristic.

C-C2a adds the models. Wiring them into the registry is C-C2b/c; nothing
here asserts that production uses them yet.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.runtime_control.calibration_policy import ApplicabilityEnvelope
from core.runtime_control.registry_schemas import (
    UNKNOWN_MODEL_FAMILY,
    MeasurementIdentity,
)

BASE = {
    "measurement_kind": "duration",
    "task_identity": "tidmad_denoise",
    "data_shape_class": "seg40000_int8",
    "model_family": "punet",
    "candidate_config_hash": "cfg:abc123",
    "phase": "training",
    "hardware_uuid": "GPU-1111-aaaa",
    "runtime_stack_identity": "stack:cb380df61b90",
}


def _identity(**over) -> MeasurementIdentity:
    return MeasurementIdentity(**{**BASE, **over})


class TestTheFrozenReuseRulesAreExpressible:
    """Each row is a frozen invariant from the PR C design §8.A. They are
    stated as identity differences, so "does not substitute" is a property
    of the comparison rather than of a threshold someone can tune."""

    @pytest.mark.parametrize(
        "field,other",
        [
            ("task_identity", "some_other_task"),
            ("data_shape_class", "seg2500_int8"),
            ("hardware_uuid", "GPU-2222-bbbb"),
            ("phase", "inference"),
            ("measurement_kind", "gpu_requirement"),
            ("model_family", "wavenet"),
            ("candidate_config_hash", "cfg:different"),
            ("runtime_stack_identity", "stack:000000000000"),
        ],
    )
    def test_a_difference_in_any_dimension_is_a_different_identity(self, field, other):
        assert _identity() != _identity(**{field: other})
        assert _identity().identity_key != _identity(**{field: other}).identity_key

    def test_a_millisecond_never_answers_a_memory_query(self):
        """The error the PR C audit caught in its own first draft: the
        ladder assumed the calibration registry could supply PR B's
        `requirement_mib`. It stores `measured_value_ms`. Making
        `measurement_kind` an identity dimension is what stops a promoted
        duration from being handed to a memory gate."""
        duration = _identity(measurement_kind="duration")
        requirement = _identity(measurement_kind="gpu_requirement")
        assert duration.identity_key != requirement.identity_key
        assert duration.components()[0] != requirement.components()[0]

    def test_training_and_inference_do_not_share_an_identity(self):
        """B-G0 measured one PUNet candidate at 1,476 MiB training and
        2,716 MiB inference -- 1.8x apart, one card, one run."""
        assert _identity(phase="training") != _identity(phase="inference")

    def test_two_cards_of_the_same_model_are_different_devices(self):
        """`hardware_compatibility_id` describes a class of card. Two 5090s
        in one host are not the same device, and a measurement from one is
        not authoritative for the other."""
        assert _identity(hardware_uuid="GPU-a") != _identity(hardware_uuid="GPU-b")


class TestUnknownFamilyIsNeverAuthoritative:
    def test_a_known_family_is_known(self):
        assert _identity(model_family="punet").family_is_known is True

    def test_the_unknown_sentinel_is_not(self):
        assert _identity(model_family=UNKNOWN_MODEL_FAMILY).family_is_known is False

    def test_the_record_is_still_legitimate(self):
        """Unknown-family evidence is still evidence. What is forbidden is
        granting it authority -- quarantining it is O-2's job, and refusing
        to construct it would throw away a measurement that really happened.
        """
        assert _identity(model_family=UNKNOWN_MODEL_FAMILY).identity_key


class TestIdentityIsExactMatchOnly:
    def test_it_carries_no_range_threshold_or_tolerance(self):
        """The split is the point. If a range ever appears in this model,
        `identity_key` stops being an equality and starts being a judgement.
        """
        for name, field in MeasurementIdentity.model_fields.items():
            assert field.annotation in (str,) or name in ("measurement_kind", "phase"), (
                f"{name} is not a plain identity dimension; ranges belong in "
                "ApplicabilityEnvelope and thresholds in CalibrationPolicy"
            )

    def test_an_unrecognised_field_is_refused(self):
        """A silently absorbed field would be an identity dimension nobody
        compares -- the shape of every field-drop defect in this project."""
        with pytest.raises(ValidationError):
            MeasurementIdentity(**{**BASE, "gpu_index": 0})

    @pytest.mark.parametrize("field", sorted(BASE))
    def test_no_dimension_may_be_blank(self, field):
        """An empty string passes `str` and reads as an answer."""
        if field in ("measurement_kind", "phase"):
            pytest.skip("closed vocabularies; a blank is already not a member")
        with pytest.raises(ValidationError):
            _identity(**{field: ""})

    def test_the_stack_is_last_so_drift_can_group_without_it(self):
        """Mirrors `bucket_components`' convention: `components()[:-1]` is
        "same everything, different stack", which is what drift analysis
        compares."""
        assert _identity().components()[-1] == BASE["runtime_stack_identity"]
        a = _identity(runtime_stack_identity="stack:aaa")
        b = _identity(runtime_stack_identity="stack:bbb")
        assert a.components()[:-1] == b.components()[:-1]


class TestTheEnvelopeAnswersADifferentQuestion:
    def test_a_candidate_inside_the_measured_region_interpolates(self):
        envelope = ApplicabilityEnvelope(ranges={"batch_size": (2.0, 8.0)}, sample_count=3)
        label, _ = envelope.classify({"batch_size": 4})
        assert label == "interpolation"

    def test_a_candidate_outside_it_does_not(self):
        envelope = ApplicabilityEnvelope(ranges={"batch_size": (2.0, 8.0)}, sample_count=3)
        label, reasons = envelope.classify({"batch_size": 64})
        assert label != "interpolation"
        assert reasons, "an out-of-range verdict must say which dimension and why"

    def test_a_dimension_with_no_evidence_fails_closed(self):
        """Absent evidence is never supporting evidence. This is the rule
        that makes "a bucket match is not applicability" real: a candidate
        can match every identity dimension and still be inapplicable."""
        envelope = ApplicabilityEnvelope(ranges={"batch_size": (2.0, 8.0)}, sample_count=3)
        label, reasons = envelope.classify({"parameter_count": 1_000_000})
        assert label == "not_applicable"
        assert any("no measured evidence" in r for r in reasons)

    def test_an_empty_envelope_is_applicable_to_nothing(self):
        label, _ = ApplicabilityEnvelope().classify({"batch_size": 4})
        assert label == "not_applicable"

    def test_an_inverted_span_is_refused(self):
        """A reversed span makes every request look out of range, which
        would read as a safe answer while being a construction error."""
        with pytest.raises(ValidationError):
            ApplicabilityEnvelope(ranges={"batch_size": (8.0, 2.0)})

    def test_the_envelope_holds_no_identity(self):
        """Structural proof of the split: you cannot get an applicability
        verdict by matching a key, because no key is in this model."""
        assert not set(ApplicabilityEnvelope.model_fields) & set(MeasurementIdentity.model_fields)
