"""Bounded caller execution using the shared process-group cleanup owner."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from typing import Literal

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
    status: Literal["completed", "failed", "timed_out"]
    returncode: int
    elapsed_seconds: float


def run(profile: SandboxProfile, argv: Sequence[str]) -> ExecutionResult:
    """Stream child output unchanged; never serialize credentials or child argv."""
    command, env = build_command(profile, argv)
    started = time.monotonic()
    process = subprocess.Popen(command, env=env, close_fds=True, start_new_session=True)
    timed_out = False
    try:
        try:
            process.wait(timeout=profile.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
    finally:
        terminate_remaining_group(process.pid, grace_seconds=1.0, poll_seconds=0.05)
        process.wait(timeout=5.0)
    return ExecutionResult(
        status="timed_out" if timed_out else "completed" if process.returncode == 0 else "failed",
        returncode=124 if timed_out else process.returncode,
        elapsed_seconds=time.monotonic() - started,
    )


class ObservedExecutionResult(BaseModel):
    """Honest supervision evidence for callers requiring proven group cleanup."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    execution: ExecutionResult
    cleanup: GroupCleanup
    direct_child_reaped: bool


class ObservedSpawnFailure(RuntimeError):
    """Command construction or Popen failed before a child was created."""


def run_observed(profile: SandboxProfile, argv: Sequence[str]) -> ObservedExecutionResult:
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
    timed_out = False
    try:
        try:
            process.wait(timeout=profile.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
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
        execution=ExecutionResult(
            status="timed_out"
            if timed_out
            else "completed"
            if process.returncode == 0
            else "failed",
            returncode=124 if timed_out else process.returncode,
            elapsed_seconds=time.monotonic() - started,
        ),
        cleanup=cleanup,
        direct_child_reaped=process.returncode is not None,
    )
