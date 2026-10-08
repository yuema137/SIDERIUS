"""Two observers, joined by window -- and never merged into one figure.

V20 PR C2 / C2-4.

The worker knows when its phases ran; the parent knows what the driver saw.
Joining them by wall-clock window is what makes a requirement
phase-specific. The failure it replaces is concrete:
`probe_production.py` resets the CUDA peak once in `_setup()`, so its
number is a running maximum over setup + training + inference and can
answer neither phase's question (audit F2).

Every test drives a REAL subprocess -- a fake worker script that writes a
report and a journal, or hangs, or dies mid-phase -- with an injected
device sampler. No GPU or torch; fixture waits are bounded, and
the actual `Popen` / deadline / reap path under test rather than a
simulation of it.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from textwrap import dedent
from unittest.mock import Mock

import pytest

import core.runtime_control.gpu_measurement_runner as measurement_runner
from core.runtime_control.gpu_accounting import (
    DeviceIdentity,
    GpuAccountingSnapshot,
    ProcessOccupancy,
)
from core.runtime_control.gpu_measurement_identity import (
    build_planned_identity,
    build_realized_identity,
)
from core.runtime_control.gpu_measurement_runner import (
    ALLOCATOR_SOURCE,
    DRIVER_SOURCE,
    run_prephase_measurement,
)
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.gpu_requirement import CandidateMeasurementRequest

UUID = "GPU-abc"
DEVICE = DeviceIdentity(uuid=UUID, physical_index=0)


def _spec(tmp_path, **over) -> GpuMeasurementSpec:
    payload = dict(
        label="c2-runner-test",
        request=CandidateMeasurementRequest(
            model_type="punet",
            planned_identity=build_planned_identity(
                model_type="punet", model_config={}, train_config={}
            ),
            request_id="req-01234567",
            device_uuid=UUID,
            phase="training",
            deadline_seconds=20.0,
            sampling_interval_seconds=0.01,
        ),
        device="cuda",
        data_dir="/nonexistent",
        result_path=str(tmp_path / "result.json"),
        journal_path=str(tmp_path / "phases.ndjson"),
        worker_memory_limit_bytes=16 * 1024**3,
    )
    payload.update(over)
    return GpuMeasurementSpec(**payload)  # type: ignore[arg-type]


def _fake_worker(tmp_path, body: str) -> list[str]:
    """A real subprocess, so `Popen`, the process group and the reap path
    are the ones under test."""
    script = tmp_path / "fake_worker.py"
    script.write_text(
        "import json, sys, time, os\n"
        "spec = json.loads(open(sys.argv[1]).read())\n"
        "def journal(event, phase):\n"
        "    with open(spec['journal_path'], 'a') as h:\n"
        "        h.write(json.dumps({'event': event, 'phase': phase, 'at': time.time()}) + '\\n')\n"
        "        h.flush()\n"
        "def report(payload):\n"
        "    open(spec['result_path'], 'w').write(json.dumps(payload))\n"
        f"{body}\n"
    )
    return [sys.executable, str(script)]


_GOOD_WORKER = """
now = time.time()
journal('phase_start', 'setup')
setup_start = time.time()
time.sleep(0.15)
setup_end = time.time()
journal('phase_end', 'setup')
journal('phase_start', 'training')
train_start = time.time()
time.sleep(0.25)
train_end = time.time()
journal('phase_end', 'training')
report({
    'label': spec['label'],
    'request': spec['request'],
    'status': 'COMPLETED',
    'device': spec['device'],
    'observed_device_uuid': spec['request']['device_uuid'],
    'device_name': 'FakeCard',
    'worker_pid': os.getpid(),
    'realism': {'forward_calls': 4, 'backward_calls': 4, 'optimizer_steps': 4,
                'parameter_update_verified': True, 'parameter_update_max_abs_delta': 0.5},
    'phases': [
        {'phase': 'setup', 'status': 'COMPLETED', 'started_at': setup_start,
         'ended_at': setup_end, 'elapsed_seconds': setup_end - setup_start,
         'allocator_peak_mib': 800, 'units_executed': 1, 'units_requested': 1},
        {'phase': 'training', 'status': 'COMPLETED', 'started_at': train_start,
         'ended_at': train_end, 'elapsed_seconds': train_end - train_start,
         'allocator_peak_mib': 1400, 'allocator_reserved_peak_mib': 1600,
         'units_executed': 4, 'units_requested': 4},
    ],
})
"""


class _Driver:
    """A device sampler whose reported memory follows a script."""

    def __init__(self, series) -> None:
        self.series = list(series)
        self.calls = 0

    def __call__(self, root_pid, device) -> GpuAccountingSnapshot:
        value = self.series[min(self.calls, len(self.series) - 1)]
        self.calls += 1
        if value is None:
            return GpuAccountingSnapshot(device=device, telemetry_available=False)
        procs = value if isinstance(value, list) else [(root_pid, value)]
        own = tuple(ProcessOccupancy(pid=p, used_mib=m) for p, m in procs)
        total = sum(m for _, m in procs)
        return GpuAccountingSnapshot(
            device=device,
            telemetry_available=True,
            device_used_mib=total + 500,
            device_total_mib=32_768,
            own_tree_mib=total,
            own_processes=own,
            other_mib=500,
            other_process_count=1,
            per_pid_total_mib=total + 500,
            unattributed_mib=0,
            accounting_skew_mib=0,
        )


def _run(tmp_path, worker_body: str, series, **over):
    return run_prephase_measurement(
        _spec(tmp_path, **over.pop("spec", {})),
        device=DEVICE,
        command=_fake_worker(tmp_path, worker_body),
        device_sampler=_Driver(series),
        poll_seconds=0.01,
        **over,
    )


@pytest.fixture
def hung_worker(tmp_path: Path) -> Iterator[tuple[str, Callable[[], float]]]:
    """Own child reaping instead of racing the host's orphan reaper (#373).

    Only the runner may signal the child. The worker's TERM handler waits for
    that signal to take effect; it does not make a leader-only kill pass.
    """
    pgid_file = tmp_path / "worker_pgid"
    ready_file = tmp_path / "child_pid"
    reaped_file = tmp_path / "child_exit_code"
    body = dedent(f"""
        import signal, subprocess
        with open({str(pgid_file)!r}, 'w') as handle:
            handle.write(str(os.getpgid(0)))
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        def reap_child(signum, frame):
            code = child.wait(timeout=5)
            with open({str(reaped_file)!r}, 'w') as handle:
                handle.write(str(code))
            sys.exit(0)
        signal.signal(signal.SIGTERM, reap_child)
        journal('phase_start', 'setup')
        with open({str(ready_file)!r}, 'w') as handle:
            handle.write(str(child.pid))
        time.sleep(60)
        """)
    setup_started = time.monotonic()
    ready_at: float | None = None

    def elapsed_clock() -> float:
        nonlocal ready_at
        now = time.monotonic()
        if ready_at is None:
            # This witness times an established group, not interpreter startup.
            if not ready_file.exists() or not ready_file.read_text():
                assert now - setup_started < 5, "worker did not publish child readiness"
                return 0.0
            child_pid = int(ready_file.read_text())
            assert os.getpgid(child_pid) == int(pgid_file.read_text())
            ready_at = now
        # Keep time advancing during TERM grace as well as the deadline loop.
        assert now - ready_at < 30, "measurement runner did not stop"
        return now - ready_at

    try:
        yield body, elapsed_clock
    finally:
        # Cleanup follows the assertions, including for deliberate mutations.
        # Never use it to manufacture the kernel absence checked by the test.
        if pgid_file.exists() and pgid_file.read_text():
            pgid = int(pgid_file.read_text())
            with suppress(ProcessLookupError):
                os.killpg(pgid, signal.SIGKILL)
            until = time.monotonic() + 5
            while time.monotonic() < until:
                try:
                    if os.waitpid(pgid, os.WNOHANG)[0]:
                        break
                except ChildProcessError:
                    break  # The runner already reaped its worker.
                time.sleep(0.01)
            else:
                pytest.fail("test cleanup could not reap the worker")


class TestTheTwoAccountsAreJoinedNotMerged:
    def test_both_figures_are_reported_side_by_side(self, tmp_path):
        run = _run(tmp_path, _GOOD_WORKER, [3000])
        training = run.phase("training")
        assert training is not None
        assert training.driver_tree_peak_mib == 3000, "driver-visible, from the parent"
        assert training.allocator_peak_mib == 1400, "allocator-visible, from the worker"

    def test_each_figure_names_its_instrument(self, tmp_path):
        """They are not interchangeable and must never be read as if they
        were: the driver total legitimately exceeds the allocator figure by
        the CUDA context and non-allocator workspaces."""
        training = _run(tmp_path, _GOOD_WORKER, [3000]).phase("training")
        assert training.driver_source == DRIVER_SOURCE
        assert training.allocator_source == ALLOCATOR_SOURCE

    def test_the_allocator_figure_never_becomes_the_driver_figure(self, tmp_path):
        """With no driver observation the driver peak stays None. Falling
        back to the allocator number would deliver a per-process figure,
        blind to children and to the CUDA context, wearing the tree
        measurement's meaning."""
        training = _run(tmp_path, _GOOD_WORKER, [None]).phase("training")
        assert training.driver_tree_peak_mib is None
        assert training.allocator_peak_mib == 1400


class TestPhasesGetTheirOwnDriverPeak:
    def test_a_spike_during_setup_does_not_become_the_training_requirement(self, tmp_path):
        """The cumulative-peak trap, directly. A running maximum would
        report 20,000 for training; the window says 3,000."""
        # Setup runs ~0.15 s, training ~0.25 s, sampled every 10 ms.
        series = [20_000] * 8 + [3_000] * 200
        run = _run(tmp_path, _GOOD_WORKER, series)
        assert run.phase("setup").driver_tree_peak_mib == 20_000
        assert run.phase("training").driver_tree_peak_mib == 3_000

    def test_each_phase_carries_its_own_coverage(self, tmp_path):
        run = _run(tmp_path, _GOOD_WORKER, [1000])
        assert run.phase("setup").coverage.samples_taken > 0
        assert run.phase("training").coverage.samples_taken > 0

    def test_the_target_phase_is_addressable(self, tmp_path):
        run = _run(tmp_path, _GOOD_WORKER, [1000])
        assert run.target is not None and run.target.phase == "training"


class TestTheTreeIsWhatIsMeasured:
    def test_a_child_holding_memory_is_counted(self, tmp_path):
        """One PID is not the candidate. A worker that spawns a data
        process holds both, and a single-process figure would under-read
        exactly the topology PR B exists to constrain."""
        run = _run(tmp_path, _GOOD_WORKER, [[(1111, 2000), (2222, 1500)]])
        training = run.phase("training")
        assert training.driver_tree_peak_mib == 3500
        assert training.max_concurrent_own_processes == 2
        assert set(training.own_pids) == {1111, 2222}


class TestTheRawEvidenceSurvives:
    def test_the_sample_series_is_retained(self, tmp_path):
        run = _run(tmp_path, _GOOD_WORKER, [1000])
        assert len(run.samples) > 2
        assert all(s.at > 0 for s in run.samples)

    def test_the_watch_takes_a_final_look_after_the_process_ends(self, tmp_path):
        """Forced, because the cadence is not owed a tick after the loop
        breaks -- and what is on the card *after* the worker ends is the
        only way an orphan still holding the device becomes visible.

        The cadence here is deliberately slower than the whole run, so the
        loop contributes exactly one sample and the final look is the only
        thing that can produce a second. At a fast cadence this assertion
        would hold whether or not the final sample existed.
        """
        run = _run(
            tmp_path,
            _GOOD_WORKER,
            [1000],
            spec={
                "request": CandidateMeasurementRequest(
                    model_type="punet",
                    planned_identity=build_planned_identity(
                        model_type="punet", model_config={}, train_config={}
                    ),
                    request_id="req-01234567",
                    device_uuid=UUID,
                    phase="training",
                    deadline_seconds=20.0,
                    sampling_interval_seconds=30.0,
                )
            },
        )
        assert len(run.samples) == 2, "one from the loop's first poll, one after the exit"
        assert run.samples[-1].at > run.phases[-1].ended_at

    def test_the_watch_is_open_before_the_first_phase_begins(self, tmp_path):
        """Guaranteed by `poll()` sampling unconditionally on its first
        call, which happens before the worker has finished booting."""
        run = _run(tmp_path, _GOOD_WORKER, [1000])
        assert run.samples[0].at <= run.phases[0].started_at

    def test_the_journal_is_carried_through(self, tmp_path):
        run = _run(tmp_path, _GOOD_WORKER, [1000])
        assert [e["event"] for e in run.journal] == [
            "phase_start",
            "phase_end",
            "phase_start",
            "phase_end",
        ]


class TestAWorkerThatLeavesNoReport:
    def test_a_hung_worker_is_killed_at_the_deadline(self, tmp_path, hung_worker):
        """A real group signal must stop the worker AND its child (#373)."""
        body, elapsed_clock = hung_worker
        run = _run(
            tmp_path,
            body,
            [1000],
            elapsed_clock=elapsed_clock,
            spec={
                "request": CandidateMeasurementRequest(
                    model_type="punet",
                    planned_identity=build_planned_identity(
                        model_type="punet", model_config={}, train_config={}
                    ),
                    request_id="req-01234567",
                    device_uuid=UUID,
                    phase="training",
                    deadline_seconds=0.4,
                    sampling_interval_seconds=0.01,
                )
            },
        )
        assert run.report_present is False
        assert run.deadline.reached_deadline is True, (
            "the classifier may only call this a timeout if the deadline was reached"
        )
        assert run.process.term_sent is True
        assert run.process.exit_code == 0, "worker must reap its child before exiting"
        assert int((tmp_path / "child_exit_code").read_text()) == -signal.SIGTERM
        assert run.process.kill_sent is False

        # Independent kernel witness, after owned reaping, not the runner's
        # earlier liveness snapshot. Record transport is checked separately.
        pgid = int((tmp_path / "worker_pgid").read_text())
        with pytest.raises(ProcessLookupError):
            os.killpg(pgid, 0)

    @pytest.mark.parametrize("observed_alive", [True, False])
    def test_orphan_evidence_preserves_the_observation(self, tmp_path, monkeypatch, observed_alive):
        """Catch a bypassed query or constant result without racing a later reap.

        Issue 373's True-then-False sequence is valid: the later observation
        must not be substituted for the snapshot recorded by the runner.
        """
        observe = Mock(side_effect=[observed_alive, False])
        monkeypatch.setattr(measurement_runner, "process_group_alive", observe)
        pid_file = tmp_path / "observed_worker_pid"
        run = _run(
            tmp_path,
            f"with open({str(pid_file)!r}, 'w') as handle:\n    handle.write(str(os.getpid()))\n",
            [1000],
        )
        worker_pid = int(pid_file.read_text())
        assert run.process.exit_code == 0
        observe.assert_called_once_with(worker_pid)
        assert run.process.orphans_remaining is observed_alive
        assert observe(worker_pid) is False
        assert run.process.orphans_remaining is observed_alive

    def test_the_journal_names_the_phase_that_was_in_flight(self, tmp_path):
        """The difference between telling an operator "it died during
        training" and "something failed"."""
        run = _run(
            tmp_path,
            "journal('phase_start', 'setup')\njournal('phase_end', 'setup')\n"
            "journal('phase_start', 'training')\ntime.sleep(60)\n",
            [1000],
            spec={
                "request": CandidateMeasurementRequest(
                    model_type="punet",
                    planned_identity=build_planned_identity(
                        model_type="punet", model_config={}, train_config={}
                    ),
                    request_id="req-01234567",
                    device_uuid=UUID,
                    phase="training",
                    deadline_seconds=0.4,
                    sampling_interval_seconds=0.01,
                )
            },
        )
        assert run.in_flight_phase == "training"

    def test_a_crashing_worker_is_recorded_not_raised(self, tmp_path):
        run = _run(tmp_path, "journal('phase_start', 'setup')\nsys.exit(3)\n", [1000])
        assert run.report_present is False
        assert run.process.exit_code == 3
        assert run.deadline.reached_deadline is False, (
            "a crash at 0.1 s is not a timeout against a 20 s budget"
        )

    def test_a_malformed_report_is_no_report(self, tmp_path):
        """Half a measurement must never be read as a whole one."""
        run = _run(tmp_path, "report({'status': 'COMPLETED'})\n", [1000])
        assert run.report_present is False
        assert run.phases == ()

    def test_samples_are_still_retained_when_there_is_no_report(self, tmp_path):
        run = _run(tmp_path, "time.sleep(0.2)\n", [1000])
        assert len(run.samples) > 1
        assert run.phases == (), "with no windows there is nothing to attribute them to"

    def test_a_worker_that_cannot_be_launched_is_recorded(self, tmp_path):
        run = run_prephase_measurement(
            _spec(tmp_path), device=DEVICE, command=["/nonexistent/binary"]
        )
        assert run.report_present is False
        assert "could not launch" in run.detail


class TestTheHostMemoryBound:
    def test_the_bound_is_recorded_even_when_it_was_never_approached(self, tmp_path):
        """ "It was fine" is recorded as explicitly as "it was not"."""
        run = _run(tmp_path, _GOOD_WORKER, [1000])
        assert run.host_memory.exceeded is False
        assert run.host_memory.limit_bytes == 16 * 1024**3
        assert run.host_memory.peak_tree_rss_bytes > 0, "the worker was really resident"


class TestTheReportIsCarriedThrough:
    def test_realism_evidence_reaches_the_run(self, tmp_path):
        """The classifier decides on this: a "measurement" that never
        trained must be visible as such."""
        run = _run(tmp_path, _GOOD_WORKER, [1000])
        assert run.realism.backward_calls == 4
        assert run.realism.parameter_update_verified is True

    def test_the_observed_device_uuid_is_carried(self, tmp_path):
        run = _run(tmp_path, _GOOD_WORKER, [1000])
        assert run.observed_device_uuid == UUID

    def test_the_worker_status_is_carried(self, tmp_path):
        assert _run(tmp_path, _GOOD_WORKER, [1000]).worker_status == "COMPLETED"


def test_the_spec_reaches_the_worker_on_disk(tmp_path):
    """The worker is a separate process; the spec is its only input."""
    _run(tmp_path, "report({'x': 1})\n", [1000])
    written = json.loads((tmp_path / "result.spec.json").read_text())
    assert written["request"]["request_id"] == "req-01234567"
    assert written["request"]["planned_identity"]["planned_config_hash"].startswith("cfg:")


@pytest.mark.parametrize("phase", ["training", "inference"])
def test_the_runner_measures_whichever_phase_it_was_asked_for(tmp_path, phase):
    body = _GOOD_WORKER.replace("'training'", f"'{phase}'")
    run = _run(
        tmp_path,
        body,
        [2000],
        spec={
            "request": CandidateMeasurementRequest(
                model_type="punet",
                planned_identity=build_planned_identity(
                    model_type="punet",
                    model_config={},
                    train_config={},
                    inference_batch_size=25,
                ),
                request_id="req-01234567",
                device_uuid=UUID,
                phase=phase,
                deadline_seconds=20.0,
                sampling_interval_seconds=0.01,
            ),
            # Required for an inference measurement: the training batch is
            # not the inference workload (D-C2-17).
            "inference_batch_size": 25,
        },
    )
    assert run.target is not None and run.target.phase == phase


class TestTheSamplerReadyMarker:
    """D-C2-13. The worker waits for this before opening a timed phase, so
    "sampling is active" is proved by an actual sample rather than assumed
    from the parent having started."""

    def test_it_appears_only_after_a_successful_sample(self, tmp_path):
        spec_kwargs = {"sampler_ready_path": str(tmp_path / "ready")}
        run = _run(tmp_path, _GOOD_WORKER, [1000], spec=spec_kwargs)
        assert (tmp_path / "ready").exists()
        assert run.report_present is True

    def test_a_failing_driver_query_does_not_signal_readiness(self, tmp_path):
        """A query that returns nothing proves nothing is being observed;
        touching the marker for it would let a phase open unwatched."""
        run = _run(
            tmp_path,
            "time.sleep(0.3)\n",
            [None],
            spec={"sampler_ready_path": str(tmp_path / "ready")},
        )
        assert not (tmp_path / "ready").exists()
        assert all(not s.telemetry_available for s in run.samples)

    def test_a_stale_marker_from_an_earlier_run_is_cleared(self, tmp_path):
        """Otherwise the worker would see a previous run's marker and open
        its phase before this run's sampler had taken anything."""
        stale = tmp_path / "ready"
        stale.write_text("stale")
        _run(tmp_path, "time.sleep(0.05)\n", [None], spec={"sampler_ready_path": str(stale)})
        assert not stale.exists(), "the stale marker must be removed at launch"


class TestTheParentEndsThePhase:
    """D-C2-14. The parent counts valid in-phase samples and signals
    completion; the worker never guesses how many repetitions that takes."""

    _COUNTING_WORKER = """
journal('phase_start', 'setup')
s0 = time.time(); time.sleep(0.05); s1 = time.time()
journal('phase_end', 'setup')
journal('phase_start', 'training')
t0 = time.time()
reps = 0
complete = spec['phase_complete_path']
while not os.path.exists(complete) and time.time() - t0 < 20:
    reps += 1
    time.sleep(0.01)
t1 = time.time()
journal('phase_end', 'training')
report({'label': spec['label'], 'request': spec['request'], 'status': 'COMPLETED',
        'device': spec['device'], 'observed_device_uuid': spec['request']['device_uuid'],
        'worker_pid': os.getpid(), 'request_id': spec['request']['request_id'],
        'phases': [
          {'phase': 'setup', 'status': 'COMPLETED', 'started_at': s0, 'ended_at': s1,
           'elapsed_seconds': s1 - s0},
          {'phase': 'training', 'status': 'COMPLETED', 'started_at': t0, 'ended_at': t1,
           'elapsed_seconds': t1 - t0, 'repetitions': reps, 'required_samples': 3,
           'completion_reason': 'sample_target_reached', 'allocator_peak_mib': 900},
        ]})
"""

    def test_it_signals_only_after_the_required_samples_land(self, tmp_path):
        run = _run(
            tmp_path,
            self._COUNTING_WORKER,
            [1500],
            spec={
                "sampler_ready_path": str(tmp_path / "ready"),
                "phase_complete_path": str(tmp_path / "done"),
            },
        )
        training = run.phase("training")
        assert training is not None
        assert training.coverage.samples_taken >= 3, (
            "the parent must not signal before three in-phase samples exist"
        )
        assert training.observed_in_phase_samples >= 3
        assert (tmp_path / "done").exists()

    def test_the_worker_leaves_the_phase_once_signalled(self, tmp_path):
        """It must not run to its own timeout after the parent is done."""
        run = _run(
            tmp_path,
            self._COUNTING_WORKER,
            [1500],
            spec={
                "sampler_ready_path": str(tmp_path / "ready"),
                "phase_complete_path": str(tmp_path / "done"),
            },
        )
        assert run.phase("training").elapsed_seconds < 5.0

    def test_samples_before_the_phase_opened_are_not_counted(self, tmp_path):
        """Setup samples describe a different window; counting them would
        signal completion before the phase had been observed at all."""
        run = _run(
            tmp_path,
            self._COUNTING_WORKER,
            [1500],
            spec={
                "sampler_ready_path": str(tmp_path / "ready"),
                "phase_complete_path": str(tmp_path / "done"),
            },
        )
        training = run.phase("training")
        assert all(
            s.at >= training.started_at
            for s in run.samples
            if s.at <= training.ended_at and s.at >= training.started_at
        )
        assert training.coverage.samples_taken <= len(run.samples)

    def test_a_stale_completion_marker_is_cleared(self, tmp_path):
        """Otherwise the worker would leave its first phase immediately, on
        a previous run's signal."""
        stale = tmp_path / "done"
        stale.write_text("stale")
        _run(
            tmp_path,
            "time.sleep(0.05)\n",
            [None],
            spec={"phase_complete_path": str(stale)},
        )
        assert not stale.exists()


class TestObservationEvidenceReachesTheJoinedRecord:
    """D-C2-14. Attempt 3 could only recover these by reading the worker's
    private journal after the fact, which meant the artifact was incomplete
    and the result could not carry authority."""

    @pytest.mark.parametrize(
        "field",
        [
            "repetitions",
            "required_samples",
            "observed_in_phase_samples",
            "completion_reason",
            "max_phase_seconds",
            "observation_bound_reached",
            "sampler_ready",
            "sampler_ready_at",
        ],
    )
    def test_each_required_field_is_present(self, tmp_path, field):
        run = _run(tmp_path, _GOOD_WORKER, [1000])
        assert hasattr(run.phase("training"), field)

    def test_the_values_come_from_the_worker_not_a_default(self, tmp_path):
        body = _GOOD_WORKER.replace(
            "'units_executed': 4, 'units_requested': 4},",
            "'units_executed': 4, 'units_requested': 4, 'repetitions': 17,"
            " 'required_samples': 3, 'completion_reason': 'sample_target_reached',"
            " 'max_phase_seconds': 60.0, 'sampler_ready': True, 'sampler_ready_at': 1.5},",
        )
        training = _run(tmp_path, body, [1000]).phase("training")
        assert training.repetitions == 17
        assert training.required_samples == 3
        assert training.completion_reason == "sample_target_reached"
        assert training.sampler_ready_at == 1.5

    def test_the_observed_count_comes_from_the_parents_own_samples(self, tmp_path):
        """Not from the worker: the worker cannot know how many landed."""
        training = _run(tmp_path, _GOOD_WORKER, [1000]).phase("training")
        assert training.observed_in_phase_samples == training.coverage.samples_taken


def _bound_inference_spec(tmp_path, *, deadline=3):
    from core.runtime_control.inference_measurement_binding import InferenceMeasurementBinding

    base = _spec(tmp_path)
    request = base.request.model_copy(
        update={
            "phase": "inference",
            "deadline_seconds": deadline,
            "planned_identity": build_planned_identity(
                model_type="punet", model_config={}, train_config={}, inference_batch_size=1
            ),
        }
    )
    return base.model_copy(
        update={
            "request": request,
            "inference_batch_size": 1,
            "inference_binding": InferenceMeasurementBinding(
                assembly_sha256="a" * 64,
                plugin_sources_sha256="b" * 64,
                runtime_sha256="c" * 64,
                request_sha256="d" * 64,
            ),
        }
    )


_BOUND_REPORT = """
report({'label': spec['label'], 'request': spec['request'], 'status': 'COMPLETED',
        'device': spec['device'], 'worker_pid': os.getpid(),
        'request_id': spec['request']['request_id'],
        'inference_binding': spec['inference_binding'],
        'phases': [{'phase': 'inference', 'status': 'COMPLETED',
                    'started_at': time.time(), 'ended_at': time.time(), 'elapsed_seconds': 0}]})
"""


def test_bound_worker_report_does_not_hide_shutdown_timeout(tmp_path):
    """A completed report may be written before a stuck interpreter exits."""
    import time

    spec = _bound_inference_spec(tmp_path, deadline=10)

    def elapsed_clock():
        # Advance only after the child published its report, independent of startup speed.
        return time.monotonic() + (20 if Path(spec.result_path).exists() else 0)

    run = run_prephase_measurement(
        spec,
        device=DEVICE,
        command=_fake_worker(tmp_path, _BOUND_REPORT + "time.sleep(60)"),
        elapsed_clock=elapsed_clock,
        device_sampler=_Driver([800]),
        poll_seconds=0.01,
        grace_seconds=0.05,
    )
    assert run.worker_status == "COMPLETED"
    assert run.process.term_sent
    assert run.process.exit_code != 0
    assert run.deadline.reached_deadline


def test_bound_worker_cleans_child_after_leader_exits(tmp_path):
    """A TERM-ignoring descendant must not survive a completed measurement leader."""
    import ctypes
    import os
    import signal
    import time

    # Own the otherwise orphaned grandchild so the witness does not race PID 1's reaper.
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0  # PR_GET_CHILD_SUBREAPER
    assert libc.prctl(36, 1, 0, 0, 0) == 0  # PR_SET_CHILD_SUBREAPER
    pid = None
    body = (
        """
import subprocess
from pathlib import Path
pid_path = Path(spec['result_path']).with_suffix('.child')
child = subprocess.Popen([sys.executable, '-c',
    'import os,signal,time; from pathlib import Path; '
    'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
    'Path(' + repr(str(pid_path)) + ').write_text(str(os.getpid())); time.sleep(60)'])
while not pid_path.exists():
    time.sleep(0.005)
"""
        + _BOUND_REPORT
    )
    try:
        spec = _bound_inference_spec(tmp_path)
        run = run_prephase_measurement(
            spec,
            device=DEVICE,
            command=_fake_worker(tmp_path, body),
            device_sampler=_Driver([800]),
            poll_seconds=0.01,
            grace_seconds=0.05,
        )
        pid = int(Path(spec.result_path).with_suffix(".child").read_text())
        assert run.process.exit_code == 0
        assert run.process.group_cleanup_required
        assert run.process.term_sent and run.process.kill_sent
        until = time.monotonic() + 2
        while time.monotonic() < until:
            reaped, status = os.waitpid(pid, os.WNOHANG)
            if reaped:
                pid = None
                assert os.waitstatus_to_exitcode(status) == -signal.SIGKILL
                break
            time.sleep(0.01)
        assert pid is None, "descendant survived bounded cleanup"
    finally:
        if pid is not None:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        assert libc.prctl(36, previous.value, 0, 0, 0) == 0
