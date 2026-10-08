"""Reservation holds must bind actual device memory to distinct driver windows."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import torch
from torch.utils.data import DataLoader, TensorDataset

from core.runtime_control import gpu_measurement_hold as holds
from core.runtime_control import gpu_measurement_phases as phases
from core.runtime_control.gpu_measurement_sampler import TreeMemorySample


def _cuda(monkeypatch, *, reservations=(700, 700)):
    calls = []
    values = iter(reservations)

    def method(name, value):
        def invoke(device):
            calls.append((name, str(device)))
            return value() if callable(value) else value

        monkeypatch.setattr(torch.cuda, name, invoke)

    method("synchronize", None)
    method("reset_peak_memory_stats", None)
    method("memory_reserved", lambda: next(values))
    method("max_memory_reserved", 701)
    method("max_memory_allocated", 601)
    return calls


def test_allocator_and_output_synchronization_use_measured_cuda_device(monkeypatch):
    """A cuda:1 worker must not read/reset the default cuda:0 allocator."""
    calls = _cuda(monkeypatch)
    phases._reset_peaks("cuda:1")
    phases._read_peaks("cuda:1")
    phases._synchronize_device(SimpleNamespace(is_cuda=True, device=torch.device("cuda:1")))
    assert holds.reservation_peak_bytes("cuda:1") == 701
    assert {device for _, device in calls} == {"cuda:1"}
    assert {name for name, _ in calls} >= {
        "reset_peak_memory_stats",
        "max_memory_allocated",
        "max_memory_reserved",
        "synchronize",
    }


def _sample(at, *, available=True):
    return TreeMemorySample(
        at=at, telemetry_available=available, own_tree_mib=800 if available else None
    )


def test_acknowledgement_requires_samples_for_each_open_nonce_phase_and_sequence(tmp_path):
    """Prior-phase readings, failed polls and closed-hold readings cannot acknowledge new work."""
    now = [10.0]
    journal_path, ack_path = tmp_path / "journal", tmp_path / "ack"
    journal = phases.PhaseJournal(str(journal_path), clock=lambda: now[0])

    def acknowledge(samples, request="request"):
        holds.acknowledge_reservation(
            journal_path=journal_path,
            ack_path=ack_path,
            samples=samples,
            minimum_samples=3,
            request_id=request,
        )

    journal.record("reservation_hold_start", "setup", hold_id="request:setup:0")
    acknowledge([_sample(9), _sample(10), _sample(11, available=False), _sample(12)])
    assert not ack_path.exists()
    acknowledge([_sample(10), _sample(11), _sample(12)])
    assert ack_path.read_text() == "request:setup:0"
    journal.record("reservation_hold_end", "setup", hold_id="request:setup:0")
    now[0] = 20
    journal.record("reservation_hold_start", "inference", hold_id="request:inference:0")
    acknowledge([_sample(10), _sample(11), _sample(12)])
    assert ack_path.read_text() == "request:setup:0"
    acknowledge([_sample(20), _sample(21), _sample(22)], request="different")
    assert ack_path.read_text() == "request:setup:0"
    acknowledge([_sample(20), _sample(21), _sample(22)])
    assert ack_path.read_text() == "request:inference:0"
    now[0] = 30
    journal.record("reservation_hold_start", "inference", hold_id="request:inference:1")
    journal.record("reservation_hold_end", "inference", hold_id="request:inference:1")
    acknowledge([_sample(30), _sample(31), _sample(32)])
    assert ack_path.read_text() == "request:inference:0"


def test_observer_preserves_byte_reservation_and_requires_a_fresh_ack(tmp_path, monkeypatch):
    """The next forward cannot reuse the first hold's acknowledgement."""
    calls = _cuda(monkeypatch, reservations=(701, 701, 503, 499))
    now = [10.0]
    monkeypatch.setattr(holds.time, "time", lambda: now[0])
    monkeypatch.setattr(holds.time, "monotonic", lambda: now[0])
    journal = phases.PhaseJournal(str(tmp_path / "journal"), clock=lambda: now[0])
    ack = tmp_path / "ack"
    waits = []

    def advance(seconds):
        waits.append(seconds)
        now[0] += 0.01
        if len(waits) == 1:
            ack.write_text("request:inference:0")

    monkeypatch.setattr(holds.time, "sleep", advance)
    observe = holds.reservation_observer(
        device="cuda:1",
        journal=journal,
        phase="inference",
        request_id="request",
        ack_path=str(ack),
        timeout_seconds=0.05,
        deadline_at=10.08,
    )
    first, second = observe(), observe()
    assert first.acknowledged and not second.acknowledged
    assert (first.reserved_before_bytes, first.reserved_after_bytes) == (701, 701)
    assert (second.reserved_before_bytes, second.reserved_after_bytes) == (503, 499)
    assert first.hold_id == "request:inference:0"
    assert second.hold_id == "request:inference:1"
    assert [event["event"] for event in journal.events] == [
        "reservation_hold_start",
        "reservation_hold_end",
        "reservation_hold_start",
        "reservation_hold_end",
    ]
    assert {device for _, device in calls} == {"cuda:1"}


@pytest.mark.parametrize("acknowledged", [True, False])
def test_phase_reports_reservation_for_setup_and_each_forward(monkeypatch, acknowledged):
    """Production phase runner must call every observer and refuse a missing acknowledgement."""
    from execute_tools.task_probe_batch import InferenceProbeBatches

    dataset = TensorDataset(torch.arange(12).reshape(3, 4).float())
    model = torch.nn.Linear(4, 4)
    components = phases.CandidateComponents(
        model=model,
        model_input=None,
        loss_target=None,
        optimizer=None,
        loss_fn=None,
        inference_batches_factory=lambda units: nullcontext(
            InferenceProbeBatches(
                loader=DataLoader(dataset, batch_size=1),
                dataset_samples=3,
                selected_samples=3,
                selected_batches=3,
            )
        ),
    )
    calls = []

    def observer(phase):
        def observe():
            index = calls.count(phase)
            calls.append(phase)
            return holds.ObservedReservation(
                hold_id=f"request:{phase}:{index}",
                started_at=1,
                ended_at=2,
                reserved_before_bytes=700,
                reserved_after_bytes=700,
                acknowledged=acknowledged if phase == "inference" else True,
            )

        return observe

    monkeypatch.setattr(phases, "reservation_peak_bytes", lambda device: 701)
    outcome = phases.run_measured_phases(
        build_components=lambda: components,
        phase="inference",
        device="cpu",
        setup_reservation_observer=observer("setup"),
        inference_reservation_observer=observer("inference"),
    )
    assert outcome.status == ("COMPLETED" if acknowledged else "WORKER_FAILURE")
    assert calls == ["setup"] + ["inference"] * (3 if acknowledged else 1)
    setup, inference = outcome.phases
    assert setup.allocator_reserved_peak_bytes == inference.allocator_reserved_peak_bytes == 701
    assert len(setup.observed_reservations) == 1
    assert [hold.hold_id for hold in inference.observed_reservations] == [
        f"request:inference:{index}" for index in range(3 if acknowledged else 1)
    ]


@pytest.mark.parametrize("bound", [True, False])
def test_worker_routes_bound_inference_to_reservation_observers(tmp_path, monkeypatch, bound):
    """A tested hold helper is useless if the production worker still uses its stale phase marker."""
    from core.runtime_control import gpu_measurement_worker_main as worker
    from core.runtime_control.gpu_measurement_identity import PlannedCandidateIdentity
    from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
    from core.runtime_control.gpu_requirement import CandidateMeasurementRequest
    from core.runtime_control.inference_measurement_binding import InferenceMeasurementBinding

    binding = InferenceMeasurementBinding(
        request_sha256="a" * 64,
        assembly_sha256="b" * 64,
        plugin_sources_sha256="c" * 64,
        runtime_sha256="d" * 64,
    )
    spec = GpuMeasurementSpec(
        label="hold-routing",
        request=CandidateMeasurementRequest(
            model_type="fixture",
            request_id="request",
            device_uuid="GPU-fixture",
            phase="inference",
            deadline_seconds=30,
            planned_identity=PlannedCandidateIdentity(
                model_type="fixture",
                model_family="fixture",
                optimizer_type="adamw",
                seg_size=4,
                batch_size=1,
                inference_batch_size=2,
                planned_config_hash="cfg:fixture",
            ),
        ),
        inference_binding=binding if bound else None,
        inference_batch_size=2,
        reservation_ack_path=str(tmp_path / "ack"),
        phase_complete_path=str(tmp_path / "complete"),
        sampler_ready_path=str(tmp_path / "ready"),
        result_path=str(tmp_path / "result"),
        journal_path=str(tmp_path / "journal"),
        worker_memory_limit_bytes=1024**3,
    )
    monkeypatch.setattr(worker, "resolve_device", lambda spec: worker.DeviceResolution(None))
    monkeypatch.setattr(worker, "validate_candidate_configs", lambda spec: None)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 100.0)
    builder_deadlines = []

    def build(measured_spec, trace, *, deadline_at):
        assert measured_spec is spec
        builder_deadlines.append(deadline_at)
        return lambda: None

    monkeypatch.setattr(worker, "build_production_components", build)
    monkeypatch.setattr(
        "core.runtime_control.inference_measurement_binding.inference_measurement_binding",
        lambda spec: binding,
    )
    factories = []

    def observer(**kwargs):
        def callback():
            return None

        factories.append((kwargs, callback))
        return callback

    monkeypatch.setattr(holds, "reservation_observer", observer)
    received = {}

    def run(**kwargs):
        received.update(kwargs)
        return phases.PhaseRunOutcome(
            status="WORKER_FAILURE", detail="stopped after callback wiring"
        )

    monkeypatch.setattr(worker, "run_measured_phases", run)
    worker.measure(spec)
    assert builder_deadlines == [130.0]
    if bound:
        assert [options["phase"] for options, _ in factories] == ["setup", "inference"]
        assert received["setup_reservation_observer"] is factories[0][1]
        assert received["inference_reservation_observer"] is factories[1][1]
        assert received["phase_observed_enough"] is None
        assert all(options["journal"] is received["journal"] for options, _ in factories)
        assert (
            factories[0][0]["deadline_at"] == factories[1][0]["deadline_at"] == builder_deadlines[0]
        )
        assert {options["request_id"] for options, _ in factories} == {"request"}
    else:
        assert factories == []
        assert received["setup_reservation_observer"] is None
        assert received["inference_reservation_observer"] is None
        assert received["phase_observed_enough"] is not None


def test_parent_recounts_samples_inside_each_reported_hold():
    """Phase-wide or stale samples cannot manufacture coverage for a later hold."""
    from core.runtime_control.gpu_measurement_hold import (
        ObservedReservation,
        bind_reservation_samples,
    )
    from core.runtime_control.gpu_measurement_sampler import TreeMemorySample

    hold = ObservedReservation(
        hold_id="r:inference:1",
        started_at=10,
        ended_at=12,
        reserved_before_bytes=100,
        reserved_after_bytes=100,
        acknowledged=True,
        driver_samples=999,
        required_samples=1,
    )
    samples = [
        TreeMemorySample(at=at, telemetry_available=True, own_tree_mib=1)
        for at in (1, 2, 3, 10.5, 12.5)
    ]
    observed = bind_reservation_samples(hold, samples, minimum_samples=3)
    assert observed.driver_samples == 1
    assert observed.required_samples == 3
