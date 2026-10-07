"""#633: a hidden process row cannot certify headroom or clean concurrency.

These witnesses exercise recorded driver arithmetic and actual launch callers;
no driver, CUDA, provider, scientific data, or copied implementation is involved.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.runtime_control.admission import GpuAdmissionPolicy, evaluate_gpu_admission
from core.runtime_control.calibration_policy import classify_contention_window
from core.runtime_control.gpu_accounting import (
    DeviceIdentity,
    GpuAccountingSnapshot,
    sample,
    sample_device_baseline,
)
from core.runtime_control.measurement_validity import (
    classify_measurement_validity,
    summarise_external_activity,
)
from core.runtime_control.probe import ContentionSnapshot, capture_contention_snapshot
from core.runtime_control.process_visibility import PROCESS_VISIBILITY_ENV

DEVICE = DeviceIdentity(uuid="GPU-synthetic-633", physical_index=0)
ROOT = Path(__file__).resolve().parents[3]


def accounting(**updates):
    # Recorded arithmetic, synthetic device/PID identity. Foreign 1986 MiB is
    # hidden inside the namespace and joins the 277 MiB driver residual.
    payload = dict(
        process_visibility="namespace_limited",
        device=DEVICE,
        telemetry_available=True,
        device_total_mib=32607,
        device_used_mib=2779,
        own_tree_mib=516,
        other_mib=0,
        other_process_count=0,
        per_pid_total_mib=516,
        unattributed_mib=2263,
        accounting_skew_mib=2263,
    )
    payload.update(updates)
    return GpuAccountingSnapshot(**payload)


def decide(snapshot=None, **updates):
    values = dict(
        snapshot=accounting() if snapshot is None else snapshot,
        requirement_mib=27 * 1024,
        requirement_provenance="measured",
        mode="formal",
        ceiling_gib=28,
    )
    values.update(updates)
    return evaluate_gpu_admission(**values)


def invoke_phase(sandbox, phase, *, watchdog=False):
    model = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
    loss = {"loss_type": "ce"}
    runtime = {"operator_budget_seconds": 60, "watchdog": {"enabled": watchdog}}
    options = {"runtime_policy": runtime, "sample_set": {"0": [0]}}
    if phase == "training":
        return sandbox.execute_training(
            "attempt",
            "visibility",
            "fcnet",
            model,
            {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
            loss,
            **options,
        )
    return sandbox.execute_inference("attempt", "visibility", "fcnet", model, loss, **options)


def test_recorded_hidden_bytes_change_admission_without_relabeling_them():
    decision = decide()
    assert not decision.admitted
    assert decision.reason_code == "environment_headroom_unproven"
    assert decision.evidence["outside_upper_bound_mib"] == 2263
    assert decision.evidence["aggregate_upper_bound_gib"] == (27648 + 2779) / 1024
    raw = decision.evidence["observed_accounting"]
    assert raw["other_mib"] == 0 and raw["own_tree_mib"] == 516
    assert "not evidence that the model is too large" in decision.reason


@pytest.mark.parametrize("capacity", [4096, 32768, 524288])
@pytest.mark.parametrize("offset,admitted", [(-1, True), (0, True), (1, False)])
def test_conservative_bound_scales_and_includes_exact_ceiling(capacity, offset, admitted):
    own, residual = capacity // 16, capacity // 8
    snapshot = accounting(
        device_total_mib=capacity,
        device_used_mib=own + residual,
        own_tree_mib=own,
        per_pid_total_mib=own,
        unattributed_mib=residual,
        accounting_skew_mib=residual,
    )
    decision = decide(
        snapshot, requirement_mib=capacity - own - residual + offset, ceiling_gib=capacity / 1024
    )
    assert decision.admitted is admitted
    assert decision.evidence["outside_upper_bound_mib"] == residual


@pytest.mark.parametrize(
    "corruption",
    [
        {"own_tree_mib": None},
        {"unattributed_mib": None},
        {"own_tree_mib": 517},
        {"device_used_mib": 32608},
        {"accounting_skew_mib": -1},
        {"per_pid_total_mib": 517},
    ],
)
def test_missing_or_inconsistent_accounting_does_not_prove_headroom(corruption):
    assert (
        decide(accounting(**corruption), requirement_mib=1).reason_code
        == "environment_headroom_unproven"
    )


@pytest.mark.parametrize(
    "requirement,provenance",
    [(None, None), (10, "predicted"), (float("nan"), "measured"), (float("inf"), "measured")],
)
def test_absent_or_unusable_phase_evidence_is_actionable(requirement, provenance):
    decision = decide(requirement_mib=requirement, requirement_provenance=provenance, mode="trial")
    assert not decision.admitted
    assert "phase-specific measurement evidence" in decision.reason
    assert "training evidence cannot substitute for inference" in decision.reason


def test_launcher_declaration_survives_real_child_environment(tmp_path, monkeypatch):
    from core.subprocess_env import subprocess_env
    from tools.workspace_sandbox.command import child_environment
    from tools.workspace_sandbox.profile import SandboxProfile

    profile = SandboxProfile(workspace=tmp_path, network=False, timeout_seconds=10)
    env = child_environment(profile, {})
    monkeypatch.setenv(PROCESS_VISIBILITY_ENV, env[PROCESS_VISIBILITY_ENV])
    child_env = subprocess_env()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from core.runtime_control.process_visibility import declared_visibility; print(declared_visibility())",
        ],
        env=child_env,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert result.stdout.strip() == "namespace_limited"
    with pytest.raises(ValueError, match="reserved"):
        SandboxProfile(
            workspace=tmp_path,
            network=False,
            timeout_seconds=10,
            environment_names=(PROCESS_VISIBILITY_ENV,),
        )


def test_collector_transports_partial_visibility_even_when_queries_fail(monkeypatch):
    monkeypatch.setenv(PROCESS_VISIBILITY_ENV, "namespace_limited")

    def query(argv, **kwargs):
        if "--query-gpu=index,uuid,memory.used,memory.total" in argv:
            return SimpleNamespace(stdout="0, GPU-synthetic-633, 2779, 32607")
        if "--query-gpu=utilization.gpu,memory.used" in argv:
            return SimpleNamespace(stdout="0, 2779")
        if "--query-gpu=clocks_throttle_reasons.active" in argv:
            return SimpleNamespace(stdout="0x0")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(subprocess, "run", query)
    snapshots = [sample(42, DEVICE), sample_device_baseline(DEVICE), capture_contention_snapshot()]
    assert all(s.process_visibility == "namespace_limited" for s in snapshots)

    def failed(*args, **kwargs):
        raise OSError("driver unavailable")

    monkeypatch.setattr(subprocess, "run", failed)
    assert sample(42, DEVICE).process_visibility == "namespace_limited"
    assert capture_contention_snapshot().process_visibility == "namespace_limited"


@pytest.mark.parametrize("declaration", ["", "global", "namespace-limitd"])
def test_bad_explicit_declaration_never_reverts_to_trial_permission(monkeypatch, declaration):
    monkeypatch.setenv(PROCESS_VISIBILITY_ENV, declaration)
    decision = evaluate_gpu_admission(
        snapshot=None, requirement_mib=None, requirement_provenance=None, mode="trial"
    )
    assert decision.reason_code == "environment_headroom_unproven"


def test_partial_rows_do_not_establish_cleanliness_or_absence_but_own_measurement_survives():
    quiet = ContentionSnapshot(
        process_visibility="namespace_limited",
        telemetry_available=True,
        gpu_utilization_pct=0,
        gpu_memory_used_gb=2779 / 1024,
        excluded_pids=(2,),
        compute_process_pids=(2,),
        compute_process_memory_gb={"2": 516 / 1024},
    )
    assert (
        classify_contention_window([quiet], device_vram_gb=32607 / 1024)[0] == "unknown_contention"
    )
    known = quiet.model_copy(update={"foreign_compute_pids": (3,), "foreign_compute_processes": 1})
    assert (
        classify_contention_window([known], device_vram_gb=32607 / 1024)[0] == "foreign_contended"
    )
    assert (
        classify_contention_window([known], device_vram_gb=32607 / 1024, expected_peer_pids=(3,))[0]
        == "unknown_contention"
    )
    assert summarise_external_activity([accounting()]).activity == "unknown"
    assert (
        classify_measurement_validity([accounting(), accounting()])[0] == "valid_current_conditions"
    )
    assert (
        classify_measurement_validity([accounting(), accounting(unattributed_mib=2264)])[0]
        == "candidate_attribution_failed"
    )


@pytest.mark.parametrize("watchdog", [False, True])
@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize("mode", ["trial", "formal"])
@pytest.mark.parametrize("enforcement", ["observe_only", "enforce", "enforce_resource_limits"])
def test_real_phase_callers_do_not_spawn_without_phase_evidence(
    tmp_path, monkeypatch, phase, mode, enforcement, watchdog
):
    import core.sandbox_executor as executor
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    monkeypatch.setenv(PROCESS_VISIBILITY_ENV, "namespace_limited")
    monkeypatch.setattr("core.runtime_control.gpu_accounting.sample", lambda *a, **k: accounting())
    monkeypatch.setattr(executor, "_make_phase_observer", lambda *a: None)
    spawn = Mock(side_effect=AssertionError("actual phase must not launch"))
    monkeypatch.setattr(executor, "_run_observed_subprocess", spawn)
    composition = compose_run_task_bindings(str(ROOT / "configs/task_composition/quickstart.yaml"))
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        sandbox = executor.TidmadSandbox(
            run_name="visibility", workspace=str(tmp_path), device_identity=DEVICE
        )
        sandbox.admission_policy = GpuAdmissionPolicy(
            mode=mode, enforcement=enforcement, ceiling_gib=28
        )
        # A valid TRAINING figure is deliberately present for inference: it
        # must never become inference's requirement.
        sandbox.measured_requirements = (
            {"training": {"requirement_mib": 1, "provenance": "measured"}}
            if phase == "inference"
            else {}
        )
        result = invoke_phase(sandbox, phase, watchdog=watchdog)
    assert result["status"] == "skipped_resource_admission"
    assert result["admission"]["reason_code"] == "environment_headroom_unproven"
    assert (
        result["admission"]["evidence"]["effective_execution_conditions"]["refusal_enforcement"]
        == "all_phase_modes"
    )
    spawn.assert_not_called()


def test_policy_exception_does_not_escape_via_trial_fallback(monkeypatch):
    from core.sandbox_executor import _admission_refusal

    monkeypatch.setenv(PROCESS_VISIBILITY_ENV, "namespace_limited")
    monkeypatch.setattr("core.runtime_control.gpu_accounting.sample", lambda *a: accounting())
    monkeypatch.setattr(
        "core.runtime_control.admission.evaluate_gpu_admission",
        Mock(side_effect=RuntimeError("bad policy")),
    )
    sandbox = SimpleNamespace(
        device_identity=DEVICE,
        admission_policy=GpuAdmissionPolicy(mode="trial"),
        measured_requirements={},
    )
    result = _admission_refusal(sandbox, phase="training")
    assert result["admission"]["reason_code"] == "environment_headroom_unproven"


def test_infrastructure_record_retains_decision_and_forbids_shrink():
    from nodes.ml_hyperparameter_tune_agent.records import _build_resource_admission_record

    decision = decide()
    record = _build_resource_admission_record(
        resource_type="gpu_memory",
        reason_code=decision.reason_code,
        detail=decision.reason,
        exp_id="attempt",
        model_type="synthetic",
        file_index=0,
        record_params={},
        expert_advice_str="",
        hypothesis="",
        round_index=0,
        attempt_in_round=1,
        admission_evidence=decision.model_dump(mode="json"),
    )
    assert record["status"] == "skipped_infrastructure_failure"
    assert record["denoising_score"] is None
    assert record["memory"]["admission_evidence"]["evidence"]["outside_upper_bound_mib"] == 2263
    assert "Do NOT reduce model" in json.dumps(record)


@pytest.mark.parametrize("phase", ["training", "inference"])
def test_executor_refusal_reaches_tuner_as_environment_evidence(monkeypatch, phase):
    from agent.schemas.ordering import resolve_ordering
    from core.sandbox_executor import _admission_refusal
    from nodes.ml_hyperparameter_tune_agent.runtime import _handle_admission_refusal

    records = []
    sandbox = SimpleNamespace(
        device_identity=DEVICE,
        run_name="join",
        save_record=records.append,
        admission_policy=GpuAdmissionPolicy(
            mode="trial", enforcement="observe_only", ceiling_gib=28
        ),
        measured_requirements={},
    )
    monkeypatch.setattr("core.runtime_control.gpu_accounting.sample", lambda *a: accounting())
    status = _admission_refusal(sandbox, phase=phase)
    assert _handle_admission_refusal(
        status,
        phase=phase,
        sandbox=sandbox,
        exp_id="attempt",
        model_type="synthetic",
        file_index=0,
        record_params={},
        expert_advice_str="",
        hypothesis="",
        round_index=0,
        attempt_in_round=1,
        ordering=resolve_ordering(resolved_scope=[0]),
        is_trial=True,
    )
    assert len(records) == 1
    record = records[0]
    assert record["status"] == "skipped_infrastructure_failure"
    assert record["denoising_score"] is None
    assert record["memory"]["reason_code"] == "environment_headroom_unproven"
    assert record["memory"]["admission_evidence"] == status["admission"]
    assert "Do NOT reduce model" in json.dumps(record)


@pytest.mark.parametrize(
    "attempted,expected", [(31000, "unknown"), (32500, "candidate_gpu_capacity")]
)
def test_hidden_occupancy_preserves_candidate_favorable_oom_interval(attempted, expected):
    from core.runtime_control.failure_attribution import attribute_gpu_failure
    from core.runtime_control.gpu_accounting import DeviceBaselineSnapshot
    from core.runtime_control.gpu_observer import GpuEvidenceBundle, GpuObservationPolicy

    snapshot = accounting()
    bundle = GpuEvidenceBundle(
        device=DEVICE,
        sampling_policy=GpuObservationPolicy(),
        baseline_before_spawn=DeviceBaselineSnapshot(
            device=DEVICE,
            telemetry_available=True,
            sampled_at=1,
            device_total_mib=32607,
            device_used_mib=2263,
            device_free_mib=30344,
        ),
        observed_peak=snapshot,
        last_while_alive=snapshot,
        valid_sample_count=10,
        child_runtime_ms=10000,
        last_valid_offset_ms=9900,
    )
    result = attribute_gpu_failure(
        bundle=bundle,
        attempted_allocation_mib=attempted,
        failure_text="CUDA out of memory. Tried to allocate 31 GiB",
    )
    assert result.attribution == expected
    assert result.evidence["free_without_all_possible_other_mib"] == 32091
    assert result.may_recommend_resource_reduction is (expected == "candidate_gpu_capacity")


@pytest.mark.parametrize("availability", [None, True, False, "False", 0])
@pytest.mark.parametrize("phase", ["training", "inference"])
def test_missing_identity_only_permits_explicit_cpu_before_real_launch(
    tmp_path, monkeypatch, availability, phase
):
    import core.sandbox_executor as executor
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    class LaunchReached(BaseException):
        pass

    monkeypatch.setenv(PROCESS_VISIBILITY_ENV, "namespace_limited")
    monkeypatch.setattr(executor, "_make_phase_observer", lambda *a: None)
    spawn = Mock(side_effect=LaunchReached)
    monkeypatch.setattr(executor, "_run_observed_subprocess", spawn)
    composition = compose_run_task_bindings(str(ROOT / "configs/task_composition/quickstart.yaml"))
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        sandbox = executor.TidmadSandbox(
            run_name="visibility",
            workspace=str(tmp_path),
            device_available=availability,
        )
        if availability is False:
            with pytest.raises(LaunchReached):
                invoke_phase(sandbox, phase)
            spawn.assert_called_once()
        else:
            result = invoke_phase(sandbox, phase)
            assert result["admission"]["reason_code"] == "environment_headroom_unproven"
            spawn.assert_not_called()


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("stub", [False, True])
def test_actual_tuner_factory_call_transports_validated_hardware_fact(
    tmp_path, monkeypatch, available, stub
):
    """Execute the source's factory expression; removing its transport breaks CPU evidence."""
    import ast
    from datetime import UTC, datetime

    from core.hardware_context import HardwareContext
    from core.sandbox_executor import StubSandbox, TidmadSandbox, _admission_refusal

    monkeypatch.setenv(PROCESS_VISIBILITY_ENV, "namespace_limited")
    hardware = HardwareContext(
        device_name="synthetic",
        total_memory_bytes=0,
        compute_capability=(0, 0),
        multiprocessor_count=0,
        torch_version="synthetic",
        hostname="synthetic",
        device_available=available,
        discovered_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    source = ROOT / "src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
    tree = ast.parse(source.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_sandbox_factory"
    ]
    assert len(calls) == 1
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    composition = compose_run_task_bindings(str(ROOT / "configs/task_composition/quickstart.yaml"))
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        sandbox = eval(
            compile(ast.Expression(calls[0]), str(source), "eval"),
            {
                "self": SimpleNamespace(_sandbox_factory=StubSandbox if stub else TidmadSandbox),
                "run_name": "transport",
                "workspace": str(tmp_path),
                "file_index": 0,
                "agent_input": SimpleNamespace(progress_bar=False, data_scope=None),
                "device_identity": None,
                "run_deliverable_naming": None,
                "hardware_context": hardware,
            },
        )
    assert sandbox.device_available is available
    assert (_admission_refusal(sandbox, phase="training") is None) is (not available)
    if stub:
        # Pseudo execution overrides the native methods and never needs admission.
        assert StubSandbox.execute_training is not TidmadSandbox.execute_training
        assert StubSandbox.execute_inference is not TidmadSandbox.execute_inference


def test_retained_parent_cuda_bytes_are_additional_to_new_worker_requirement():
    # The measured worker is gone; this 2-GiB parent remains while a new
    # 3-GiB phase starts. Subtracting the parent would falsely admit at4GiB.
    snapshot = accounting(
        device_total_mib=8192,
        device_used_mib=2048,
        own_tree_mib=2048,
        per_pid_total_mib=2048,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )
    decision = decide(snapshot, requirement_mib=3072, ceiling_gib=4)
    assert not decision.admitted
    assert decision.evidence["outside_upper_bound_mib"] == 0
    assert decision.evidence["retained_own_tree_mib"] == 2048
    assert decision.evidence["aggregate_upper_bound_gib"] == 5
