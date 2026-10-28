"""Supervised pytest child for generated candidate tests (issue #984).

One owner for both validator pytest launches: the plain validator check and
the task-owned model-probe check. The child runs in its own process group under
``core.runtime_control.observed_subprocess.supervise_subprocess``, so a
deadline, an interrupt of the parent or leftover descendants all end with the
group terminated (TERM, grace, KILL) instead of holding the validation slot.

The deadline is a caller declaration only. ``timeout_seconds=None`` means the
caller declared no limit: the child is still group-supervised, but no deadline
is applied and no host cap is guessed here.

Verdict mapping (status vocabulary unchanged: ``(tests_passed, output)``):

* exit 0 -> ``(True, stdout + stderr)``;
* non-zero exit -> ``(False, stdout + stderr)``;
* declared deadline exceeded -> ``(False, "pytest exceeded N seconds" + tails)``,
  matching the isolated probe's ``"Validation probe exceeded N seconds"``;
* exit 0 whose leftover descendants were terminated and are verified absent
  -> ``(True, stdout + stderr + one warning line)``. Every other supervision
  failure propagates as ``ProcessSupervisionError``.
"""

from __future__ import annotations

import math
import subprocess
import sys

from core.runtime_control.observed_subprocess import (
    ProcessSupervisionError,
    supervise_subprocess,
)
from core.runtime_control.session import WatchdogConfig

#: TERM->KILL grace and deadline-check cadence: the runtime watchdog defaults,
#: read from their owner rather than restated.
_GRACE_SECONDS: float = WatchdogConfig.model_fields["grace_seconds"].default
_POLL_SECONDS: float = WatchdogConfig.model_fields["poll_seconds"].default

LEFTOVER_WARNING = (
    "WARNING: pytest exited 0 but left descendant processes; their process group was terminated."
)


def _require_declared_limit(timeout_seconds: float | None) -> None:
    if timeout_seconds is None:
        return
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int | float)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError(
            f"pytest timeout_seconds must be a positive finite number, got {timeout_seconds!r}"
        )


def _terminated_leftovers_after_pass(error: ProcessSupervisionError) -> bool:
    """Exit 0, no stop reason, group cleaned and verified absent, no cleanup errors."""
    lifecycle = error.lifecycle
    cleanup = lifecycle.group_cleanup
    return (
        lifecycle.returncode == 0
        and lifecycle.stop_reason is None
        and not lifecycle.cleanup_errors
        and cleanup is not None
        and cleanup.final.status == "absent"
    )


def run_generated_pytest(
    test_file_path: str,
    env: dict[str, str],
    *,
    timeout_seconds: float | None = None,
) -> tuple[bool, str]:
    """Run ``pytest -v --tb=short`` on one file as a supervised process group."""
    _require_declared_limit(timeout_seconds)

    def deadline() -> tuple[float | None, str]:
        if timeout_seconds is None:
            return None, "undeclared"
        return timeout_seconds, "caller_declared"

    try:
        result = supervise_subprocess(
            [sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"],
            env=env,
            preexec_fn=None,
            capture_stdout=True,
            deadline_provider=deadline,
            grace_seconds=_GRACE_SECONDS,
            poll_seconds=_POLL_SECONDS,
            label="validator-pytest",
        )
    except subprocess.CalledProcessError as failed:
        return False, (failed.output or "") + (failed.stderr or "")
    except ProcessSupervisionError as error:
        if not _terminated_leftovers_after_pass(error):
            raise
        return True, (error.stdout or "") + (error.stderr or "") + "\n" + LEFTOVER_WARNING
    if result.timeout is not None:
        tails = str(result.timeout.get("stdout_tail", "")) + str(
            result.timeout.get("stderr_tail", "")
        )
        return False, f"pytest exceeded {timeout_seconds:g} seconds\n{tails}"
    completed = result.completed
    assert completed is not None
    return True, (completed.stdout or "") + (completed.stderr or "")
