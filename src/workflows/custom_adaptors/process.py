"""Launch one custom adaptor child under ``supervise_subprocess`` and classify its end.

The child environment is an explicit allowlist (no provider keys, no inherited
transport). ``-P`` keeps the working directory off ``sys.path`` so a module in
the caller's directory cannot shadow framework imports before pin verification;
``-s`` drops the user site directory. The author's ``timeout_seconds`` starts
when the child creates its ``entered`` marker, immediately before the first
member import; interpreter and framework startup before it has its own bounded
allowance. This is not a network or filesystem sandbox.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from core.runtime_control.observed_subprocess import supervise_subprocess
from core.subprocess_env import CHILD_HASH_SEED, HASH_SEED_ENV_VAR
from workflows.custom_adaptors.errors import CustomAdaptorError, CustomAdaptorReason
from workflows.custom_adaptors.invocation import (
    ENTERED_FILE,
    FAILURE_FILE,
    LOG_FILE,
    ChildFailure,
    CustomInvocation,
)

#: Interpreter + framework import before ``entered`` (torch import ~2 s).
STARTUP_ALLOWANCE_SECONDS = 120.0
_POLL_SECONDS = 0.05
_GRACE_SECONDS = 1.0
_LOG_TAIL = 2000
_FORWARDED = ("PATH", "VIRTUAL_ENV", "LANG", "LANGUAGE", "LD_LIBRARY_PATH")


def child_env(control_dir: Path) -> dict[str, str]:
    """Allowlisted environment; HOME and TMPDIR are private to the invocation."""
    home = control_dir / "home"
    temporary = control_dir / "tmp"
    home.mkdir(exist_ok=True)
    temporary.mkdir(exist_ok=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if key in _FORWARDED or key.startswith("LC_")
    }
    env[HASH_SEED_ENV_VAR] = os.environ.get(HASH_SEED_ENV_VAR, CHILD_HASH_SEED)
    env["HOME"] = str(home)
    env["TMPDIR"] = str(temporary)
    env["PYTHONNOUSERSITE"] = "1"
    return env


class EnteredDeadline:
    """Deadline provider: startup allowance, then ``timeout`` once ``entered`` is seen."""

    def __init__(self, entered: Path, timeout: float):
        self.entered = entered
        self.timeout = timeout
        self.started = time.perf_counter()
        self.entered_at: float | None = None

    def __call__(self) -> tuple[float | None, str]:
        if self.entered_at is None and self.entered.exists():
            self.entered_at = time.perf_counter() - self.started
        if self.entered_at is None:
            return STARTUP_ALLOWANCE_SECONDS, "adaptor-startup"
        return self.entered_at + self.timeout, "adaptor-manifest"


def _log_tail(invocation: CustomInvocation) -> str:
    try:
        return invocation.file(LOG_FILE).read_bytes()[-_LOG_TAIL:].decode(errors="replace")
    except OSError:
        return ""


def _failure_reason(
    invocation: CustomInvocation,
    returncode: int,
    entered_seen: bool,
    pins_changed: Callable[[], bool],
) -> CustomAdaptorError:
    """Classify from parent observations; the child's failure file is only a hint.

    Identity mismatch requires: an ``identity`` hint, ``entered`` never observed
    (during polling or now), and an independent re-capture that differs from
    the loaded pins. Everything else that exits non-zero is ``custom_exception``,
    except an ``output`` hint (``custom_invalid_output``; both are failures).
    """
    detail = f"exit {returncode}: {_log_tail(invocation)}"
    try:
        failure = ChildFailure.model_validate_json(invocation.file(FAILURE_FILE).read_bytes())
    except (OSError, ValidationError):
        return CustomAdaptorError("custom_exception", detail)
    detail = f"{failure.stage}: {failure.detail[-_LOG_TAIL:]}"
    reason: CustomAdaptorReason = "custom_exception"
    if failure.stage == "output":
        reason = "custom_invalid_output"
    elif failure.stage == "identity" and not entered_seen and pins_changed():
        reason = "custom_identity_mismatch"
    return CustomAdaptorError(reason, detail)


def launch(
    invocation: CustomInvocation,
    request: Path,
    timeout: float,
    pins_changed: Callable[[], bool],
) -> None:
    """Run the child to completion; raise a typed ``CustomAdaptorError`` on any failure.

    ``pins_changed`` re-captures the declared members and compares them with the
    loaded identity; it is called only to confirm a claimed identity mismatch.
    """
    control = Path(invocation.control_dir)
    entered = invocation.file(ENTERED_FILE)
    deadline = EnteredDeadline(entered, timeout)
    try:
        # The supervisor prints its watchdog notice on stdout; keep CLI stdout JSON-only.
        with contextlib.redirect_stdout(sys.stderr):
            observed = supervise_subprocess(
                [sys.executable, "-P", "-s", "-m", "workflows.custom_adaptors.child", str(request)],
                env=child_env(control),
                preexec_fn=None,
                capture_stdout=True,
                deadline_provider=deadline,
                grace_seconds=_GRACE_SECONDS,
                poll_seconds=_POLL_SECONDS,
                label=f"adaptor:{invocation.adaptor_id}",
            )
    except subprocess.CalledProcessError as exc:  # The supervisor raises on non-zero exit.
        entered_seen = deadline.entered_at is not None or entered.exists()
        raise _failure_reason(invocation, exc.returncode, entered_seen, pins_changed) from exc
    if observed.timeout is not None or observed.completed is None:
        phase = "after entry" if deadline.entered_at is not None else "during startup"
        raise CustomAdaptorError(
            "custom_timeout", f"deadline exceeded {phase} ({observed.timeout})"
        )
