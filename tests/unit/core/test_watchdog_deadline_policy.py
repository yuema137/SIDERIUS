"""Explicit ceilings must not be replaced by point forecasts or a larger floor."""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from core.runtime_control.session import RuntimeControlPolicy, WatchdogConfig
from core.runtime_control.watchdog_deadline import watchdog_deadline_provider
from core.sandbox_executor import _run_observed_subprocess

# Frozen reported observation values, not expectations recomputed by the owner.
REPORTED_ATTEMPTS = (
    ((1.8150514606386423, 107.92820740863681, 111.14064147695899), 220.88390034623444),
    ((1.992011085152626, 62.11786184087396, 60.40196493268013), 124.51183785870671),
    ((1.923782927915454, 30.557044704444706, 29.742515720427036), 62.2233433527872),
)


def _observation(seconds):
    return {
        "components": {
            phase: {
                "prediction": {"predicted_seconds": value, "source": source},
                "workload": {"unit_count": 1},
            }
            for phase, value, source in zip(
                ("setup", "training", "validation"),
                seconds,
                (
                    "real_dataset_setup",
                    "real_training_verification",
                    "real_validation_verification",
                ),
                strict=True,
            )
        }
    }


@pytest.mark.parametrize("seconds,old_deadline", REPORTED_ATTEMPTS)
def test_recorded_forecasts_do_not_shrink_authorized_budget(seconds, old_deadline):
    observation = _observation(seconds)
    for selection, expected in (
        ("budget-ceiling-v1", (900.0, "operator_budget")),
        ("forecast-tightening-v1", (old_deadline, "verified_components")),
    ):
        policy = RuntimeControlPolicy(
            operator_budget_seconds=900,
            watchdog=WatchdogConfig(enabled=True, deadline_policy=selection),
        )
        result = watchdog_deadline_provider(
            policy, "unused", observation_reader=lambda _: observation
        )()
        assert result[0] == pytest.approx(expected[0], abs=1e-12)
        assert result[1] == expected[1]


@pytest.mark.parametrize("budget", [0.02, 900.0, 86_400.0])
def test_native_deadline_never_reads_missing_partial_or_changing_predictions(budget):
    reader = Mock(side_effect=AssertionError("Point forecasts are not deadline authority"))
    policy = RuntimeControlPolicy(
        operator_budget_seconds=budget,
        watchdog=WatchdogConfig(enabled=True, floor_seconds=120, safety_factor=100),
    )
    provider = watchdog_deadline_provider(policy, "absent", observation_reader=reader)
    assert provider() == (budget, "operator_budget")
    assert provider() == (budget, "operator_budget")
    reader.assert_not_called()


@pytest.mark.parametrize(
    "outer,watchdog_budget,emergency,expected,source",
    [
        (None, 900, None, 900, "watchdog_budget"),
        (900, 600, None, 600, "watchdog_budget"),
        (300, 600, None, 300, "operator_budget"),
        (900, 600, 5, 5, "validation_max_phase"),
        (None, None, 0.1, 0.1, "validation_max_phase"),
    ],
)
def test_declared_ceilings_are_minimized_without_raising_them_to_floor(
    outer, watchdog_budget, emergency, expected, source
):
    policy = RuntimeControlPolicy(
        operator_budget_seconds=outer,
        watchdog=WatchdogConfig(
            enabled=True,
            budget_seconds=watchdog_budget,
            max_phase_seconds=emergency,
            floor_seconds=120,
        ),
    )
    assert watchdog_deadline_provider(policy, "unused")() == (expected, source)
    restored = RuntimeControlPolicy.model_validate_json(policy.model_dump_json())
    assert watchdog_deadline_provider(restored, "unused")() == (expected, source)


def test_missing_native_ceiling_fails_while_disabled_and_explicit_legacy_remain_valid():
    with pytest.raises(ValidationError, match="finite explicit phase budget"):
        RuntimeControlPolicy(watchdog=WatchdogConfig(enabled=True))
    with pytest.raises(ValidationError, match="finite explicit phase budget"):
        RuntimeControlPolicy(
            operator_budget_seconds=float("inf"), watchdog=WatchdogConfig(enabled=True)
        )
    RuntimeControlPolicy()
    legacy = RuntimeControlPolicy(
        watchdog=WatchdogConfig(enabled=True, deadline_policy="forecast-tightening-v1")
    )
    restored = RuntimeControlPolicy.model_validate_json(legacy.model_dump_json())
    assert restored.watchdog.deadline_policy == "forecast-tightening-v1"
    assert watchdog_deadline_provider(restored, "absent")() == (None, "none")
    with pytest.raises(ValidationError, match=r"does not accept watchdog\.budget_seconds"):
        WatchdogConfig(deadline_policy="forecast-tightening-v1", budget_seconds=30)


def test_explicit_legacy_preserves_floor_after_minimum():
    policy = RuntimeControlPolicy(
        operator_budget_seconds=5,
        watchdog=WatchdogConfig(
            enabled=True, deadline_policy="forecast-tightening-v1", floor_seconds=60
        ),
    )
    assert watchdog_deadline_provider(policy, "absent")() == (60, "operator_budget")


def _supervise(script, policy, observation):
    return _run_observed_subprocess(
        [sys.executable, "-c", script],
        env=os.environ.copy(),
        preexec_fn=None,
        capture_stdout=True,
        deadline_provider=watchdog_deadline_provider(
            policy, "unused", observation_reader=lambda _: observation
        ),
        grace_seconds=policy.watchdog.grace_seconds,
        poll_seconds=policy.watchdog.poll_seconds,
        label="deadline-contract-test",
    )


def test_progressing_subprocess_can_finish_after_forecast_before_explicit_budget(tmp_path):
    progress = tmp_path / "progress"
    policy = RuntimeControlPolicy(
        operator_budget_seconds=5,
        watchdog=WatchdogConfig(enabled=True, floor_seconds=0, poll_seconds=0.02),
    )
    # The marker is written well past the old 0.03-second forecast. Baseline
    # forecast tightening kills before it, instead of allowing normal progress.
    script = (
        "import time; from pathlib import Path; time.sleep(0.2); "
        f"Path({str(progress)!r}).write_text('completed after forecast')"
    )
    result, killed = _supervise(script, policy, _observation((0.01, 0.01, 0.01)))
    assert result is not None and result.returncode == 0
    assert killed is None
    assert progress.read_text() == "completed after forecast"


def test_actual_native_budget_overrun_kills_descendants_despite_large_floor(tmp_path):
    group_file = tmp_path / "process-group"
    policy = RuntimeControlPolicy(
        watchdog=WatchdogConfig(
            enabled=True,
            budget_seconds=0.5,
            floor_seconds=60,
            grace_seconds=0.1,
            poll_seconds=0.02,
        ),
    )
    script = (
        "import os,subprocess,sys,time; from pathlib import Path; "
        f"Path({str(group_file)!r}).write_text(str(os.getpgrp())); "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "time.sleep(60)"
    )
    result, killed = _supervise(script, policy, _observation((10, 100, 10)))
    assert result is None and killed is not None
    assert killed["deadline_s"] == 0.5
    assert killed["estimate_source"] == "watchdog_budget"
    with pytest.raises(ProcessLookupError):
        os.killpg(int(group_file.read_text()), 0)
