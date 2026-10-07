"""Task inference measurement must match evaluation inputs and consumption."""

import dataclasses

import pytest
import torch
from pydantic import BaseModel

from core.runtime_control.gpu_measurement_identity import build_planned_identity
from core.runtime_control.gpu_measurement_phases import run_measured_phases
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.gpu_measurement_worker_main import build_production_components
from core.runtime_control.gpu_requirement import CandidateMeasurementRequest
from execute_tools.task_probe_batch import task_inference_probe_batches
from tests.helpers.inference_measurement import evaluation_probe
from tests.helpers.step04a_fixtures import regressor_model_io


@pytest.mark.parametrize(
    "rows,batch,limit,counts", [(1, 4, 3, [1]), (7, 3, 3, [3, 3, 1]), (70, 3, 2, [3, 3])]
)
def test_real_evaluation_batches_are_bounded_without_padding(tmp_path, rows, batch, limit, counts):
    probe = evaluation_probe(tmp_path, rows=rows)
    with task_inference_probe_batches(probe, batch_size=batch, max_batches=limit) as workload:
        inputs = [pair[0] for pair in workload.loader]
        assert workload.dataset_samples == rows
        assert workload.selected_samples == sum(counts)
        assert workload.selected_batches == len(counts)
    assert [len(value) for value in inputs] == counts
    assert torch.cat(inputs).tolist() == (torch.arange(sum(counts) * 4).reshape(-1, 4) - 6).tolist()
    assert all(value.dtype == torch.int16 for value in inputs)


@pytest.mark.parametrize(
    "change,message",
    [
        ({"evaluation_scope_payload": None}, "explicit evaluation scope"),
        ({"semantic_fingerprint": "changed"}, "fingerprint mismatch"),
        ({"max_inference_batch_size": 1}, "batch ceiling changed"),
    ],
)
def test_unverifiable_evaluation_transport_is_refused(tmp_path, change, message):
    probe = evaluation_probe(tmp_path, rows=5).model_copy(update=change)
    with pytest.raises(ValueError, match=message):
        with task_inference_probe_batches(probe, batch_size=2, max_batches=2):
            pytest.fail("invalid transport was accepted")


def test_empty_dataset_is_not_a_successful_zero_memory_measurement(tmp_path):
    probe = evaluation_probe(tmp_path, rows=0)
    with pytest.raises(ValueError, match="nonempty"):
        with task_inference_probe_batches(probe, batch_size=2, max_batches=2):
            pytest.fail("empty workload was accepted")


@pytest.fixture
def inference_components(tmp_path, monkeypatch):
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY

    seen = []

    class Config(BaseModel):
        pass

    class Model(torch.nn.Module):
        def __init__(self, cfg, loss_type=None):
            super().__init__()
            self.scale = torch.nn.Parameter(torch.ones(1))

        def forward(self, inputs):
            assert inputs.dtype == torch.int64
            assert not self.training
            assert not torch.is_grad_enabled()
            seen.append(inputs.clone())
            return inputs.float() * self.scale

    monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, "bounded_eval_fixture", Config)
    monkeypatch.setitem(MODEL_REGISTRY, "bounded_eval_fixture", Model)
    probe = evaluation_probe(tmp_path, rows=7)
    identity = build_planned_identity(
        model_type="bounded_eval_fixture",
        model_config={},
        train_config={"batch_size": 1},
        inference_batch_size=3,
        segmentation_applicability="not_applicable",
    )
    spec = GpuMeasurementSpec(
        label="bounded-evaluation",
        request=CandidateMeasurementRequest(
            model_type="bounded_eval_fixture",
            planned_identity=identity,
            request_id="bounded-evaluation",
            device_uuid="GPU-test",
            phase="inference",
            deadline_seconds=30,
        ),
        train_config={"batch_size": 1},
        loss_config={"loss_type": "smooth_l1"},
        device="cpu",
        data_dir=str(tmp_path),
        task_probe_data=probe,
        model_io_contract=regressor_model_io(),
        inference_batch_size=3,
        result_path=str(tmp_path / "report.json"),
        journal_path=str(tmp_path / "journal.jsonl"),
        worker_memory_limit_bytes=1024**3,
    )

    def forbidden(*args, **kwargs):
        pytest.fail("inference constructed a training-only component")

    monkeypatch.setattr("execute_tools.train_engine_sandbox.build_training_optimizer", forbidden)
    monkeypatch.setattr("ml_models.loss_models_sandbox.get_criterion", forbidden)
    monkeypatch.setattr("execute_tools.task_probe_batch.load_task_probe_batch", forbidden)
    return build_production_components(spec), seen


def test_measured_forward_uses_evaluation_dtype_and_exact_tail(inference_components):
    builder, seen = inference_components
    outcome = run_measured_phases(
        build_components=builder, phase="inference", device="cpu", inference_batches=3
    )
    assert outcome.status == "COMPLETED", outcome.detail
    assert [len(value) for value in seen] == [3, 3, 1]
    assert seen[0][0].tolist() == [-6, -5, -4, -3]
    evidence = outcome.realism
    assert evidence.backward_calls == evidence.optimizer_steps == 0
    assert evidence.inference_grad_free
    assert evidence.inference_data.dataset_samples == evidence.inference_data.consumed_samples == 7
    assert [batch.shape for batch in evidence.inference_data.batches] == [(3, 4), (3, 4), (1, 4)]
    assert {batch.input_dtype for batch in evidence.inference_data.batches} == {"torch.int64"}


def test_missing_batch_source_cannot_complete(inference_components):
    builder, _ = inference_components
    outcome = run_measured_phases(
        build_components=lambda: dataclasses.replace(builder(), inference_batches_factory=None),
        phase="inference",
        device="cpu",
    )
    assert outcome.status == "WORKER_FAILURE"
    assert "evaluation batch source" in outcome.detail


def test_plugin_timeout_is_not_the_workers_budget(inference_components):
    builder, _ = inference_components

    def build():
        components = builder()

        def forward(inputs):
            raise TimeoutError("external data source did not answer")

        components.model.forward = forward
        return components

    outcome = run_measured_phases(build_components=build, phase="inference", device="cpu")
    assert outcome.status == "WORKER_FAILURE"
    assert "TimeoutError" in outcome.detail
    assert not outcome.detail.startswith("deadline:")


def test_absent_model_io_preserves_storage_dtype_at_measured_forward(inference_components):
    builder, seen = inference_components

    def build():
        components = builder()

        def forward(inputs):
            assert inputs.dtype == torch.int16
            seen.append(inputs.clone())
            return inputs.float()

        components.model.forward = forward
        return dataclasses.replace(components, inference_input_dtype=None)

    outcome = run_measured_phases(
        build_components=build, phase="inference", device="cpu", inference_batches=2
    )
    assert outcome.status == "COMPLETED", outcome.detail
    assert [len(value) for value in seen] == [3, 3]
    assert {batch.input_dtype for batch in outcome.realism.inference_data.batches} == {
        "torch.int16"
    }


def test_constructor_uses_task_cardinality_and_production_loss_convention(monkeypatch):
    from execute_tools.inference_model import construct_inference_model
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY
    from tests.helpers.step04a_fixtures import tidmad_model_io

    class Config(BaseModel):
        num_classes: int = 2

    class Model(torch.nn.Module):
        def __init__(self, cfg, loss_type="ce"):
            super().__init__()
            self.head = torch.nn.Linear(4, cfg.num_classes)
            self.loss_type = loss_type

    monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, "constructor_fixture", Config)
    monkeypatch.setitem(MODEL_REGISTRY, "constructor_fixture", Model)
    model, config = construct_inference_model(
        "constructor_fixture",
        {},
        model_io_contract=tidmad_model_io(num_classes=37),
        loss_type="smooth_l1",
    )
    assert config.num_classes == model.head.out_features == 37
    assert model.loss_type == "ce"


def test_production_and_measurement_share_values_lifetimes_and_batch_boundaries(
    tmp_path, monkeypatch, inference_components
):
    import weakref

    from execute_tools.generic_inference import run_generic_inference
    from execute_tools.task_data_path import DeliverableWriteRequest
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    builder, seen = inference_components
    probe = evaluation_probe(tmp_path / "production", rows=7, data_dir=str(tmp_path))
    composition = compose_run_task_bindings(probe.manifest_path)
    scope = composition.task_data_path.deserialize_scope(probe.evaluation_scope_payload)
    values = []
    events = []

    class Timing:
        def __init__(self, *args, **kwargs):
            pass

        def start_batch(self):
            events.append("start")
            return 0.0

        def finish_batch(self, started, count):
            events.append(("finish", count))

        def finish(self):
            events.append("complete")

    monkeypatch.setattr("execute_tools.generic_inference.InferenceRuntimeEvidence", Timing)

    def consume(outputs, request):
        for output in outputs:
            values.append(output.tolist())
            events.append("consume")

    monkeypatch.setattr(composition.task_data_path, "write_deliverable", consume)

    def watched_builder(lifetimes):
        components = builder()
        forward = components.model.forward
        references = []

        def watched(inputs):
            lifetimes.append(sum(reference() is not None for reference in references))
            output = forward(inputs)
            references.append(weakref.ref(output))
            return output

        components.model.forward = watched
        return components

    production_lifetimes = []
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        production = run_generic_inference(
            data_path=composition.task_data_path,
            task_scope=scope,
            model=watched_builder(production_lifetimes).model,
            device=torch.device("cpu"),
            data_dir=str(tmp_path),
            batch_size=3,
            input_dtype=torch.int64,
            write_request=DeliverableWriteRequest(
                output_dir=str(tmp_path),
                exp_id="test",
                run_name="test",
                model_type="bounded_eval_fixture",
            ),
            runtime_session=object(),
        )
    production_inputs = [value.tolist() for value in seen]
    seen.clear()
    measurement_lifetimes = []
    measured = run_measured_phases(
        build_components=lambda: watched_builder(measurement_lifetimes),
        phase="inference",
        device="cpu",
        inference_batches=3,
    )
    assert measured.status == "COMPLETED", measured.detail
    assert production_lifetimes == measurement_lifetimes == [0, 1, 1]
    assert [value.tolist() for value in seen] == production_inputs
    assert values == (torch.arange(28).reshape(7, 4) - 6).tolist()
    assert production.samples == measured.realism.inference_data.consumed_samples == 7
    assert production.batches == measured.realism.inference_batches == 3
    assert events == [
        "start",
        "consume",
        "consume",
        "consume",
        ("finish", 3),
        "start",
        "consume",
        "consume",
        "consume",
        ("finish", 3),
        "start",
        "consume",
        ("finish", 1),
        "start",
        "complete",
    ]
