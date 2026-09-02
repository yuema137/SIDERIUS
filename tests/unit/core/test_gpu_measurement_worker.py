"""The worker measures the real candidate on the requested device, or says why not.

V20 PR C2 / C2-2.

Three refusals carry most of the weight here, because each of them would
otherwise produce a number that LOOKS like a measurement:

* **no CPU fallback** -- a CPU figure wearing a GPU requirement's
  provenance under-states by the whole device footprint;
* **no synthetic data** -- a fabricated batch measures a candidate nobody
  will run (F-1a);
* **no unverified device** -- answering about the wrong GPU is worse than
  not answering, which is the rule `gpu_accounting` already follows.

The candidate here is a real `nn.Module` registered through the plugin
registries the production builder actually reads, so `build_production_components`
runs unmodified. Patching the builder itself would test nothing: the
question is whether the production path constructs what the trainer
constructs.
"""

from __future__ import annotations

import json

import pytest
import torch
from pydantic import BaseModel, ValidationError
from torch import nn

from core.runtime_control.gpu_measurement_identity import (
    build_planned_identity,
    build_realized_identity,
)
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.gpu_measurement_worker_main import (
    _normalize_uuid,
    build_production_components,
    main,
    measure,
    resolve_device,
    validate_candidate_configs,
)
from core.runtime_control.gpu_requirement import CandidateMeasurementRequest
from execute_tools.task_data_path import EpochSamplingParams, TaskProbeDataSpec
from tests.helpers.two_family_profile import make_two_family_profile

MODEL_TYPE = "c2probe"
UUID = "GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef"
WORKER_PROFILE = make_two_family_profile()


class _ProbeConfig(BaseModel):
    segmentation_size: int = 8


class _ProbeModel(nn.Module):
    """[B, T] int -> [B, 256, T] float: the forward contract, minimally."""

    def __init__(self, cfg, loss_type: str | None = None) -> None:
        super().__init__()
        self.loss_type = loss_type
        self.embed = nn.Embedding(256, 4)
        self.head = nn.Linear(4, 256)

    def forward(self, x):
        return self.head(self.embed(x.long())).permute(0, 2, 1)


@pytest.fixture
def registered(monkeypatch, tmp_path):
    """Register the candidate where the PRODUCTION builder looks for it."""
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY

    monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, MODEL_TYPE, _ProbeConfig)
    monkeypatch.setitem(MODEL_REGISTRY, MODEL_TYPE, _ProbeModel)

    _patch_bounded_loader(monkeypatch)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return str(data_dir)


def _patch_bounded_loader(monkeypatch):
    """Stand in for the BOUNDED loader -- the one production now calls.

    Patching anything else here would leave these tests green while the
    worker used a different path entirely, which is how a fixture stops
    describing production.
    """
    import core.runtime_control.gpu_measurement_data as data_mod

    def _bounded(*, data_dir, batch_size, segment_length, profile=None):
        assert profile is not None, "the worker omitted its declared dataset profile"
        channels = profile.to_wire()["channels"]
        return data_mod.BoundedProbeBatch(
            tensor=torch.randint(0, 256, (batch_size, segment_length), dtype=torch.long),
            evidence=data_mod.BoundedReadEvidence(
                source_file="fixture.h5",
                channel=channels["input_channel"],
                segment_count=batch_size,
                segment_length=segment_length,
                first_sample=0,
                last_sample=batch_size * segment_length,
                bytes_read=batch_size * segment_length,
                file_sample_count=batch_size * segment_length * 10,
            ),
        )

    monkeypatch.setattr(data_mod, "load_bounded_probe_batch", _bounded)


def _spec(tmp_path, data_dir: str | None, **over) -> GpuMeasurementSpec:
    payload = dict(
        label="c2-worker-test",
        request=CandidateMeasurementRequest(
            model_type=MODEL_TYPE,
            planned_identity=build_planned_identity(
                model_type="punet", model_config={}, train_config={}
            ),
            request_id="req-01234567",
            device_uuid=UUID,
            phase="training",
            deadline_seconds=120.0,
        ),
        model_config_payload={"segmentation_size": 8},
        train_config={"batch_size": 2, "optimizer_type": "adamw"},
        loss_config={"loss_type": "focal"},
        device="cpu",
        data_dir=data_dir,
        training_steps=2,
        inference_batches=2,
        result_path=str(tmp_path / "result.json"),
        journal_path=str(tmp_path / "phases.ndjson"),
        worker_memory_limit_bytes=8 * 1024**3,
        dataset_profile=WORKER_PROFILE,
    )
    payload.update(over)
    return GpuMeasurementSpec(**payload)  # type: ignore[arg-type]


class TestTheSpecRefusesAnUnmeasurableRequest:
    def test_setup_may_not_be_the_target_phase(self, tmp_path):
        """A spec asking only for setup produces a report that can never be
        admitted -- discovered after the worker has already run."""
        with pytest.raises(ValidationError, match="may not be 'setup'"):
            _spec(
                tmp_path,
                None,
                request=CandidateMeasurementRequest(
                    model_type=MODEL_TYPE,
                    planned_identity=build_planned_identity(
                        model_type="punet", model_config={}, train_config={}
                    ),
                    request_id="req-01234567",
                    device_uuid=UUID,
                    phase="setup",
                    deadline_seconds=60.0,
                ),
            )

    def test_the_soft_budget_must_sit_below_the_hard_deadline(self, tmp_path):
        """At or above it, the worker is always killed instead of
        reporting, and the partial evidence is lost every time."""
        with pytest.raises(ValidationError, match="never fire"):
            _spec(tmp_path, None, soft_deadline_seconds=120.0)

    def test_a_soft_budget_below_the_deadline_is_accepted(self, tmp_path):
        assert _spec(tmp_path, None, soft_deadline_seconds=90.0).soft_deadline_seconds == 90.0


class TestThereIsNoCpuFallback:
    def test_a_cuda_request_without_cuda_refuses_rather_than_measuring(
        self, tmp_path, registered, monkeypatch
    ):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        report = measure(_spec(tmp_path, registered, device="cuda"))
        assert report.status == "DEVICE_UNAVAILABLE"
        assert "does not fall back to the CPU" in report.detail
        assert report.phases == (), "nothing may be measured on a device we do not have"

    def test_the_refusal_carries_no_device_uuid(self, tmp_path, registered, monkeypatch):
        """A `None` UUID cannot satisfy the authority contract's match, so
        this result can never reach PR B as a requirement."""
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        assert measure(_spec(tmp_path, registered, device="cuda")).observed_device_uuid is None


class TestComposedTaskBatch:
    def test_worker_uses_task_data_path_instead_of_physical_array_loader(
        self, tmp_path, registered, monkeypatch
    ):
        """Dropping this branch makes generic Formal admission policy-unavailable."""
        import execute_tools.task_probe_batch as task_probe_module

        calls: list[int] = []

        def _task_batch(_reference, batch_size):
            calls.append(batch_size)
            batch = torch.randint(0, 256, (batch_size, 8), dtype=torch.long)
            return batch, batch.clone()

        monkeypatch.setattr(task_probe_module, "load_task_probe_batch", _task_batch)
        task_ref = TaskProbeDataSpec(
            manifest_path="/task/composition.yaml",
            semantic_fingerprint="a" * 64,
            training_scope_payload='{"kind":"synthetic"}',
            sampling=EpochSamplingParams(data_dir=registered),
        )

        components = build_production_components(
            _spec(tmp_path, registered, task_probe_data=task_ref)
        )()

        assert calls == [2]
        assert tuple(components.model_input.shape) == (2, 8)
        assert components.bounded_read == {
            "source": "task_data_path",
            "semantic_fingerprint": "a" * 64,
        }


class TestTheDeviceIsVerifiedNotAssumed:
    def test_a_different_gpu_is_refused(self, tmp_path, registered, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(
            torch.cuda,
            "get_device_properties",
            lambda _i: type("P", (), {"uuid": "aaaaaaaa-0000-0000-0000-000000000000", "name": "X"}),
        )
        resolution = resolve_device(_spec(tmp_path, registered, device="cuda"))
        assert resolution.status == "DEVICE_MISMATCH"
        assert "but the request names" in resolution.detail

    def test_an_unreadable_uuid_fails_closed(self, tmp_path, registered, monkeypatch):
        """Fail closed in BOTH directions: an unverifiable device is
        refused, never assumed to be the right one."""
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(
            torch.cuda, "get_device_properties", lambda _i: type("P", (), {"name": "X"})
        )
        assert resolve_device(_spec(tmp_path, registered, device="cuda")).status == (
            "DEVICE_MISMATCH"
        )

    def test_the_matching_gpu_is_accepted(self, tmp_path, registered, monkeypatch):
        """Positive control: the guard must reject the wrong card, not
        every card."""
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(
            torch.cuda,
            "get_device_properties",
            lambda _i: type("P", (), {"uuid": UUID.removeprefix("GPU-"), "name": "RTX 5090"}),
        )
        resolution = resolve_device(_spec(tmp_path, registered, device="cuda"))
        assert resolution.status is None
        assert resolution.observed_uuid == UUID

    def test_the_driver_prefix_is_normalized_once(self):
        """torch returns a bare `uuid.UUID`; nvidia-smi and `DeviceIdentity`
        use the `GPU-` form. A comparison failing on punctuation would be
        reported as a wrong-device refusal."""
        assert _normalize_uuid("c30b6678-ff2a") == "GPU-c30b6678-ff2a"
        assert _normalize_uuid("GPU-c30b6678-ff2a") == "GPU-c30b6678-ff2a"


class TestThereIsNoSyntheticData:
    def test_a_missing_dataset_root_is_reported_not_fabricated(self, tmp_path, registered):
        spec = _spec(tmp_path, None)
        report = measure(spec)
        assert report.status == "WORKER_FAILURE"
        assert "no silent synthetic fallback" in report.detail

    def test_an_absent_directory_is_refused(self, tmp_path, registered):
        report = measure(_spec(tmp_path, str(tmp_path / "not-there")))
        assert report.status == "WORKER_FAILURE"
        assert "dataset directory unavailable" in report.detail


class TestTheConfigurationIsJudgedBeforeTheMeasurement:
    def test_an_invalid_config_is_rejected_not_measured(self, tmp_path, registered):
        """A schema rejection is a fact about the configuration. Reporting
        it as a failed measurement would blame the candidate for something
        that was never run."""
        report = measure(_spec(tmp_path, registered, train_config={"lr": 99.0}))
        assert report.status == "CONFIG_REJECTED"
        assert report.phases == ()

    def test_a_valid_config_passes_validation(self, tmp_path, registered):
        assert validate_candidate_configs(_spec(tmp_path, registered)) is None


class TestTheBuilderConstructsWhatTheTrainerConstructs:
    @pytest.mark.parametrize(
        "optimizer_type,expected",
        [("adamw", torch.optim.AdamW), ("adam", torch.optim.Adam), ("sgd", torch.optim.SGD)],
    )
    def test_the_optimizer_is_productions_own(self, tmp_path, registered, optimizer_type, expected):
        """Adam-family moments are a first-order term in the memory being
        measured. Measuring SGD for a run that trains with AdamW
        under-states by two parameter tensors."""
        spec = _spec(tmp_path, registered, train_config={"optimizer_type": optimizer_type})
        assert type(build_production_components(spec)().optimizer) is expected

    def test_the_input_and_target_are_distinct_tensors(self, tmp_path, registered):
        """The trainer holds an input tensor AND a target tensor. Reusing
        one object for both leaves the measurement one resident tensor
        short of the process it describes."""
        components = build_production_components(_spec(tmp_path, registered))()
        assert components.model_input is not components.loss_target

    def test_the_target_dtype_comes_from_the_single_source_of_truth(self, tmp_path, registered):
        components = build_production_components(_spec(tmp_path, registered))()
        assert components.loss_target.dtype is torch.long

    def test_fcnet_receives_the_loss_type_the_trainer_passes(self, tmp_path, monkeypatch):
        """`train_engine_sandbox` constructs fcnet as
        `model_class(cfg, loss_type=...)`; `probe_production.py:128` does
        not, and a candidate that needs it would fail to construct."""
        from ml_models.models_sandbox import MODEL_REGISTRY

        # `get_config_class` resolves built-ins before plugins, so fcnet
        # keeps its real `AEConfig`; only the module is substituted.
        monkeypatch.setitem(MODEL_REGISTRY, "fcnet", _ProbeModel)
        _patch_bounded_loader(monkeypatch)
        data_dir = tmp_path / "d"
        data_dir.mkdir()
        spec = _spec(
            tmp_path,
            str(data_dir),
            request=CandidateMeasurementRequest(
                model_type="fcnet",
                planned_identity=build_planned_identity(
                    model_type="punet", model_config={}, train_config={}
                ),
                request_id="req-01234567",
                device_uuid=UUID,
                phase="training",
                deadline_seconds=60.0,
            ),
            loss_config={"loss_type": "smooth_l1"},
            model_config_payload={"segmentation_size": 1000},
        )
        assert build_production_components(spec)().model.loss_type == "smooth_l1"

    def test_the_parameter_count_is_realized_not_estimated(self, tmp_path, registered):
        """F-1b: recomputed from the instantiated module, never the LLM's
        number."""
        components = build_production_components(_spec(tmp_path, registered))()
        expected = sum(p.numel() for p in components.model.parameters())
        assert components.parameter_count == expected


class TestTheWorkerEndToEnd:
    def test_a_complete_run_reports_a_real_training_phase(self, tmp_path, registered):
        report = measure(_spec(tmp_path, registered))
        assert report.status == "COMPLETED"
        assert report.realism.parameter_update_verified is True
        training = report.phase_report("training")
        assert training is not None
        # D-C2-13: the count is steps x repetitions, not a fixed number.
        # This candidate is microseconds long against the cadence, so the
        # phase repeats to become observable at all.
        assert report.realism.backward_calls == 2 * training.repetitions
        assert report.realism.backward_calls == report.realism.optimizer_steps

    def test_the_request_comes_back_unchanged(self, tmp_path, registered):
        """A report about a different candidate is not a weaker
        measurement, it is a different one -- so the parent must be able to
        check that this answers the question it asked."""
        spec = _spec(tmp_path, registered)
        assert measure(spec).request == spec.request

    def test_main_writes_the_report_where_the_parent_will_read_it(self, tmp_path, registered):
        spec = _spec(tmp_path, registered)
        (tmp_path / "spec.json").write_text(spec.model_dump_json())
        assert main([str(tmp_path / "spec.json")]) == 0
        written = json.loads((tmp_path / "result.json").read_text())
        assert written["status"] == "COMPLETED"
        reps = written["phases"][-1]["repetitions"]
        assert written["realism"]["optimizer_steps"] == 2 * reps

    def test_the_journal_records_the_phase_boundaries(self, tmp_path, registered):
        spec = _spec(tmp_path, registered)
        measure(spec)
        events = [
            json.loads(line) for line in (tmp_path / "phases.ndjson").read_text().splitlines()
        ]
        assert [e["phase"] for e in events] == ["setup", "setup", "training", "training"]


class TestTheWorkerConsultsNoLanguageModel:
    def test_no_llm_is_constructed_during_a_measurement(self, tmp_path, registered, monkeypatch):
        """This runs on the critical path of every formal launch. A model
        call here would put an external service between a candidate and its
        GPU, and a quota stall would look like a hung measurement."""
        import agent.llm_bridge as llm_bridge

        def forbidden(*_a, **_k):
            raise AssertionError("the GPU measurement worker called an LLM")

        monkeypatch.setattr(llm_bridge.LLMBridge, "__init__", forbidden)
        assert measure(_spec(tmp_path, registered)).status == "COMPLETED"


class TestTheWorkerReadsTheDatasetBoundedly:
    """D-C2-12. Gate 2 Lite-A c1 was killed at 24.10 GiB host RSS before the
    model was built, because the previous loader materialized the whole
    2,010,000,000-sample channel. The worker must not be able to reach that
    path again."""

    def test_it_calls_the_bounded_loader(self, tmp_path, registered, monkeypatch):
        seen: list[dict] = []
        import core.runtime_control.gpu_measurement_data as data_mod

        real = data_mod.load_bounded_probe_batch

        def spy(**kw):
            seen.append(kw)
            return real(**kw)

        monkeypatch.setattr(data_mod, "load_bounded_probe_batch", spy)
        build_production_components(_spec(tmp_path, registered))()
        assert seen and seen[0]["batch_size"] == 2

    def test_the_unbounded_loader_no_longer_exists(self, tmp_path, registered):
        """The regression guard, strengthened by 07c C2.

        `load_probe_batch` could not run under the 24 GiB cap, so Q-07c-1
        DELETED it outright rather than leaving a shim the worker could fall
        back into. Previously this test patched the function with a raiser and
        proved the worker did not call it; now there is nothing to call, and
        reintroducing the module IS the c1 failure returning.
        """
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("execute_tools.probe_data")
        components = build_production_components(_spec(tmp_path, registered))()
        assert components.model_input is not None

    def test_the_read_evidence_travels_with_the_components(self, tmp_path, registered):
        """ "Bounded" has to be auditable from the artifact, not asserted in
        a docstring."""
        components = build_production_components(_spec(tmp_path, registered))()
        assert components.bounded_read is not None
        assert components.bounded_read.bytes_read > 0
        assert components.bounded_read.fraction_of_file_read < 1.0


class TestTheInferencePhaseUsesTheProductionBatch:
    """Gate attempt 6 measured the inference phase at the TRAINING batch of
    1 and reported 1050 MiB where the real phase held 3642 MiB -- a 3.47x
    under-read that would have reached PR B's admission gate."""

    def _spec(self, tmp_path, data_dir, phase):
        from core.runtime_control.gpu_measurement_identity import (
            build_planned_identity,
            resolve_inference_batch,
        )

        batch = resolve_inference_batch(MODEL_TYPE)
        return _spec(
            tmp_path,
            data_dir,
            request=CandidateMeasurementRequest(
                model_type=MODEL_TYPE,
                planned_identity=build_planned_identity(
                    model_type=MODEL_TYPE,
                    model_config={},
                    train_config={"batch_size": 2},
                    inference_batch_size=batch,
                ),
                request_id="req-inf",
                device_uuid=UUID,
                phase=phase,
                deadline_seconds=60.0,
            ),
            inference_batch_size=batch,
        )

    def test_the_inference_input_uses_the_production_batch_not_the_training_one(
        self, tmp_path, registered
    ):
        """The defect, directly: train_config says 2, production inference
        says 25, and the measured tensor must be 25."""
        from core.runtime_control.gpu_measurement_identity import resolve_inference_batch

        spec = self._spec(tmp_path, registered, "inference")
        components = build_production_components(spec)()
        assert components.model_input.shape[0] == resolve_inference_batch(MODEL_TYPE)
        assert components.model_input.shape[0] != 2, "not the training batch"

    def test_the_training_input_still_uses_the_training_batch(self, tmp_path, registered):
        """The validated 1474/1476 MiB training result must not move."""
        components = build_production_components(self._spec(tmp_path, registered, "training"))()
        assert components.model_input.shape[0] == 2

    def test_the_realized_identity_reports_the_batch_actually_used(self, tmp_path, registered):
        from core.runtime_control.gpu_measurement_identity import resolve_inference_batch

        spec = self._spec(tmp_path, registered, "inference")
        realized = build_production_components(spec)().realized_identity
        # `batch_size` keeps meaning the TRAINING batch in every phase --
        # it is the field C1's hash uses, and overloading it made every
        # inference measurement mismatch its own request.
        assert realized.batch_size == 2
        assert realized.inference_batch_size == resolve_inference_batch(MODEL_TYPE)
        assert realized.inference_workload_hash is not None

    def test_an_inference_spec_without_a_batch_is_refused(self, tmp_path, registered):
        """Falling back to the training batch is the substitution that
        produced the under-read."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="requires inference_batch_size"):
            _spec(
                tmp_path,
                registered,
                request=CandidateMeasurementRequest(
                    model_type=MODEL_TYPE,
                    planned_identity=build_planned_identity(
                        model_type=MODEL_TYPE, model_config={}, train_config={}
                    ),
                    request_id="r",
                    device_uuid=UUID,
                    phase="inference",
                    deadline_seconds=60.0,
                ),
            )

    def test_the_resolver_is_productions_own(self):
        """Not a Gate parameter and not a guess: the same registered
        per-architecture constant `execute_inference` resolves."""
        from core.inference_defaults import inference_batch_for
        from core.runtime_control.gpu_measurement_identity import resolve_inference_batch

        for model in ("punet", "wavenet", "rnn", "transformer"):
            assert resolve_inference_batch(model) == inference_batch_for(model)
        assert resolve_inference_batch("punet") == 25
