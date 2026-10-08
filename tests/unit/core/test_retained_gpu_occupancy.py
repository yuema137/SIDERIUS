"""#634: a retired worker's demand cannot erase retained parent/device bytes.

These witnesses exercise producer/consumer boundaries and real phase refusal;
all GPU facts are synthetic, and no GPU, provider or training is used.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from core.runtime_control.admission import GpuAdmissionPolicy, evaluate_gpu_admission
from core.runtime_control.gpu_accounting import (
    DeviceIdentity,
    GpuAccountingSnapshot,
    ProcessOccupancy,
)
from core.runtime_control.gpu_measurement_classifier import classify_measurement
from core.runtime_control.gpu_requirement import MeasuredRequirementTable
from core.runtime_control.gpu_requirement_evidence import ProcessEvidence
from core.runtime_control.prephase_admission import decide_prephase_admission
from core.runtime_control.process_visibility import PROCESS_VISIBILITY_ENV
from tests.helpers.gpu_requirement import ended_worker_ownership
from tests.unit.core.test_namespace_gpu_visibility import invoke_phase
from tests.unit.core.test_prephase_admission import UUID, _phase, _run

DEVICE = DeviceIdentity(uuid=UUID, physical_index=7, logical_index=0)
ROOT = Path(__file__).resolve().parents[3]


def snapshot(*, own=500, other=0, residual=0, total=2000, **changes):
    values = dict(
        device=DEVICE,
        telemetry_available=True,
        device_total_mib=total,
        device_used_mib=own + other + residual,
        own_tree_mib=own,
        other_mib=other,
        per_pid_total_mib=own + other,
        unattributed_mib=residual,
        accounting_skew_mib=residual,
    )
    values.update(changes)
    return GpuAccountingSnapshot(**values)


def decide(current=None, **changes):
    values = dict(
        snapshot=snapshot() if current is None else current,
        requirement_mib=1000,
        requirement_provenance="measured",
        requirement_ownership=ended_worker_ownership(UUID),
        mode="formal",
        ceiling_gib=1200 / 1024,
    )
    values.update(changes)
    return evaluate_gpu_admission(**values)


def measurement(**changes):
    return _run(phases=(_phase(driver_tree_peak_mib=1000),), **changes)


@pytest.mark.parametrize("scale", [1, 8, 1024])
@pytest.mark.parametrize("split", [(500, 0, 0), (0, 500, 0), (0, 0, 500), (200, 200, 100)])
def test_parent_other_and_residual_each_consume_headroom_at_any_scale(scale, split):
    own, other, residual = (value * scale for value in split)
    result = decide(
        snapshot(own=own, other=other, residual=residual, total=2000 * scale),
        requirement_mib=1000 * scale,
        ceiling_gib=1200 * scale / 1024,
    )
    assert not result.admitted
    assert result.reason_code == "insufficient_headroom"
    assert result.evidence["aggregate_gib"] == 1500 * scale / 1024
    assert result.evidence["retained_own_tree_mib"] == own
    assert result.evidence["unattributed_mib"] == residual


@pytest.mark.parametrize("capacity", [1500, 4096, 131072])
@pytest.mark.parametrize("extra,accepted", [(0, True), (1, False)])
def test_exact_capacity_or_stricter_ceiling_never_acquires_rounding_padding(
    capacity, extra, accepted
):
    result = decide(
        snapshot(total=capacity),
        requirement_mib=1000 + extra,
        ceiling_gib=(1500 if capacity > 1500 else 999999) / 1024,
    )
    assert result.admitted is accepted
    assert result.evidence["effective_ceiling_gib"] == 1500 / 1024


def test_actual_prephase_producer_retains_ownership_and_refuses_parent_counterexample():
    result = decide_prephase_admission(
        measurement(), snapshot=snapshot(), mode="formal", ceiling_gib=1200 / 1024
    )
    assert result.disposition == "STOP_OVER_CAP"
    assert result.admission.reason_code == "insufficient_headroom"
    assert result.admission.evidence["requirement_ownership"]["process"]["worker_pid"] == 4242
    assert result.admission.evidence["aggregate_gib"] == 1500 / 1024
    assert result.requirement.driver_tree_peak_mib == 1000


@pytest.mark.parametrize(
    "facts",
    [
        {"exit_code": None},
        {"exit_code": 3},
        {"signal_number": 15},
        {"term_sent": True},
        {"kill_sent": True},
        {"group_cleanup_required": True},
        {"orphans_remaining": True},
    ],
)
def test_completed_looking_worker_with_unclean_lifecycle_has_no_positive_authority(facts):
    process = ProcessEvidence.model_validate(
        dict(worker_pid=4242, worker_pgid=4242, exit_code=0) | facts
    )
    result = decide_prephase_admission(
        measurement(process=process), snapshot=snapshot(), mode="formal", ceiling_gib=999
    )
    assert result.disposition == "STOP_MEASUREMENT_UNAVAILABLE"
    assert result.requirement.authority_refusal == "requirement_ownership_unavailable"
    assert result.requirement.ownership.process == process
    assert result.requirement.driver_tree_peak_mib == 1000
    assert result.table is None


@pytest.mark.parametrize(
    "status,outcome",
    [("CUDA_OOM", "MEASURED_CUDA_OOM"), ("DEADLINE_EXCEEDED", "MEASURED_HARD_TIMEOUT")],
)
def test_failure_facts_survive_even_when_the_worker_needed_cleanup(status, outcome):
    run = measurement(
        worker_status=status,
        soft_deadline_seconds=1,
        process=ProcessEvidence(worker_pid=4242, worker_pgid=4242, exit_code=1, term_sent=True),
    )
    result = classify_measurement(run)
    assert result.outcome == outcome
    assert result.driver_tree_peak_mib == 1000
    assert result.ownership.process.term_sent
    assert not result.authoritative


@pytest.mark.parametrize("rows", ["own_processes", "other_processes"])
def test_live_measured_pid_or_pid_reuse_cannot_be_added_as_new_worker_demand(rows):
    result = decide(snapshot(**{rows: (ProcessOccupancy(pid=4242, used_mib=500),)}), ceiling_gib=99)
    assert not result.admitted
    assert result.reason_code == "policy_unavailable"
    assert "still present" in result.evidence["requirement_error"]


def test_device_binding_is_uuid_based_not_index_or_vendor_name():
    wrong = ended_worker_ownership("GPU-other")
    assert decide(requirement_ownership=wrong).detail == "device_identity_mismatch"
    current = snapshot(
        device=DeviceIdentity(
            uuid=UUID,
            physical_index=2,
            logical_index=1,
            telemetry_backend="synthetic-other-backend",
        )
    )
    assert decide(current, ceiling_gib=2).admitted


@pytest.mark.parametrize("mode", ["formal", "trial"])
@pytest.mark.parametrize("limited", [False, True])
def test_unlabelled_promoted_values_follow_existing_gap_posture_not_guessed_ownership(
    mode, limited
):
    result = decide(
        snapshot(process_visibility="namespace_limited" if limited else None),
        requirement_provenance="promoted_measurement",
        requirement_ownership=None,
        mode=mode,
    )
    assert result.admitted is (mode == "trial" and not limited)
    assert result.requirement_source == "unavailable"
    assert "aggregate_gib" not in result.evidence


@pytest.mark.parametrize(
    "changes",
    [
        {"own_tree_mib": None},
        {"device_used_mib": None},
        {"unattributed_mib": 1},
        {"accounting_skew_mib": -1},
    ],
)
def test_unknown_or_incoherent_current_occupancy_never_becomes_zero(changes):
    result = decide(snapshot(**changes), ceiling_gib=99)
    assert not result.admitted
    assert result.reason_code == "measurement_unavailable"
    assert "aggregate_gib" not in result.evidence


@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize("watchdog", [False, True])
@pytest.mark.parametrize("mode", ["formal", "trial"])
@pytest.mark.parametrize("enforcement", ["observe_only", "enforce", "enforce_resource_limits"])
def test_real_phase_paths_apply_retained_parent_decision_with_existing_posture(
    tmp_path, monkeypatch, phase, watchdog, mode, enforcement
):
    import core.sandbox_executor as executor
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    monkeypatch.delenv(PROCESS_VISIBILITY_ENV, raising=False)
    monkeypatch.setattr("core.runtime_control.gpu_accounting.sample", lambda *a, **k: snapshot())
    monkeypatch.setattr(executor, "_make_phase_observer", lambda *a: None)

    # Observing a refusal still proceeds by explicit policy. Raise a dedicated
    # sentinel at the shared launcher so no model/training process can run.
    class ReachedLaunch(Exception):
        pass

    spawn = Mock(side_effect=ReachedLaunch)
    monkeypatch.setattr(executor, "_run_observed_subprocess", spawn)
    composition = compose_run_task_bindings(str(ROOT / "configs/task_composition/quickstart.yaml"))
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        sandbox = executor.TidmadSandbox(
            run_name="visibility", workspace=str(tmp_path), device_identity=DEVICE
        )
        sandbox.admission_policy = GpuAdmissionPolicy(
            mode=mode, enforcement=enforcement, ceiling_gib=1200 / 1024
        )
        requirement = classify_measurement(measurement())
        # Explicitly select this consumer phase; no inference producer or
        # training-to-inference fallback is introduced by the test.
        entry = requirement.as_admission_entry()
        sandbox.measured_requirement_table = MeasuredRequirementTable(
            entries={phase: entry}, measurements=(requirement,)
        )
        if enforcement == "observe_only" and phase == "inference":
            with pytest.raises(ReachedLaunch):
                invoke_phase(sandbox, phase, watchdog=watchdog)
            result = {"status": "test_launcher_reached"}
        else:
            result = invoke_phase(sandbox, phase, watchdog=watchdog)
    if enforcement == "observe_only":
        spawn.assert_called_once()
        assert result["status"] != "skipped_resource_admission"
    else:
        spawn.assert_not_called()
        assert result["status"] == "skipped_resource_admission"
        assert result["admission"]["reason_code"] == "insufficient_headroom"
        assert result["admission"]["evidence"]["aggregate_gib"] == 1500 / 1024


def test_absent_device_observation_keeps_process_failure_without_capacity_authority():
    run = measurement(
        observed_device_uuid=None,
        worker_status="WORKER_FAILURE",
        process=ProcessEvidence(worker_pid=4242, worker_pgid=4242, exit_code=3),
    )
    result = classify_measurement(run)
    assert result.outcome == "PROBE_INFRASTRUCTURE_FAILURE"
    assert result.ownership.device_uuid is None
    assert result.ownership.process.exit_code == 3
    assert not result.authoritative


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, -1])
def test_invalid_demand_cannot_become_authority_through_typed_table_or_direct_gate(bad):
    table = MeasuredRequirementTable(
        entries={
            "training": {
                "requirement_mib": bad,
                "provenance": "measured",
                "ownership": ended_worker_ownership(UUID).model_dump(),
            }
        }
    )
    evidence = table.for_phase_evidence("training")
    assert evidence.validation_error is not None
    result = decide(requirement_mib=bad, ceiling_gib=99)
    assert not result.admitted
    assert result.reason_code == "policy_unavailable"
    assert "aggregate_gib" not in result.evidence


@pytest.mark.parametrize(
    "filename",
    [
        "gpu_requirement_evidence.py",
        "admission.py",
        "isolated_admission.py",
        "prephase_admission.py",
        "pair_admission.py",
    ],
)
def test_changed_ownership_or_consumed_decision_source_invalidates_estimator_identity(
    monkeypatch, filename
):
    from core.preflight_estimation import estimation_assembly_digest

    baseline = estimation_assembly_digest()
    original = Path.read_bytes
    changed = ROOT / "src/core/runtime_control" / filename

    def read(path):
        value = original(path)
        return value + b"\n# changed decision authority\n" if path == changed else value

    monkeypatch.setattr(Path, "read_bytes", read)
    assert estimation_assembly_digest() != baseline
