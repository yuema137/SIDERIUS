"""Selected native wiring with synthetic GPU facts and no optimizer updates."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from core.runtime_control.gpu_execution_policy import GpuExecutionPolicy
from core.runtime_control.inference_startup import (
    InferenceStartup,
    InferenceStartupMessage,
    InferenceStartupRequest,
    load_and_wait_for_authorization,
    publish_message,
    read_message,
)
from core.runtime_control.measurement_allowance import MeasurementAllowance
from core.runtime_control.observed_subprocess import supervise_process
from tests.unit.core.test_checkpoint_inference_measurement import bound_spec
from tests.unit.core.test_gpu_runtime_protection import Clock, policy


@pytest.fixture(autouse=True)
def no_optimizer_updates(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("activation CPU tests must not perform optimizer updates")

    for optimizer in (torch.optim.Adam, torch.optim.AdamW, torch.optim.SGD):
        monkeypatch.setattr(optimizer, "step", forbidden)


def execution_policy():
    return GpuExecutionPolicy(
        phase_measurement_budget_seconds=60.0,
        worker_rss_limit_bytes=1024**3,
        startup_ack_timeout_seconds=2.0,
        startup_receipt_limit_bytes=1024**2,
        protection=policy(),
    )


def test_shared_allowance_excludes_execution_and_does_not_reset():
    clock = Clock()
    allowance = MeasurementAllowance(60.0, clock=clock)
    assert allowance.begin("training") == 60
    clock.value = 20
    allowance.finish("measured")
    clock.value += 1000  # actual training, outside measurement segments
    assert allowance.remaining == 40
    assert allowance.begin("inference") == 1060
    with pytest.raises(RuntimeError, match="already active"):
        allowance.begin("nested")
    clock.value = 1061  # includes cleanup overrun
    allowance.finish("timeout")
    assert allowance.remaining == 0
    with pytest.raises(TimeoutError):
        allowance.begin("startup")
    with pytest.raises(RuntimeError, match="no measurement"):
        allowance.finish("duplicate")
    assert [r.spent_seconds for r in allowance.receipts] == [20, 41]


def startup_fixture(tmp_path, spec, *, clock=None, child_pid=1234):
    clock = clock or time.monotonic
    directory = tmp_path / "startup"
    directory.mkdir()
    request = InferenceStartupRequest(
        nonce="attempt",
        spec=spec,
        deadline_at=clock() + 10,
        ack_timeout_seconds=1.0,
        poll_seconds=0.01,
        receipt_limit_bytes=1024**2,
    )
    path = directory / "request.json"
    publish_message(path, request, request.receipt_limit_bytes)
    publications = []
    startup = InferenceStartup(
        path, request, rss_limit_bytes=1024**3, on_publication=publications.append, clock=clock
    )
    message = InferenceStartupMessage(
        nonce=request.nonce,
        child_pid=child_pid,
        reference=spec.inference_checkpoint,
        binding_sha256=spec.inference_binding.request_sha256,
    )
    return startup, message, publications


def test_startup_publication_then_consumption_has_one_charge(tmp_path, bound_spec):
    clock = Clock()
    startup, message, publications = startup_fixture(tmp_path, bound_spec, clock=clock)
    startup.check(message.child_pid)
    assert publications == []
    publish_message(startup.path.parent / "loaded.json", message, 1024**2)
    clock.value = 4
    startup.check(message.child_pid)
    assert publications == [4]
    publish_message(startup.path.parent / "consumed.json", message, 1024**2)
    startup.check(message.child_pid, terminal=True)
    startup.check(message.child_pid, terminal=True)
    assert publications == [4]
    assert startup.receipt.consumed == message


@pytest.mark.parametrize(
    "mutation", ["nonce", "pid", "checkpoint", "late_consumed", "missing_consumed"]
)
def test_startup_refuses_stale_wrong_or_late_receipts(tmp_path, bound_spec, mutation):
    clock = Clock()
    startup, message, publications = startup_fixture(tmp_path, bound_spec, clock=clock)
    loaded = message
    if mutation == "nonce":
        loaded = message.model_copy(update={"nonce": "previous"})
    if mutation == "pid":
        loaded = message.model_copy(update={"child_pid": 9876})
    if mutation == "checkpoint":
        loaded = message.model_copy(
            update={
                "reference": message.reference.model_copy(update={"checkpoint_sha256": "f" * 64})
            }
        )
    publish_message(startup.path.parent / "loaded.json", loaded, 1024**2)
    if mutation in {"nonce", "pid", "checkpoint"}:
        with pytest.raises(ValueError, match="differs"):
            startup.check(message.child_pid)
        assert not publications
        return
    startup.check(message.child_pid)
    if mutation == "late_consumed":
        publish_message(startup.path.parent / "consumed.json", message, 1024**2)
    clock.value = 1.0
    with pytest.raises(TimeoutError, match="late"):
        startup.check(message.child_pid)


def test_startup_fifo_refuses_without_blocking(tmp_path, bound_spec):
    startup, message, _ = startup_fixture(tmp_path, bound_spec)
    os.mkfifo(startup.path.parent / "loaded.json")
    started = time.monotonic()
    with pytest.raises(ValueError, match="not_regular"):
        startup.check(message.child_pid)
    assert time.monotonic() - started < 1


def test_actual_bound_loader_waits_before_forward_and_accepts_published_authorization(
    tmp_path, bound_spec, monkeypatch
):
    startup, message, _ = startup_fixture(tmp_path, bound_spec, child_pid=os.getpid())
    message = message.model_copy(update={"child_pid": os.getpid()})
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY

    name = bound_spec.request.model_type
    model = MODEL_REGISTRY[name](PLUGIN_CONFIG_REGISTRY[name]())
    actual_read = read_message
    waits = []

    def read(path, schema, byte_limit):
        if path.name == "authorized.json":
            assert not (path.parent / "consumed.json").exists()
            assert (path.parent / "loaded.json").exists()
            waits.append("loaded-before-authorized")
            publish_message(path, message, byte_limit)
            # The authorization already exists: preparation expiry must not
            # supersede the parent's separate post-publication ACK allowance.
            monkeypatch.setattr(
                "core.runtime_control.inference_startup.time.monotonic",
                lambda: startup.request.deadline_at + 0.1,
            )
        return actual_read(path, schema, byte_limit)

    monkeypatch.setattr("core.runtime_control.inference_startup.read_message", read)
    loaded = load_and_wait_for_authorization(
        model,
        str(startup.path),
        checkpoint_path=message.reference.checkpoint_path,
        exp_id=message.reference.experiment_id,
    )
    assert waits == ["loaded-before-authorized"]
    assert (
        actual_read(startup.path.parent / "consumed.json", InferenceStartupMessage, 1024**2)
        == message
    )
    assert torch.equal(loaded(torch.tensor([[2.0, 0.0, 0.0, 0.0]])), torch.tensor([[37.0]]))


def test_selected_policy_is_actual_cli_launch_value_and_lock_field(tmp_path):
    from core.run_invariants import RunInvariants
    from workflows.launch_identity import resolve_launch_identity
    from workflows.standard_cli import build_parser, normalize_args
    from workflows.standard_launch import build_standard_launch_config

    path = tmp_path / "gpu.json"
    selected = execution_policy()
    path.write_text(selected.model_dump_json())
    args = build_parser().parse_args(
        [
            "--workspace",
            str(tmp_path / "run"),
            "--run_name",
            "test",
            "--start_iteration",
            "1",
            "--gpu_execution_policy_json",
            str(path),
            "--task_composition",
            "configs/task_composition/quickstart.yaml",
            "--data_dir",
            str(tmp_path),
        ]
    )
    normalize_args(args)
    identity = resolve_launch_identity(args)
    launch = build_standard_launch_config(
        args, identity, resolved_paths=[], fixed_candidate_plan=None
    )
    assert launch.gpu_execution_policy == selected
    assert "gpu_execution_policy" in RunInvariants._CANONICAL
    path.write_text('{"worker_rss_limit_bytes": 1}')
    with pytest.raises(ValueError):
        resolve_launch_identity(args)


_CHILD_HANDSHAKE = """
import json, os, pathlib, sys, time
root = pathlib.Path(sys.argv[1]); mode = sys.argv[2]
request = json.loads((root / 'request.json').read_text())
message = dict(nonce=request['nonce'], child_pid=os.getpid(),
    reference=request['spec']['inference_checkpoint'],
    binding_sha256=request['spec']['inference_binding']['request_sha256'])
def publish(name):
    p = root / (name + '.tmp'); p.write_text(json.dumps(message)); p.rename(root / name)
if mode == 'fail':
    print('original child failure', file=sys.stderr); sys.exit(7)
publish('loaded.json')
while not (root / 'authorized.json').exists(): time.sleep(.005)
if mode == 'no-ack': time.sleep(10)
publish('consumed.json')
(root / 'forward-marker').write_text('authorized')
print('child completed')
"""


@pytest.mark.parametrize("watchdog", [False, True])
def test_real_child_handshake_owns_group_and_records_consumption(tmp_path, bound_spec, watchdog):
    from tests.unit.core.test_gpu_runtime_protection import observer

    startup, _, publications = startup_fixture(tmp_path, bound_spec)
    obs = observer()
    result = supervise_process(
        [sys.executable, "-c", _CHILD_HANDSHAKE, str(startup.path.parent), "ok"],
        env=dict(os.environ),
        preexec_fn=None,
        capture_stdout=True,
        observer=obs,
        control=obs,
        startup=startup,
        deadline_provider=(lambda: (2.0, "test")) if watchdog else None,
    )
    assert result.completed.stdout.strip() == "child completed"
    assert startup.receipt.loaded == startup.receipt.consumed
    assert len(publications) == 1
    assert result.lifecycle.owned_pgid == result.lifecycle.child_pid
    assert result.lifecycle.group_cleanup.final.status == "absent"
    assert (startup.path.parent / "forward-marker").read_text() == "authorized"
    assert obs.protection_receipt().decision.status != "stop"


@pytest.mark.parametrize("rss_kind", ["incomplete", "over-limit"])
def test_startup_checks_rss_before_publication(tmp_path, bound_spec, monkeypatch, rss_kind):
    from core.runtime_control.process_group import RssObservation
    from tests.unit.core.test_gpu_runtime_protection import observer

    startup, _, publications = startup_fixture(tmp_path, bound_spec)
    obs = observer()
    monkeypatch.setattr(
        "core.runtime_control.observed_subprocess.observe_tree_rss",
        lambda _: RssObservation(
            status="incomplete" if rss_kind == "incomplete" else "complete",
            sampled_bytes=startup.rss_limit_bytes + 1,
        ),
    )
    with pytest.raises(RuntimeError, match="startup RSS") as error:
        supervise_process(
            [sys.executable, "-c", _CHILD_HANDSHAKE, str(startup.path.parent), "ok"],
            env=dict(os.environ),
            preexec_fn=None,
            capture_stdout=True,
            observer=obs,
            control=obs,
            startup=startup,
        )
    assert publications == []
    assert not (startup.path.parent / "authorized.json").exists()
    assert not (startup.path.parent / "forward-marker").exists()
    assert error.value.process_lifecycle.group_cleanup.final.status == "absent"


def test_failed_child_retains_original_output_without_loaded_receipt(tmp_path, bound_spec):
    from tests.unit.core.test_gpu_runtime_protection import observer

    startup, _, publications = startup_fixture(tmp_path, bound_spec)
    obs = observer()
    with pytest.raises(subprocess.CalledProcessError) as error:
        supervise_process(
            [sys.executable, "-c", _CHILD_HANDSHAKE, str(startup.path.parent), "fail"],
            env=dict(os.environ),
            preexec_fn=None,
            capture_stdout=True,
            observer=obs,
            control=obs,
            startup=startup,
        )
    assert error.value.returncode == 7
    assert "original child failure" in error.value.stderr
    assert error.value.process_lifecycle.group_cleanup.final.status == "absent"
    assert publications == []


def test_missing_ack_stops_real_child_with_watchdog_disabled(tmp_path, bound_spec):
    from tests.unit.core.test_gpu_runtime_protection import observer

    startup, _, publications = startup_fixture(tmp_path, bound_spec)
    startup.request = startup.request.model_copy(update={"ack_timeout_seconds": 0.1})
    obs = observer()
    with pytest.raises(TimeoutError, match="late") as error:
        supervise_process(
            [sys.executable, "-c", _CHILD_HANDSHAKE, str(startup.path.parent), "no-ack"],
            env=dict(os.environ),
            preexec_fn=None,
            capture_stdout=True,
            observer=obs,
            control=obs,
            startup=startup,
        )
    assert len(publications) == 1
    assert error.value.process_lifecycle.group_cleanup.final.status == "absent"
    assert not (startup.path.parent / "forward-marker").exists()


def test_native_adapter_preserves_ordinary_call_and_selected_typed_lifecycle(monkeypatch):
    from core.runtime_control import native_gpu_execution as native
    from core.runtime_control.gpu_execution_evidence import AttemptGpuExecution
    from core.runtime_control.observed_subprocess import ObservedProcessResult, ProcessLifecycle

    calls = []
    marker = object()

    def ordinary(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return marker

    assert (
        native.run_native_subprocess(SimpleNamespace(), ordinary, ["command"], capture_stdout=True)
        is marker
    )
    assert calls == [(["command"], {"capture_stdout": True})]
    policy_value = execution_policy()
    state = AttemptGpuExecution(
        "attempt",
        "exp",
        policy_value,
        MeasurementAllowance(policy_value.phase_measurement_budget_seconds),
    )
    state.allowance.begin("launch")
    lifecycle = ProcessLifecycle(elapsed_seconds=1.0, child_reaped=True, returncode=0)
    result = ObservedProcessResult(
        completed=subprocess.CompletedProcess(["command"], 0), lifecycle=lifecycle
    )

    def selected(cmd, **kwargs):
        assert kwargs["launch_measurement"] is state.allowance
        assert cmd == ["command"]
        return result

    monkeypatch.setattr(native, "supervise_subprocess", selected)
    assert native.run_native_subprocess(
        SimpleNamespace(gpu_execution=state), ordinary, ["command"]
    ) == (result.completed, None)
    assert state.current_lifecycle is lifecycle
    assert len(calls) == 1


def selected_state(spec, phase):
    """Supply typed completed measurement facts; no GPU work is performed."""
    from core.runtime_control.gpu_execution_evidence import AttemptGpuExecution, PreparedGpuPhase
    from core.runtime_control.inference_measurement_assessment import InferenceMeasurementAssessment
    from core.runtime_control.process_group import GroupObservation, RssObservation
    from core.runtime_control.training_measurement_assessment import TrainingMeasurementAssessment
    from tests.helpers.inference_verification import _verification
    from tests.unit.core.test_gpu_runtime_protection import DEVICE

    measured = _verification().measurement
    measured = measured.model_copy(
        update={
            "observed_device_uuid": DEVICE.uuid,
            "host_memory": measured.host_memory.model_copy(
                update={
                    "observations_complete": True,
                    "latest_observation": RssObservation(status="complete", sampled_bytes=100),
                }
            ),
            "process": measured.process.model_copy(
                update={"final_group_observation": GroupObservation(status="absent")}
            ),
        }
    )
    assessment_type = (
        TrainingMeasurementAssessment if phase == "training" else InferenceMeasurementAssessment
    )
    selected = execution_policy()
    state = AttemptGpuExecution("attempt", "exp-a", selected, MeasurementAllowance(60.0))
    state.phases[phase] = PreparedGpuPhase(
        attempt_token="attempt",
        spec=spec,
        run=measured,
        assessment=assessment_type(
            disposition="admitted",
            detail="Synthetic completed measurement",
            worker_requirement_mib=800,
        ),
    )
    return state


@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize("mode", ["trial", "formal"])
@pytest.mark.parametrize("enforcement", ["observe_only", "enforce", "enforce_resource_limits"])
@pytest.mark.parametrize("watchdog", [False, True])
def test_actual_native_launch_and_terminal_receipt(
    tmp_path, bound_spec, monkeypatch, phase, mode, enforcement, watchdog
):
    """Real executor and process supervisor; only scientific child/GPU facts are replaced."""
    from core import sandbox_executor as executor
    from core.runtime_control import native_gpu_execution as native
    from core.runtime_control.admission import GpuAdmissionPolicy
    from core.runtime_control.gpu_execution_evidence import GpuExecutionReceipt
    from core.training_execution_bindings import TrainingExecutionBindings
    from tests.unit.core.test_gpu_runtime_protection import DEVICE, snapshot
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    composition = compose_run_task_bindings("configs/task_composition/quickstart.yaml")
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        sandbox = executor.TidmadSandbox(
            run_name="run",
            workspace=str(tmp_path / "ws"),
            device_identity=DEVICE,
            device_available=True,
            admission_policy=GpuAdmissionPolicy(
                mode=mode, enforcement=enforcement, ceiling_gib=1.5
            ),
        )
        from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY

        monkeypatch.setitem(PLUGIN_OUTPUT_TYPE_REGISTRY, bound_spec.request.model_type, "regressor")
        state = selected_state(bound_spec, phase)
        sandbox.gpu_execution = state
        # Validation/source freshness has separate direct witnesses below; this
        # matrix exercises the four actual process branches and terminal owner.
        monkeypatch.setattr(executor, "validate_native_inputs", lambda *a, **k: None)
        monkeypatch.setattr(executor, "task_scope_argv", lambda *a, **k: [])
        monkeypatch.setattr(executor, "validation_rows_argv", lambda *a, **k: [])
        monkeypatch.setattr(native, "sample", lambda *a: snapshot())
        monkeypatch.setattr("core.runtime_control.gpu_observer.sample", lambda *a: snapshot())
        actual_supervise = native.supervise_subprocess
        seen = []

        def scientific_child(cmd, **kwargs):
            seen.append(kwargs)
            if phase == "training":
                sentinel = Path(sandbox.dirs["models"]) / "_OK_exp-a"
                replacement = [
                    sys.executable,
                    "-c",
                    "import pathlib,sys;pathlib.Path(sys.argv[1]).touch()",
                    str(sentinel),
                ]
            else:
                assert "--inference_startup_json" in cmd
                path = Path(cmd[cmd.index("--inference_startup_json") + 1])
                replacement = [sys.executable, "-c", _CHILD_HANDSHAKE, str(path.parent), "ok"]
            return actual_supervise(replacement, **kwargs)

        monkeypatch.setattr(native, "supervise_subprocess", scientific_child)
        scopes = SimpleNamespace(training=object(), evaluation=object())
        runtime = {
            "operator_budget_seconds": 10.0,
            "watchdog": {"enabled": watchdog, "poll_seconds": 0.01, "grace_seconds": 0.1},
        }
        if phase == "training":
            result = sandbox.execute_training(
                "exp-a",
                "run",
                bound_spec.request.model_type,
                {},
                {"device": "cpu"},
                {"loss_type": "smooth_l1"},
                runtime_policy=runtime,
                execution_bindings=TrainingExecutionBindings(task_scopes=scopes),
            )
        else:
            result = sandbox.execute_inference(
                "exp-a",
                "run",
                bound_spec.request.model_type,
                {},
                {"loss_type": "smooth_l1"},
                inference_batch=3,
                runtime_policy=runtime,
                task_scopes=scopes,
            )
        assert result["status"] == "success", result
        assert len(seen) == 1
        assert ("deadline_provider" in seen[0]) == watchdog
        receipt_path = (
            Path(sandbox.base_dir) / "gpu_execution" / "attempt" / f"{phase}-terminal.json"
        )
        receipt = GpuExecutionReceipt.model_validate_json(receipt_path.read_bytes())
        assert receipt == GpuExecutionReceipt.model_validate(result["gpu_execution"])
        assert receipt.admission.admitted
        assert receipt.protection.binding.effective_ceiling_gib == 1.5
        assert receipt.lifecycle.group_cleanup.final.status == "absent"
        assert receipt.lifecycle.child_reaped
        assert receipt.measurement_segments[-1].outcome in {"training authorized", "authorized"}
        if phase == "inference":
            assert receipt.startup.loaded == receipt.startup.consumed


@pytest.mark.parametrize("mode", ["trial", "formal"])
@pytest.mark.parametrize("fault", ["unknown", "capacity"])
def test_selected_current_admission_distinguishes_gap_from_capacity(
    tmp_path, bound_spec, monkeypatch, mode, fault
):
    from core.runtime_control import native_gpu_execution as native
    from core.runtime_control.admission import GpuAdmissionPolicy
    from tests.unit.core.test_gpu_runtime_protection import DEVICE, snapshot

    state = selected_state(bound_spec, "training")
    sandbox = SimpleNamespace(
        gpu_execution=state,
        device_identity=DEVICE,
        admission_policy=GpuAdmissionPolicy(mode=mode, ceiling_gib=1.0),
    )
    from core.runtime_control.gpu_accounting import GpuAccountingSnapshot

    current = (
        snapshot(used=900)
        if fault == "capacity"
        else GpuAccountingSnapshot(device=DEVICE, telemetry_available=False)
    )
    monkeypatch.setattr(native, "sample", lambda *a: current)
    refusal = native.admit_phase(sandbox, "training")
    assert refusal["status"] == (
        "skipped_resource_admission" if fault == "capacity" else "aborted_infrastructure"
    )
    assert state.current_observer is None


@pytest.mark.parametrize("fault", ["cleanup", "mkdir", "publish"])
def test_terminal_failure_never_becomes_candidate_retry_or_false_success(
    tmp_path, bound_spec, monkeypatch, fault
):
    from core.runtime_control import native_gpu_execution as native
    from core.runtime_control.gpu_execution_evidence import GpuExecutionReceipt
    from nodes.ml_hyperparameter_tune_agent.runtime import (
        RuntimeEvidenceChannelError,
        _raise_if_evidence_channel_failure,
    )

    state = selected_state(bound_spec, "training")
    sandbox = SimpleNamespace(gpu_execution=state, base_dir=str(tmp_path), dirs={})

    @native.record_protected_phase("training")
    def execute(sandbox):
        state.allowance.finish("training authorized")
        return {
            "status": "error" if fault == "cleanup" else "success",
            "message": "original result",
        }

    def denied(*args, **kwargs):
        raise PermissionError("synthetic storage failure")

    if fault == "cleanup":
        monkeypatch.setattr(native, "_cleanup_attempt", denied)
    elif fault == "mkdir":
        monkeypatch.setattr(Path, "mkdir", denied)
    else:
        monkeypatch.setattr(native, "publish_bytes_write_once", denied)
    result = execute(sandbox)
    assert result["status"] == "aborted_infrastructure"
    receipt = GpuExecutionReceipt.model_validate(result["gpu_execution"])
    assert receipt.outcome == result["status"]
    assert "synthetic storage failure" in receipt.detail
    assert state.receipts[-1] == receipt
    with pytest.raises(RuntimeEvidenceChannelError):
        _raise_if_evidence_channel_failure(result, sandbox, "run")


@pytest.mark.parametrize("mutation", [None, "batch", "scope", "data", "model", "attempt", "source"])
def test_actual_native_freshness_validation_refuses_changed_phase_input(
    bound_spec, monkeypatch, mutation
):
    from core.runtime_control import native_gpu_execution as native
    from core.runtime_control.gpu_accounting import DeviceIdentity

    spec = bound_spec
    state = selected_state(spec, "inference")
    sandbox = SimpleNamespace(
        gpu_execution=state,
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
    args = dict(
        exp_id="exp-a",
        model_type=spec.request.model_type,
        model_config=spec.model_config_payload,
        loss_config=spec.loss_config,
        task_scopes=SimpleNamespace(evaluation=spec.task_probe_data.evaluation_scope_payload),
        inference_batch=spec.inference_batch_size,
    )
    if mutation == "batch":
        args["inference_batch"] += 1
    if mutation == "scope":
        args["task_scopes"].evaluation = "other scope"
    if mutation == "data":
        sandbox.dirs["data"] = "/other/data"
    if mutation == "model":
        args["model_config"] = {"changed": 1}
    if mutation == "attempt":
        args["exp_id"] = "other-attempt"
    if mutation == "source":
        monkeypatch.setattr(
            native,
            "inference_measurement_binding",
            lambda *a, **k: spec.inference_binding.model_copy(update={"assembly_sha256": "f" * 64}),
        )
    if mutation:
        with pytest.raises(ValueError, match=r"differ|changed|evidence"):
            native.validate_native_inputs(sandbox, "inference", **args)
    else:
        native.validate_native_inputs(sandbox, "inference", **args)


def test_parent_authorization_checks_declared_child_plugin_environment(
    tmp_path, bound_spec, monkeypatch
):
    from core.runtime_control import inference_startup as startup_owner

    startup, message, _ = startup_fixture(tmp_path, bound_spec)
    environment = {"SIDERIUS_PLUGIN_DIRS": "/explicit/run/plugins"}
    startup.environment = environment
    seen = []

    def binding(spec, *, environ=None):
        seen.append(environ)
        return spec.inference_binding

    monkeypatch.setattr(startup_owner, "inference_measurement_binding", binding)
    publish_message(startup.path.parent / "loaded.json", message, 1024**2)
    startup.check(message.child_pid)
    assert seen == [environment]


def test_record_owner_adds_only_selected_typed_evidence(tmp_path, bound_spec):
    import importlib

    records = importlib.import_module("nodes.ml_hyperparameter_tune_agent.records")
    payload = {
        "exp_id": "exp-a",
        "status": "success",
        "model_type": "synthetic",
        "timestamp": "2000-01-01",
        "params": {},
    }
    saved = []
    sandbox = SimpleNamespace(save_record=saved.append)
    records._emit_record(sandbox, dict(payload))
    assert "gpu_execution" not in saved[-1]
    state = selected_state(bound_spec, "training")
    sandbox.gpu_execution = state
    records._emit_record(sandbox, dict(payload))
    assert saved[-1] == saved[-2]
    receipt = state.receipt("training", "success")
    records._emit_record(sandbox, dict(payload))
    assert saved[-1]["gpu_execution"] == [receipt.model_dump(mode="json")]
    assert {k: v for k, v in saved[-1].items() if k != "gpu_execution"} == saved[-2]


def test_inference_dispatch_binds_actual_cpu_checkpoint_and_current_batch(
    tmp_path, bound_spec, monkeypatch
):
    import importlib

    from core.runtime_control.gpu_measurement_identity import build_realized_identity
    from core.runtime_control.process_group import GroupObservation, RssObservation
    from tests.helpers.inference_verification import _verification

    gpu = importlib.import_module("nodes.ml_hyperparameter_tune_agent.gpu_execution")
    runtime = importlib.import_module("nodes.ml_hyperparameter_tune_agent.runtime")
    from core.runtime_control.gpu_accounting import DeviceIdentity

    sandbox = SimpleNamespace(
        base_dir=str(tmp_path),
        dirs={"models": str(tmp_path)},
        device_available=True,
        device_identity=DeviceIdentity(uuid=bound_spec.request.device_uuid, physical_index=0),
        plugin_dir=None,
        loss_dir=None,
    )
    agent_input = SimpleNamespace(
        gpu_execution_policy=execution_policy(),
        task_composition_ref=object(),
        validation_max_train_samples=None,
        gpu_pair_ceiling_gib=2.0,
    )
    gpu.begin_attempt(sandbox, agent_input, "exp-a")
    bindings = SimpleNamespace(
        sandbox=sandbox,
        agent_input=agent_input,
        time_data_dir=str(tmp_path),
        run_profile=None,
        run_model_io=bound_spec.model_io_contract,
        hardware_context=SimpleNamespace(total_memory_gb=4.0),
    )
    prepared = SimpleNamespace(
        exp_id="exp-a",
        model_type=bound_spec.request.model_type,
        task_scopes=object(),
        trial_config=SimpleNamespace(train_base_seed=19, train_portion=0.25),
        active_params={
            "model_config": {},
            "train_config": {"batch_size": 1},
            "loss_config": bound_spec.loss_config,
            "inference_batch": 2,
        },
        expected_custom_loss_snapshot=None,
    )
    monkeypatch.setattr(gpu, "build_task_probe_data", lambda **kw: bound_spec.task_probe_data)
    monkeypatch.setattr(gpu, "candidate_evaluation_executor", lambda: None)
    seen = []

    def measurement(spec, **kwargs):
        assert spec.inference_checkpoint == bound_spec.inference_checkpoint
        assert spec.inference_batch_size == 2
        seen.append(spec)
        run = _verification(batch=2).measurement
        phases = tuple(
            p.model_copy(
                update={
                    "observed_reservations": tuple(
                        h.model_copy(update={"hold_id": f"{spec.request.request_id}:{p.phase}:{i}"})
                        for i, h in enumerate(p.observed_reservations)
                    )
                }
            )
            for p in run.phases
        )
        return run.model_copy(
            update={
                "request": spec.request,
                "inference_binding": spec.inference_binding,
                "reported_request_id": spec.request.request_id,
                "observed_device_uuid": spec.request.device_uuid,
                "verified_checkpoint": spec.inference_checkpoint,
                "phases": phases,
                "realized_identity": build_realized_identity(
                    model_type=spec.request.model_type,
                    optimizer_type="adamw",
                    seg_size=None,
                    batch_size=1,
                    precision="float32",
                    parameter_count=100,
                    trainable_parameter_count=100,
                    inference_batch_size=2,
                    segmentation_applicability="not_applicable",
                ),
                "host_memory": run.host_memory.model_copy(
                    update={
                        "observations_complete": True,
                        "latest_observation": RssObservation(
                            status="complete", sampled_bytes=1000000
                        ),
                    }
                ),
                "process": run.process.model_copy(
                    update={"final_group_observation": GroupObservation(status="absent")}
                ),
            }
        )

    monkeypatch.setattr(gpu, "run_prephase_measurement", measurement)
    result = gpu.prepare_phase(bindings, prepared, SimpleNamespace(), phase="inference")
    assert result is runtime.PrephaseOutcome.PROCEED
    assert len(seen) == 1
    entry = sandbox.gpu_execution.phases["inference"]
    assert entry.requirement().requirement_mib == 800
    assert len(sandbox.gpu_execution.allowance.receipts) == 1
    assert sandbox.gpu_execution.allowance.receipts[0].spent_seconds > 0


@pytest.mark.parametrize("fault", ["stopped-during-source-check", "late-publication"])
def test_authorization_refuses_changed_control_or_late_publication(
    tmp_path, bound_spec, monkeypatch, fault
):
    from core.runtime_control import inference_startup as owner
    from core.runtime_control.process_control import ProcessControlDecision

    clock = Clock()
    startup, message, _ = startup_fixture(tmp_path, bound_spec, clock=clock)
    publish_message(startup.path.parent / "loaded.json", message, 1024**2)
    if fault == "stopped-during-source-check":
        startup.control = SimpleNamespace(
            check_control=lambda: ProcessControlDecision(
                status="stop", binding_token="attempt", sequence=1, reason="stale observation"
            )
        )
        with pytest.raises(RuntimeError, match="stale observation"):
            startup.check(message.child_pid)
        assert not (startup.path.parent / "authorized.json").exists()
    else:
        original = publish_message

        def delayed(path, receipt, limit):
            original(path, receipt, limit)
            clock.value = startup.request.deadline_at

        monkeypatch.setattr(owner, "publish_message", delayed)
        with pytest.raises(TimeoutError, match="publication exhausted"):
            startup.check(message.child_pid)
        assert startup.receipt.published_at == startup.request.deadline_at
    assert startup.receipt.error is not None
