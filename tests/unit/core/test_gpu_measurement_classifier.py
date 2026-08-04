"""Eight outcomes, each checked against evidence before it is claimed.

V20 PR C2 / C2-5.

The defects here are misattributions -- an outcome that is plausible, typed
and wrong:

* a timeout claimed against a deadline nothing reached (a 65.6 s inspection
  was filed against a 600 s budget on 2026-07-31);
* a CUDA OOM inferred from a killed worker, blaming a candidate for the
  machinery;
* an above-cap verdict -- which carries authority to tell an agent to
  shrink its model -- drawn from a watch with holes in it;
* an incomplete measurement admitted as a smaller requirement rather than
  an unknown one.

Every classification is asserted together with its authority consequence,
because naming the outcome correctly is only half of it: the other half is
that the wrong ones cannot reach admission.
"""

from __future__ import annotations

import pytest

from agent.skills.evaluate_vram_skill.isolated_probe import NO_DOWNSIZING_AUTHORITY
from core.runtime_control.gpu_measurement_classifier import classify_measurement
from core.runtime_control.gpu_measurement_identity import (
    build_planned_identity,
    build_realized_identity,
)
from core.runtime_control.gpu_measurement_runner import (
    HostMemoryBound,
    PhaseMeasurement,
    PrephaseMeasurementRun,
    ProcessEvidence,
)
from core.runtime_control.gpu_requirement import (
    CandidateMeasurementRequest,
    MeasurementDeadline,
    SamplingCoverage,
)

UUID = "GPU-c30b6678"
REQUEST = CandidateMeasurementRequest(
    model_type="punet",
    planned_identity=build_planned_identity(model_type="punet", model_config={}, train_config={}),
    request_id="req-01234567",
    device_uuid=UUID,
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

COMPLETE = SamplingCoverage(interval_seconds=0.25, samples_taken=40)


def _phase(**over) -> PhaseMeasurement:
    payload = dict(
        phase="training",
        status="COMPLETED",
        started_at=1000.0,
        ended_at=1010.0,
        elapsed_seconds=10.0,
        driver_tree_peak_mib=9_312,
        allocator_peak_mib=6_004,
        coverage=COMPLETE,
        own_pids=(4242,),
        max_concurrent_own_processes=1,
        units_executed=4,
        units_requested=4,
    )
    payload.update(over)
    return PhaseMeasurement(**payload)  # type: ignore[arg-type]


def _run(**over) -> PrephaseMeasurementRun:
    payload = dict(
        label="c2-classify",
        request=REQUEST,
        worker_status="COMPLETED",
        report_present=True,
        observed_device_uuid=UUID,
        realized_identity=REALIZED,
        reported_request_id=REQUEST.request_id,
        phases=(_phase(),),
        deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=12.5),
        host_memory=HostMemoryBound(limit_bytes=24 * 1024**3, peak_tree_rss_bytes=3 * 1024**3),
        process=ProcessEvidence(worker_pid=4242, worker_pgid=4242, exit_code=0),
    )
    payload.update(over)
    return PrephaseMeasurementRun(**payload)  # type: ignore[arg-type]


class TestTheAcceptedShape:
    """The positive control. Without it every refusal below is vacuous."""

    def test_a_complete_measurement_is_authoritative(self):
        requirement = classify_measurement(_run())
        assert requirement.outcome == "COMPLETED_MEASUREMENT"
        assert requirement.authoritative is True
        assert requirement.as_admission_entry()["requirement_mib"] == 9_312

    def test_the_allocator_figure_travels_but_never_as_the_requirement(self):
        requirement = classify_measurement(_run())
        assert requirement.allocator_peak_mib == 6_004
        assert requirement.as_admission_entry()["requirement_mib"] == 9_312


class TestATimeoutMustHaveReachedADeadline:
    def test_a_reaped_worker_past_its_deadline_is_a_timeout(self):
        requirement = classify_measurement(
            _run(
                report_present=False,
                worker_status=None,
                phases=(),
                in_flight_phase="training",
                deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=120.4),
                process=ProcessEvidence(
                    worker_pid=1, worker_pgid=1, exit_code=-9, signal_number=9, term_sent=True
                ),
            )
        )
        assert requirement.outcome == "MEASURED_HARD_TIMEOUT"
        assert "during training" in requirement.detail

    def test_a_worker_that_died_early_is_not_a_timeout(self):
        """The 2026-07-31 mislabelling, directly: every inconclusive status
        mapped to the timeout outcome, and a 65.6 s inspection was filed
        against a 600 s budget."""
        requirement = classify_measurement(
            _run(
                report_present=False,
                worker_status=None,
                phases=(),
                deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=9.0),
                process=ProcessEvidence(worker_pid=1, worker_pgid=1, exit_code=1),
            )
        )
        assert requirement.outcome == "PROBE_INFRASTRUCTURE_FAILURE"

    def test_a_worker_side_budget_reports_the_budget_that_actually_fired(self):
        """The soft budget sits BELOW the parent's by construction, so
        reporting the parent's would produce a timeout whose elapsed time
        never reached it -- and C2-1's validator would refuse to build it
        at all."""
        requirement = classify_measurement(
            _run(
                worker_status="DEADLINE_EXCEEDED",
                soft_deadline_seconds=90.0,
                phases=(_phase(status="FAILED"),),
                deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=91.2),
            )
        )
        assert requirement.outcome == "MEASURED_HARD_TIMEOUT"
        assert requirement.deadline.budget_seconds == 90.0
        assert requirement.deadline.reached_deadline is True


class TestACudaOomIsNeverInferred:
    def test_only_the_worker_can_report_one(self):
        requirement = classify_measurement(
            _run(worker_status="CUDA_OOM", phases=(_phase(status="CUDA_OOM"),))
        )
        assert requirement.outcome == "MEASURED_CUDA_OOM"
        assert requirement.establishes_insufficient_capacity is True
        assert requirement.authoritative is False, "an OOM supplies no number to admit on"

    def test_a_killed_worker_holding_memory_is_not_an_oom(self):
        """ "Died while using a lot of memory" is exactly the inference that
        would blame a candidate for the machinery. Only the process that
        holds the exception may report one."""
        requirement = classify_measurement(
            _run(
                report_present=False,
                worker_status=None,
                phases=(),
                in_flight_phase="training",
                deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=121.0),
                process=ProcessEvidence(
                    worker_pid=1, worker_pgid=1, exit_code=-9, signal_number=9, kill_sent=True
                ),
            )
        )
        assert requirement.outcome != "MEASURED_CUDA_OOM"
        assert requirement.outcome == "MEASURED_HARD_TIMEOUT"


class TestAboveCapNeedsAnOtherwiseAuthoritativeMeasurement:
    def test_a_complete_measurement_over_the_cap_is_refused(self):
        requirement = classify_measurement(_run(), vram_cap_mib=8_000)
        assert requirement.outcome == "MEASURED_PEAK_ABOVE_VRAM_CAP"
        assert requirement.establishes_insufficient_capacity is True

    def test_a_measurement_under_the_cap_is_accepted(self):
        """Positive control: the cap must refuse oversized candidates, not
        every candidate."""
        assert classify_measurement(_run(), vram_cap_mib=32_000).outcome == "COMPLETED_MEASUREMENT"

    def test_no_configured_cap_is_never_a_guessed_one(self):
        assert classify_measurement(_run(), vram_cap_mib=None).outcome == "COMPLETED_MEASUREMENT"

    def test_an_incomplete_watch_over_the_cap_is_inconclusive_not_above_cap(self):
        """Deliberately conservative. `MEASURED_PEAK_ABOVE_VRAM_CAP` grants
        authority to tell an agent to SHRINK its model, and a gappy watch is
        not a safe basis for that instruction. The run still stops -- the
        outcome carries no authority either way -- and the observed figure
        is kept in the detail so nothing measured is lost."""
        requirement = classify_measurement(
            _run(
                phases=(
                    _phase(
                        driver_tree_peak_mib=30_000,
                        coverage=SamplingCoverage(
                            interval_seconds=0.25, samples_taken=3, samples_missed=9
                        ),
                    ),
                ),
            ),
            vram_cap_mib=8_000,
        )
        assert requirement.outcome == "INCONCLUSIVE_MEASUREMENT"
        assert "30000 MiB observed is a lower bound" in requirement.detail
        assert requirement.outcome in NO_DOWNSIZING_AUTHORITY, (
            "and so it establishes nothing about the candidate's size"
        )


class TestIncompleteSamplingCarriesNoAuthority:
    @pytest.mark.parametrize(
        "coverage",
        [
            SamplingCoverage(interval_seconds=0.25, samples_taken=0),
            SamplingCoverage(interval_seconds=0.25, samples_taken=10, samples_missed=2),
            SamplingCoverage(interval_seconds=0.25, samples_taken=10, covered_whole_phase=False),
        ],
        ids=["no-samples", "missed-samples", "partial-coverage"],
    )
    def test_each_incompleteness_yields_an_unknown_requirement(self, coverage):
        requirement = classify_measurement(_run(phases=(_phase(coverage=coverage),)))
        assert requirement.outcome == "INCONCLUSIVE_MEASUREMENT"
        assert requirement.authoritative is False

    def test_an_unobserved_phase_is_unknown_not_zero(self):
        requirement = classify_measurement(_run(phases=(_phase(driver_tree_peak_mib=None),)))
        assert requirement.outcome == "INCONCLUSIVE_MEASUREMENT"
        assert "unknown, not zero" in requirement.detail

    def test_a_run_with_no_phase_at_all_fails_closed(self):
        requirement = classify_measurement(
            _run(worker_status="COMPLETED", phases=(), report_present=True)
        )
        assert requirement.outcome == "INCONCLUSIVE_MEASUREMENT"
        assert requirement.coverage.complete is False


class TestInfrastructureIsNotCandidateBlame:
    @pytest.mark.parametrize(
        "status,expected",
        [
            ("DEVICE_UNAVAILABLE", "PROBE_INFRASTRUCTURE_FAILURE"),
            ("DEVICE_MISMATCH", "PROBE_INFRASTRUCTURE_FAILURE"),
            ("WORKER_FAILURE", "PROBE_INFRASTRUCTURE_FAILURE"),
            ("CONFIG_REJECTED", "SCHEMA_REJECTED"),
        ],
    )
    def test_environment_and_config_faults_are_named_as_such(self, status, expected):
        requirement = classify_measurement(_run(worker_status=status, phases=()))
        assert requirement.outcome == expected

    @pytest.mark.parametrize(
        "status", ["DEVICE_UNAVAILABLE", "DEVICE_MISMATCH", "WORKER_FAILURE", "CONFIG_REJECTED"]
    )
    def test_none_of_them_may_ask_a_candidate_to_shrink(self, status):
        """Reusing PR A's frozen `NO_DOWNSIZING_AUTHORITY` rather than
        re-deciding which outcomes establish nothing about size."""
        requirement = classify_measurement(_run(worker_status=status, phases=()))
        assert requirement.outcome in NO_DOWNSIZING_AUTHORITY
        assert requirement.establishes_insufficient_capacity is False


class TestHostMemoryIsNeverAVramVerdict:
    def test_the_parent_bound_produces_a_host_outcome(self):
        """The candidate may fit the GPU perfectly and still have exhausted
        CPU memory; on 2026-07-31 one did, at 60.5 GB of RSS with the GPU
        at 273 MiB."""
        requirement = classify_measurement(
            _run(
                host_memory=HostMemoryBound(
                    limit_bytes=24 * 1024**3,
                    peak_tree_rss_bytes=25 * 1024**3,
                    exceeded=True,
                ),
                report_present=False,
                worker_status=None,
                phases=(),
            )
        )
        assert requirement.outcome == "MEASURED_HOST_MEMORY_EXCEEDED"
        assert "says nothing about VRAM" in requirement.detail
        assert requirement.establishes_insufficient_capacity is False, (
            "a HOST bound is not evidence the candidate is too big for the GPU"
        )

    def test_the_host_bound_outranks_a_worker_report(self):
        """The parent measured the bound itself. A worker that reported
        cleanly on its way to being terminated must not overrule it."""
        requirement = classify_measurement(
            _run(
                host_memory=HostMemoryBound(
                    limit_bytes=24 * 1024**3, peak_tree_rss_bytes=25 * 1024**3, exceeded=True
                )
            )
        )
        assert requirement.outcome == "MEASURED_HOST_MEMORY_EXCEEDED"


class TestTheWrongDeviceCannotBeAdmitted:
    def test_a_measurement_from_another_card_is_refused(self):
        """The worker verifies this too. Checking it again here is not
        redundancy: this is the last point before admission, and the
        request is what the requirement will be judged against."""
        requirement = classify_measurement(_run(observed_device_uuid="GPU-somewhere-else"))
        assert requirement.outcome == "COMPLETED_MEASUREMENT"
        assert requirement.authoritative is False
        assert requirement.authority_refusal == "device_uuid_mismatch"


def test_classification_never_raises_for_anything_it_can_observe():
    """The control-flow rule. Every outcome O-7 has a rule for is a value;
    exceptions are reserved for programming errors."""
    for status in (
        "COMPLETED",
        "CUDA_OOM",
        "DEADLINE_EXCEEDED",
        "DEVICE_UNAVAILABLE",
        "DEVICE_MISMATCH",
        "CONFIG_REJECTED",
        "WORKER_FAILURE",
        None,
    ):
        run = _run(
            worker_status=status,
            report_present=status is not None,
            phases=(),
            soft_deadline_seconds=90.0 if status == "DEADLINE_EXCEEDED" else None,
        )
        assert classify_measurement(run).outcome is not None
