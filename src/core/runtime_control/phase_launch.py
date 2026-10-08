"""Select watchdog or ordinary launch without owning phase admission or cleanup."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any, Protocol

from core.runtime_control.session import RuntimeControlPolicy

LaunchResult = tuple[subprocess.CompletedProcess | None, dict[str, Any] | None]


class DeadlineFactory(Protocol):
    def __call__(
        self, policy: RuntimeControlPolicy, observation_path: str, /, *, phase: str
    ) -> Callable[[], tuple[float | None, str]]: ...


def run_phase_subprocess(
    runner: Callable[..., LaunchResult],
    cmd: list[str],
    *,
    policy: RuntimeControlPolicy | None,
    armed: bool,
    phase: str,
    observation_path: str,
    deadline_factory: DeadlineFactory,
    **kwargs: Any,
) -> LaunchResult:
    """Share the executor's phase-launch choice, preserving runner keyword presence.

    Callers have already admitted the phase and selected its native/ordinary
    runner. Only an armed watchdog receives deadline, cadence and label options.
    Ordinary launches retain their historical tuple projection: timeout metadata
    is ignored. Artifact cleanup and result classification remain with callers.
    """
    if policy is not None and policy.watchdog.enabled and armed:
        return runner(
            cmd,
            **kwargs,
            deadline_provider=deadline_factory(policy, observation_path, phase=phase),
            grace_seconds=policy.watchdog.grace_seconds,
            poll_seconds=policy.watchdog.poll_seconds,
            label=phase,
        )
    result, _ = runner(cmd, **kwargs)
    return result, None
