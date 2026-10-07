"""Checkpoint identity must reach real inference setup and complete evidence checks."""

import hashlib
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
import torch
from pydantic import BaseModel, ValidationError

from core.runtime_control.gpu_measurement_hold import ObservedReservation
from core.runtime_control.gpu_measurement_identity import build_planned_identity
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec, WorkerMeasurementReport
from core.runtime_control.gpu_measurement_worker_main import build_production_components, measure
from core.runtime_control.inference_checkpoint_reference import InferenceCheckpointReference
from core.runtime_control.inference_measurement_assessment import assess_inference_measurement
from core.runtime_control.inference_measurement_binding import (
    MeasurementSources,
    inference_measurement_binding,
)
from core.sandbox_layout import training_checkpoint_path
from ml_models.target_standardization import StandardizedTargetModel
from tests.helpers.inference_measurement import evaluation_probe
from tests.helpers.inference_verification import _verification
from tests.helpers.step04a_fixtures import regressor_model_io
from tests.unit.core.test_gpu_measurement_runner import DEVICE, _run, _spec


@pytest.fixture
def bound_spec(tmp_path, monkeypatch):
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY

    class Config(BaseModel):
        pass

    class Model(torch.nn.Module):
        def __init__(self, cfg, loss_type=None):
            super().__init__()
            self.scale = torch.nn.Parameter(torch.ones(1))

        def forward(self, inputs):
            return inputs[:, :1].float() * self.scale

    name = "checkpoint_fixture"
    monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, name, Config)
    monkeypatch.setitem(MODEL_REGISTRY, name, Model)
    source = Model(Config())
    with torch.no_grad():
        source.scale.fill_(3)
    source = StandardizedTargetModel(source, mean=7, scale=5)
    path = training_checkpoint_path(tmp_path, name, "exp-a")
    torch.save(source.state_dict(), path)
    (tmp_path / "_OK_exp-a").touch()
    reference = InferenceCheckpointReference(
        checkpoint_path=str(path),
        experiment_id="exp-a",
        checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        checkpoint_byte_size=path.stat().st_size,
    )
    original = _spec(tmp_path)
    request = original.request.model_copy(
        update={
            "model_type": name,
            "phase": "inference",
            "planned_identity": build_planned_identity(
                model_type=name,
                model_config={},
                train_config={"batch_size": 1},
                inference_batch_size=3,
                segmentation_applicability="not_applicable",
            ),
        }
    )
    spec = GpuMeasurementSpec(
        **{
            **original.model_dump(),
            "request": request,
            "device": "cpu",
            "train_config": {"batch_size": 1},
            "loss_config": {"loss_type": "smooth_l1"},
            "data_dir": str(tmp_path),
            "task_probe_data": evaluation_probe(tmp_path, rows=7),
            "model_io_contract": regressor_model_io(),
            "inference_batch_size": 3,
            "inference_batches": 3,
            "inference_checkpoint": reference,
            "reservation_ack_path": str(tmp_path / "reservation"),
        }
    )
    monkeypatch.setattr(
        "core.runtime_control.inference_measurement_binding.measurement_sources",
        lambda **kwargs: MeasurementSources(
            assembly_sha256="a" * 64, plugin_sources_sha256="b" * 64, runtime_sha256="c" * 64
        ),
    )
    binding = inference_measurement_binding(spec)
    return spec.model_copy(update={"inference_binding": binding})


def test_actual_builder_loads_wrapper_and_emits_correct_trace(bound_spec):
    trace = Mock()
    components = build_production_components(bound_spec, trace, deadline_at=time.monotonic() + 10)()
    assert isinstance(components.model, StandardizedTargetModel)
    assert torch.equal(components.model(torch.tensor([[2, 0, 0, 0]])), torch.tensor([[37.0]]))
    assert not components.model.training
    assert components.verified_checkpoint == bound_spec.inference_checkpoint
    assert components.optimizer is components.loss_fn is None
    details = [call.kwargs.get("detail") for call in trace.record.call_args_list]
    assert "no checkpoint" not in details
    assert "checkpoint load pending" in details
    assert any(call.args[0] == "after_checkpoint_load" for call in trace.record.call_args_list)


def test_actual_worker_transports_success_receipt_and_evaluation_geometry(bound_spec, monkeypatch):
    def observer(**kwargs):
        sequence = 0

        def hold():
            nonlocal sequence
            now = time.time()
            item = ObservedReservation(
                hold_id=f"{bound_spec.request.request_id}:{kwargs['phase']}:{sequence}",
                started_at=now,
                ended_at=now,
                reserved_before_bytes=0,
                reserved_after_bytes=0,
                acknowledged=True,
                driver_samples=3,
                required_samples=3,
            )
            sequence += 1
            return item

        return hold

    monkeypatch.setattr("core.runtime_control.gpu_measurement_hold.reservation_observer", observer)
    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_phases.reservation_peak_bytes", lambda device: 0
    )
    monkeypatch.setattr(torch.cuda, "_lazy_init", lambda: pytest.fail("CPU witness reached CUDA"))
    report = measure(bound_spec)
    assert report.status == "COMPLETED", report.detail
    assert report.verified_checkpoint == bound_spec.inference_checkpoint
    assert report.observed_device_uuid is None  # CPU proof cannot become GPU authority.
    assert report.realism.backward_calls == report.realism.optimizer_steps == 0
    assert [batch.shape[0] for batch in report.realism.inference_data.batches] == [3, 3, 1]
    assert WorkerMeasurementReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("fault", ["hash", "expired"])
def test_actual_setup_integrity_or_deadline_failure_has_no_capacity_authority(bound_spec, fault):
    from core.runtime_control.gpu_measurement_phases import run_measured_phases

    spec = bound_spec
    deadline = time.monotonic() + 10
    if fault == "hash":
        ref = spec.inference_checkpoint.model_copy(update={"checkpoint_sha256": "0" * 64})
        spec = spec.model_copy(update={"inference_checkpoint": ref})
    else:
        deadline = time.monotonic() - 1
    result = run_measured_phases(
        build_components=build_production_components(spec, deadline_at=deadline),
        phase="inference",
        device="cpu",
    )
    assert result.status == "WORKER_FAILURE"
    assert result.verified_checkpoint is None
    assert result.realism.forward_calls == 0
    assert result.phases[0].status == "FAILED"
    assert "checkpoint" in result.detail
    assert ("TimeoutError" in result.detail) == (fault == "expired")


def test_binding_changes_for_every_checkpoint_identity_field(bound_spec):
    old = bound_spec.inference_binding
    for field, value in {
        "checkpoint_path": "/other/model_checkpoint_fixture_exp-a_agent.pth",
        "experiment_id": "exp-b",
        "checkpoint_sha256": "0" * 64,
        "checkpoint_byte_size": 1,
    }.items():
        ref = bound_spec.inference_checkpoint.model_copy(update={field: value})
        changed = bound_spec.model_copy(update={"inference_checkpoint": ref})
        assert inference_measurement_binding(changed).request_sha256 != old.request_sha256


def test_schema_preserves_unbound_then_bound_creation_but_rejects_other_phase(bound_spec):
    payload = bound_spec.model_dump()
    payload["inference_binding"] = None
    unbound = GpuMeasurementSpec.model_validate(payload)
    assert unbound.inference_checkpoint is not None
    payload["request"]["phase"] = "training"
    with pytest.raises(ValidationError, match="only valid for inference"):
        GpuMeasurementSpec.model_validate(payload)


def test_dispatch_without_binding_refuses_before_spawn(bound_spec, monkeypatch):
    from core.runtime_control.gpu_measurement_runner import run_prephase_measurement

    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_runner.subprocess.Popen",
        lambda *a, **k: pytest.fail("unbound checkpoint spawned"),
    )
    result = run_prephase_measurement(
        bound_spec.model_copy(update={"inference_binding": None}), device=DEVICE
    )
    assert result.worker_status is None  # Refused before any worker existed.
    assert "source binding" in result.detail
    assert not result.report_present


def assessment(verification, checkpoint):
    return assess_inference_measurement(
        request=verification.request,
        binding=verification.binding,
        run=verification.measurement,
        batch_size=2,
        max_batches=3,
        cap_mib=900,
        checkpoint=checkpoint,
    )


def test_positive_checkpoint_evidence_requires_receipt_and_covers_setup_peak(bound_spec):
    v = _verification()
    assert assessment(v, bound_spec.inference_checkpoint).disposition == "unavailable"
    run = v.measurement
    setup, inference = run.phases
    run = run.model_copy(
        update={
            "verified_checkpoint": bound_spec.inference_checkpoint,
            "phases": (setup.model_copy(update={"driver_tree_peak_mib": 890}), inference),
        }
    )
    result = assessment(v.model_copy(update={"measurement": run}), bound_spec.inference_checkpoint)
    assert result.disposition == "admitted"
    assert result.worker_requirement_mib == 890
    assert bound_spec.inference_checkpoint.checkpoint_sha256 in result.detail
    assert "trained-weight behavior" not in result.detail


def test_early_checkpoint_oom_preserves_raw_status_without_claiming_capacity(bound_spec):
    v = _verification()
    run = v.measurement.model_copy(update={"worker_status": "CUDA_OOM"})
    v = v.model_copy(update={"measurement": run})
    assert assessment(v, bound_spec.inference_checkpoint).disposition == "unavailable"
    assert v.measurement.worker_status == "CUDA_OOM"
    assert v.assessment[0] == "capacity_refused"  # Existing fresh-model classification.


def test_parent_preserves_worker_receipt(bound_spec, tmp_path):
    ref = bound_spec.inference_checkpoint.model_dump_json()
    binding = bound_spec.inference_binding.model_dump_json()
    body = f"""
report({{
    'label': spec['label'], 'request': spec['request'], 'status': 'WORKER_FAILURE',
    'device': spec['device'], 'detail': 'failed after successful checkpoint setup',
    'verified_checkpoint': __import__('json').loads({ref!r}),
    'inference_binding': __import__('json').loads({binding!r}),
}})
"""
    result = _run(tmp_path, body, [1], spec=bound_spec.model_dump())
    assert result.verified_checkpoint == bound_spec.inference_checkpoint
    assert result.worker_status == "WORKER_FAILURE"


@pytest.mark.parametrize("fault", ["missing_binding", "stale_binding"])
def test_worker_rejects_unbound_or_changed_reference_before_device_resolution(
    bound_spec, monkeypatch, fault
):
    if fault == "missing_binding":
        changed = bound_spec.model_copy(update={"inference_binding": None})
    else:
        ref = bound_spec.inference_checkpoint.model_copy(update={"checkpoint_sha256": "0" * 64})
        changed = bound_spec.model_copy(update={"inference_checkpoint": ref})
    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_worker_main.resolve_device",
        lambda spec: pytest.fail("unverified request reached device resolution"),
    )
    with pytest.raises(ValueError, match="binding"):
        measure(changed)


@pytest.mark.parametrize(
    "fault",
    [
        "setup",
        "hold",
        "peak",
        "data",
        "geometry",
        "grad",
        "device",
        "source",
        "cleanup",
        "checkpoint",
    ],
)
def test_checkpoint_receipt_cannot_replace_complete_workload_evidence(bound_spec, fault):
    v = _verification()
    run = v.measurement.model_copy(update={"verified_checkpoint": bound_spec.inference_checkpoint})
    setup, inference = run.phases
    if fault == "setup":
        run = run.model_copy(update={"phases": (inference,)})
    elif fault == "hold":
        run = run.model_copy(
            update={"phases": (setup.model_copy(update={"observed_reservations": ()}), inference)}
        )
    elif fault == "peak":
        run = run.model_copy(
            update={
                "phases": (
                    setup.model_copy(update={"allocator_reserved_peak_bytes": 999 * 1024**2}),
                    inference,
                )
            }
        )
    elif fault in {"data", "geometry"}:
        data = run.realism.inference_data
        if fault == "data":
            data = data.model_copy(update={"consumed_samples": 1})
        else:
            batches = list(data.batches)
            batches[0] = batches[0].model_copy(update={"output_shape": (1, 1)})
            data = data.model_copy(update={"batches": tuple(batches)})
        run = run.model_copy(
            update={"realism": run.realism.model_copy(update={"inference_data": data})}
        )
    elif fault == "grad":
        run = run.model_copy(
            update={"realism": run.realism.model_copy(update={"inference_grad_free": False})}
        )
    elif fault == "device":
        run = run.model_copy(update={"observed_device_uuid": "GPU-other"})
    elif fault == "source":
        run = run.model_copy(update={"inference_binding": None})
    elif fault == "cleanup":
        run = run.model_copy(
            update={"process": run.process.model_copy(update={"orphans_remaining": True})}
        )
    else:
        run = run.model_copy(
            update={
                "verified_checkpoint": bound_spec.inference_checkpoint.model_copy(
                    update={"experiment_id": "other"}
                )
            }
        )
    result = assessment(v.model_copy(update={"measurement": run}), bound_spec.inference_checkpoint)
    assert result.disposition == "unavailable"
    assert result.worker_requirement_mib is None


@pytest.mark.parametrize(
    "module",
    [
        "core/runtime_control/inference_checkpoint_reference.py",
        "core/runtime_control/inference_measurement_assessment.py",
        "core/stream_identity.py",
        "core/file_identity.py",
        "execute_tools/inference_checkpoint.py",
    ],
)
def test_extracted_checkpoint_sources_participate_in_assembly_identity(module, monkeypatch):
    from pathlib import Path

    from core.preflight_estimation import estimation_assembly_digest

    baseline = estimation_assembly_digest()
    original = Path.read_bytes

    def modified(path):
        payload = original(path)
        return payload + b"\n# changed implementation\n" if str(path).endswith(module) else payload

    monkeypatch.setattr(Path, "read_bytes", modified)
    assert estimation_assembly_digest() != baseline
