"""Calibration state reporting must never overstate what exists.

V20 PR C1 / C-C7.

The defect this guards: the live v1 registry held 20 observations and 0
promotions for weeks and nothing said so. "Calibration exists" was true;
"calibration is working" was not; no artifact distinguished them. A report
that counts records rather than authority reproduces exactly that.
"""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_context import (
    CalibrationContextInputs,
    build_calibration_context,
    candidate_config_hash,
)
from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.calibration_state import (
    CalibrationStateReport,
    collect_calibration_state,
)
from core.runtime_control.registry_schemas import (
    CalibrationObservation,
    MeasurementIdentity,
)

INPUTS = CalibrationContextInputs(
    precision="float32",
    optimizer_type="adamw",
    model_family="wavenet",
    param_count=156_320,
    seg_size=40_000,
    batch_size=8,
)
ENV_ID = "sha256:" + "b" * 64


def _identity(**over) -> MeasurementIdentity:
    from core.runtime_control.calibration_policy import stack_identity
    from core.runtime_control.provenance import capture_software_stack

    base = dict(
        measurement_kind="duration",
        task_identity="tidmad_denoising",
        data_shape_class="tidmad_int8_1d",
        model_family=INPUTS.model_family,
        candidate_config_hash=candidate_config_hash(build_calibration_context(INPUTS)),
        phase="training",
        hardware_uuid="GPU-1111",
        runtime_stack_identity=stack_identity(capture_software_stack()),
    )
    base.update(over)
    return MeasurementIdentity(**base)


def _record(registry, *, ms: float, **over) -> CalibrationObservation:
    payload = dict(
        operation="training",
        measurement_unit="optimizer_step",
        measured_value_ms=ms,
        workload={"batch_size": 8, "seg_size": 40_000, "param_count": 156_320},
        realized_model={"parameter_count": 156_320},
        hardware_compatibility_id="sha256:" + "a" * 64,
        execution_environment_id=ENV_ID,
        concurrency_identity="single_candidate_idle",
        software_stack={"torch": "2.7.0"},
        producer_identity="derived_runtime_observation@1.0.0",
        provenance="real_training_verification",
        validation_status="unvalidated",
        timestamp_metadata="2026-08-02T12:00:00Z",
        identity=_identity(),
    )
    payload.update(over)
    obs = CalibrationObservation(**payload)
    registry.record_observation(obs)
    return obs


def _promote(registry, observations):
    from core.runtime_control.calibration_policy import evaluate_promotions

    for promo in evaluate_promotions(observations, generation=registry.load_manifest().generation):
        registry.record_promotion(promo)


@pytest.fixture
def registry(tmp_path) -> CalibrationRegistry:
    return CalibrationRegistry(tmp_path / "runtime_calibration_v2")


class TestZeroAuthorityIsNeverReportedAsActive:
    def test_an_empty_registry_is_inactive_and_says_why(self, registry):
        report = collect_calibration_state(registry)
        assert report.is_active is False
        assert report.observations_collected == 0
        assert any("no observations" in r for r in report.reasons)

    def test_observations_without_promotion_are_still_inactive(self, registry):
        """The exact v1 shape: evidence collected, none promoted."""
        for ms in (20.0, 21.0, 22.0):
            _record(registry, ms=ms)

        report = collect_calibration_state(registry)

        assert report.observations_collected == 3
        assert report.buckets_validated == 0
        assert report.is_active is False, (
            "collected evidence was reported as active calibration; that is "
            "the exact overstatement the v1 registry made for weeks"
        )
        assert any("validated" in r for r in report.reasons)
        assert "INACTIVE" in report.summary_line()

    def test_a_provisional_bucket_is_not_authoritative(self, registry):
        """`provisional` is a real state and explicitly NOT authoritative.
        Counting it as authority is how a report starts overstating."""
        report = CalibrationStateReport(buckets_provisional=1, buckets_validated=0)
        assert report.buckets_authoritative == 0
        assert report.is_active is False

    def test_a_validated_bucket_is_active(self, registry):
        observations = [_record(registry, ms=ms) for ms in (20.0, 21.0, 22.0)]
        _promote(registry, observations)

        report = collect_calibration_state(registry)

        assert report.buckets_validated >= 1
        assert report.is_active is True
        assert "ACTIVE" in report.summary_line()


class TestTheCategoriesActuallyDiffer:
    def test_refusal_reasons_name_the_blocked_bucket(self, registry):
        """An operator asking "why is nothing authoritative?" must get an
        answer, not a count."""
        _record(registry, ms=20.0)

        report = collect_calibration_state(registry)

        assert report.buckets_unpromoted == 1
        assert report.rejected_promotion_reasons
        assert any("below the minimum" in r for r in report.rejected_promotion_reasons)

    def test_quarantined_evidence_is_counted_separately(self, registry):
        """Quarantined records are evidence that is kept but not usable;
        folding them into the collected count would hide where authority is
        being lost."""
        observations = [_record(registry, ms=ms) for ms in (20.0, 21.0, 22.0)]
        _promote(registry, observations)

        report = collect_calibration_state(registry)

        assert report.observations_quarantined == 0
        assert report.observations_eligible == 3


class TestReportingNeverAltersTheWorkflow:
    def test_an_unreadable_registry_is_reported_not_raised(self):
        class _Broken:
            def iter_observations(self):
                raise OSError("registry unavailable")

        report = collect_calibration_state(_Broken())

        assert report.readable is False
        assert report.is_active is False
        assert "UNREADABLE" in report.summary_line()

    def test_an_unreadable_registry_is_not_reported_as_empty(self):
        """The distinction that matters: "nothing recorded" and "cannot
        read" look identical in a bare count and mean opposite things."""

        class _Broken:
            def iter_observations(self):
                raise OSError("boom")

        broken = collect_calibration_state(_Broken())
        assert broken.readable is False
        assert broken.summary_line() != CalibrationStateReport().summary_line()

    def test_an_unusable_root_is_reported_not_raised(self, tmp_path):
        """Regression, found by audit 2026-08-02.

        `CalibrationRegistry.__init__` mkdirs six subdirectories, so simply
        CONSTRUCTING one against a read-only parent raises. The first C-C7
        wiring built the registry in `BootstrapReport.render()` and passed
        the object in -- putting the only raising step outside the guard the
        collector advertises. Reporting must absorb this, not propagate it.
        """
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        readonly.chmod(0o500)
        try:
            report = collect_calibration_state(root=readonly / "runtime_calibration_v2")
        finally:
            readonly.chmod(0o700)

        assert report.readable is False
        assert "UNREADABLE" in report.summary_line()

    def test_bootstrap_render_survives_an_unusable_registry_root(self, tmp_path):
        """Reachability: the guarantee must hold at the production caller,
        not only in the collector's own unit test."""
        from core.runtime_control.bootstrap import BootstrapReport

        readonly = tmp_path / "ro"
        readonly.mkdir()
        readonly.chmod(0o500)
        try:
            rendered = BootstrapReport(
                ready=True,
                steps=[],
                registry_root=str(readonly / "runtime_calibration_v2"),
                elapsed_seconds=0.1,
            ).render()
        finally:
            readonly.chmod(0o700)

        assert "UNREADABLE" in rendered
