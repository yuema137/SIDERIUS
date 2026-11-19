"""Wall-clock bounds for real child processes started by unit tests (#1578).

A unit test that starts a real Python child (the framework, torch, a worker
module) and expects it to finish on its own must not let host speed decide the
verdict. Under CI load (load average 40-80 on 24 cores) interpreter start and
imports took several times longer than on an idle host, and fixed 5-90 s bounds
expired on healthy runs.

``CHILD_PROCESS_BOUND_SECONDS`` is the one bound for such children and for the
waits that observe them (``subprocess.run(timeout=...)``, ``communicate``,
``wait``, readiness polls, joins of threads that drive a child). A passing run
never waits for it; only a hung child reaches it, so it still turns a hang into
a failure. Tests whose purpose is a deadline (it must fire, or fire in a given
phase) do not use it: they scale their deadline from a measured baseline (for
precision witnesses, :func:`host_time_unit`) or gate the phase on an event.
"""

import subprocess
import sys
import time
from typing import Final

CHILD_PROCESS_BOUND_SECONDS: Final[float] = 300.0


def host_time_unit(*, floor_seconds: float = 0.5, factor: float = 4.0) -> float:
    """The time unit of a deadline-precision witness on this host, now.

    Such a test writes its stalls, allocations, grace periods and overrun bounds
    as multiples of one unit, so a defect overruns its bound by the same factor
    at any host speed. The unit is ``floor_seconds`` (the test's historical
    idle-host scale) or ``factor`` times the slowest of three trivial interpreter
    starts timed now, whichever is larger, so scheduling delay on a loaded host scales
    with the bounds instead of eating their margin.
    """
    slowest = 0.0
    for _ in range(3):  # the slowest of three, so one lucky start cannot shrink the unit
        started = time.monotonic()
        subprocess.run(
            [sys.executable, "-c", "pass"], check=True, timeout=CHILD_PROCESS_BOUND_SECONDS
        )
        slowest = max(slowest, time.monotonic() - started)
    return max(floor_seconds, factor * slowest)
