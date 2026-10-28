"""Supervised generated-pytest child (issue #984): one witness per outcome class.

Real tiny pytest children (no Torch, no LLM): the defect class is process
supervision itself, which a mocked launcher cannot exhibit.
"""

from __future__ import annotations

import os
import time

import pytest

from agent.skills.generated_pytest import LEFTOVER_WARNING, PytestLimit, run_generated_pytest
from core.runtime_control.observed_subprocess import (
    ProcessLifecycle,
    ProcessSupervisionError,
    observe_process_lifecycle,
)


def _pid_gone_or_zombie(pid: int, *, within: float = 5.0) -> bool:
    until = time.monotonic() + within
    while time.monotonic() < until:
        stat = f"/proc/{pid}/stat"
        if not os.path.exists(stat):
            return True
        with open(stat) as handle:
            if handle.read().rsplit(")", 1)[1].split()[0] == "Z":
                return True
        time.sleep(0.05)
    return False


#: Written after pytest restores its fd capture, so it reaches the child's real stderr.
STDERR_MARKER = "stderr-witness-984"
_STDERR_AT_EXIT = (
    f"import atexit, sys\natexit.register(lambda: sys.stderr.write({STDERR_MARKER!r} + '\\n'))\n"
)


def _spawn_sleeper(pid_file, *, inherit_pipes: bool) -> str:
    redirect = "" if inherit_pipes else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
    return (
        "import subprocess, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']"
        f"{redirect})\n"
        f"open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
    )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("caller_declared", "pytest exceeded 8 seconds"),
        ("worker_budget", "pytest exceeded the remaining worker budget (8 s)"),
    ],
)
def test_declared_timeout_kills_the_hanging_group_and_fails_the_check(tmp_path, source, message):
    """Fails if the deadline is ignored (hang), the descendant survives, or the limit is unnamed."""
    pid_file = tmp_path / "sleeper.pid"
    test_file = tmp_path / "test_hang.py"
    test_file.write_text(
        _spawn_sleeper(pid_file, inherit_pipes=True)
        + "import time\ndef test_hangs():\n    time.sleep(120)\n"
    )
    started = time.monotonic()
    passed, output = run_generated_pytest(
        str(test_file), dict(os.environ), limit=PytestLimit(seconds=8.0, source=source)
    )
    assert time.monotonic() - started < 30
    assert passed is False
    assert output.startswith(message + "\n")
    assert _pid_gone_or_zombie(int(pid_file.read_text()))


def test_nonzero_exit_fails_the_check_with_pytest_output(tmp_path):
    """Fails if a non-zero pytest exit escapes as CalledProcessError or loses output."""
    test_file = tmp_path / "test_fail.py"
    test_file.write_text(_STDERR_AT_EXIT + "def test_broken():\n    assert 1 == 2\n")
    passed, output = run_generated_pytest(
        str(test_file), dict(os.environ), limit=PytestLimit(seconds=60.0)
    )
    assert passed is False
    assert "1 failed" in output and "assert 1 == 2" in output
    assert STDERR_MARKER in output


def test_undeclared_limit_runs_unbounded_but_in_an_owned_group(tmp_path):
    """Fails if an undeclared limit is replaced by a guessed cap or loses group ownership."""
    test_file = tmp_path / "test_ok.py"
    test_file.write_text(_STDERR_AT_EXIT + "import time\ndef test_ok():\n    time.sleep(1.5)\n")
    seen: list[ProcessLifecycle] = []
    with observe_process_lifecycle(seen.append):
        passed, output = run_generated_pytest(str(test_file), dict(os.environ))
    assert passed is True and "1 passed" in output
    assert STDERR_MARKER in output
    (lifecycle,) = seen
    assert lifecycle.owned_pgid == lifecycle.child_pid
    assert lifecycle.stop_reason is None


def test_terminated_leftovers_keep_a_pass_with_output_and_warning(tmp_path):
    """Fails if leftovers flip a pass, drop the pytest output, or are not terminated."""
    pid_file = tmp_path / "daemon.pid"
    test_file = tmp_path / "test_leftover.py"
    test_file.write_text(
        _spawn_sleeper(pid_file, inherit_pipes=False) + "def test_ok():\n    pass\n"
    )
    try:
        passed, output = run_generated_pytest(
            str(test_file), dict(os.environ), limit=PytestLimit(seconds=60.0)
        )
    except ProcessSupervisionError as error:
        # A terminated grandchild left as a zombie is not certified absent;
        # that uncertainty must propagate rather than be called a pass.
        assert error.lifecycle.group_cleanup is not None
        assert error.lifecycle.group_cleanup.final.status != "absent"
        pytest.skip("host reaper left the terminated grandchild as a zombie")
    assert passed is True
    assert "1 passed" in output
    assert output.rstrip().endswith(LEFTOVER_WARNING)
    assert _pid_gone_or_zombie(int(pid_file.read_text()))
