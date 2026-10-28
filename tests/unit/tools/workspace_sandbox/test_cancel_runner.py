"""A cancel probe ends a real process group through the shared cleanup owner.

The sandbox command is replaced by a plain shell group (no bwrap needed); the
runner's own ``Popen(start_new_session=True)``, wait loop and group cleanup run.
"""

import time
from types import SimpleNamespace

import pytest

from core.runtime_control.process_group import observe_group
from tools.workspace_sandbox import runner

LONG_GROUP = ["/bin/sh", "-c", "sleep 600 & sleep 600 & wait"]


@pytest.fixture
def shell_group(monkeypatch):
    monkeypatch.setattr(runner, "build_command", lambda profile, argv: (list(argv), {}))
    monkeypatch.setattr(runner, "CANCEL_POLL_SECONDS", 0.05)


def _execute(kind, argv, timeout, probe):
    spawned = []
    execute = runner.run if kind == "run" else runner.run_observed
    result = execute(
        SimpleNamespace(timeout_seconds=timeout),
        argv,
        on_spawn=spawned.append,
        cancel_requested=probe,
    )
    return (result if kind == "run" else result.execution), spawned[0], result


@pytest.mark.parametrize("kind", ["run", "run_observed"])
def test_cancel_terminates_the_whole_group_and_reports_cancelled(shell_group, kind):
    """Fails if a fired probe is ignored (run lasts until timeout), reported as failed or
    timed_out, or if only the leader dies and the grandchild sleeps survive."""
    polls = []

    def probe():
        polls.append(time.monotonic())
        return len(polls) >= 3  # cancel while the group is demonstrably running

    started = time.monotonic()
    execution, pgid, result = _execute(kind, LONG_GROUP, 120, probe)
    assert execution.status == "cancelled"
    assert time.monotonic() - started < 30
    assert observe_group(pgid).status == "absent"
    if kind == "run_observed":
        assert result.cleanup.term is not None and result.cleanup.term.status == "delivered"
        assert result.cleanup.final.status == "absent" and result.direct_child_reaped


@pytest.mark.parametrize(
    ("argv", "timeout", "expected"),
    [
        (["/bin/sh", "-c", "exit 0"], 120, ("completed", 0)),
        (["/bin/sh", "-c", "exit 3"], 120, ("failed", 3)),
        (LONG_GROUP, 0.3, ("timed_out", 124)),
    ],
)
def test_unfired_probe_keeps_exit_and_timeout_semantics(shell_group, argv, timeout, expected):
    """Fails if the polling wait loses the wall-clock cap or misreports a normal exit."""
    execution, pgid, _ = _execute("run_observed", argv, timeout, lambda: False)
    assert (execution.status, execution.returncode) == expected
    assert observe_group(pgid).status == "absent"


@pytest.mark.parametrize(("code", "expected"), [(0, "completed"), (3, "failed")])
def test_probe_firing_after_natural_exit_keeps_the_natural_outcome(shell_group, code, expected):
    """Fails if a cancel that lands after the child already exited relabels a finished run
    as ``cancelled`` (with its own return code), hiding its real result."""

    def late_probe():
        time.sleep(0.5)  # the child exits during this first poll
        return True

    execution, _, _ = _execute("run_observed", ["/bin/sh", "-c", f"exit {code}"], 120, late_probe)
    assert (execution.status, execution.returncode) == (expected, code)
