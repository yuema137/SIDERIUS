"""Shared process-group termination for Data Analysis subprocess supervisors.

The skill-worker executor and the generated-code sandbox launch their child in
a new session and stop it through this one wrapper, so their poll interval,
SIGTERM grace and SIGKILL escalation cannot drift apart. Group signalling,
observation and reaping are owned by core ``terminate_observed_group``.
"""

from __future__ import annotations

import signal
import subprocess

from core.runtime_control.process_group import signal_group, terminate_observed_group

#: Supervisor observation interval, also the termination poll interval.
SUPERVISION_POLL_S = 0.02
#: Time a group gets after SIGTERM before SIGKILL.
TERMINATION_GRACE_S = 1.0
#: Bound on the final leader wait before a second SIGKILL.
_LEADER_WAIT_S = 1.0


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM the leader's group, SIGKILL after the grace, and reap the leader.

    The core owner reaps the leader while waiting. Without that, a leader that
    exited on SIGTERM stays a zombie, keeps its group observable and turns every
    termination into the full grace period (#1425, #1447).
    """
    terminate_observed_group(
        process.pid,
        grace_seconds=TERMINATION_GRACE_S,
        poll_seconds=SUPERVISION_POLL_S,
        child=process,
        retain_unknown=False,
    )
    try:
        process.wait(timeout=_LEADER_WAIT_S)
    except subprocess.TimeoutExpired:
        signal_group(process.pid, signal.SIGKILL)
        process.wait()
