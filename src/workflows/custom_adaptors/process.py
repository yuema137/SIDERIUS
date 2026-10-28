"""Launch one custom adaptor child under ``supervise_subprocess`` and classify its end.

The child environment is an explicit allowlist (no provider keys, no inherited
transport). ``-P`` keeps the working directory off ``sys.path`` so a module in
the caller's directory cannot shadow framework imports before pin verification;
``-s`` drops the user site directory. The author's ``timeout_seconds`` starts
when the child publishes its ready marker; startup before that marker has its
own bounded allowance. This is not a network or filesystem sandbox.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from core.runtime_control.observed_subprocess import supervise_subprocess
from core.subprocess_env import HASH_SEED_ENV_VAR, subprocess_env
from workflows.custom_adaptors.errors import CustomAdaptorError, CustomAdaptorReason
from workflows.custom_adaptors.invocation import (
    FAILURE_FILE,
    LOG_FILE,
    READY_FILE,
    ChildFailure,
    CustomInvocation,
)

#: Interpreter + framework import before the ready marker (torch import ~2 s).
STARTUP_ALLOWANCE_SECONDS = 120.0
_POLL_SECONDS = 0.05
_GRACE_SECONDS = 1.0
_LOG_TAIL = 2000
_FORWARDED = ("PATH", "VIRTUAL_ENV", "LANG", "LANGUAGE")
_PRE_READY: dict[str, CustomAdaptorReason] = {
    "identity": "custom_identity_mismatch",
    "input": "custom_invalid_input",
    "parameters": "custom_invalid_input",
}


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
    env[HASH_SEED_ENV_VAR] = subprocess_env()[HASH_SEED_ENV_VAR]
    env["HOME"] = str(home)
    env["TMPDIR"] = str(temporary)
    env["PYTHONNOUSERSITE"] = "1"
    return env


class ReadyDeadline:
    """Deadline provider: startup allowance, then ``timeout`` after the ready marker."""

    def __init__(self, ready: Path, timeout: float):
        self.ready = ready
        self.timeout = timeout
        self.started = time.perf_counter()
        self.ready_at: float | None = None

    def __call__(self) -> tuple[float | None, str]:
        if self.ready_at is None and self.ready.exists():
            self.ready_at = time.perf_counter() - self.started
        if self.ready_at is None:
            return STARTUP_ALLOWANCE_SECONDS, "adaptor-startup"
        return self.ready_at + self.timeout, "adaptor-manifest"


def _log_tail(invocation: CustomInvocation) -> str:
    try:
        return invocation.file(LOG_FILE).read_bytes()[-_LOG_TAIL:].decode(errors="replace")
    except OSError:
        return ""


def _failure_reason(invocation: CustomInvocation, returncode: int) -> CustomAdaptorError:
    """Pre-ready typed failures are trusted; after ready, adaptor code could forge them."""
    reason: CustomAdaptorReason = "custom_exception"
    detail = f"exit {returncode}: {_log_tail(invocation)}"
    try:
        failure = ChildFailure.model_validate_json(invocation.file(FAILURE_FILE).read_bytes())
    except (OSError, ValidationError):
        return CustomAdaptorError(reason, detail)
    if not invocation.file(READY_FILE).exists():
        reason = _PRE_READY.get(failure.stage, "custom_exception")
    if failure.stage == "output":
        reason = "custom_invalid_output"
    return CustomAdaptorError(reason, f"{failure.stage}: {failure.detail[-_LOG_TAIL:]}")


def launch(invocation: CustomInvocation, request: Path, timeout: float) -> None:
    """Run the child to completion; raise a typed ``CustomAdaptorError`` on any failure."""
    control = Path(invocation.control_dir)
    deadline = ReadyDeadline(invocation.file(READY_FILE), timeout)
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
        raise _failure_reason(invocation, exc.returncode) from exc
    if observed.timeout is not None or observed.completed is None:
        phase = "after ready" if deadline.ready_at is not None else "during startup"
        raise CustomAdaptorError(
            "custom_timeout", f"deadline exceeded {phase} ({observed.timeout})"
        )
