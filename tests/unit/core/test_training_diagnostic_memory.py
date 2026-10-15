"""Parameter-update instrumentation must not inflate candidate GPU evidence."""

import pytest
import torch

from core.runtime_control import gpu_measurement_phases as phases
from core.runtime_control.gpu_measurement_hold import ObservedReservation
from tests.unit.core.test_gpu_measurement_phases import _components


class _DeviceWatch:
    """Model diagnostic device allocations while real training runs on CPU.

    This is an allocation-order witness, not an emulator of CUDA's allocator.
    Both old and corrected diagnostic operations execute real tensor arithmetic.
    """

    def __init__(self, tensor, memory, events):
        self.tensor = tensor
        self.memory = memory
        self.events = events

    def detach(self):
        return self

    def clone(self):
        self.events.append("device_snapshot")
        self.memory["peak"] = max(self.memory["peak"], 24)
        return self.tensor.detach().clone()

    def to(self, device, *, copy=False):
        assert str(device) == "cpu"
        assert copy, "A CPU parameter must not alias its pre-update snapshot"
        self.events.append("cpu_snapshot")
        return self.tensor.detach().to(device, copy=copy)

    def __sub__(self, before):
        self.events.append("device_delta")
        self.memory["peak"] = max(self.memory["peak"], 26)
        return self.tensor.detach() - before


def test_diagnostics_do_not_add_unobserved_device_peaks(monkeypatch):
    components = _components()
    memory = {"peak": 0}
    events = []
    watched = _DeviceWatch(components.model.linear.weight, memory, events)
    monkeypatch.setattr(phases, "_watched_parameter", lambda model: watched)
    monkeypatch.setattr(phases, "_reset_peaks", lambda device: memory.update(peak=0))
    monkeypatch.setattr(phases, "_read_peaks", lambda device: (memory["peak"], memory["peak"]))
    monkeypatch.setattr(phases, "reservation_peak_bytes", lambda device: memory["peak"])
    original_step = components.optimizer.step

    def step(*args, **kwargs):
        memory["peak"] = max(memory["peak"], 22)
        return original_step(*args, **kwargs)

    monkeypatch.setattr(components.optimizer, "step", step)

    def observe():
        events.append("hold")
        return ObservedReservation(
            hold_id=str(len(events)),
            started_at=0,
            ended_at=1,
            reserved_before_bytes=22,
            reserved_after_bytes=22,
            acknowledged=True,
            driver_samples=3,
            required_samples=3,
        )

    outcome = phases.run_measured_phases(
        build_components=lambda: components,
        phase="training",
        device="cpu",
        training_steps=3,
        training_reservation_observer=observe,
    )
    assert outcome.status == "COMPLETED"
    assert outcome.realism.optimizer_steps == 3
    assert outcome.realism.parameter_update_verified
    assert events == ["cpu_snapshot", "hold", "hold", "hold", "cpu_snapshot"]
    training = outcome.phases[-1]
    assert training.allocator_reserved_peak_bytes == 22
    assert len(training.observed_reservations) == 3


@pytest.mark.parametrize("lr", [0.0, 0.1])
def test_diagnostic_preserves_real_parameter_delta(lr):
    components = _components(lr=lr)
    before = components.model.linear.weight.detach().clone()
    outcome = phases.run_measured_phases(
        build_components=lambda: components,
        phase="training",
        device="cpu",
        training_steps=3,
    )
    expected = float((components.model.linear.weight.detach() - before).abs().max())
    assert outcome.status == "COMPLETED"
    assert outcome.realism.parameter_update_max_abs_delta == expected
    assert outcome.realism.parameter_update_verified == (expected > 0)


def test_snapshot_failure_does_not_claim_verified_update(monkeypatch):
    components = _components()

    class UnreadableWatch:
        def detach(self):
            return self

        def to(self, *args, **kwargs):
            raise RuntimeError("diagnostic copy unavailable")

    monkeypatch.setattr(phases, "_watched_parameter", lambda model: UnreadableWatch())
    outcome = phases.run_measured_phases(
        build_components=lambda: components,
        phase="training",
        device="cpu",
        training_steps=3,
    )
    assert outcome.realism.optimizer_steps == 3
    assert not outcome.realism.parameter_update_verified
    assert outcome.realism.parameter_update_max_abs_delta is None
