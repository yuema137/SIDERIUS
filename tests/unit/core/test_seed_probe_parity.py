"""Issue #983 T10 (M1): the GPU probe measures the trainer's epoch-0 selection.

Each test names the defect whose assertion it owns. The protected-launch check
is driven through ``validate_native_inputs`` with typed measurement facts; no
GPU work runs.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from core.seeding import SeedCoordinates
from core.training_seeds import SeedContext, TrainingSeedPlan
from tests.unit.core.test_checkpoint_inference_measurement import bound_spec
from tests.unit.core.test_native_gpu_execution import selected_state

CONTEXT = SeedContext(run_seed=5, at=SeedCoordinates(iteration=2, round=1, attempt=3))


def _training_launch(spec, monkeypatch, context: SeedContext):
    """A protected training launch measured with ``CONTEXT``'s epoch-0 seed."""
    from core.runtime_control import native_gpu_execution as native
    from core.runtime_control.gpu_accounting import DeviceIdentity
    from ml_models.models_format_sandbox import TrainConfig

    sampling = spec.task_probe_data.sampling.model_copy(
        update={"epoch_seed": TrainingSeedPlan(CONTEXT).epoch(0).subsample}
    )
    spec = spec.model_copy(
        update={"task_probe_data": spec.task_probe_data.model_copy(update={"sampling": sampling})}
    )
    sandbox = SimpleNamespace(
        gpu_execution=selected_state(spec, "training"),
        device_identity=DeviceIdentity(uuid=spec.request.device_uuid, physical_index=0),
        dirs={"data": spec.data_dir},
        plugin_dir=None,
        loss_dir=None,
        _validate_model_and_loss=lambda model, config, loss: (config, loss),
    )
    import execute_tools.task_data_path as task

    monkeypatch.setattr(task, "require_bound_task_data_path", lambda: object())
    monkeypatch.setattr(
        task,
        "resolve_task_scope_capability",
        lambda _: SimpleNamespace(serialize_scope=lambda value: value),
    )
    monkeypatch.setattr(
        "workflows.task_composition.active_composition_fingerprint",
        lambda: spec.task_probe_data.semantic_fingerprint,
    )
    monkeypatch.setattr(
        "workflows.task_config.run_bound_model_io_contract", lambda: spec.model_io_contract
    )
    monkeypatch.setattr(
        native, "training_measurement_binding", lambda *a, **k: spec.training_binding
    )
    native.validate_native_inputs(
        sandbox,
        "training",
        exp_id="exp-a",
        model_type=spec.request.model_type,
        model_config=spec.model_config_payload,
        loss_config=spec.loss_config,
        train_config=TrainConfig(**spec.train_config).model_dump(),
        task_scopes=SimpleNamespace(training=spec.task_probe_data.training_scope_payload),
        train_portion=spec.task_probe_data.sampling.train_portion,
        seed_context=context,
        custom_loss_snapshot=spec.expected_custom_loss_snapshot,
    )


def test_matching_seed_context_is_admitted(bound_spec, monkeypatch):
    """Fails if the check compares a value the tuner no longer sends (the
    retired ``train_base_seed``) and so refuses every protected launch."""
    _training_launch(bound_spec, monkeypatch, CONTEXT)


def test_a_different_seed_context_is_refused(bound_spec, monkeypatch):
    """Fails if a launch whose epoch-0 selection differs from the measured
    probe's is admitted under that measurement."""
    other = CONTEXT.model_copy(update={"run_seed": 6})
    with pytest.raises(ValueError, match="sampling differs"):
        _training_launch(bound_spec, monkeypatch, other)


def test_a_missing_seed_context_is_refused(bound_spec, monkeypatch):
    """Fails if a protected launch without a seed context (a trainer that
    would generate its own seeds) passes the measurement check."""
    with pytest.raises(ValueError, match="sampling differs"):
        _training_launch(bound_spec, monkeypatch, None)  # type: ignore[arg-type]


def test_probe_epoch_seed_equals_the_trainer_epoch_zero_subsample(tmp_path, monkeypatch):
    """Fails if the tuner's probe and the trainer derive epoch 0 from
    different inputs: the probe value is captured from the production probe
    builder call, the trainer value from the transported seed-context file."""
    from core.training_seeds import publish_seed_context, resolve_trainer_seed_plan
    from execute_tools.train_engine_sandbox import _load_seed_context_arg

    gpu_execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.gpu_execution")

    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("captured")

    monkeypatch.setattr(gpu_execution, "build_task_probe_data", capture)
    prepared = SimpleNamespace(
        task_scopes=object(),
        trial_config=SimpleNamespace(seed_context=CONTEXT, train_portion=0.5),
        active_params={},
    )
    bindings = SimpleNamespace(
        sandbox=None,
        time_data_dir=str(tmp_path),
        agent_input=SimpleNamespace(task_composition_ref=None, validation_max_train_samples=None),
    )
    with pytest.raises(RuntimeError, match="captured"):
        gpu_execution._spec(bindings, prepared, "training", None, 0.0, tmp_path)
    path = tmp_path / "seed_context.json"
    publish_seed_context(str(path), CONTEXT)
    plan, source = resolve_trainer_seed_plan(_load_seed_context_arg(str(path)))
    assert source == "supplied"
    assert seen["epoch_seed"] == plan.epoch(0).subsample


def test_task_scope_requests_carry_the_derived_attempt_seeds(monkeypatch):
    """Data-path contract: fails if a composed attempt asks the task for a
    scope with ``ScopeBuildRequest.seed=None`` (a non-deterministic draw) or
    with a seed other than the attempt's derived one."""
    acquisition = importlib.import_module("nodes.ml_hyperparameter_tune_agent.scope_acquisition")
    from nodes.ml_hyperparameter_tune_agent.attempt_seeds import derive_attempt_seeds

    seeds = derive_attempt_seeds(
        5, SeedCoordinates(iteration=2), round_index=1, attempt=3, align=False
    )
    requests = []

    def build(request):
        requests.append(request)
        return object()

    capability = SimpleNamespace(build_training_scope=build, build_eval_scope=build)
    monkeypatch.setattr(acquisition, "require_bound_task_data_path", lambda: object())
    monkeypatch.setattr(acquisition, "resolve_task_scope_capability", lambda _: capability)
    monkeypatch.setattr(acquisition, "resolve_frozen_training_pool_capability", lambda _: None)
    acquisition.acquire_attempt_scopes(
        composed=True,
        mode="trial",
        trial_strategy="snapshot",
        trial_portion=0.1,
        eval_strategy="snapshot",
        eval_portion=0.1,
        train_sampling_seed=seeds.train_sampling,
        eval_sampling_seed=seeds.eval_sampling,
        target_files=None,
        subset=None,
        validation_max_samples=None,
        task_parameters={},
    )
    assert [r.seed for r in requests] == [seeds.train_sampling, seeds.eval_sampling]
    assert None not in [r.seed for r in requests]
