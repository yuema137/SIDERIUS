"""Deterministic slow-storage witness for the real-clock handshake fixture policy."""

from types import SimpleNamespace

from core.runtime_control.inference_startup import publish_message
from tests.unit.core import test_native_gpu_execution as fixtures
from tests.unit.core.test_checkpoint_inference_measurement import bound_spec
from tests.unit.core.test_gpu_runtime_protection import Clock, observer


def test_handshake_accepts_slow_publication_and_consumption(tmp_path, bound_spec, monkeypatch):
    """Old success-path deadlines reject these valid receipts before assertions run."""
    clock = Clock()
    # Replace only the fixture's time namespace, not the runtime's clock module.
    # Omitting clock= deliberately exercises its real-process budget selection.
    monkeypatch.setattr(fixtures, "time", SimpleNamespace(monotonic=clock))
    startup, message, publications = fixtures.startup_fixture(tmp_path, bound_spec)
    publish_message(startup.path.parent / "loaded.json", message, 1024**2)
    clock.value = 90.0
    startup.check(message.child_pid)
    publish_message(startup.path.parent / "consumed.json", message, 1024**2)
    clock.value = 180.0
    startup.check(message.child_pid, terminal=True)
    assert publications == [90.0]
    assert startup.receipt.loaded == startup.receipt.consumed == message


def test_synthetic_observation_survives_slow_setup_but_still_expires():
    """Scratch publication must not age fake GPU facts out before child launch."""
    clock = Clock()
    selected = fixtures.execution_policy(slow_storage=True).protection
    control = observer(selected=selected, clock=clock)
    clock.value = 90.0
    assert control.check_control().status == "continue"
    clock.value = 601.0
    decision = control.check_control()
    assert decision.status == "stop"
    assert decision.reason == "GPU observation coverage expired"
