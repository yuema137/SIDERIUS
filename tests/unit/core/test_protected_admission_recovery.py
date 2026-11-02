"""Real native phase entry + tuner recovery owner, with synthetic GPU/child facts.

Reverting routing breaks recovery counts; reverting receipt handling makes a
successful retry fail publication. No optimizer, provider or GPU work runs.
"""

import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from core import sandbox_executor as executor
from core.runtime_control import native_gpu_execution as native
from core.runtime_control.admission import GpuAdmissionPolicy
from core.runtime_control.gpu_accounting import GpuAccountingSnapshot, GpuQueryFailure
from core.runtime_control.gpu_execution_evidence import GpuExecutionReceipt
from core.runtime_control.process_visibility import PROCESS_VISIBILITY_ENV
from core.training_execution_bindings import TrainingExecutionBindings
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AttemptIdentity,
    PreparedAttempt,
    RunBindings,
)
from nodes.ml_hyperparameter_tune_agent.phase_admission import run_admitted_skill
from tests.unit.core.test_checkpoint_inference_measurement import bound_spec
from tests.unit.core.test_gpu_runtime_protection import DEVICE, Clock, snapshot
from tests.unit.core.test_native_gpu_execution import selected_state
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

runtime = importlib.import_module("nodes.ml_hyperparameter_tune_agent.runtime")


@pytest.fixture
def recovery_case(tmp_path, bound_spec, monkeypatch, phase, mode, isolated, fault):
    if isolated:
        monkeypatch.setenv(PROCESS_VISIBILITY_ENV, "namespace_limited")
    else:
        monkeypatch.delenv(PROCESS_VISIBILITY_ENV, raising=False)
    composition = compose_run_task_bindings("configs/task_composition/quickstart.yaml")
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        sandbox = executor.TidmadSandbox(
            run_name="run",
            workspace=str(tmp_path / "ws"),
            device_identity=DEVICE,
            device_available=True,
            admission_policy=GpuAdmissionPolicy(
                mode=mode, enforcement="observe_only", ceiling_gib=1.5
            ),
        )
        state = selected_state(bound_spec, phase)
        sandbox.gpu_execution = state
        measured = state.phases[phase]
        clock = Clock()
        state.allowance.clock = clock
        state.allowance.total_seconds = {"deadline": 1, "backoff_deadline": 1.125}.get(fault, 60)
        # A completed training checkpoint must survive every inference refusal.
        from core.sandbox_layout import training_checkpoint_path

        checkpoint = Path(
            training_checkpoint_path(sandbox.dirs["models"], bound_spec.request.model_type, "exp-a")
        )
        checkpoint.write_bytes(b"completed training")
        monkeypatch.setattr(executor, "validate_native_inputs", lambda *a, **k: None)
        monkeypatch.setattr(executor, "task_scope_argv", lambda *a, **k: [])
        monkeypatch.setattr(executor, "validation_rows_argv", lambda *a, **k: [])
        from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY

        monkeypatch.setitem(PLUGIN_OUTPUT_TYPE_REGISTRY, bound_spec.request.model_type, "regressor")
        samples, calls, launches, delays, saved = [], [], [], [], []

        def sample(*args):
            assert state.current_observer is None
            assert state.current_startup is None
            assert state.phases[phase] is measured
            samples.append(state.allowance.deadline)
            clock.value += 1
            if fault == "exception" and len(samples) == 1:
                raise OSError("temporary proc read error")
            if (
                fault in {"exhaust", "persistent", "deadline", "backoff_deadline", "storage"}
                or len(samples) == 1
            ):
                return GpuAccountingSnapshot(
                    device=DEVICE,
                    telemetry_available=False,
                    query_failure=None if fault == "persistent" else GpuQueryFailure.TIMEOUT,
                )
            return snapshot()

        monkeypatch.setattr(native, "sample", sample)

        # Stop at the exact child launch boundary; preserve production admission,
        # decorator, observer binding, and cumulative allowance bookkeeping.
        def launch(*args, **kwargs):
            launches.append(state.current_observer)
            assert state.current_admission.admitted
            assert state.current_observer is not None
            state.allowance.finish("synthetic authorized")
            (Path(sandbox.dirs["models"]) / "_OK_exp-a").touch()
            return subprocess.CompletedProcess([], 0, stdout="", stderr=""), None

        monkeypatch.setattr(executor, "run_phase_subprocess", launch)
        # Inference startup has its own handshake tests; refuse no earlier than
        # this post-admission boundary so no request directory is made on refusals.
        monkeypatch.setattr(executor, "prepare_startup", lambda *a: None)
        scopes = SimpleNamespace(training=object(), evaluation=object())

        def skill(name, target, **params):
            calls.append((name, params))
            assert target is sandbox
            assert params == {"candidate": "unchanged"}
            if phase == "training":
                return sandbox.execute_training(
                    "exp-a",
                    "run",
                    bound_spec.request.model_type,
                    {},
                    {"device": "cpu"},
                    {"loss_type": "smooth_l1"},
                    execution_bindings=TrainingExecutionBindings(task_scopes=scopes),
                )
            return sandbox.execute_inference(
                "exp-a",
                "run",
                bound_spec.request.model_type,
                {},
                {"loss_type": "smooth_l1"},
                inference_batch=3,
                task_scopes=scopes,
            )

        monkeypatch.setattr(runtime, "_run_skill", skill)
        monkeypatch.setattr(
            runtime, "_handle_admission_refusal", lambda status, **k: saved.append(status)
        )
        if fault == "storage":
            original = native.publish_bytes_write_once

            def publish(path, data):
                if path.endswith("terminal.json"):
                    raise OSError("synthetic terminal write failure")
                return original(path, data)

            monkeypatch.setattr(native, "publish_bytes_write_once", publish)
        bindings = cast(
            RunBindings,
            SimpleNamespace(
                sandbox=sandbox,
                agent_input=SimpleNamespace(
                    attempts_per_round=3,
                    attempts_per_formal_round=3,
                    candidate_id=None,
                    experiment_arm=None,
                ),
                file_index=0,
                expert_advice_str="",
            ),
        )
        prepared = cast(
            PreparedAttempt,
            SimpleNamespace(
                active_params={"candidate": "unchanged"},
                ordering=None,
                exp_id="exp-a",
                model_type=bound_spec.request.model_type,
                record_params={},
                hypothesis="same",
                plan=SimpleNamespace(is_trial=mode == "trial"),
            ),
        )
        identity = AttemptIdentity(
            round_index=1, attempt_in_round=1, is_formal_round=mode == "formal"
        )

        def pause(seconds):
            delays.append(seconds)
            clock.value += seconds

        result, refusal = run_admitted_skill(
            bindings,
            prepared,
            identity,
            phase=phase,
            sleep=pause,
        )
        yield SimpleNamespace(
            sandbox=sandbox,
            state=state,
            measured=measured,
            checkpoint=checkpoint,
            samples=samples,
            calls=calls,
            launches=launches,
            delays=delays,
            saved=saved,
            result=result,
            refusal=refusal,
        )


@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize("mode", ["trial", "formal"])
@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.parametrize(
    "fault",
    ["recover", "exception", "exhaust", "persistent", "deadline", "backoff_deadline", "storage"],
)
def test_protected_recovery(recovery_case, phase, mode, isolated, fault):
    case = recovery_case
    sandbox, state, measured = case.sandbox, case.state, case.measured
    checkpoint, samples, calls = case.checkpoint, case.samples, case.calls
    launches, delays, saved = case.launches, case.delays, case.saved
    result, refusal = case.result, case.refusal
    expected = (
        2
        if fault in {"recover", "exception", "deadline", "backoff_deadline"}
        else 1
        if fault == "persistent"
        else 3
    )
    assert len(calls) == expected
    assert {name for name, _ in calls} == {f"{phase}_skill"}
    expected_delays = {
        "recover": [0.25],
        "exception": [0.25],
        "exhaust": [0.25, 0.5],
        "persistent": [],
        "deadline": [],
        "backoff_deadline": [0.125],
        "storage": [0.25, 0.5],
    }
    assert delays == expected_delays[fault]
    assert state.phases[phase] is measured
    if phase == "inference":
        assert checkpoint.read_bytes() == b"completed training"
    assert len(launches) == (1 if fault in {"recover", "exception"} else 0)
    assert samples == {"deadline": [1], "backoff_deadline": [1.125]}.get(fault, [60] * expected)
    assert state.allowance.remaining == (
        0 if fault in {"deadline", "backoff_deadline"} else 60 - expected - sum(delays)
    )
    root = Path(sandbox.base_dir) / "gpu_execution" / "attempt"
    terminal = (
        GpuExecutionReceipt.model_validate_json((root / f"{phase}-terminal.json").read_bytes())
        if fault != "storage"
        else None
    )
    sampling_files = sorted(root.glob(f"{phase}-admission-*.json"))
    expected_samples = {
        "persistent": 0,
        "recover": 1,
        "exception": 1,
        "deadline": 1,
        "backoff_deadline": 1,
        "exhaust": 3,
        "storage": 3,
    }
    assert len(sampling_files) == expected_samples[fault]
    for path in sampling_files:
        sampled = GpuExecutionReceipt.model_validate_json(path.read_bytes())
        assert sampled.admission.refusal_kind == "transient_sampling"
        assert sampled.lifecycle is None
        assert sampled.measurement.model_dump(mode="json") == measured.model_dump(mode="json")
    _assert_terminal_result(result, refusal, saved, terminal, fault)
    assert state.current_startup is None


def _assert_terminal_result(result, refusal, saved, terminal, fault):
    if terminal is not None:
        assert terminal == GpuExecutionReceipt.model_validate(result["gpu_execution"])
    if fault in {"persistent", "exhaust"}:
        assert result["status"] == "skipped_resource_admission"
        assert refusal is not None
        assert len(saved) == 1
        assert terminal.admission == refusal
    else:
        assert result["status"] == (
            "success" if fault in {"recover", "exception"} else "aborted_infrastructure"
        )
        assert refusal is None
        assert not saved
        if fault == "storage":
            assert "synthetic terminal write failure" in result["message"]
        elif fault in {"deadline", "backoff_deadline"}:
            assert "allowance is exhausted" in result["message"]
        else:
            assert terminal.admission.admitted
