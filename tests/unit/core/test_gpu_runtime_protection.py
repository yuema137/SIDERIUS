"""CPU witnesses for sampled GPU protection, with no driver or model work."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from core.runtime_control.gpu_accounting import DeviceIdentity, GpuAccountingSnapshot
from core.runtime_control.gpu_observer import GpuObservationPolicy, GpuPhaseObserver
from core.runtime_control.gpu_protection import (
    GpuProtectionBinding,
    GpuRuntimeProtectionPolicy,
    TimedGpuObservation,
    observation_refusal,
    protection_mechanism_digest,
)
from core.runtime_control.gpu_protection_state import ProtectedGpuObservation
from core.runtime_control.observed_subprocess import (
    ProcessControlError,
    ProcessLimits,
    supervise_process,
    supervise_subprocess,
)
from core.runtime_control.process_control import ProcessControlPolicy

DEVICE = DeviceIdentity(uuid="synthetic-device", physical_index=3, telemetry_backend="test")


def snapshot(used=100, *, total=2048, device=DEVICE, **changes):
    fields = dict(
        device=device,
        telemetry_available=True,
        device_total_mib=total,
        device_used_mib=used,
        own_tree_mib=0,
        other_mib=used,
        unattributed_mib=0,
        per_pid_total_mib=used,
        accounting_skew_mib=0,
    )
    fields.update(changes)
    return GpuAccountingSnapshot(**fields)


def policy(*, age=1.0, join_ms=100, poll=0.01, grace=0.1):
    return GpuRuntimeProtectionPolicy(
        observation=GpuObservationPolicy(
            fast_interval_ms=10, fast_window_ms=50, steady_interval_ms=20, join_timeout_ms=join_ms
        ),
        max_sample_age_seconds=age,
        control=ProcessControlPolicy(poll_seconds=poll, grace_seconds=grace, reap_seconds=0.5),
    )


def binding(*, total=2048, cap=1.0):
    return GpuProtectionBinding(
        attempt_token="attempt-a",
        phase="inference",
        device=DEVICE,
        device_total_mib=total,
        effective_ceiling_gib=cap,
        ceiling_origin="explicit test input",
    )


def observation(used=100, *, start=0.0, end=None, total=2048, **changes):
    return TimedGpuObservation(
        sequence=0,
        query_started_at=start,
        query_completed_at=start if end is None else end,
        snapshot=snapshot(used, total=total, **changes),
    )


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


class Child:
    pid = 12345
    returncode = None

    def poll(self):
        return self.returncode


def state_fixture(*, clock=None, initial=None):
    clock = clock or Clock()
    state = ProtectedGpuObservation(binding(), policy(), initial or observation(), clock)
    state.configure(policy().control)
    child = Child()
    state.attach(child)
    state.start(child.pid)
    return state, clock, child


def observer(*, sampler=None, selected=None, clock=time.monotonic, initial=None):
    return GpuPhaseObserver(
        DEVICE,
        protection_policy=selected or policy(),
        protection_binding=binding(),
        initial_observation=initial or observation(start=clock()),
        sampler=sampler or (lambda *_: snapshot()),
        clock=clock,
    )


def run(obs, source="import time; time.sleep(.12)", **kwargs):
    return supervise_process(
        [sys.executable, "-c", source],
        env=dict(os.environ),
        preexec_fn=None,
        capture_stdout=True,
        observer=obs,
        control=obs,
        **kwargs,
    )


@pytest.mark.parametrize("scale", [1, 8, 64])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_total_occupancy_boundary_is_scaled_without_worker_double_count(scale, delta):
    b = binding(total=2048 * scale, cap=float(scale))
    sample = observation(1024 * scale + delta, total=2048 * scale)
    reason = observation_refusal(sample, b, policy(), now=0.0)
    assert bool(reason) == (delta > 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"device": DeviceIdentity(uuid="other", physical_index=3)},
        {"total": 4096},
        {"unattributed_mib": 1},
    ],
)
def test_unusable_device_or_accounting_refuses(changes):
    assert observation_refusal(observation(**changes), binding(), policy(), now=0.0)


def test_query_start_and_future_interval_are_authoritative():
    assert "expired" in observation_refusal(
        observation(start=0.0, end=2.0), binding(), policy(), now=2.0
    )
    assert "future" in observation_refusal(observation(start=2.0), binding(), policy(), now=1.0)
    assert observation_refusal(observation(), binding(), policy(), now=1.0) is None


@pytest.mark.parametrize("bad", ["breach", "exception", "unavailable"])
def test_first_bad_observation_survives_recovery_between_polls(bad):
    state, clock, _ = state_fixture()

    def sample(*_):
        if bad == "exception":
            raise OSError("driver unavailable")
        if bad == "unavailable":
            return GpuAccountingSnapshot(device=DEVICE, telemetry_available=False)
        return snapshot(1500)

    state.sample_once(sample)
    first = state.check(thread_alive=True)
    assert first.status == "stop"
    clock.value = 0.1
    state.sample_once(lambda *_: snapshot(10))
    assert state.check(thread_alive=True) == first
    assert state.receipt().observations == 2


def test_new_fresh_sample_cannot_erase_expired_previous_coverage():
    state, clock, _ = state_fixture()
    state.sample_once(lambda *_: snapshot())
    clock.value = 2.0

    def fresh(*_):
        clock.value = 2.1
        return snapshot()

    state.sample_once(fresh)
    receipt = state.receipt()
    assert receipt.last_live.query_started_at == 2.0  # diagnostic only
    assert receipt.decision.status == "stop"
    assert "expired" in receipt.decision.reason
    assert receipt.first_stop_observation.query_started_at == 0.0


def test_exact_age_renewal_and_terminal_time_exclude_cleanup():
    state, clock, child = state_fixture()
    clock.value = 1.0
    state.sample_once(lambda *_: snapshot())
    assert state.check(thread_alive=True).status == "continue"
    clock.value = 1.5
    child.returncode = 0
    state.end()
    clock.value = 100.0
    state.finish(join_timed_out=False)
    assert state.check(thread_alive=False).status == "continue"
    assert state.receipt().ended_at == 1.5


@pytest.mark.parametrize("live_sample", [False, True])
def test_post_exit_sample_never_improves_live_coverage(live_sample):
    state, clock, child = state_fixture()
    if live_sample:
        state.sample_once(lambda *_: snapshot())

    def crossing(*_):
        child.returncode = 0
        clock.value = 0.1
        return snapshot(0)

    state.sample_once(crossing)
    state.finish(join_timed_out=False)
    receipt = state.receipt()
    assert receipt.valid_live_samples == int(live_sample)
    assert receipt.decision.status == ("continue" if live_sample else "stop")


def test_dead_sampler_and_long_sample_are_not_healthy():
    state, clock, _ = state_fixture()
    assert "not running" in state.check(thread_alive=False).reason
    other, clock, _ = state_fixture()

    def slow(*_):
        clock.value = 2.0
        return snapshot()

    other.sample_once(slow)
    assert "expired" in other.check(thread_alive=True).reason


def test_state_slots_remain_bounded_and_late_completion_cannot_mutate_frozen_receipt():
    state, clock, _ = state_fixture()
    for i in range(100):
        clock.value = i / 100
        state.sample_once(lambda *_: snapshot())
    entered, release = threading.Event(), threading.Event()

    def blocked(*_):
        entered.set()
        assert release.wait(2)
        return snapshot(1500)

    thread = threading.Thread(target=state.sample_once, args=(blocked,))
    thread.start()
    assert entered.wait(1)
    # These acquire the state lock while sampler IO remains blocked.
    state.end()
    state.finish(join_timed_out=True)
    before = state.receipt().model_dump_json()
    release.set()
    thread.join(1)
    assert not thread.is_alive()
    assert state.receipt().model_dump_json() == before
    assert state.receipt().observations == 100
    assert len(before) < 10000


def test_liveness_io_is_outside_state_lock():
    state, _, child = state_fixture()
    entered, release = threading.Event(), threading.Event()

    def blocked_poll():
        entered.set()
        assert release.wait(2)
        return None

    child.poll = blocked_poll
    thread = threading.Thread(target=state.sample_once, args=(lambda *_: snapshot(),))
    thread.start()
    assert entered.wait(1)
    assert state.check(thread_alive=True).status == "continue"
    state.end()
    state.finish(join_timed_out=True)
    release.set()
    thread.join(1)
    assert not thread.is_alive()


@pytest.mark.parametrize(
    "timed,limited", [(False, False), (True, False), (False, True), (True, True)]
)
def test_actual_cpu_child_success_uses_owned_group_and_one_control(timed, limited):
    obs = observer()
    kwargs = {}
    if timed:
        kwargs["deadline_provider"] = lambda: (3.0, "test")
        kwargs["poll_seconds"] = 0.0  # legacy sentinel must not busy-spin protection
    if limited:
        kwargs["limits"] = ProcessLimits(
            deadline_seconds=3.0,
            rss_limit_bytes=2**30,
            poll_seconds=0.02,
            grace_seconds=0.2,
            reap_seconds=0.6,
        )
    result = run(obs, **kwargs)
    assert result.completed.returncode == 0
    assert result.lifecycle.owned_pgid == result.lifecycle.child_pid
    assert result.lifecycle.control_decision.status == "continue"
    receipt = obs.protection_receipt()
    assert receipt.state == "frozen" and receipt.valid_live_samples > 0
    assert receipt.effective_control.poll_seconds == 0.01
    assert receipt.child_pid == result.lifecycle.child_pid


@pytest.mark.parametrize("kind", ["expired", "breach"])
def test_refused_initial_observation_prevents_real_popen(monkeypatch, kind):
    called = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: called.append(kw))
    obs = observer(
        initial=observation(1500 if kind == "breach" else 100, start=0.0),
        clock=lambda: 0.0 if kind == "breach" else 2.0,
    )
    with pytest.raises(ProcessControlError):
        run(obs)
    assert called == []
    receipt = obs.protection_receipt()
    assert receipt.state == "frozen" and receipt.child_pid is None


def test_actual_occupancy_stop_retains_child_output_and_does_not_become_oom():
    count = 0

    def rising(*_):
        nonlocal count
        count += 1
        return snapshot(1500 if count > 10 else 100)

    obs = observer(sampler=rising)
    with pytest.raises(ProcessControlError) as caught:
        run(obs, "import time; print('owned output', flush=True); time.sleep(10)")
    error = caught.value
    assert "occupancy" in error.decision.reason
    assert "owned output" in error.stdout
    assert error.lifecycle.child_reaped
    assert error.lifecycle.group_cleanup.final.status == "absent"
    assert obs.protection_receipt().decision == error.decision


def test_zero_exit_after_term_still_carries_original_guard_stop(tmp_path):
    ready = tmp_path / "ready"

    def sample(*_):
        return snapshot(1500 if ready.exists() else 100)

    obs = observer(sampler=sample, selected=policy(grace=0.5))
    source = f"import signal,time,pathlib; signal.signal(signal.SIGTERM, lambda *_: exit(0)); pathlib.Path({str(ready)!r}).touch(); time.sleep(10)"
    with pytest.raises(ProcessControlError) as caught:
        run(obs, source)
    assert caught.value.lifecycle.returncode == 0
    assert caught.value.decision.status == "stop"


def test_inflight_query_join_timeout_is_bounded_and_late_write_discarded():
    entered, release = threading.Event(), threading.Event()

    def blocked(*_):
        entered.set()
        release.wait(3)
        return snapshot()

    obs = observer(sampler=blocked, selected=policy(age=0.1, join_ms=10))
    try:
        with pytest.raises(ProcessControlError):
            run(obs, "import time; time.sleep(10)")
        assert entered.is_set()
        before = obs.protection_receipt().model_dump_json()
        assert obs.protection_receipt().join_timed_out
    finally:
        release.set()
        if obs._thread is not None:
            obs._thread.join(1)
    assert obs.protection_receipt().model_dump_json() == before


@pytest.mark.parametrize("stage", ["popen", "start"])
def test_startup_error_freezes_and_preserves_original_exception(monkeypatch, stage):
    obs = observer()
    original = RuntimeError("startup failure")

    def fail(*_args, **_kwargs):
        raise original

    if stage == "popen":
        monkeypatch.setattr(subprocess, "Popen", fail)
    else:
        monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(RuntimeError) as caught:
        run(obs)
    assert caught.value is original
    receipt = obs.protection_receipt()
    assert receipt.state == "frozen"
    if stage == "start":
        assert caught.value.process_lifecycle.child_reaped
    with pytest.raises(ValueError, match="single-use"):
        obs.configure_control(policy().control)


def test_package_aware_facade_transports_control():
    obs = observer()
    result = supervise_subprocess(
        [sys.executable, "-c", "import time; time.sleep(.1)"],
        env=dict(os.environ),
        preexec_fn=None,
        capture_stdout=True,
        observer=obs,
        control=obs,
    )
    assert result.lifecycle.control_decision.status == "continue"
    assert obs.protection_receipt().state == "frozen"


def test_mechanism_identity_covers_decision_and_lifecycle_sources(monkeypatch):
    original = Path.read_bytes
    baseline = protection_mechanism_digest()
    for name in (
        "gpu_observer.py",
        "gpu_protection_state.py",
        "process_control.py",
        "observed_subprocess.py",
        "process_group.py",
        "gpu_accounting.py",
    ):
        with monkeypatch.context() as patch:
            patch.setattr(
                Path,
                "read_bytes",
                lambda path, target=name: (
                    original(path) + (b"\n# changed" if path.name == target else b"")
                ),
            )
            assert protection_mechanism_digest() != baseline


def test_missing_or_mismatched_control_refuses_before_spawn(monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: called.append(kw))
    for mismatch in (False, True):
        obs = observer()
        with pytest.raises(ValueError):
            supervise_process(
                [sys.executable],
                env={},
                preexec_fn=None,
                capture_stdout=True,
                observer=obs,
                control=observer() if mismatch else None,
            )
    assert called == []


def test_active_bounds_intersect_without_changing_absent_control():
    obs = observer(selected=policy(poll=0.04, grace=0.5))
    result = run(
        obs,
        deadline_provider=lambda: (3.0, "test"),
        poll_seconds=0.01,
        grace_seconds=0.1,
        limits=ProcessLimits(
            deadline_seconds=3.0,
            rss_limit_bytes=2**30,
            poll_seconds=0.03,
            grace_seconds=0.2,
            reap_seconds=0.7,
        ),
    )
    assert result.completed.returncode == 0
    effective = obs.protection_receipt().effective_control
    assert effective.poll_seconds == 0.01
    assert effective.grace_seconds == 0.1
    assert effective.reap_seconds == 0.5


def test_zero_exit_finalization_cannot_hide_last_observation_breach(monkeypatch):
    obs = observer()
    original = obs.stop

    def final_breach(**kwargs):
        # An observation received before freeze must defeat apparent child success.
        obs._protected().failed("last observation exceeded the ceiling")
        original(**kwargs)

    monkeypatch.setattr(obs, "stop", final_breach)
    with pytest.raises(ProcessControlError) as caught:
        run(obs)
    assert caught.value.lifecycle.returncode == 0
    assert "last observation" in caught.value.decision.reason


def test_primary_interrupt_survives_monitor_and_stop_failures(monkeypatch):
    obs = observer()
    original = KeyboardInterrupt("operator stop")

    def interrupt():
        raise original

    with pytest.raises(KeyboardInterrupt) as caught:
        run(obs, deadline_provider=interrupt)
    assert caught.value is original
    assert caught.value.process_lifecycle.child_reaped
    assert caught.value.process_lifecycle.control_decision is not None
    assert obs.protection_receipt().state == "frozen"


def test_guard_kills_only_owned_group_and_escalates_ignoring_term(tmp_path):
    ready = tmp_path / "ready"
    foreign = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], start_new_session=True
    )
    obs = observer(
        sampler=lambda *_: snapshot(1500 if ready.exists() else 100), selected=policy(grace=0.02)
    )
    source = (
        "import signal,time,pathlib,subprocess,sys; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(ready)!r}).touch(); time.sleep(10)"
    )
    try:
        with pytest.raises(ProcessControlError) as caught:
            run(obs, source)
        assert caught.value.lifecycle.group_cleanup.kill.status == "delivered"
        assert caught.value.lifecycle.child_reaped
        assert foreign.poll() is None
    finally:
        foreign.kill()
        foreign.wait(timeout=2)


def test_grace_drains_large_child_output_before_exit(tmp_path):
    ready = tmp_path / "ready"
    obs = observer(
        sampler=lambda *_: snapshot(1500 if ready.exists() else 100), selected=policy(grace=1.0)
    )
    source = "import signal,sys,time,pathlib\n"
    source += (
        "def stop(*_):\n sys.stdout.write('x'*1048576); sys.stdout.flush(); sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        f"pathlib.Path({str(ready)!r}).touch()\ntime.sleep(10)\n"
    )
    with pytest.raises(ProcessControlError) as caught:
        run(obs, source)
    assert caught.value.lifecycle.returncode == 0
    assert len(caught.value.stdout) == 1048576
    assert caught.value.lifecycle.group_cleanup.kill is None


def test_package_preparation_error_freezes_without_child(monkeypatch):
    from core.local_code import child

    obs = observer()
    original = ValueError("package failure")

    def fail(*_):
        raise original

    monkeypatch.setattr(child, "prepare_child", fail)
    with pytest.raises(ValueError) as caught:
        supervise_subprocess(
            [sys.executable],
            env={},
            preexec_fn=None,
            capture_stdout=True,
            observer=obs,
            control=obs,
        )
    assert caught.value is original
    assert obs.protection_receipt().state == "frozen"
    assert obs.protection_receipt().child_pid is None


def test_late_healthy_query_does_not_charge_cleanup_time_as_live_staleness():
    state, clock, _ = state_fixture()
    state.sample_once(lambda *_: snapshot())

    def crossing(*_):
        clock.value = 0.1
        state.end()
        clock.value = 3.0
        return snapshot()

    state.sample_once(crossing)
    state.finish(join_timed_out=False)
    assert state.receipt().decision.status == "continue"
    assert state.receipt().valid_live_samples == 1
    assert state.receipt().ended_at == 0.1


def test_no_control_lifecycle_has_no_new_serialized_field():
    from core.runtime_control.observed_subprocess import ProcessLifecycle

    receipt = ProcessLifecycle(elapsed_seconds=0.0)
    assert "control_decision" not in receipt.model_dump(mode="json")
    obs = GpuPhaseObserver(None)
    assert obs.bundle().model_dump() == {
        "device": None,
        "sampling_policy": None,
        "baseline_before_spawn": None,
        "observed_peak": None,
        "last_while_alive": None,
        "post_failure": None,
        "valid_sample_count": 0,
        "failed_sample_count": 0,
        "child_runtime_ms": None,
        "first_valid_offset_ms": None,
        "last_valid_offset_ms": None,
        "observer_join_timed_out": False,
        "observer_error": None,
    }


def test_guard_precedence_retains_competing_watchdog_evidence(monkeypatch):
    obs = observer()
    original = obs.stop

    def failed_reading(**kwargs):
        obs._protected().failed("terminal telemetry unavailable")
        original(**kwargs)

    monkeypatch.setattr(obs, "stop", failed_reading)
    with pytest.raises(ProcessControlError) as caught:
        run(obs, deadline_provider=lambda: (0.0, "explicit time budget"))
    assert caught.value.timeout["deadline_s"] == 0.0
    assert caught.value.timeout["estimate_source"] == "explicit time budget"
    assert caught.value.lifecycle.stop_reason == "watchdog_deadline"
    assert caught.value.decision.status == "stop"


def test_clock_is_read_with_current_slot_after_lock_acquisition():
    state, clock, _ = state_fixture()
    original_lock = state._lock
    attempted = threading.Event()

    class ObservedLock:
        def __enter__(self):
            attempted.set()
            original_lock.acquire()

        def __exit__(self, *_):
            original_lock.release()

    state._lock = ObservedLock()
    decisions = []
    original_lock.acquire()
    thread = threading.Thread(target=lambda: decisions.append(state.check(thread_alive=True)))
    thread.start()
    assert attempted.wait(1)
    # Publish a newer accepted sample while the checker is waiting for the slot.
    clock.value = 0.1
    state._live = observation(start=0.1)
    original_lock.release()
    thread.join(1)
    assert not thread.is_alive()
    assert decisions[0].status == "continue"


def test_guard_cleans_owned_descendant_and_leader_reaps_it(tmp_path):
    ready = tmp_path / "ready"
    obs = observer(
        sampler=lambda *_: snapshot(1500 if ready.exists() else 100), selected=policy(grace=0.5)
    )
    source = (
        "import signal,subprocess,sys,time,pathlib\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
        "def stop(*_):\n child.wait(timeout=2); sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        f"pathlib.Path({str(ready)!r}).write_text(str(child.pid))\n"
        "time.sleep(10)\n"
    )
    with pytest.raises(ProcessControlError) as caught:
        run(obs, source)
    assert caught.value.lifecycle.returncode == 0
    assert caught.value.lifecycle.group_cleanup.required
    assert caught.value.lifecycle.group_cleanup.final.status == "absent"
    with pytest.raises(ProcessLookupError):
        os.kill(int(ready.read_text()), 0)


def test_publication_lock_wait_cannot_hide_previous_coverage_expiry():
    state, clock, _ = state_fixture()
    original_lock = state._lock
    query_entered, query_release, publishing = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    class PublicationLock:
        calls = 0

        def __enter__(self):
            self.calls += 1
            if self.calls == 2:
                publishing.set()
            original_lock.acquire()

        def __exit__(self, *_):
            original_lock.release()

    state._lock = PublicationLock()
    clock.value = 0.2

    def sample(*_):
        query_entered.set()
        assert query_release.wait(2)
        return snapshot()

    thread = threading.Thread(target=state.sample_once, args=(sample,))
    thread.start()
    assert query_entered.wait(1)
    original_lock.acquire()
    try:
        query_release.set()
        assert publishing.wait(1)
        # New sample is still fresh, but OLD coverage expired while waiting.
        clock.value = 1.1
    finally:
        original_lock.release()
    thread.join(1)
    assert not thread.is_alive()
    receipt = state.receipt()
    assert receipt.last_live.query_started_at == 0.2
    assert "expired" in receipt.decision.reason
    assert receipt.first_stop_observation.query_started_at == 0.0
    assert state.check(thread_alive=True).status == "stop"
