"""Raw task/host causes must remain in diagnostics, never in console projections."""

import builtins
import sys
from types import SimpleNamespace

import pytest

from tools.candidate_console import gpu_check, task_summary
from tools.setup_review.composition_models import CompositionResult
from tools.workspace_sandbox.command import SandboxUnavailable

SECRET = "private-secret-sentinel"


@pytest.mark.parametrize("stage", ["composition", "planner_strategy", "sandbox"])
@pytest.mark.parametrize(
    "error,expected",
    [
        (OSError(SECRET), "Filesystem error"),
        (ValueError(SECRET), "Invalid value"),
        (type(SECRET, (RuntimeError,), {})(SECRET), "Unexpected error"),
    ],
)
def test_serialized_task_failure_is_safe_and_logged(
    console_config, monkeypatch, caplog, stage, error, expected
):
    """The serialized message and even its custom exception name used to reach the tab."""

    def observe(job, task):
        return SimpleNamespace(result=CompositionResult.failed(job, stage, error))

    summaries = task_summary.TaskSummaries(
        console_config.tasks, observer=observe, start=lambda work: work()
    )
    view = summaries.summary("synthetic")
    assert view is not None and view.failure is not None
    assert view.failure.stage == stage
    assert view.failure.message.startswith(expected)
    assert SECRET not in view.model_dump_json()
    assert SECRET in caplog.text


def test_console_observation_exception_retains_private_diagnostics(console_config, caplog):
    """A safe summary still needs the original cause available to task authors."""

    def observe(job, task):
        raise RuntimeError(SECRET)

    view = task_summary.TaskSummaries(
        console_config.tasks, observer=observe, start=lambda work: work()
    ).summary("synthetic")
    assert view is not None and SECRET not in view.model_dump_json()
    assert SECRET in caplog.text


@pytest.mark.parametrize("stage", ["import", "cuda", "profile", "sandbox"])
def test_gpu_failure_uses_safe_category(stage, console_config, monkeypatch, caplog):
    """Every caught GPU failure previously interpolated the underlying exception."""

    def fail(*args, **kwargs):
        errors = {
            "import": ImportError,
            "cuda": RuntimeError,
            "profile": ValueError,
            "sandbox": SandboxUnavailable,
        }
        raise errors[stage](SECRET)

    if stage == "import":
        original = builtins.__import__

        def importing(name, *args, **kwargs):
            return fail() if name == "torch" else original(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", importing)
        passed, message = gpu_check.probe()
    elif stage == "cuda":
        monkeypatch.setitem(
            sys.modules,
            "torch",
            SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True), zeros=fail),
        )
        passed, message = gpu_check.probe()
    else:
        if stage == "profile":
            monkeypatch.setattr(gpu_check, "task_profile", fail)
        else:
            monkeypatch.setattr(
                gpu_check, "task_profile", lambda *args: SimpleNamespace(devices=())
            )
            monkeypatch.setattr(gpu_check, "run", fail)
        passed, message = gpu_check._check_task(console_config.tasks[0])
    assert not passed and SECRET not in message
    assert "Invalid value" in message if stage == "profile" else "Unexpected error" in message
    assert SECRET in caplog.text
