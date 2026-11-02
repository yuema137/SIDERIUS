"""Preparation and consumption use distinct product windows even with slow I/O."""

from pathlib import Path

import pytest

from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.inference_startup import (
    InferenceStartupMessage,
    publish_message,
    read_message,
)
from tests.helpers.inference_startup import startup_fixture
from tests.unit.core.test_checkpoint_inference_measurement import bound_spec as bound_spec
from tests.unit.core.test_gpu_runtime_protection import Clock


@pytest.mark.parametrize("consumed_at", [650.0, 690.0], ids=["within-ack-window", "ack-expired"])
def test_consumption_window_starts_at_authorization_publication(
    tmp_path: Path, bound_spec: GpuMeasurementSpec, consumed_at: float
) -> None:
    """Reject deadline reuse and timeout bypass without waiting for a real hang."""
    clock = Clock()
    startup, message, publications = startup_fixture(
        tmp_path, bound_spec, clock=clock, preparation_seconds=600.0, ack_seconds=600.0
    )
    publish_message(startup.path.parent / "loaded.json", message, 1024**2)
    clock.value = 90.0
    startup.check(message.child_pid)
    assert (
        read_message(startup.path.parent / "authorized.json", InferenceStartupMessage, 1024**2)
        == message
    )
    publish_message(startup.path.parent / "consumed.json", message, 1024**2)
    clock.value = consumed_at
    if consumed_at == 690.0:
        with pytest.raises(TimeoutError, match="consumption observation was late"):
            startup.check(message.child_pid, terminal=True)
        assert startup.receipt.consumed is None
    else:
        startup.check(message.child_pid, terminal=True)
        assert startup.receipt.consumed == message
    assert publications == [90.0]
    assert startup.receipt.loaded == message
