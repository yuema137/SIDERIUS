"""Real CPU lifecycle witnesses and unavailable-evidence regressions (#633)."""

from __future__ import annotations

import builtins
import os
import signal
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from core.runtime_control import observed_subprocess as supervisor
from core.runtime_control import process_group as groups
from core.runtime_control.observed_subprocess import (
    ProcessLimits,
    ProcessSupervisionError,
    supervise_process,
)


def run(body, **kwargs):
    return supervise_process(
        [sys.executable, "-c", body],
        env=dict(os.environ),
        preexec_fn=None,
        capture_stdout=True,
        **kwargs,
    )


def limits(**kwargs):
    return ProcessLimits(
        **dict(
            dict(
                deadline_seconds=2,
                rss_limit_bytes=256 * 1024**2,
                poll_seconds=0.01,
                grace_seconds=0.05,
                reap_seconds=0.1,
            ),
            **kwargs,
        )
    )


class Observer:
    def __init__(self, fail=None):
        self.fail = fail
        self.pid = None
        self.stops = 0

    def capture_baseline(self):
        pass

    def start(self, child_pid):
        self.pid = child_pid
        if self.fail == "start":
            raise ValueError("primary start failure")
        if self.fail == "slow":
            time.sleep(0.05)

    def stop(self, **kwargs):
        self.stops += 1
        self.last_failed = kwargs["failed"]
        if self.fail in ("start", "stop"):
            raise RuntimeError("secondary stop failure")


@pytest.mark.parametrize("timed", [False, True])
def test_start_exception_reaps_and_stop_cannot_replace_primary(timed):
    """Previously start ran outside cleanup and stop could replace the cause."""
    observer = Observer("start")
    kwargs = dict(deadline_provider=lambda: (5, "test"), poll_seconds=0.01) if timed else {}
    with pytest.raises(ValueError, match="primary start failure") as caught:
        run("import time; time.sleep(20)", observer=observer, **kwargs)
    assert observer.stops == 1
    with pytest.raises(ProcessLookupError):
        os.kill(observer.pid, 0)
    evidence = caught.value.process_lifecycle
    assert evidence.child_reaped
    assert any("secondary stop failure" in err for err in evidence.cleanup_errors)


def test_stop_failure_is_infrastructure_after_child_reaped():
    observer = Observer("stop")
    with pytest.raises(ProcessSupervisionError) as caught:
        run("print('done')", observer=observer)
    assert observer.stops == 1
    assert caught.value.lifecycle.child_reaped
    assert "observer.stop" in caught.value.lifecycle.cleanup_errors[0]


def test_callback_exception_and_keyboard_interrupt_preserve_owned_cleanup():
    for cause in (LookupError("deadline callback"), KeyboardInterrupt()):

        def callback(cause=cause):
            raise cause

        with pytest.raises(type(cause)) as caught:
            run("import time; time.sleep(20)", deadline_provider=callback, poll_seconds=0.01)
        assert caught.value is cause
        assert cause.process_lifecycle.child_reaped
        with pytest.raises(ProcessLookupError):
            os.killpg(cause.process_lifecycle.owned_pgid, 0)


def test_observer_startup_is_charged_before_work():
    with pytest.raises(ProcessSupervisionError) as caught:
        run(
            "import time; time.sleep(20)",
            observer=Observer("slow"),
            limits=limits(deadline_seconds=0.02),
        )
    assert caught.value.lifecycle.stop_reason == "work_deadline_exceeded"
    assert caught.value.lifecycle.elapsed_seconds >= 0.05


@pytest.mark.parametrize("inherit_pipes", [False, True])
def test_zero_exit_with_descendant_is_not_clean_even_after_cleanup(tmp_path, inherit_pipes):
    """A vanished leader and inherited open pipes used to bypass group cleanup."""
    pid_file = tmp_path / "descendant"
    body = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']"
        + ("" if inherit_pipes else ",stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL")
        + f"); open({str(pid_file)!r},'w').write(str(p.pid))"
    )
    with pytest.raises(ProcessSupervisionError) as caught:
        run(body, limits=limits())
    evidence = caught.value.lifecycle
    assert evidence.child_reaped
    assert evidence.group_cleanup.required
    assert evidence.group_cleanup.term.status == "delivered"
    # Grandchild zombies belong to the host reaper; do not label those absent.
    stat = f"/proc/{int(pid_file.read_text())}/stat"
    if os.path.exists(stat):
        assert open(stat).read().split()[2] == "Z"
        assert evidence.group_cleanup.final.status == "present"


def test_rss_breach_terminates_only_owned_group():
    foreign = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True
    )
    try:
        with pytest.raises(ProcessSupervisionError) as caught:
            run(
                "import time; x=bytearray(32*1024*1024); time.sleep(20)",
                limits=limits(rss_limit_bytes=20 * 1024**2),
            )
        assert caught.value.lifecycle.stop_reason == "host_rss_exceeded"
        assert foreign.poll() is None
        with pytest.raises(ProcessLookupError):
            os.killpg(caught.value.lifecycle.owned_pgid, 0)
    finally:
        foreign.terminate()
        foreign.wait(timeout=2)


@pytest.mark.parametrize("status", ["incomplete", "unavailable"])
def test_missing_rss_refuses_before_spawn(monkeypatch, status):
    monkeypatch.setattr(
        supervisor, "observe_tree_rss", lambda pgid: groups.RssObservation(status=status)
    )
    with patch.object(subprocess, "Popen", side_effect=AssertionError("must not spawn")):
        with pytest.raises(ProcessSupervisionError, match="before launch"):
            run("raise AssertionError('ran')", limits=limits())


def test_monitor_loss_after_spawn_stops_and_retains_uncertainty(monkeypatch):
    observations = iter(
        [
            groups.RssObservation(status="complete"),
            groups.RssObservation(status="unavailable", errors=("lost proc",)),
        ]
    )
    monkeypatch.setattr(supervisor, "observe_tree_rss", lambda pgid: next(observations))
    with pytest.raises(ProcessSupervisionError) as caught:
        run("import time; time.sleep(20)", limits=limits())
    assert caught.value.lifecycle.stop_reason == "monitoring_unavailable"
    assert caught.value.lifecycle.child_reaped


@pytest.mark.parametrize("error", [PermissionError("denied"), FileNotFoundError("no proc")])
def test_unreadable_proc_is_unavailable_but_legacy_projection_stays_zero(monkeypatch, error):
    def fail(path):
        raise error

    monkeypatch.setattr(groups.os, "listdir", fail)
    assert groups.observe_tree_rss(os.getpgrp()).status == "unavailable"
    assert groups.tree_rss_bytes(os.getpgrp()) == 0


def test_member_rss_and_membership_failures_are_not_zero(monkeypatch):
    monkeypatch.setattr(groups.os, "listdir", lambda path: ["123"])
    monkeypatch.setattr(groups.os, "getpgid", lambda pid: 100)
    for content in ("broken", "3 -1"):
        from io import StringIO

        monkeypatch.setattr(builtins, "open", lambda path, content=content: StringIO(content))
        assert groups.observe_tree_rss(100).status == "incomplete"

    def denied(*args):
        raise PermissionError("membership")

    monkeypatch.setattr(groups.os, "getpgid", denied)
    assert groups.observe_tree_rss(100).status == "incomplete"


def test_permission_error_cannot_certify_group_cleanup(monkeypatch):
    def denied(*args):
        raise PermissionError("signal denied")

    monkeypatch.setattr(groups.os, "killpg", denied)
    assert groups.observe_group(123).status == "unknown"
    assert groups.observe_signal(123, signal.SIGTERM).status == "unavailable"
    cleanup = groups.terminate_observed_group(123, grace_seconds=0, poll_seconds=0.01)
    assert cleanup.required
    assert cleanup.final.status == "unknown"
    assert cleanup.term.status == cleanup.kill.status == "unavailable"
    # Existing users retain the old lossy conversions, not a new false claim.
    assert groups.process_group_alive(123) is False
    assert groups.signal_group(123, signal.SIGTERM) is False
    assert groups.terminate_remaining_group(123, grace_seconds=0, poll_seconds=0.01) == (
        False,
        False,
    )


def test_plain_failure_never_signals_callers_group(monkeypatch):
    def forbidden(*args):
        raise AssertionError("plain route must never signal a group")

    monkeypatch.setattr(groups.os, "killpg", forbidden)
    with pytest.raises(ValueError):
        run("import time; time.sleep(20)", observer=Observer("start"))


def test_strict_success_has_typed_receipt_and_cached_group():
    outcome = run("print('ordinary bytes')", limits=limits())
    assert outcome.completed.stdout == "ordinary bytes\n"
    assert outcome.timeout is None
    assert outcome.lifecycle.child_reaped
    assert outcome.lifecycle.owned_pgid == outcome.lifecycle.child_pid
    assert not outcome.lifecycle.group_cleanup.required
    assert outcome.lifecycle.group_cleanup.final.status == "absent"


def test_monitor_module_import_has_no_model_or_torch_side_effect():
    """Identity preparation must be able to reuse supervision without models."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import core.runtime_control.observed_subprocess; "
            "assert 'torch' not in sys.modules; "
            "assert 'ml_models.models_sandbox' not in sys.modules; "
            "assert 'core.sandbox_executor' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_supervisor_does_not_turn_unknown_cleanup_into_success(monkeypatch):
    monkeypatch.setattr(
        groups, "observe_group", lambda pgid: groups.GroupObservation(status="unknown")
    )
    monkeypatch.setattr(
        supervisor, "observe_group", lambda pgid: groups.GroupObservation(status="unknown")
    )
    with pytest.raises(ProcessSupervisionError) as caught:
        run("pass", limits=limits())
    assert caught.value.lifecycle.child_reaped
    assert caught.value.lifecycle.group_cleanup.final.status == "unknown"


def test_watchdog_uses_cached_owned_group_not_late_getpgid(monkeypatch):
    def forbidden(pid):
        raise AssertionError("owned group must be cached when child is launched")

    monkeypatch.setattr(os, "getpgid", forbidden)
    result = run(
        "import time; time.sleep(20)",
        deadline_provider=lambda: (0.03, "test"),
        poll_seconds=0.01,
        grace_seconds=0.05,
    )
    assert result.timeout["survivors_detected"] is False
    assert result.lifecycle.child_reaped


def test_nonzero_leader_retains_output_after_descendant_pipe_cleanup():
    """The first communicate may time out despite an already-failed leader."""
    body = (
        "import subprocess,sys; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); "
        "print('LEADER OUT',flush=True); print('LEADER ERR',file=sys.stderr,flush=True); "
        "sys.exit(7)"
    )
    with pytest.raises(subprocess.CalledProcessError) as caught:
        run(body, limits=limits())
    assert caught.value.returncode == 7
    assert caught.value.output == "LEADER OUT\n"
    assert caught.value.stderr == "LEADER ERR\n"
    assert caught.value.process_lifecycle.group_cleanup.required


def test_group_cleanup_exception_still_kills_and_reaps_direct_child(monkeypatch):
    def broken_cleanup(*args, **kwargs):
        raise RuntimeError("group cleanup failed")

    monkeypatch.setattr(supervisor, "terminate_observed_group", broken_cleanup)
    observer = Observer("start")
    with pytest.raises(ValueError, match="primary start failure") as caught:
        run("import time; time.sleep(20)", limits=limits(), observer=observer)
    assert caught.value.process_lifecycle.child_reaped
    with pytest.raises(ProcessLookupError):
        os.kill(observer.pid, 0)
    assert any(
        "group cleanup failed" in message
        for message in caught.value.process_lifecycle.cleanup_errors
    )
    assert observer.stops == 1


@pytest.mark.parametrize("final_status", ["unknown", "present"])
def test_final_group_evidence_must_be_absent_even_if_initially_clean(monkeypatch, final_status):
    monkeypatch.setattr(
        supervisor,
        "terminate_observed_group",
        lambda *args, **kwargs: groups.GroupCleanup(
            required=False, final=groups.GroupObservation(status="absent")
        ),
    )
    monkeypatch.setattr(
        supervisor, "observe_group", lambda pgid: groups.GroupObservation(status=final_status)
    )
    observer = Observer()
    with pytest.raises(ProcessSupervisionError) as caught:
        run("pass", limits=limits(), observer=observer)
    assert observer.last_failed is True
    assert not caught.value.lifecycle.group_cleanup.required
    assert caught.value.lifecycle.group_cleanup.final.status == final_status


def test_term_handler_can_flush_beyond_pipe_capacity_without_escalation(tmp_path):
    """Grace must drain both pipes, not poll a handler blocked on a full pipe."""
    ready = tmp_path / "ready"
    body = (
        "import signal,sys,time\n"
        "def finish(*args):\n"
        "    sys.stdout.write('O' * (1024 * 1024)); sys.stdout.flush()\n"
        "    sys.stderr.write('E' * (1024 * 1024)); sys.stderr.flush()\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, finish)\n"
        f"open({str(ready)!r}, 'w').close()\n"
        "time.sleep(20)\n"
    )
    result = run(
        body,
        deadline_provider=lambda: (0 if ready.exists() else 5, "test"),
        poll_seconds=0.01,
        grace_seconds=2,
    )
    assert result.timeout["escalated_to_kill"] is False
    assert result.timeout["stdout_tail"] == "O" * 2000
    assert result.timeout["stderr_tail"] == "E" * 2000
    assert result.lifecycle.returncode == 0
