"""Finalize the measurement's owned group without hiding cleanup uncertainty."""

import subprocess

from core.runtime_control.process_group import (
    GroupCleanup,
    GroupObservation,
    observe_group,
    terminate_observed_group,
)


def finish_training_measurement_group(
    process: subprocess.Popen, *, grace_seconds: float, poll_seconds: float
) -> GroupCleanup:
    """Use the existing termination owner and independently reap our direct child."""
    cleanup = None
    errors: list[str] = []
    interrupt = None
    try:
        cleanup = terminate_observed_group(
            process.pid, grace_seconds=grace_seconds, poll_seconds=poll_seconds, child=process
        )
    except BaseException as error:
        errors.append(f"group cleanup: {type(error).__name__}")
        if not isinstance(error, Exception):
            interrupt = error
    finally:
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=grace_seconds)
        except BaseException as error:
            errors.append(f"direct child cleanup: {type(error).__name__}")
            if interrupt is None and not isinstance(error, Exception):
                interrupt = error
    if interrupt is not None:
        raise interrupt
    final = observe_group(process.pid)
    if errors:
        final = GroupObservation(status="unknown", error="; ".join(errors))
    if cleanup is None:
        return GroupCleanup(required=True, final=final)
    return cleanup.model_copy(update={"final": final})
