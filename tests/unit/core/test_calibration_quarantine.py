"""Evidence kept, authority withheld.

V20 PR C1 / C-C2c, operator decision O-2.

A measurement whose identity is incomplete is still a measurement that
really happened. Two bad options and one chosen:

  refuse the write   the measurement is destroyed, and the operator never
                     learns how often identity is incomplete -- a failure
                     that leaves no trace
  bucket it anyway   it either lands in the wrong bucket or manufactures a
                     new one; both make a wrong answer available to
                     promotion and admission
  QUARANTINE         keep it, count it, and make it structurally unable to
                     reach a bucket

The structural part is what these tests are about. It is not enough that
today's code declines to promote a quarantined record; the record must not
be reachable from the path promotion walks. `iter_observations` reads
`manifest.observation_ids`, so a quarantined id living in a separate list is
what makes "never authoritative" a property rather than a policy someone
could forget to apply.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.registry_schemas import QuarantineRecord

PAYLOAD = {
    "operation": "training",
    "measurement_unit": "optimizer_step",
    "measured_value_ms": 12.5,
}


@pytest.fixture
def registry(tmp_path) -> CalibrationRegistry:
    return CalibrationRegistry(tmp_path / "runtime_calibration_v2")


class TestQuarantinedEvidenceIsKept:
    def test_the_measurement_survives_verbatim(self, registry):
        """The point of not refusing the write. A later build with a
        complete identity can re-derive the record rather than re-measure."""
        registry.quarantine_observation(PAYLOAD, reason="task_identity absent")
        record = next(registry.iter_quarantined())
        assert record.observation_payload == PAYLOAD

    def test_the_reason_is_recorded_in_words(self, registry):
        registry.quarantine_observation(
            PAYLOAD,
            reason="model_family unresolvable for an invented candidate",
            missing_identity_fields=("model_family",),
        )
        record = next(registry.iter_quarantined())
        assert "unresolvable" in record.reason
        assert record.missing_identity_fields == ("model_family",)

    def test_identical_records_dedup(self, registry):
        a = registry.quarantine_observation(PAYLOAD, reason="same")
        b = registry.quarantine_observation(PAYLOAD, reason="same")
        assert a == b
        assert len(registry.load_manifest().quarantined_ids) == 1

    def test_it_is_content_addressed_like_every_other_record(self, registry):
        qid = registry.quarantine_observation(PAYLOAD, reason="r")
        assert registry.load_quarantined(qid).quarantine_id == qid


class TestQuarantinedEvidenceHasNoAuthority:
    """The structural half. Each test names a path that must not reach it."""

    def test_it_never_enters_the_observation_list(self, registry):
        registry.quarantine_observation(PAYLOAD, reason="task_identity absent")
        manifest = registry.load_manifest()
        assert manifest.observation_ids == []
        assert len(manifest.quarantined_ids) == 1

    def test_iter_observations_does_not_yield_it(self, registry):
        """`iter_observations` is what promotion, bucketing and applicability
        all walk. A quarantined record that appeared here would be
        indistinguishable from usable evidence to every one of them."""
        registry.quarantine_observation(PAYLOAD, reason="task_identity absent")
        assert list(registry.iter_observations()) == []

    def test_auditing_it_requires_asking_for_it_by_name(self, registry):
        """A separate method, not a flag on the normal reader. A caller that
        wants usable evidence must not receive these by default, and a
        caller auditing what was lost has to say so."""
        registry.quarantine_observation(PAYLOAD, reason="r")
        assert len(list(registry.iter_quarantined())) == 1
        assert list(registry.iter_observations()) == []

    def test_the_two_lists_are_disjoint_by_construction(self, registry):
        """A single list with a status flag would make "never authoritative"
        depend on every reader remembering to check the flag."""
        registry.quarantine_observation(PAYLOAD, reason="r")
        manifest = registry.load_manifest()
        assert not set(manifest.observation_ids) & set(manifest.quarantined_ids)

    def test_it_lives_in_a_different_directory(self, registry):
        """Physical separation too, so a directory walk meaning to read
        usable evidence cannot pick one up."""
        registry.quarantine_observation(PAYLOAD, reason="r")
        assert list(registry._quarantine_dir.glob("*.json"))
        assert not list(registry._obs_dir.glob("*.json"))
