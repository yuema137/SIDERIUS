"""Bounded caller execution using the shared process-group cleanup owner."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict

from core.runtime_control.process_group import (
    GroupCleanup,
    terminate_observed_group,
    terminate_remaining_group,
)
from tools.workspace_sandbox.command import build_command
from tools.workspace_sandbox.profile import SandboxProfile


class ExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    # ``cancelled`` only when the caller supplied a cancel probe that fired.
    status: Literal["completed", "failed", "timed_out", "cancelled"]
    returncode: int
    elapsed_seconds: float


#: Called with the sandbox (bwrap) PID right after ``Popen``, while it is unreaped.
SpawnObserver = Callable[[int], None]
#: Polled while the sandbox runs; ``True`` ends it through the same group cleanup.
CancelProbe = Callable[[], bool]
#: How often a supplied cancel probe is polled.
CANCEL_POLL_SECONDS = 0.5
WaitOutcome = Literal["exited", "timed_out", "cancelled"]


class SupervisionOptions(TypedDict, total=False):
    """Optional keyword arguments shared by ``run`` and ``run_observed``."""

    on_spawn: SpawnObserver
    cancel_requested: CancelProbe


def run(
    profile: SandboxProfile,
    argv: Sequence[str],
    *,
    on_spawn: SpawnObserver | None = None,
    cancel_requested: CancelProbe | None = None,
) -> ExecutionResult:
    """Stream child output unchanged; never serialize credentials or child argv."""
    command, env = build_command(profile, argv)
    started = time.monotonic()
    process = subprocess.Popen(command, env=env, close_fds=True, start_new_session=True)
    outcome: WaitOutcome = "exited"
    try:
        _observe_spawn(process, on_spawn)
        outcome = _await(process, profile.timeout_seconds, cancel_requested)
    finally:
        terminate_remaining_group(process.pid, grace_seconds=1.0, poll_seconds=0.05)
        process.wait(timeout=5.0)
    return _result(outcome, process.returncode, started)


class ObservedExecutionResult(BaseModel):
    """Honest supervision evidence for callers requiring proven group cleanup."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    execution: ExecutionResult
    cleanup: GroupCleanup
    direct_child_reaped: bool


class ObservedSpawnFailure(RuntimeError):
    """Command construction or Popen failed before a child was created."""


def run_observed(
    profile: SandboxProfile,
    argv: Sequence[str],
    *,
    on_spawn: SpawnObserver | None = None,
    cancel_requested: CancelProbe | None = None,
) -> ObservedExecutionResult:
    """Run one group; retain uncertainty and never change legacy run semantics.

    Exceptions after spawn propagate only after attempting observed cleanup. The
    caller must treat them as unresolved supervision, never pre-dispatch refusal.
    """
    started = time.monotonic()
    try:
        command, env = build_command(profile, argv)
        process = subprocess.Popen(command, env=env, close_fds=True, start_new_session=True)
    except (OSError, ValueError, RuntimeError) as error:
        raise ObservedSpawnFailure("sandbox child was not created") from error
    outcome: WaitOutcome = "exited"
    try:
        _observe_spawn(process, on_spawn)
        outcome = _await(process, profile.timeout_seconds, cancel_requested)
    finally:
        cleanup = terminate_observed_group(
            process.pid,
            child=process,
            retain_unknown=True,
            grace_seconds=1.0,
            poll_seconds=0.05,
        )
        process.wait(timeout=5.0)
    return ObservedExecutionResult(
        execution=_result(outcome, process.returncode, started),
        cleanup=cleanup,
        direct_child_reaped=process.returncode is not None,
    )


def _observe_spawn(process: subprocess.Popen, on_spawn: SpawnObserver | None) -> None:
    """Report the live sandbox before waiting; the caller's finally still reaps it."""
    if on_spawn is not None:
        on_spawn(process.pid)


def _await(
    process: subprocess.Popen, timeout: float, cancel_requested: CancelProbe | None
) -> WaitOutcome:
    """Wait for exit, the wall-clock cap or a cancel request, whichever comes first.

    Without a probe this is the single historical ``wait(timeout)``. A probe is
    polled first (an intent recorded before spawn takes effect at once) and then
    every ``CANCEL_POLL_SECONDS``. A fired probe yields ``cancelled`` only while the
    child is still running; a child that already exited reports its own outcome.
    The caller's ``finally`` owns termination.
    """
    if cancel_requested is None:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return "timed_out"
        return "exited"
    deadline = time.monotonic() + timeout
    while True:
        if cancel_requested():
            # A child that already exited on its own keeps its natural outcome.
            return "exited" if process.poll() is not None else "cancelled"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timed_out"
        try:
            process.wait(timeout=min(CANCEL_POLL_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            continue
        return "exited"


def _result(outcome: WaitOutcome, returncode: int, started: float) -> ExecutionResult:
    elapsed = time.monotonic() - started
    if outcome == "timed_out":
        return ExecutionResult(status="timed_out", returncode=124, elapsed_seconds=elapsed)
    if outcome == "cancelled":
        return ExecutionResult(status="cancelled", returncode=returncode, elapsed_seconds=elapsed)
    status = "completed" if returncode == 0 else "failed"
    return ExecutionResult(status=status, returncode=returncode, elapsed_seconds=elapsed)
