"""Supervised pytest child for generated candidate tests (issue #984).

One owner for both validator pytest launches: the plain validator check and
the task-owned model-probe check. The child runs in its own process group under
``core.runtime_control.observed_subprocess.supervise_subprocess``, so a
deadline, an interrupt of the parent or leftover descendants all end with the
group terminated (TERM, grace, KILL) instead of holding the validation slot.

The deadline is a caller declaration only (``PytestLimit``). ``limit=None`` means the
caller declared no limit: the child is still group-supervised, but no deadline
is applied and no host cap is guessed here.

Verdict mapping (status vocabulary unchanged: ``(tests_passed, output)``):

* exit 0 -> ``(True, stdout + stderr)``;
* non-zero exit -> ``(False, stdout + stderr)``;
* declared deadline exceeded -> ``(False, "pytest exceeded N seconds" + tails)``,
  matching the isolated probe's ``"Validation probe exceeded N seconds"``
  (``"pytest exceeded the remaining worker budget (N s)"`` for a worker budget);
* exit 0 whose leftover descendants were terminated and are verified absent
  -> ``(True, stdout + stderr + one warning line)``. Every other supervision
  failure propagates as ``ProcessSupervisionError``.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class PytestLimit(BaseModel):
    """A caller-declared pytest deadline and where it came from.

    ``caller_declared`` is an explicit limit; ``worker_budget`` is what remains
    of the candidate worker's ``CandidateRunRequest.timeout_seconds``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    seconds: float = Field(gt=0, allow_inf_nan=False)
    source: Literal["caller_declared", "worker_budget"] = "caller_declared"

    def exceeded_message(self) -> str:
        if self.source == "worker_budget":
            return f"pytest exceeded the remaining worker budget ({self.seconds:g} s)"
        return f"pytest exceeded {self.seconds:g} seconds"


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
    limit: PytestLimit | None = None,
) -> tuple[bool, str]:
    """Run ``pytest -v --tb=short`` on one file as a supervised process group."""

    def deadline() -> tuple[float | None, str]:
        if limit is None:
            return None, "undeclared"
        return limit.seconds, limit.source

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
        assert limit is not None
        stdout_tail = str(result.timeout.get("stdout_tail", ""))
        stderr_tail = str(result.timeout.get("stderr_tail", ""))
        return False, f"{limit.exceeded_message()}\n{stdout_tail}\n{stderr_tail}"
    completed = result.completed
    assert completed is not None
    return True, (completed.stdout or "") + (completed.stderr or "")
