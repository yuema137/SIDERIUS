"""Task fidelity and connected training evidence, without optimizer updates."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import torch
from torch import nn
from torch.utils.data import TensorDataset

from core.runtime_control.gpu_measurement_phases import CandidateComponents, run_measured_phases
from core.runtime_control.gpu_measurement_spec import (
    GpuMeasurementSpec,
    TrainingDataCoverage,
    TrainingStepEvidence,
)
from core.runtime_control.gpu_training_components import prepare_task_training_components
from core.runtime_control.inference_measurement_binding import MeasurementSources
from core.runtime_control.training_measurement_binding import bind_training_measurement
from execute_tools.task_data_path import EpochSamplingParams, TaskProbeDataSpec
from ml_models.models_format_sandbox import LossConfig, TrainConfig
from tests.unit.core.test_gpu_measurement_runner import _spec


@pytest.fixture(autouse=True)
def forbid_real_optimizer_updates(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("this cohort permits only non-updating recording optimizers")

    for optimizer in (torch.optim.Adam, torch.optim.AdamW, torch.optim.SGD):
        monkeypatch.setattr(optimizer, "step", forbidden)


@pytest.fixture
def bound_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.runtime_control.training_measurement_binding.measurement_sources",
        lambda: MeasurementSources(
            assembly_sha256="a" * 64, plugin_sources_sha256="b" * 64, runtime_sha256="c" * 64
        ),
    )
    reference = TaskProbeDataSpec(
        manifest_path=str(tmp_path / "manifest.yaml"),
        semantic_fingerprint="d" * 64,
        training_scope_payload='{"selected":"train"}',
        sampling=EpochSamplingParams(
            data_dir=str(tmp_path), epoch_seed=19, train_portion=0.25, max_samples=11
        ),
        segmentation_applicability="not_applicable",
    )
    spec = _spec(tmp_path).model_copy(
        update={
            "device": "cpu",
            "data_dir": str(tmp_path),
            "task_probe_data": reference,
            "train_config": {"batch_size": 4, "drop_last": False},
            "loss_config": {"loss_type": "smooth_l1"},
            "sampler_ready_path": str(tmp_path / "ready"),
            "phase_complete_path": str(tmp_path / "work"),
            "setup_complete_path": str(tmp_path / "setup"),
            "reservation_ack_path": str(tmp_path / "ack"),
        }
    )
    from core.runtime_control.gpu_measurement_identity import build_planned_identity

    spec = spec.model_copy(
        update={
            "request": spec.request.model_copy(
                update={
                    "planned_identity": build_planned_identity(
                        model_type="punet",
                        model_config={},
                        train_config=spec.train_config,
                        segmentation_applicability="not_applicable",
                    )
                }
            )
        }
    )
    return bind_training_measurement(spec)


@pytest.fixture
def task_source(monkeypatch):
    active = []
    calls = []
    rows = [1]

    class Data:
        def training_dataset(self, scope, sampling):
            assert active == [True] and scope == "authorized-training"
            calls.append(sampling)
            count = 8 if sampling.train_portion == 1 else rows[0]
            return TensorDataset(
                torch.arange(count * 2).reshape(count, 2).double(),
                torch.arange(count, dtype=torch.float32).reshape(count, 1),
            )

    composition = SimpleNamespace(semantic_fingerprint="d" * 64, task_data_path=Data())
    monkeypatch.setattr(
        "execute_tools.task_probe_batch.compose_run_task_bindings", lambda path: composition
    )

    @contextmanager
    def bind(comp, *, physical_data_root):
        assert comp is composition
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    monkeypatch.setattr("execute_tools.task_probe_batch.bind_run_task_composition", bind)
    monkeypatch.setattr(
        "execute_tools.task_probe_batch.resolve_task_scope_capability",
        lambda path: SimpleNamespace(deserialize_scope=lambda payload: "authorized-training"),
    )
    monkeypatch.setattr("ml_models.plugin_loader.get_output_type", lambda name: "regressor")
    return rows, calls, active


@pytest.mark.parametrize(
    "rows,drop_last",
    [(1, False), (3, False), (4, False), (9, False), (1, True), (4, True), (9, True)],
)
def test_real_tail_geometry_and_authorization_lifetime(bound_spec, task_source, rows, drop_last):
    sizes, calls, active = task_source
    sizes[0] = rows
    config = TrainConfig(batch_size=4, drop_last=drop_last)
    if drop_last and rows < 4:
        with pytest.raises(ValueError, match="one full resource probe batch"):
            prepare_task_training_components(
                bound_spec,
                model=nn.Linear(2, 1),
                train_cfg=config,
                loss_cfg=LossConfig(loss_type="smooth_l1"),
                input_dtype=torch.float32,
                deadline_at=None,
            )
    else:
        result = prepare_task_training_components(
            bound_spec,
            model=nn.Linear(2, 1),
            train_cfg=config,
            loss_cfg=LossConfig(loss_type="smooth_l1"),
            input_dtype=torch.float32,
            deadline_at=None,
        )
        assert result.coverage.observed_batch_rows == min(rows, 4)
        assert result.coverage.materialized_dataset_rows == rows
        assert result.coverage.configured_batch_size == 4
        assert result.model_input.dtype == torch.float32
        assert result.coverage.storage_input_dtype == "torch.float64"
        assert result.standardization is None
    assert calls == [bound_spec.task_probe_data.sampling]
    assert not active


def test_enabled_transform_fits_full_authorized_pool_then_real_tail(bound_spec, task_source):
    _, calls, active = task_source
    model = nn.Linear(2, 1)
    result = prepare_task_training_components(
        bound_spec,
        model=model,
        train_cfg=TrainConfig(
            batch_size=4, drop_last=False, target_standardization="training_pool_global"
        ),
        loss_cfg=LossConfig(loss_type="smooth_l1"),
        input_dtype=torch.float32,
        deadline_at=None,
    )
    assert [request.train_portion for request in calls] == [1.0, 0.25]
    assert all(request.epoch_seed == 19 and request.max_samples == 11 for request in calls)
    assert result.standardization.mean == 3.5
    assert result.standardization.scale == pytest.approx((63 / 12) ** 0.5)
    assert result.standardization.training_rows == 8
    assert result.coverage.observed_batch_rows == 1
    assert {id(p) for p in result.model.parameters()} == {id(p) for p in model.parameters()}
    assert {id(p) for g in result.optimizer.param_groups for p in g["params"]} == {
        id(p) for p in model.parameters()
    }
    assert not active


def test_fit_deadline_refuses_without_prefix_statistics_and_resets_binding(
    bound_spec, task_source, monkeypatch
):
    import core.runtime_control.gpu_training_components as owner

    times = iter([0, 0, 0, 0, 0, 20])
    monkeypatch.setattr(owner.time, "monotonic", lambda: next(times, 20))
    with pytest.raises(owner.TrainingPreparationDeadline):
        prepare_task_training_components(
            bound_spec,
            model=nn.Linear(2, 1),
            train_cfg=TrainConfig(
                batch_size=4, drop_last=False, target_standardization="training_pool_global"
            ),
            loss_cfg=LossConfig(loss_type="smooth_l1"),
            input_dtype=torch.float32,
            deadline_at=10,
        )
    assert [request.train_portion for request in task_source[1]] == [1.0]
    assert not task_source[2]


class RecordingOptimizer:
    def __init__(self, model):
        self.param_groups = [{"params": list(model.parameters())}]
        self.calls = 0

    def zero_grad(self, *, set_to_none):
        assert set_to_none
        for group in self.param_groups:
            for parameter in group["params"]:
                parameter.grad = None

    def step(self):
        self.calls += 1


def coverage(spec):
    return TrainingDataCoverage(
        configured_batch_size=4,
        materialized_dataset_rows=1,
        observed_batch_rows=1,
        input_shape=(1, 2),
        target_shape=(1, 1),
        storage_input_dtype="torch.float32",
        model_input_dtype="torch.float32",
        target_dtype="torch.float32",
        sampling=spec.task_probe_data.sampling,
    )


@pytest.mark.parametrize(
    "case",
    ["zero_gradient", "unused_first", "independent_leaf", "wrong_optimizer", "stale_gradient"],
)
def test_completed_steps_require_connection_not_parameter_motion(bound_spec, case):
    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            self.unused = nn.Parameter(torch.ones(1))
            self.layer = nn.Linear(2, 1)

        def forward(self, inputs):
            return self.layer(inputs)

    model = Model()
    optimizer = RecordingOptimizer(nn.Linear(2, 1) if case == "wrong_optimizer" else model)
    if case == "stale_gradient":
        model.unused.grad = torch.ones_like(model.unused)
        optimizer.zero_grad = lambda **kwargs: None

    def criterion(output, target):
        if case == "independent_leaf":
            return torch.tensor(1.0, requires_grad=True)
        return (output * 0).sum() if case == "zero_gradient" else output.square().sum()

    components = CandidateComponents(
        model=model,
        model_input=torch.ones(1, 2),
        loss_target=torch.ones(1, 1),
        optimizer=optimizer,
        loss_fn=criterion,
        training_data=coverage(bound_spec),
    )
    result = run_measured_phases(
        build_components=lambda: components, phase="training", device="cpu", training_steps=2
    )
    if case in {"zero_gradient", "unused_first"}:
        assert result.status == "COMPLETED"
        assert result.realism.training_steps.connected_backward_calls == 2
        assert result.realism.optimizer_steps == optimizer.calls == 2
        assert result.realism.parameter_update_verified is False
        assert result.realism.training_data.observed_output_shape == (1, 1)
    else:
        assert result.status == "WORKER_FAILURE"
        assert optimizer.calls == 0


def assessment_run(spec):
    from core.runtime_control.gpu_measurement_spec import RealismEvidence
    from core.runtime_control.process_group import GroupObservation, RssObservation
    from tests.helpers.inference_verification import _verification

    old = _verification().measurement
    setup = old.phases[0].model_copy(update={"driver_tree_peak_mib": 900})
    work = old.phases[1].model_copy(
        update={"phase": "training", "units_executed": 3, "driver_tree_peak_mib": 700}
    )
    phases = []
    for phase in (setup, work):
        phases.append(
            phase.model_copy(
                update={
                    "observed_reservations": tuple(
                        hold.model_copy(
                            update={"hold_id": f"{spec.request.request_id}:{phase.phase}:{i}"}
                        )
                        for i, hold in enumerate(phase.observed_reservations)
                    )
                }
            )
        )
    from core.runtime_control.gpu_measurement_identity import build_realized_identity

    identity = build_realized_identity(
        model_type="punet",
        optimizer_type="adamw",
        seg_size=None,
        batch_size=4,
        precision="float32",
        parameter_count=100,
        trainable_parameter_count=100,
        segmentation_applicability="not_applicable",
    )
    return old.model_copy(
        update={
            "request": spec.request,
            "training_binding": spec.training_binding,
            "inference_binding": None,
            "observed_device_uuid": spec.request.device_uuid,
            "reported_request_id": spec.request.request_id,
            "realized_identity": identity,
            "phases": tuple(phases),
            "process": old.process.model_copy(
                update={"final_group_observation": GroupObservation(status="absent")}
            ),
            "host_memory": old.host_memory.model_copy(
                update={
                    "observations_complete": True,
                    "latest_observation": RssObservation(status="complete", sampled_bytes=1000000),
                }
            ),
            "realism": RealismEvidence(
                forward_calls=3,
                backward_calls=3,
                optimizer_steps=3,
                training_steps=TrainingStepEvidence(
                    optimizer_matches_model_parameters=True, connected_backward_calls=3
                ),
                training_data=coverage(spec).model_copy(update={"observed_output_shape": (1, 1)}),
            ),
        }
    )


def test_whole_worker_peak_and_missing_evidence_refusals(bound_spec):
    from core.runtime_control.process_group import GroupObservation
    from core.runtime_control.training_measurement_assessment import assess_training_measurement

    run = assessment_run(bound_spec)
    result = assess_training_measurement(bound_spec, run, cap_mib=900)
    assert result.disposition == "admitted", result.detail
    assert result.worker_requirement_mib == 900
    assert (
        assess_training_measurement(bound_spec, run, cap_mib=899).disposition == "capacity_refused"
    )
    for changed in (
        run.model_copy(
            update={
                "host_memory": run.host_memory.model_copy(update={"observations_complete": False})
            }
        ),
        run.model_copy(
            update={
                "process": run.process.model_copy(
                    update={"final_group_observation": GroupObservation(status="unknown")}
                )
            }
        ),
        run.model_copy(update={"realism": run.realism.model_copy(update={"training_steps": None})}),
        run.model_copy(update={"training_binding": None}),
        run.model_copy(update={"worker_status": "CUDA_OOM"}),
    ):
        refusal = assess_training_measurement(bound_spec, changed, cap_mib=900)
        assert refusal.disposition == "unavailable"
        assert refusal.worker_requirement_mib is None


def test_worker_rejects_stale_binding_before_device_resolution(bound_spec, monkeypatch):
    from core.runtime_control.gpu_measurement_worker_main import measure

    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_worker_main.resolve_device",
        lambda spec: pytest.fail("stale request reached hardware"),
    )
    changed = bound_spec.model_copy(update={"train_config": {"batch_size": 9}})
    with pytest.raises(ValueError, match="binding mismatch"):
        measure(changed)


@pytest.mark.parametrize("bound", [True, False])
def test_actual_builder_and_worker_propagate_fit_receipt(
    bound_spec, task_source, monkeypatch, bound
):
    from pydantic import BaseModel

    from core.runtime_control.gpu_measurement_worker_main import measure
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY

    class Config(BaseModel):
        model_type: str = "synthetic_training"

    monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, "synthetic_training", Config)
    monkeypatch.setitem(MODEL_REGISTRY, "synthetic_training", lambda config: nn.Linear(2, 1))
    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_worker_main.resolve_device",
        lambda spec: SimpleNamespace(
            status=None, observed_uuid=spec.request.device_uuid, device_name="synthetic"
        ),
    )
    spec = bound_spec.model_copy(
        update={
            "request": bound_spec.request.model_copy(update={"model_type": "synthetic_training"}),
            "model_config_payload": {},
            "train_config": {
                "batch_size": 4,
                "drop_last": False,
                "target_standardization": "training_pool_global",
            },
        }
    )
    from agent.schemas.model_io_contract import (
        Dimension,
        DtypeAdmissibility,
        ModelIOContract,
        TensorAxis,
        TensorContract,
    )

    contract = ModelIOContract(
        input=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B")),
                TensorAxis(dimension=Dimension(fixed=2)),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
        output=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B")),
                TensorAxis(dimension=Dimension(fixed=1)),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
    )
    spec = bind_training_measurement(spec.model_copy(update={"model_io_contract": contract}))
    if not bound:
        spec = spec.model_copy(update={"training_binding": None})
    import time

    from core.runtime_control.gpu_measurement_hold import ObservedReservation

    def observer(**kwargs):
        sequence = 0

        def hold():
            nonlocal sequence
            now = time.time()
            result = ObservedReservation(
                hold_id=f"{spec.request.request_id}:{kwargs['phase']}:{sequence}",
                started_at=now,
                ended_at=now,
                reserved_before_bytes=0,
                reserved_after_bytes=0,
                acknowledged=True,
                driver_samples=3,
                required_samples=3,
            )
            sequence += 1
            return result

        return hold

    monkeypatch.setattr("core.runtime_control.gpu_measurement_hold.reservation_observer", observer)
    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_phases.reservation_peak_bytes", lambda device: 0
    )
    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_worker_main._marker_waiter",
        lambda *args: lambda: True,
    )
    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_worker_main._marker_probe", lambda *args: lambda: True
    )
    monkeypatch.setattr(
        "execute_tools.train_engine_sandbox.build_training_optimizer",
        lambda model, cfg: RecordingOptimizer(model),
    )
    result = measure(spec)
    assert result.status == "COMPLETED", result.detail
    assert result.training_binding == spec.training_binding
    assert result.realism.training_standardization.mean == 3.5
    if bound:
        assert result.realism.training_data.observed_batch_rows == 1
        assert result.realism.training_steps.connected_backward_calls == spec.training_steps
        assert len(result.phases[0].observed_reservations) == 1
        assert len(result.phases[1].observed_reservations) == spec.training_steps
    else:
        assert result.realism.training_data is None and result.realism.training_steps is None
        assert all(not phase.observed_reservations for phase in result.phases)
    assert not result.realism.parameter_update_verified


@pytest.mark.parametrize("status", ["complete", "unavailable"])
def test_real_cpu_worker_cleanup_and_rss_evidence(bound_spec, tmp_path, monkeypatch, status):
    from core.runtime_control.gpu_measurement_runner import run_prephase_measurement
    from core.runtime_control.process_group import RssObservation
    from tests.unit.core.test_gpu_measurement_runner import DEVICE, _Driver, _fake_worker

    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_runner.observe_tree_rss",
        lambda pgid: RssObservation(status=status, sampled_bytes=100),
    )
    run = run_prephase_measurement(
        bound_spec,
        device=DEVICE,
        command=_fake_worker(tmp_path, "time.sleep(0.06)"),
        device_sampler=_Driver([100]),
        poll_seconds=0.005,
        grace_seconds=0.3,
    )
    assert run.process.final_group_observation.status == "absent"
    assert run.host_memory.observations_complete is (status == "complete")
    if status == "unavailable":
        assert run.process.group_cleanup_required
        assert "training_host_monitoring_unavailable" in run.detail
    else:
        assert run.process.exit_code == 0 and not run.process.group_cleanup_required


def test_sampler_exception_keeps_primary_and_cleans_owned_child(bound_spec, tmp_path, monkeypatch):
    from core.runtime_control.gpu_measurement_runner import run_prephase_measurement
    from core.runtime_control.process_group import RssObservation
    from tests.unit.core.test_gpu_measurement_runner import DEVICE, _fake_worker

    error = RuntimeError("synthetic sampler error")
    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_runner.observe_tree_rss",
        lambda pgid: RssObservation(status="complete", sampled_bytes=100),
    )

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("core.runtime_control.gpu_measurement_runner.GpuTreeSampler.poll", fail)
    with pytest.raises(RuntimeError) as caught:
        run_prephase_measurement(
            bound_spec,
            device=DEVICE,
            command=_fake_worker(tmp_path, "time.sleep(10)"),
            device_sampler=fail,
            poll_seconds=0.005,
            grace_seconds=0.3,
        )
    assert caught.value is error
    assert error.measurement_group_cleanup.final.status == "absent"


def test_bound_worker_deadline_retains_timeout_and_owned_cleanup(bound_spec, tmp_path, monkeypatch):
    from core.runtime_control.gpu_measurement_runner import run_prephase_measurement
    from core.runtime_control.process_group import RssObservation
    from tests.unit.core.test_gpu_measurement_runner import DEVICE, _Driver, _fake_worker

    monkeypatch.setattr(
        "core.runtime_control.gpu_measurement_runner.observe_tree_rss",
        lambda pgid: RssObservation(status="complete", sampled_bytes=100),
    )
    spec = bind_training_measurement(
        bound_spec.model_copy(
            update={"request": bound_spec.request.model_copy(update={"deadline_seconds": 0.05})}
        )
    )
    run = run_prephase_measurement(
        spec,
        device=DEVICE,
        command=_fake_worker(tmp_path, "time.sleep(10)"),
        device_sampler=_Driver([100]),
        poll_seconds=0.005,
        grace_seconds=0.2,
    )
    assert run.deadline.reached_deadline
    assert run.process.group_cleanup_required
    assert run.process.final_group_observation.status == "absent"
    assert run.worker_status is None  # No invented CUDA OOM or model failure.


def test_preprocessing_and_assessment_sources_affect_estimation_identity(monkeypatch):
    from pathlib import Path

    from core.preflight_estimation import estimation_assembly_digest

    baseline = estimation_assembly_digest()
    original = Path.read_bytes
    for owner in (
        "execute_tools/target_standardization.py",
        "core/runtime_control/training_measurement_assessment.py",
    ):
        with monkeypatch.context() as patch:
            patch.setattr(
                Path,
                "read_bytes",
                lambda path, selected=owner: (
                    original(path) + b"\n# altered execution authority\n"
                    if str(path).endswith(selected)
                    else original(path)
                ),
            )
            assert estimation_assembly_digest() != baseline
