"""Actual tuner measurement dispatch with synthetic complete CPU evidence."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.runtime_control.gpu_accounting import DeviceIdentity
from core.runtime_control.inference_measurement_binding import MeasurementSources
from tests.unit.core.test_native_gpu_execution import execution_policy
from tests.unit.core.test_training_measurement_evidence import (
    assessment_run,
    bound_spec,
)

gpu = importlib.import_module("nodes.ml_hyperparameter_tune_agent.gpu_execution")
execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")
runtime = importlib.import_module("nodes.ml_hyperparameter_tune_agent.runtime")


@pytest.mark.parametrize("trial", [True, False])
@pytest.mark.parametrize("fault", [None, "missing-host", "capacity", "storage", "record-storage"])
def test_tuner_phase_uses_actual_assessment_and_shared_budget(
    tmp_path, bound_spec, monkeypatch, trial, fault
):
    sources = MeasurementSources(
        assembly_sha256="a" * 64, plugin_sources_sha256="b" * 64, runtime_sha256="c" * 64
    )
    monkeypatch.setattr(
        "core.runtime_control.training_measurement_binding.measurement_sources",
        lambda **kw: sources,
    )
    probe = bound_spec.task_probe_data.model_copy(update={"evaluation_scope_payload": "evaluation"})
    monkeypatch.setattr(gpu, "build_task_probe_data", lambda **kw: probe)
    monkeypatch.setattr(gpu, "candidate_evaluation_executor", lambda: None)
    sandbox = SimpleNamespace(
        base_dir=str(tmp_path),
        device_available=True,
        device_identity=DeviceIdentity(uuid=bound_spec.request.device_uuid, physical_index=0),
        plugin_dir=None,
        loss_dir=None,
    )
    agent_input = SimpleNamespace(
        gpu_execution_policy=execution_policy(),
        task_composition_ref=object(),
        validation_max_train_samples=11,
        gpu_pair_ceiling_gib=0.5 if fault in {"capacity", "record-storage"} else 2.0,
        candidate_id=None,
        experiment_arm=None,
    )
    gpu.begin_attempt(sandbox, agent_input, "exp")
    bindings = SimpleNamespace(
        sandbox=sandbox,
        agent_input=agent_input,
        time_data_dir=str(tmp_path),
        run_profile=None,
        run_model_io=None,
        hardware_context=SimpleNamespace(total_memory_gb=4.0),
        file_index=None,
        expert_advice_str="",
    )
    prepared = SimpleNamespace(
        exp_id="exp",
        model_type="punet",
        task_scopes=object(),
        trial_config=SimpleNamespace(train_base_seed=19, train_portion=0.25),
        active_params={
            "model_config": {},
            "train_config": bound_spec.train_config,
            "loss_config": bound_spec.loss_config,
            "inference_batch": 2,
        },
        expected_custom_loss_snapshot=None,
        record_params={},
        hypothesis="",
        ordering=None,
        plan=SimpleNamespace(is_trial=trial),
    )
    observed = []

    def measurement(spec, **kwargs):
        observed.append((spec, kwargs))
        assert (
            spec.strict_lifecycle
            and kwargs["deadline_at"] == sandbox.gpu_execution.allowance.deadline
        )
        result = assessment_run(spec)
        if fault == "missing-host":
            result = result.model_copy(
                update={
                    "host_memory": result.host_memory.model_copy(
                        update={"observations_complete": False}
                    )
                }
            )
        return result

    monkeypatch.setattr(gpu, "run_prephase_measurement", measurement)
    emissions = []
    records = importlib.import_module("nodes.ml_hyperparameter_tune_agent.records")
    monkeypatch.setattr(records, "_emit_record", lambda *a, **k: emissions.append(a[1]))
    first_receipt = []
    if fault == "record-storage":

        def reject_record(*args, **kwargs):
            path = (
                tmp_path
                / "gpu_execution"
                / sandbox.gpu_execution.attempt_token
                / "training-terminal.json"
            )
            first_receipt.append(path.read_bytes())
            raise PermissionError("candidate record storage denied")

        monkeypatch.setattr(records, "_emit_record", reject_record)
    if fault == "storage":
        monkeypatch.setattr(
            gpu,
            "publish_bytes_write_once",
            lambda *a: (_ for _ in ()).throw(PermissionError("storage denied")),
        )
    identity = SimpleNamespace(round_index=2, attempt_in_round=1)
    if fault in {"missing-host", "storage", "record-storage"}:
        with pytest.raises(runtime.RuntimeEvidenceChannelError):
            gpu.prepare_phase(bindings, prepared, identity, phase="training")
        assert sandbox.gpu_execution.receipts[-1].outcome == "aborted_infrastructure"
    else:
        result = gpu.prepare_phase(bindings, prepared, identity, phase="training")
        assert result is (
            runtime.PrephaseOutcome.TERMINAL_RESOURCE_REFUSAL
            if fault == "capacity"
            else runtime.PrephaseOutcome.PROCEED
        )
        entry = sandbox.gpu_execution.phases["training"]
        assert entry.assessment.disposition == ("capacity_refused" if fault else "admitted")
        assert entry.spec.task_probe_data == probe
    if fault == "record-storage":
        path = (
            tmp_path
            / "gpu_execution"
            / sandbox.gpu_execution.attempt_token
            / "training-terminal.json"
        )
        assert path.read_bytes() == first_receipt[0]
        assert '"outcome":"capacity_refused"' in first_receipt[0].decode()
        assert "candidate record storage denied" in sandbox.gpu_execution.receipts[-1].detail
    assert len(observed) == 1
    assert len(sandbox.gpu_execution.allowance.receipts) == 1
    assert len(emissions) == (fault == "capacity")
    gpu.end_attempt(sandbox)
    assert sandbox.gpu_execution is None


def test_local_inference_checks_checkpoint_phase_before_skill(monkeypatch):
    calls = []

    def reject(bindings, prepared, identity, *, phase):
        calls.append(phase)
        return runtime.PrephaseOutcome.TERMINAL_RESOURCE_REFUSAL

    monkeypatch.setattr(gpu, "prepare_phase", reject)
    monkeypatch.setattr(
        runtime,
        "_run_skill",
        lambda *a, **k: pytest.fail("refused inference reached scientific skill"),
    )
    bindings = SimpleNamespace(
        **{
            name: None
            for name in (
                "agent_input",
                "anchor_map_data",
                "expert_advice_str",
                "file_index",
                "run_deliverable_naming",
                "run_metric",
                "run_secondary_metrics",
                "run_name",
                "run_profile",
                "sandbox",
                "workspace",
            )
        }
    )
    prepared = SimpleNamespace(
        **{
            name: None
            for name in (
                "active_params",
                "eval_sample_set",
                "exp_id",
                "hypothesis",
                "model_type",
                "record_params",
                "ordering",
            )
        }
    )
    result = execution._run_local_evaluation_phase(
        bindings,
        prepared,
        SimpleNamespace(attempt_in_round=1, round_index=1),
        SimpleNamespace(name="training"),
        train_time=0.0,
    )
    assert result == execution.AttemptExecution.next_attempt()
    assert calls == ["inference"]
