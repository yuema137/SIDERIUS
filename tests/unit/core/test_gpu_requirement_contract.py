"""Authority is computed from evidence, never asserted by a caller.

V20 PR C2 / C2-1.

The defect this guards is the one `sandbox_executor.py:489` already describes
in its own words: a substituted figure is "an assumption wearing a
measurement's provenance". The contract therefore refuses to emit an admission
entry unless every frozen condition holds, and `authoritative` is a computed
property so no caller can simply declare a measurement trustworthy.

Every refusal test below is paired with the same measurement in its ACCEPTED
form, so a test cannot pass because the object was malformed for an unrelated
reason.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.runtime_control.gpu_measurement_identity import (
    build_planned_identity,
    build_realized_identity,
)
from core.runtime_control.gpu_requirement import (
    ADMISSIBLE_PHASES,
    CandidateMeasurementRequest,
    MeasuredGpuRequirement,
    MeasurementDeadline,
    SamplingCoverage,
)

REQUEST = CandidateMeasurementRequest(
    model_type="punet",
    planned_identity=build_planned_identity(model_type="punet", model_config={}, train_config={}),
    request_id="req-c23fbeb8",
    device_uuid="GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef",
    phase="training",
    deadline_seconds=120.0,
)
REALIZED = build_realized_identity(
    model_type="punet",
    optimizer_type="adamw",
    seg_size=40_000,
    batch_size=1,
    precision="float32",
    parameter_count=1_000_000,
    trainable_parameter_count=1_000_000,
)
COMPLETE = SamplingCoverage(interval_seconds=0.25, samples_taken=200)
IN_TIME = MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=31.4)


def _measurement(**over) -> MeasuredGpuRequirement:
    payload = dict(
        request=REQUEST,
        outcome="COMPLETED_MEASUREMENT",
        driver_tree_peak_mib=9_312,
        allocator_peak_mib=6_004,
        observed_device_uuid=REQUEST.device_uuid,
        owned_pids=(4242, 4243),
        realized_identity=REALIZED,
        coverage=COMPLETE,
        deadline=IN_TIME,
    )
    payload.update(over)
    return MeasuredGpuRequirement(**payload)


class TestTheAcceptedShape:
    """The positive control for every refusal below. If this stops being
    authoritative, the refusal tests become vacuous."""

    def test_a_complete_measurement_is_authoritative(self):
        m = _measurement()
        assert m.authority_refusal is None
        assert m.authoritative is True

    def test_the_admission_entry_carries_the_driver_figure(self):
        entry = _measurement().as_admission_entry()
        assert entry["requirement_mib"] == 9_312, (
            "the admission entry must carry the DRIVER-visible tree peak, not the allocator figure"
        )

    def test_the_provenance_is_the_category_admission_accepts(self):
        """C2-6 correction. `evaluate_gpu_admission` tests membership in
        `AUTHORITATIVE_PROVENANCE` (`admission.py:429`), so a DESCRIPTIVE
        provenance string is delivered, judged non-authoritative, and
        refused as `policy_unavailable` -- the failure C2 exists to fix,
        one layer deeper, with the requirement present and still not
        counting."""
        from core.runtime_control.admission import AUTHORITATIVE_PROVENANCE

        assert _measurement().as_admission_entry()["provenance"] in AUTHORITATIVE_PROVENANCE

    def test_the_description_travels_beside_the_category(self):
        """`_phase_requirement` ignores this key, so nothing is lost by
        keeping the traceable form out of the field admission tests."""
        entry = _measurement().as_admission_entry()
        assert "isolated_prephase_measurement:training" in str(entry["measurement_detail"])


class TestAuthorityIsRefusedWithANamedReason:
    @pytest.mark.parametrize(
        "over,expected",
        [
            (
                {
                    "outcome": "MEASURED_HARD_TIMEOUT",
                    "driver_tree_peak_mib": None,
                    "deadline": MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=120.0),
                },
                "outcome_has_no_capacity_authority",
            ),
            (
                {"outcome": "INCONCLUSIVE_MEASUREMENT", "driver_tree_peak_mib": None},
                "outcome_has_no_capacity_authority",
            ),
            ({"observed_device_uuid": "GPU-somewhere-else"}, "device_uuid_mismatch"),
            ({"realized_identity": None}, "realized_identity_absent"),
            ({"identity_mismatch": "batch_size_mismatch"}, "candidate_identity_mismatch"),
            ({"request": REQUEST.model_copy(update={"phase": "setup"})}, "phase_not_admissible"),
            (
                {
                    "coverage": SamplingCoverage(
                        interval_seconds=0.25, samples_taken=200, samples_missed=3
                    )
                },
                "sampling_incomplete",
            ),
            (
                {"coverage": SamplingCoverage(interval_seconds=0.25, samples_taken=0)},
                "sampling_incomplete",
            ),
            (
                {
                    "coverage": SamplingCoverage(
                        interval_seconds=0.25, samples_taken=8, covered_whole_phase=False
                    )
                },
                "sampling_incomplete",
            ),
        ],
        ids=[
            "timeout",
            "inconclusive",
            "wrong-gpu",
            "no-realized-identity",
            "identity-mismatch",
            "setup-phase",
            "missed-samples",
            "zero-samples",
            "partial-coverage",
        ],
    )
    def test_each_violation_names_itself(self, over, expected):
        m = _measurement(**over)
        assert m.authority_refusal == expected
        assert m.authoritative is False

    def test_a_refused_measurement_cannot_produce_an_admission_entry(self):
        """Refusing must RAISE, not emit a placeholder. A zero or a fallback
        would reach PR B wearing a measurement's provenance."""
        m = _measurement(observed_device_uuid="GPU-somewhere-else")
        with pytest.raises(ValueError, match=r"not\s+authoritative"):
            m.as_admission_entry()


class TestSamplingFailsClosed:
    @pytest.mark.parametrize("taken", [0, 1, 2])
    def test_fewer_than_three_in_phase_samples_fail_closed(self, taken):
        """D-C2-13. Gate 2 Lite-A c7 got ZERO samples from a 0.138 s phase
        at a 0.25 s cadence. One or two are barely better: a single reading
        cannot tell a steady peak from a transient, and gives the phase no
        observed shape. Three is the smallest count that shows a phase was
        watched rather than glanced at."""
        coverage = SamplingCoverage(interval_seconds=0.25, samples_taken=taken)
        assert coverage.complete is False
        assert coverage.incompleteness_reason

    def test_three_samples_are_enough(self):
        """Positive control: the threshold must refuse thin evidence, not
        all evidence."""
        assert SamplingCoverage(interval_seconds=0.25, samples_taken=3).complete is True

    def test_a_two_sample_measurement_carries_no_authority(self):
        """The same rule where it matters -- at the requirement, not just on
        the coverage object."""
        m = _measurement(
            coverage=SamplingCoverage(interval_seconds=0.25, samples_taken=2),
        )
        assert m.authoritative is False
        assert m.authority_refusal == "sampling_incomplete"

    def test_zero_samples_is_not_zero_memory(self):
        """The under-read that would look like a very small candidate."""
        coverage = SamplingCoverage(interval_seconds=0.25, samples_taken=0)
        assert coverage.complete is False
        assert "absence of samples is not absence of memory" in (
            coverage.incompleteness_reason or ""
        )

    def test_incomplete_sampling_refuses_even_with_a_driver_figure(self):
        """A gappy watch yields an UNKNOWN requirement, not a smaller one --
        so the presence of a number must not rescue it."""
        m = _measurement(
            driver_tree_peak_mib=1_024,
            coverage=SamplingCoverage(interval_seconds=0.25, samples_taken=4, samples_missed=11),
        )
        assert m.authoritative is False
        assert m.authority_refusal == "sampling_incomplete"


class TestTheAllocatorFigureIsNeverTheAuthority:
    def test_a_measurement_with_only_an_allocator_peak_is_rejected(self):
        """COMPLETED_MEASUREMENT + allocator-only is exactly the
        silent-success shape: it reads as a real measurement and contains no
        admissible evidence."""
        with pytest.raises(ValidationError, match="no driver-visible"):
            _measurement(driver_tree_peak_mib=None, allocator_peak_mib=6_004)

    def test_the_two_figures_stay_distinct(self):
        """They must never be conflated: the driver total legitimately exceeds
        the allocator figure (CUDA context, workspaces, other owned PIDs)."""
        m = _measurement()
        assert m.driver_tree_peak_mib != m.allocator_peak_mib
        assert m.as_admission_entry()["requirement_mib"] == m.driver_tree_peak_mib


class TestTimeoutClaimsAreValidatedNotBelieved:
    def test_a_timeout_that_never_reached_its_deadline_is_refused(self):
        """PR A added this guard after a 65.6 s inspection was filed as a
        timeout on 2026-07-31. The same trap exists here."""
        with pytest.raises(ValidationError, match="deadline was reached"):
            _measurement(
                outcome="MEASURED_HARD_TIMEOUT",
                driver_tree_peak_mib=None,
                deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=9.0),
            )

    def test_a_genuine_timeout_is_accepted(self):
        """Positive control: the guard must reject mislabelling, not timeouts."""
        m = _measurement(
            outcome="MEASURED_HARD_TIMEOUT",
            driver_tree_peak_mib=None,
            deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=120.0),
        )
        assert m.deadline.reached_deadline is True


class TestCapacityEvidenceIsSeparateFromRequirementAuthority:
    """A measured OOM proves the candidate does not fit, but supplies no
    number to admit on. Conflating the two would either admit on a
    non-existent figure or discard a real capacity fact."""

    @pytest.mark.parametrize("outcome", ["MEASURED_CUDA_OOM", "MEASURED_PEAK_ABOVE_VRAM_CAP"])
    def test_capacity_outcomes_establish_insufficiency_without_authority(self, outcome):
        m = _measurement(outcome=outcome, driver_tree_peak_mib=None)
        assert m.establishes_insufficient_capacity is True
        assert m.authoritative is False

    def test_a_completed_measurement_establishes_no_insufficiency(self):
        m = _measurement()
        assert m.establishes_insufficient_capacity is False
        assert m.authoritative is True


class TestPhaseScoping:
    def test_only_admissible_phases_may_carry_authority(self):
        assert ADMISSIBLE_PHASES == frozenset({"training", "inference"})

    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_both_consumer_phases_are_authoritative_independently(self, phase):
        """Training and inference are separate requirements, never merged --
        PR B measured them 1.8x apart."""
        m = _measurement(request=REQUEST.model_copy(update={"phase": phase}))
        assert m.authoritative is True
        assert f":{phase}:" in str(m.as_admission_entry()["measurement_detail"])
