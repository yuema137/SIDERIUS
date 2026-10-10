"""Issue 672: extracting launch selection must preserve both subprocess contracts."""

import subprocess
from unittest.mock import Mock

import pytest

from core.runtime_control.phase_launch import run_phase_subprocess
from core.runtime_control.session import RuntimeControlPolicy, WatchdogConfig


@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize("selection", ["absent", "disabled", "unarmed", "watchdog"])
def test_shared_selection_preserves_exact_runner_options_and_timeout_projection(phase, selection):
    """A changed deadline/label keyword or plain timeout projection changes execution."""
    policy = (
        None
        if selection == "absent"
        else RuntimeControlPolicy(
            operator_budget_seconds=30, watchdog=WatchdogConfig(enabled=selection != "disabled")
        )
    )
    completed = subprocess.CompletedProcess(["child"], 0)
    timeout = {"elapsed_s": 12, "deadline_s": 10, "estimate_source": "fixture"}
    runner = Mock(return_value=(completed, timeout))
    deadline = Mock(return_value=(10.0, "fixture"))
    factory = Mock(return_value=deadline)
    env, observer, control, startup = {"EXPLICIT": "binding"}, object(), object(), object()
    options = dict(
        env=env,
        preexec_fn=None,
        capture_stdout=False,
        observer=observer,
        control=control,
        startup=startup,
    )

    result = run_phase_subprocess(
        runner,
        ["child"],
        policy=policy,
        armed=selection != "unarmed",
        phase=phase,
        observation_path="fixture.json",
        deadline_factory=factory,
        **options,
    )

    if selection == "watchdog":
        factory.assert_called_once_with(policy, "fixture.json", phase=phase)
        runner.assert_called_once_with(
            ["child"],
            **options,
            deadline_provider=deadline,
            grace_seconds=policy.watchdog.grace_seconds,
            poll_seconds=policy.watchdog.poll_seconds,
            label=phase,
        )
        assert result == (completed, timeout)
    else:
        factory.assert_not_called()
        runner.assert_called_once_with(["child"], **options)
        assert result == (completed, None)


def test_shared_launch_propagates_the_original_failure():
    """The extraction must not reinterpret native lifecycle exceptions or retry."""
    failure = RuntimeError("measured launch evidence refused")
    runner = Mock(side_effect=failure)
    with pytest.raises(RuntimeError) as caught:
        run_phase_subprocess(
            runner,
            ["child"],
            policy=None,
            armed=False,
            phase="training",
            observation_path="fixture.json",
            deadline_factory=Mock(),
        )
    assert caught.value is failure
    runner.assert_called_once()
