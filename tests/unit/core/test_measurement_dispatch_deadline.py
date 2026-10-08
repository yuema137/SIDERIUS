"""Parent preparation cannot grant a new allowance to an expired measurement."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.local_code import child
from core.runtime_control import gpu_measurement_runner as runner
from tests.unit.core.test_gpu_measurement_runner import (
    DEVICE,
    _bound_inference_spec,
    _Driver,
    _fake_worker,
)


def _advance_preparation(monkeypatch, *, at, stage):
    clock = [100.0]
    logs = []
    prepare = child.prepare_child
    write = Path.write_text
    open_file = Path.open

    def prepare_child(*args, **kwargs):
        invocation = prepare(*args, **kwargs)
        if stage == "package":
            clock[0] = at
        return invocation

    def write_text(path, *args, **kwargs):
        result = write(path, *args, **kwargs)
        if stage == "request" and path.name.endswith(".spec.json"):
            clock[0] = at
        return result

    def open_log(path, *args, **kwargs):
        handle = open_file(path, *args, **kwargs)
        if path.name.endswith(".worker.log") and handle.writable():
            logs.append(handle)
        return handle

    monkeypatch.setattr(child, "prepare_child", prepare_child)
    monkeypatch.setattr(Path, "write_text", write_text)
    monkeypatch.setattr(Path, "open", open_log)
    return lambda: clock[0], logs


@pytest.mark.parametrize(
    ("absolute", "relative", "prepared_at", "stage", "effective"),
    [
        (110, 60, 110, "package", 10),
        (110, 60, 111, "package", 10),
        (200, 10, 110, "package", 10),
        (110, 60, 110, "request", 10),
    ],
)
def test_expired_preparation_refuses_before_spawn_and_closes_log(
    tmp_path, monkeypatch, absolute, relative, prepared_at, stage, effective
):
    """Catch both a missing final check and a check that ignores the shorter cap."""
    spec = _bound_inference_spec(tmp_path, deadline=relative)
    original = spec.model_dump_json()
    clock, logs = _advance_preparation(monkeypatch, at=prepared_at, stage=stage)
    popen = Mock(side_effect=AssertionError("expired preparation reached Popen"))
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    result = runner.run_prephase_measurement(
        spec, device=DEVICE, deadline_at=absolute, elapsed_clock=clock
    )
    popen.assert_not_called()
    assert len(logs) == 1 and logs[0].closed
    assert "TimeoutError('measurement deadline expired during launch preparation')" in result.detail
    assert result.report_present is False
    assert result.process.worker_pid == 1  # Existing no-child projection, not an observed PID.
    assert result.deadline.budget_seconds == effective
    assert result.deadline.elapsed_seconds == 0  # Existing launch-failure projection.
    assert spec.model_dump_json() == original
    persisted = Path(spec.result_path).with_suffix(".spec.json").read_text()
    assert json.loads(persisted) == json.loads(original)


@pytest.mark.parametrize(
    ("absolute", "relative", "prepared_at", "expected_budget", "expected_elapsed"),
    [(110, 60, 109, 10, 9), (200, 10, 109, 10, 9), (None, 10, 150, 10, 0)],
)
def test_remaining_allowance_and_ordinary_postspawn_clock_are_preserved(
    tmp_path, monkeypatch, absolute, relative, prepared_at, expected_budget, expected_elapsed
):
    """A real CPU child proves nonexpiry is not refused and ordinary time is reset."""
    spec = _bound_inference_spec(tmp_path, deadline=relative)
    original = spec.model_dump_json()
    command = _fake_worker(tmp_path, "pass")
    clock, logs = _advance_preparation(monkeypatch, at=prepared_at, stage="package")
    result = runner.run_prephase_measurement(
        spec,
        device=DEVICE,
        command=command,
        deadline_at=absolute,
        elapsed_clock=clock,
        device_sampler=_Driver([0]),
        poll_seconds=0.01,
        grace_seconds=0.05,
    )
    assert result.process.worker_pid > 1
    assert result.process.exit_code == 0
    assert not result.process.term_sent and not result.process.kill_sent
    assert result.deadline.budget_seconds == expected_budget
    assert result.deadline.elapsed_seconds == expected_elapsed
    assert len(logs) == 1 and logs[0].closed
    assert spec.model_dump_json() == original
