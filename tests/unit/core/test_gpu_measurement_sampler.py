"""The tree is watched from outside, and what was not watched is said so.

V20 PR C2 / C2-3.

The failures these rule out all produce a number that looks fine:

* counting one PID as the whole candidate -- under-reads a tree, which is
  precisely the chain/pair topology PR B exists to constrain;
* counting a failed driver query as 0 MiB -- reports a very small
  candidate, the admit-too-eagerly direction;
* judging a phase with samples taken outside it -- lets a training peak
  answer an inference question;
* reporting a peak from a watch that started late -- the unobserved part
  can hold the peak.

The device sampler is injected, so these exercise the real attribution and
coverage logic on a fake clock with no GPU and no sleeps.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.runtime_control.gpu_accounting import (
    DeviceIdentity,
    GpuAccountingSnapshot,
    ProcessOccupancy,
)
from core.runtime_control.gpu_measurement_sampler import (
    GpuTreeSampler,
    TreeMemorySample,
    measure_window,
)

DEVICE = DeviceIdentity(uuid="GPU-abc", physical_index=0)


def _snapshot(*pids_and_mib: tuple[int, int], device_used: int = 9000) -> GpuAccountingSnapshot:
    own = tuple(ProcessOccupancy(pid=pid, used_mib=mib) for pid, mib in pids_and_mib)
    return GpuAccountingSnapshot(
        device=DEVICE,
        telemetry_available=True,
        device_used_mib=device_used,
        device_total_mib=32_768,
        own_tree_mib=sum(m for _, m in pids_and_mib),
        own_processes=own,
        other_mib=max(0, device_used - sum(m for _, m in pids_and_mib)),
        other_process_count=1,
        per_pid_total_mib=device_used,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )


_UNAVAILABLE = GpuAccountingSnapshot(device=DEVICE, telemetry_available=False)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _sampler(responses, clock, interval=0.25) -> GpuTreeSampler:
    queue = list(responses)

    def device_sampler(_root, _device):
        return queue.pop(0) if queue else _UNAVAILABLE

    return GpuTreeSampler(
        4242, DEVICE, interval_seconds=interval, device_sampler=device_sampler, clock=clock
    )


class TestOnePidIsNotTheCandidate:
    def test_the_peak_sums_every_own_process_alive_at_that_instant(self):
        """Simultaneous parent/child residency. Taking the largest single
        process would report 6,000 where the tree held 9,000."""
        clock = _Clock()
        sampler = _sampler([_snapshot((4242, 6000), (4243, 3000))], clock)
        sampler.poll()
        clock.now += 1.0
        sampler.stop()

        window = sampler.measure_window(100.0, 101.0)
        assert window.driver_tree_peak_mib == 9000
        assert window.max_concurrent_own_processes == 2
        assert set(window.own_pids) == {4242, 4243}

    def test_per_process_maxima_are_not_summed_across_time(self):
        """6,000 and 3,000 never coexisted: the true simultaneous peak is
        6,000, not 9,000. Summing each process's own maximum would invent
        a state the machine was never in."""
        clock = _Clock()
        sampler = _sampler([_snapshot((4242, 6000)), _snapshot((4243, 3000))], clock)
        sampler.poll()
        clock.now += 0.5
        sampler.poll()
        clock.now += 0.5
        sampler.stop()

        assert sampler.measure_window(100.0, 101.0).driver_tree_peak_mib == 6000

    def test_the_peak_sample_is_retained_for_audit(self):
        clock = _Clock()
        sampler = _sampler([_snapshot((4242, 1000)), _snapshot((4242, 7000))], clock)
        sampler.poll()
        clock.now += 0.5
        sampler.poll()
        clock.now += 0.1
        sampler.stop()

        peak = sampler.measure_window(100.0, 101.0).peak_sample
        assert peak is not None and peak.own_tree_mib == 7000
        assert peak.at == 100.5


class TestOwnershipIsRootedAtTheWorker:
    def test_the_candidates_own_pid_is_what_ownership_is_traced_from(self):
        """`gpu_accounting` decides "ours" by ancestry from a root PID, and
        it tests what it is given. Handing it the TUNER's pid instead of
        the worker's would claim every sibling GPU process -- a concurrent
        scoring run, the other chain -- as this candidate's requirement,
        and every attribution would still look valid.
        """
        seen: list[int] = []
        clock = _Clock()

        def device_sampler(root_pid, _device):
            seen.append(root_pid)
            return _snapshot((4242, 1000))

        sampler = GpuTreeSampler(
            4242, DEVICE, interval_seconds=0.25, device_sampler=device_sampler, clock=clock
        )
        sampler.poll()
        assert seen == [4242]

    def test_memory_held_by_anyone_else_never_enters_the_peak(self):
        """The device held 9,000 MiB; the candidate held 1,000. Admitting
        on the device total would refuse candidates for other people's
        occupancy, and it is not a requirement at all."""
        clock = _Clock()
        sampler = _sampler([_snapshot((4242, 1000), device_used=9000)], clock)
        sample = sampler.poll()
        clock.now += 1.0
        sampler.stop()

        assert sampler.measure_window(100.0, 101.0).driver_tree_peak_mib == 1000
        assert sample.device_used_mib == 9000
        assert sample.other_mib == 8000, "kept as context, in its own field"


class TestAGapIsNotAZero:
    def test_a_failed_query_carries_no_figure(self):
        clock = _Clock()
        sampler = _sampler([_UNAVAILABLE], clock)
        assert sampler.poll().own_tree_mib is None

    def test_a_failed_query_counts_as_missed_not_as_zero_memory(self):
        clock = _Clock()
        sampler = _sampler([_UNAVAILABLE, _snapshot((4242, 5000))], clock)
        sampler.poll()
        clock.now += 0.5
        sampler.poll()
        clock.now += 0.1
        sampler.stop()

        window = sampler.measure_window(100.0, 101.0)
        assert window.coverage.samples_missed == 1
        assert window.coverage.complete is False, "an incomplete watch fails closed"
        assert window.driver_tree_peak_mib == 5000, (
            "the successful sample is still real evidence; it is the COVERAGE "
            "that refuses, not the figure that vanishes"
        )

    def test_a_raising_device_sampler_is_a_missed_sample(self):
        clock = _Clock()

        def explode(_root, _device):
            raise OSError("nvidia-smi vanished")

        sampler = GpuTreeSampler(
            4242, DEVICE, interval_seconds=0.25, device_sampler=explode, clock=clock
        )
        assert sampler.poll().telemetry_available is False

    def test_a_sample_may_not_be_built_with_figures_and_no_telemetry(self):
        with pytest.raises(ValidationError, match="must stay None"):
            TreeMemorySample(at=1.0, telemetry_available=False, own_tree_mib=0)


class TestSampledZeroIsNotNoObservation:
    def test_a_candidate_holding_nothing_is_a_real_observation(self):
        """Distinct from a missed sample: the driver was asked and
        answered. Collapsing the two would discard evidence that the
        candidate genuinely had not allocated yet."""
        clock = _Clock()
        sampler = _sampler([_snapshot()], clock)
        sample = sampler.poll()
        clock.now += 1.0
        sampler.stop()

        assert sample.telemetry_available is True
        assert sample.own_tree_mib == 0
        window = sampler.measure_window(100.0, 101.0)
        assert window.coverage.samples_taken == 1
        assert window.coverage.samples_missed == 0
        assert window.driver_tree_peak_mib == 0

    def test_no_samples_at_all_yields_no_figure_and_fails_closed(self):
        clock = _Clock()
        sampler = _sampler([], clock)
        clock.now += 1.0
        sampler.stop()

        window = sampler.measure_window(100.0, 101.0)
        assert window.driver_tree_peak_mib is None
        assert window.coverage.samples_taken == 0
        assert window.coverage.complete is False


class TestWindowsKeepPhasesApart:
    def test_a_sample_outside_the_window_is_not_consulted(self):
        """The training peak must never be able to answer the inference
        question. The window is what enforces it."""
        samples = [
            TreeMemorySample(at=100.0, telemetry_available=True, own_tree_mib=20_000),
            TreeMemorySample(at=105.0, telemetry_available=True, own_tree_mib=3_000),
        ]
        window = measure_window(
            samples,
            started_at=104.0,
            ended_at=106.0,
            interval_seconds=0.25,
            watch_started_at=99.0,
            watch_stopped_at=107.0,
        )
        assert window.driver_tree_peak_mib == 3_000

    def test_a_watch_that_started_late_is_not_complete(self):
        """The unobserved head of a phase can hold the peak, so the
        measurement is unknown rather than smaller."""
        samples = [TreeMemorySample(at=105.0, telemetry_available=True, own_tree_mib=3_000)]
        window = measure_window(
            samples,
            started_at=104.0,
            ended_at=106.0,
            interval_seconds=0.25,
            watch_started_at=104.5,
            watch_stopped_at=107.0,
        )
        assert window.coverage.covered_whole_phase is False
        assert window.coverage.complete is False

    def test_a_watch_that_stopped_early_is_not_complete(self):
        samples = [TreeMemorySample(at=105.0, telemetry_available=True, own_tree_mib=3_000)]
        window = measure_window(
            samples,
            started_at=104.0,
            ended_at=106.0,
            interval_seconds=0.25,
            watch_started_at=100.0,
            watch_stopped_at=105.5,
        )
        assert window.coverage.covered_whole_phase is False

    def test_a_fully_covered_window_is_complete(self):
        """Positive control: coverage must refuse gappy watches, not every
        watch."""
        samples = [
            TreeMemorySample(at=t, telemetry_available=True, own_tree_mib=1_000)
            for t in (104.2, 104.6, 105.0, 105.4, 105.8)
        ]
        window = measure_window(
            samples,
            started_at=104.0,
            ended_at=106.0,
            interval_seconds=0.5,
            watch_started_at=103.0,
            watch_stopped_at=107.0,
        )
        assert window.coverage.complete is True
        assert window.coverage.incompleteness_reason is None


class TestTheUnwatchedStretchStaysVisible:
    def test_the_largest_gap_includes_the_window_edges(self):
        """A window whose only sample sits at its start was unwatched for
        the rest of it. Measuring gaps only between samples would report
        0.0 s of exposure for exactly that case."""
        samples = [TreeMemorySample(at=100.1, telemetry_available=True, own_tree_mib=5)]
        window = measure_window(
            samples,
            started_at=100.0,
            ended_at=102.0,
            interval_seconds=0.25,
            watch_started_at=99.0,
            watch_stopped_at=103.0,
        )
        assert window.coverage.max_gap_seconds == pytest.approx(1.9)

    def test_an_unsampled_window_reports_its_whole_length_as_the_gap(self):
        window = measure_window(
            [],
            started_at=100.0,
            ended_at=102.0,
            interval_seconds=0.25,
            watch_started_at=99.0,
            watch_stopped_at=103.0,
        )
        assert window.coverage.max_gap_seconds == pytest.approx(2.0)

    def test_a_gap_alone_does_not_make_a_watch_incomplete(self):
        """Risk and incompleteness are different verdicts. Every polled
        watch is blind between polls; that is quantified, not disqualifying,
        or no measurement could ever be authoritative."""
        samples = [
            TreeMemorySample(at=t, telemetry_available=True, own_tree_mib=5)
            for t in (100.0, 101.0, 102.0)
        ]
        window = measure_window(
            samples,
            started_at=100.0,
            ended_at=102.0,
            interval_seconds=1.0,
            watch_started_at=99.0,
            watch_stopped_at=103.0,
        )
        assert window.coverage.max_gap_seconds == pytest.approx(1.0)
        assert window.coverage.complete is True


class TestTheCadence:
    def test_polling_faster_than_the_interval_takes_no_extra_sample(self):
        """A driver query costs ~72 ms on this deployment; a supervision
        loop calling `poll()` every few milliseconds must not turn that
        into a busy spin."""
        clock = _Clock()
        sampler = _sampler([_snapshot((1, 1)) for _ in range(5)], clock, interval=0.25)
        assert sampler.poll() is not None
        clock.now += 0.05
        assert sampler.poll() is None
        clock.now += 0.25
        assert sampler.poll() is not None
        assert len(sampler.samples) == 2

    def test_force_takes_a_boundary_sample_regardless(self):
        """The caller wants one immediately after spawn and one just
        before reaping; those must not wait for the cadence."""
        clock = _Clock()
        sampler = _sampler([_snapshot((1, 1)), _snapshot((1, 2))], clock)
        sampler.poll()
        assert sampler.poll(force=True) is not None
        assert len(sampler.samples) == 2

    def test_a_nonpositive_interval_is_refused(self):
        with pytest.raises(ValueError, match="must be positive"):
            GpuTreeSampler(1, DEVICE, interval_seconds=0.0)


class TestTheRawSeriesIsRetained:
    def test_every_sample_is_kept_with_its_timestamp(self):
        """A peak with no series behind it cannot be audited, and no later
        question about which phase a spike belonged to can be answered."""
        clock = _Clock()
        sampler = _sampler([_snapshot((1, 100)), _UNAVAILABLE, _snapshot((1, 300))], clock)
        for _ in range(3):
            sampler.poll()
            clock.now += 0.5

        assert [s.at for s in sampler.samples] == [100.0, 100.5, 101.0]
        assert [s.own_tree_mib for s in sampler.samples] == [100, None, 300]
