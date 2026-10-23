"""Observed runner retains cleanup uncertainty and attempts cleanup on failures."""

import subprocess
from types import SimpleNamespace

import pytest

from core.runtime_control.process_group import GroupCleanup, GroupObservation
from tools.workspace_sandbox import runner


@pytest.mark.parametrize("cleanup", ["absent", "present", "unknown"])
@pytest.mark.parametrize("failure", ["none", "timeout", "wait", "reap"])
def test_observed_runner_never_invents_cleanup(monkeypatch, cleanup, failure):
    """A late group exit stays unresolved; post-spawn failures cannot bypass cleanup."""
    calls = []

    class Process:
        pid = 123
        returncode = 0

        def wait(self, timeout):
            calls.append(("wait", timeout))
            if timeout == 7 and failure == "timeout":
                raise subprocess.TimeoutExpired("worker", timeout)
            if (timeout == 7 and failure == "wait") or (timeout == 5 and failure == "reap"):
                raise RuntimeError("unresolved")

    monkeypatch.setattr(runner, "build_command", lambda *args: (["exact"], {}))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())

    def terminate(pgid, **kwargs):
        assert pgid == 123 and kwargs["retain_unknown"] is True
        assert kwargs["child"].pid == 123
        calls.append(("cleanup", cleanup))
        return GroupCleanup(required=False, final=GroupObservation(status=cleanup))

    monkeypatch.setattr(runner, "terminate_observed_group", terminate)
    if failure in {"wait", "reap"}:
        with pytest.raises(RuntimeError):
            runner.run_observed(SimpleNamespace(timeout_seconds=7), ["exact"])
    else:
        result = runner.run_observed(SimpleNamespace(timeout_seconds=7), ["exact"])
        assert result.cleanup.final.status == cleanup
        assert result.execution.status == ("timed_out" if failure == "timeout" else "completed")
    assert ("cleanup", cleanup) in calls


@pytest.mark.parametrize("stage", ["build", "spawn"])
def test_proven_pre_spawn_failure_is_distinct(monkeypatch, stage):
    def refused(*args, **kwargs):
        raise OSError("private command")

    monkeypatch.setattr(
        runner, "build_command", refused if stage == "build" else lambda *a: (["exact"], {})
    )
    monkeypatch.setattr(runner.subprocess, "Popen", refused)
    with pytest.raises(runner.ObservedSpawnFailure, match="not created"):
        runner.run_observed(SimpleNamespace(timeout_seconds=7), ["exact"])
