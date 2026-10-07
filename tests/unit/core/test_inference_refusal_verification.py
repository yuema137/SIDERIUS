"""Admission must not turn incomplete inference observations into capacity facts."""

import pytest

from agent.schemas.preflight import StaticPreflightEvidence
from core.runtime_control.inference_refusal_verification import (
    eligible_inference_refusal,
    preflight_allows_execution,
    preflight_inference_batch,
    preflight_refusal_detail,
)
from tests.helpers.inference_verification import MIB, _static, _verification


@pytest.mark.parametrize(("samples", "batch"), [(1, 1), (5, 2), (65, 32)])
def test_complete_observation_admits_its_batch_without_rewriting_static_evidence(samples, batch):
    """Full/tail/scaled workloads must clear only the measured batch; static provenance stays refused."""
    verification = _verification(samples=samples, batch=batch)
    assert verification.assessment[0] == "admitted"
    result = {
        "feasible": False,
        "preflight_outcome": "STATIC_PREFLIGHT_REFUSAL",
        "static_preflight_evidence": verification.static_evidence.model_dump(),
        "inference_verification": verification.model_dump(),
    }
    assert preflight_allows_execution(result)
    assert preflight_inference_batch(result) == batch
    assert result["feasible"] is False
    assert result["preflight_outcome"] == "STATIC_PREFLIGHT_REFUSAL"
    assert "does not certify" in preflight_refusal_detail(result)


@pytest.mark.parametrize("peak", [700 * MIB, 500 * MIB + 1])
def test_context_overhead_cannot_hide_a_released_reservation_peak(peak):
    """500 allocator + 300 context samples 800, but transient 700 actually needs 1000 (>900)."""
    verification = _verification(peak_bytes=peak)
    assert verification.assessment[0] == "unavailable"
    assert "not resident" in verification.assessment[1]


def test_released_intermediate_is_safe_when_its_allocator_backing_remains_visible():
    verification = _verification(peak_bytes=700 * MIB, held_bytes=700 * MIB, driver_mib=850)
    assert verification.assessment[0] == "admitted"


@pytest.mark.parametrize(
    "defect",
    [
        "wrong_device_oom",
        "wrong_request",
        "wrong_source",
        "orphan",
        "missing_setup",
        "gappy_setup",
        "missing_hold",
        "stale_ack",
        "unstable_reservation",
        "missing_peak",
        "partial_data",
    ],
)
def test_incomplete_evidence_never_acquires_capacity_authority(defect):
    verification = _verification()
    run = verification.measurement
    assert run is not None
    setup, inference = run.phases
    if defect == "wrong_device_oom":
        run = run.model_copy(
            update={"observed_device_uuid": "GPU-other", "worker_status": "CUDA_OOM"}
        )
    elif defect == "wrong_request":
        run = run.model_copy(
            update={"request": run.request.model_copy(update={"request_id": "different"})}
        )
    elif defect == "wrong_source":
        run = run.model_copy(update={"inference_binding": None})
    elif defect == "orphan":
        run = run.model_copy(
            update={"process": run.process.model_copy(update={"orphans_remaining": True})}
        )
    elif defect == "missing_setup":
        run = run.model_copy(update={"phases": (inference,)})
    elif defect == "gappy_setup":
        setup = setup.model_copy(
            update={"coverage": setup.coverage.model_copy(update={"covered_whole_phase": False})}
        )
    elif defect == "missing_hold":
        setup = setup.model_copy(update={"observed_reservations": ()})
    elif defect in {"stale_ack", "unstable_reservation"}:
        hold = setup.observed_reservations[0]
        changes = (
            {"hold_id": "old:setup:1"} if defect == "stale_ack" else {"reserved_after_bytes": 0}
        )
        setup = setup.model_copy(
            update={"observed_reservations": (hold.model_copy(update=changes),)}
        )
    elif defect == "missing_peak":
        setup = setup.model_copy(update={"allocator_reserved_peak_bytes": None})
    elif defect == "partial_data":
        data = run.realism.inference_data
        assert data is not None
        run = run.model_copy(
            update={
                "realism": run.realism.model_copy(
                    update={"inference_data": data.model_copy(update={"consumed_samples": 1})}
                )
            }
        )
    if defect not in {"missing_setup"}:
        run = run.model_copy(update={"phases": (setup, inference)})
    verification = verification.model_copy(update={"measurement": run})
    assert verification.assessment[0] == "unavailable"


@pytest.mark.parametrize("kind", ["above_cap", "oom"])
def test_actual_capacity_failures_remain_distinct_from_unavailable(kind):
    verification = _verification(driver_mib=1000 if kind == "above_cap" else 800)
    if kind == "oom":
        assert verification.measurement is not None
        verification = verification.model_copy(
            update={
                "measurement": verification.measurement.model_copy(
                    update={"worker_status": "CUDA_OOM"}
                )
            }
        )
    assert verification.assessment[0] == "capacity_refused"


@pytest.mark.parametrize("case", ["training", "compute", "only_inference", "reversed"])
def test_only_passing_training_then_sole_inference_vram_refusal_is_eligible(case):
    training, inference = _static().phases
    if case == "training":
        training = training.model_copy(update={"vram_estimate_bytes": 2000 * MIB})
    if case == "compute":
        inference = inference.model_copy(update={"intensity_product": 20, "intensity_limit": 10})
    phases = (training, inference)
    if case == "only_inference":
        phases = (inference,)
    if case == "reversed":
        phases = (inference, training)
    assert eligible_inference_refusal(StaticPreflightEvidence(phases=phases)) is None


def test_completed_report_followed_by_deadline_kill_cannot_admit():
    """A result file can precede a hung interpreter shutdown; successful JSON is not clean completion."""
    verification = _verification()
    run = verification.measurement
    assert run is not None
    run = run.model_copy(
        update={
            "process": run.process.model_copy(
                update={"exit_code": -15, "signal_number": 15, "term_sent": True}
            ),
            "deadline": run.deadline.model_copy(update={"elapsed_seconds": 65}),
        }
    )
    assert verification.model_copy(update={"measurement": run}).assessment[0] == "unavailable"
