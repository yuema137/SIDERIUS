"""Own child lifecycle without importing model, task or executor implementations.

Plain calls retain their caller's session (terminal stop signals still reach the
child). Timed and explicitly bounded calls create their own group. Group cleanup
contains that group, not descendants deliberately escaping to a different session.
Observer callbacks and package preparation remain synchronous parent operations;
this supervisor cannot interrupt blocked parent code or cap arbitrary pipe output.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from typing import Any, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from core.runtime_control.process_group import (
    GroupCleanup,
    GroupObservation,
    RssObservation,
    observe_group,
    observe_tree_rss,
    terminate_observed_group,
)


class _SessionOptions(TypedDict, total=False):
    start_new_session: bool


class ProcessObserver(Protocol):
    def capture_baseline(self) -> None: ...
    def start(self, child_pid: int) -> None: ...
    def stop(self, *, child_pid: int, failed: bool) -> None: ...


class ProcessLimits(BaseModel):
    """Explicit bounded-work policy; selecting it requires a new owned session.

    Work and cleanup limits are separate. No scientific phase budget or GPU
    policy is inferred here. RSS enforcement samples Linux process-group memory.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    deadline_seconds: float = Field(gt=0, allow_inf_nan=False, strict=True)
    rss_limit_bytes: StrictInt = Field(gt=0)
    poll_seconds: float = Field(gt=0, allow_inf_nan=False, strict=True)
    grace_seconds: float = Field(ge=0, allow_inf_nan=False, strict=True)
    reap_seconds: float = Field(gt=0, allow_inf_nan=False, strict=True)


class ProcessLifecycle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    child_pid: int | None = None
    owned_pgid: int | None = None
    elapsed_seconds: float
    stop_reason: str | None = None
    peak_sampled_rss_bytes: int = 0
    last_rss_observation: RssObservation | None = None
    child_reaped: bool = False
    returncode: int | None = None
    group_cleanup: GroupCleanup | None = None
    cleanup_errors: tuple[str, ...] = ()


class ProcessSupervisionError(RuntimeError):
    """Infrastructure failure, never a model-size or CUDA-capacity judgment."""

    def __init__(self, message: str, lifecycle: ProcessLifecycle):
        super().__init__(message)
        self.lifecycle = lifecycle


class ObservedProcessResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)
    completed: subprocess.CompletedProcess | None
    timeout: dict[str, Any] | None = None
    lifecycle: ProcessLifecycle


def remaining_process_limits(limits: ProcessLimits, elapsed: float) -> ProcessLimits:
    """Deduct one caller-owned preparation interval without replenishing work."""
    remaining = limits.deadline_seconds - elapsed
    if remaining <= 0:
        raise ProcessSupervisionError(
            "Process preparation exhausted the work deadline before launch",
            ProcessLifecycle(elapsed_seconds=elapsed, stop_reason="work_deadline_exceeded"),
        )
    return limits.model_copy(update={"deadline_seconds": remaining})


def _finalize(
    proc: subprocess.Popen,
    *,
    owned_pgid: int | None,
    terminate: bool,
    observer: ProcessObserver | None,
    failed: bool,
    grace_seconds: float,
    poll_seconds: float,
    reap_seconds: float,
) -> tuple[GroupCleanup | None, tuple[str, ...]]:
    """Independent cleanup attempts; one failing action cannot skip the rest."""
    errors: list[str] = []
    group: GroupCleanup | None = None
    try:
        if owned_pgid is not None:
            group = terminate_observed_group(
                owned_pgid,
                grace_seconds=grace_seconds,
                poll_seconds=poll_seconds,
                child=proc,
            )
        elif terminate and proc.poll() is None:
            # Plain children share our group. Never send a group signal here.
            proc.kill()
    except BaseException as exc:
        errors.append(f"terminate: {type(exc).__name__}: {exc}")
    # Group termination can itself fail (including an interrupted callback).
    # Independently attempt the direct child before reaping; never signal the
    # plain caller's group. Remaining descendants keep separate final evidence.
    try:
        if proc.poll() is None:
            proc.kill()
    except BaseException as exc:
        errors.append(f"direct child kill: {type(exc).__name__}: {exc}")
    try:
        proc.wait(timeout=reap_seconds)
    except BaseException as exc:
        errors.append(f"reap: {type(exc).__name__}: {exc}")
    if owned_pgid is not None:
        try:
            until = time.monotonic() + reap_seconds
            final = observe_group(owned_pgid)
            while final.status == "present" and time.monotonic() < until:
                time.sleep(min(poll_seconds, max(0.0, until - time.monotonic())))
                final = observe_group(owned_pgid)
            if group is None:
                group = GroupCleanup(required=True, final=final)
            else:
                group = group.model_copy(update={"final": final})
        except BaseException as exc:
            errors.append(f"group check: {type(exc).__name__}: {exc}")
            group = GroupCleanup(
                required=True, final=GroupObservation(status="unknown", error=str(exc))
            )
    if observer is not None:
        try:
            observer.stop(
                child_pid=proc.pid,
                failed=(
                    failed
                    or bool(errors)
                    or proc.returncode is None
                    or (group is not None and (group.required or group.final.status != "absent"))
                ),
            )
        except BaseException as exc:
            errors.append(f"observer.stop: {type(exc).__name__}: {exc}")
    return group, tuple(errors)


def supervise_process(
    cmd: list[str],
    *,
    env: dict,
    preexec_fn: Callable[[], None] | None,
    capture_stdout: bool,
    deadline_provider: Callable[[], tuple[float | None, str]] | None = None,
    grace_seconds: float = 0.0,
    poll_seconds: float = 0.0,
    label: str = "",
    observer: ProcessObserver | None = None,
    limits: ProcessLimits | None = None,
) -> ObservedProcessResult:
    """Run one child, preserving primary exceptions with lifecycle evidence.

    New strict work refuses missing RSS evidence before spawn and during polling.
    A zero-exit leader that needed descendant termination is not clean success.
    Legacy deadline stops retain their existing timeout dictionary projection.
    """
    strict_started = time.perf_counter() if limits is not None else None
    if limits is not None:
        assert strict_started is not None
        baseline = observe_tree_rss(os.getpgrp())
        if baseline.status != "complete":
            raise ProcessSupervisionError(
                "Process RSS monitoring unavailable before launch",
                ProcessLifecycle(
                    elapsed_seconds=time.perf_counter() - strict_started,
                    stop_reason="monitoring_unavailable",
                    last_rss_observation=baseline,
                ),
            )
        poll_seconds = limits.poll_seconds
        grace_seconds = limits.grace_seconds
    # Existing watchdog cleanup waits at most two seconds for the reap window.
    reap_seconds = limits.reap_seconds if limits is not None else 2.0
    cleanup_poll = poll_seconds if poll_seconds > 0 else 0.05
    if observer is not None:
        observer.capture_baseline()
    started = strict_started if strict_started is not None else time.perf_counter()
    if limits is not None:
        # RSS and baseline preparation can block the parent. Once they return,
        # expired work must refuse here rather than give a fresh child allowance.
        remaining_process_limits(limits, time.perf_counter() - started)
    owned = deadline_provider is not None or limits is not None
    session_kwargs: _SessionOptions = {"start_new_session": True} if owned else {}
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE if capture_stdout else None,
        stderr=subprocess.PIPE,
        text=True,
        cwd=os.getcwd(),
        env=env,
        preexec_fn=preexec_fn,
        **session_kwargs,
    )
    # The owned group is established by Popen's new session, not rediscovered.
    owned_pgid = proc.pid if owned else None
    primary: BaseException | None = None
    child_error: subprocess.CalledProcessError | None = None
    stdout, stderr = "", ""
    timeout: dict[str, Any] | None = None
    stop_reason: str | None = None
    peak_rss = 0
    rss = None
    try:
        if observer is not None:
            observer.start(proc.pid)
        while True:
            elapsed = time.perf_counter() - started
            if limits is not None:
                rss = observe_tree_rss(proc.pid)
                peak_rss = max(peak_rss, rss.sampled_bytes)
                if rss.status != "complete":
                    stop_reason = "monitoring_unavailable"
                    break
                if rss.sampled_bytes > limits.rss_limit_bytes:
                    stop_reason = "host_rss_exceeded"
                    break
                if elapsed > limits.deadline_seconds:
                    stop_reason = "work_deadline_exceeded"
                    break
            if deadline_provider is not None:
                deadline, source = deadline_provider()
                if deadline is not None and elapsed > deadline:
                    stop_reason = "watchdog_deadline"
                    print(
                        f"--- Watchdog [{label}] deadline exceeded "
                        f"({elapsed:.1f}s > {deadline:.1f}s, source={source}) — "
                        f"killing process group {owned_pgid} ---"
                    )
                    timeout = {
                        "elapsed_s": round(elapsed, 3),
                        "deadline_s": round(deadline, 3),
                        "estimate_source": source,
                    }
                    break
            try:
                stdout, stderr = proc.communicate(timeout=poll_seconds if owned else None)
                break
            except subprocess.TimeoutExpired:
                # A leader may exit while descendants keep its pipes open.
                # Do not wait for pipe EOF before inspecting the owned group.
                if proc.poll() is not None:
                    break
                continue
        if stop_reason is None and proc.returncode != 0:
            child_error = subprocess.CalledProcessError(
                proc.returncode, cmd, output=stdout, stderr=stderr
            )
            raise child_error
    except BaseException as exc:
        primary = exc
    finally:
        group, cleanup_errors = _finalize(
            proc,
            owned_pgid=owned_pgid,
            terminate=primary is not None or stop_reason is not None,
            observer=observer,
            failed=primary is not None or stop_reason is not None,
            grace_seconds=grace_seconds,
            poll_seconds=cleanup_poll,
            reap_seconds=reap_seconds,
        )
    drain_errors = list(cleanup_errors)
    try:
        stdout, stderr = proc.communicate(timeout=reap_seconds)
    except BaseException as exc:
        drain_errors.append(f"pipe drain: {type(exc).__name__}: {exc}")
    finally:
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except BaseException as exc:
                    drain_errors.append(f"pipe close: {type(exc).__name__}: {exc}")
    cleanup_errors = tuple(drain_errors)
    if child_error is not None:
        # Descendants may have kept the pipes open until finalization. Preserve
        # the original exception object while attaching the now-drained output.
        child_error.output = stdout
        child_error.stderr = stderr
    lifecycle = ProcessLifecycle(
        child_pid=proc.pid,
        owned_pgid=owned_pgid,
        elapsed_seconds=time.perf_counter() - started,
        stop_reason=stop_reason,
        peak_sampled_rss_bytes=peak_rss,
        last_rss_observation=rss,
        child_reaped=proc.returncode is not None,
        returncode=proc.returncode,
        group_cleanup=group,
        cleanup_errors=cleanup_errors,
    )
    if primary is not None:
        # Preserve exception type/identity/traceback, including KeyboardInterrupt.
        primary.add_note(f"Process lifecycle: {lifecycle.model_dump_json()}")
        primary.process_lifecycle = lifecycle  # type: ignore[attr-defined]
        raise primary.with_traceback(primary.__traceback__)
    if timeout is not None:
        timeout.update(
            escalated_to_kill=bool(group and group.kill and group.kill.status == "delivered"),
            survivors_detected=group is None or group.final.status != "absent",
            stdout_tail=(stdout or "")[-2000:],
            stderr_tail=(stderr or "")[-2000:],
        )
        if cleanup_errors:
            raise ProcessSupervisionError("Process cleanup failed", lifecycle)
        return ObservedProcessResult(completed=None, timeout=timeout, lifecycle=lifecycle)
    if (
        stop_reason is not None
        or cleanup_errors
        or not lifecycle.child_reaped
        or (group is not None and (group.required or group.final.status != "absent"))
    ):
        raise ProcessSupervisionError(stop_reason or "Process lifecycle was not clean", lifecycle)
    return ObservedProcessResult(
        completed=subprocess.CompletedProcess(cmd, proc.returncode, stdout=stdout, stderr=stderr),
        lifecycle=lifecycle,
    )


def run_observed_process(
    cmd: list[str],
    *,
    env: dict,
    preexec_fn: Callable[[], None] | None,
    capture_stdout: bool,
    deadline_provider: Callable[[], tuple[float | None, str]] | None = None,
    grace_seconds: float = 0.0,
    poll_seconds: float = 0.0,
    label: str = "",
    observer: ProcessObserver | None = None,
    limits: ProcessLimits | None = None,
) -> tuple[subprocess.CompletedProcess | None, dict[str, Any] | None]:
    """Compatibility projection: ordinary callers keep the original two values."""
    result = supervise_process(
        cmd,
        env=env,
        preexec_fn=preexec_fn,
        capture_stdout=capture_stdout,
        deadline_provider=deadline_provider,
        grace_seconds=grace_seconds,
        poll_seconds=poll_seconds,
        label=label,
        observer=observer,
        limits=limits,
    )
    return result.completed, result.timeout


def supervise_subprocess(
    cmd: list[str],
    *,
    env: dict,
    preexec_fn: Callable[[], None] | None,
    capture_stdout: bool,
    deadline_provider: Callable[[], tuple[float | None, str]] | None = None,
    grace_seconds: float = 0.0,
    poll_seconds: float = 0.0,
    label: str = "",
    observer: ProcessObserver | None = None,
    limits: ProcessLimits | None = None,
) -> ObservedProcessResult:
    """Retain package refusal checks around the process owner."""
    prepared_at = time.perf_counter() if limits is not None else None
    from core.local_code.child import prepare_child

    invocation = prepare_child(cmd, env)
    if limits is not None and prepared_at is not None:
        limits = remaining_process_limits(limits, time.perf_counter() - prepared_at)
    try:
        result = supervise_process(
            invocation.argv,
            env=invocation.env,
            preexec_fn=preexec_fn,
            capture_stdout=capture_stdout,
            deadline_provider=deadline_provider,
            grace_seconds=grace_seconds,
            poll_seconds=poll_seconds,
            label=label,
            observer=observer,
            limits=limits,
        )
    except Exception as exc:
        try:
            invocation.check(
                exc.returncode if isinstance(exc, subprocess.CalledProcessError) else None
            )
        except Exception as refusal:
            evidence = (
                exc.lifecycle
                if isinstance(exc, ProcessSupervisionError)
                else getattr(exc, "process_lifecycle", None)
            )
            if isinstance(evidence, ProcessLifecycle):
                refusal.process_lifecycle = evidence  # type: ignore[attr-defined]
            raise
        raise
    try:
        invocation.check(result.completed.returncode if result.completed is not None else None)
    except Exception as refusal:
        refusal.process_lifecycle = result.lifecycle  # type: ignore[attr-defined]
        raise
    return result


def run_observed_subprocess(
    cmd: list[str],
    *,
    env: dict,
    preexec_fn: Callable[[], None] | None,
    capture_stdout: bool,
    deadline_provider: Callable[[], tuple[float | None, str]] | None = None,
    grace_seconds: float = 0.0,
    poll_seconds: float = 0.0,
    label: str = "",
    observer: ProcessObserver | None = None,
    limits: ProcessLimits | None = None,
) -> tuple[subprocess.CompletedProcess | None, dict[str, Any] | None]:
    """Keep the historical tuple facade over package-aware typed supervision."""
    result = supervise_subprocess(
        cmd,
        env=env,
        preexec_fn=preexec_fn,
        capture_stdout=capture_stdout,
        deadline_provider=deadline_provider,
        grace_seconds=grace_seconds,
        poll_seconds=poll_seconds,
        label=label,
        observer=observer,
        limits=limits,
    )
    return result.completed, result.timeout
