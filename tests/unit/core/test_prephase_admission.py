"""One disposition to the tuner, and a chain that fails when a link is cut.

V20 PR C2 / C2-6 and C2-7.

The chain this closes:

```text
exact candidate/config -> isolated worker -> process-tree sampler
  -> typed phase measurement -> authoritative requirement
  -> PR B admission -> formal launch or pre-launch stop
```

§8.A named the gap it replaces: `getattr(sandbox, "measured_requirements",
None)` was a read *no production code satisfied*, so PR B's gate was
correct, fully tested and unreachable. Tests that only check the gate's
logic cannot see that; the reachability tests below cut each producer to
consumer edge in turn and require a failure.

O-7 is asserted for **every** stop disposition rather than for a
representative one. The rules are identical across them by design, and a
per-disposition table is the only shape that catches one drifting.
"""

from __future__ import annotations

import pytest

from core.runtime_control.gpu_accounting import DeviceIdentity, GpuAccountingSnapshot
from core.runtime_control.gpu_measurement_identity import (
    build_planned_identity,
    build_realized_identity,
)
from core.runtime_control.gpu_measurement_runner import (
    HostMemoryBound,
    PhaseMeasurement,
    PrephaseMeasurementRun,
    ProcessEvidence,
)
from core.runtime_control.gpu_requirement import (
    ADMISSIBLE_PHASES,
    MEASURED_PROVENANCE,
    CandidateMeasurementRequest,
    MeasuredGpuRequirement,
    MeasuredRequirementTable,
    MeasurementDeadline,
    SamplingCoverage,
)
from core.runtime_control.prephase_admission import (
    attach_measured_requirements,
    decide_prephase_admission,
)

UUID = "GPU-c30b6678"
DEVICE = DeviceIdentity(uuid=UUID, physical_index=0)
REQUEST = CandidateMeasurementRequest(
    model_type="punet",
    planned_identity=build_planned_identity(model_type="punet", model_config={}, train_config={}),
    request_id="req-01234567",
    device_uuid=UUID,
    phase="training",
    deadline_seconds=120.0,
)


REALIZED = build_realized_identity(
    model_type="punet",
    optimizer_type="adamw",
    seg_size=40_000,
    batch_size=1,
    precision="float32",
    parameter_count=1_000_000,
    trainable_parameter_count=1_000_000,
)


def _snapshot(*, own_mib: int = 0, other_mib: int = 500) -> GpuAccountingSnapshot:
    return GpuAccountingSnapshot(
        device=DEVICE,
        telemetry_available=True,
        device_used_mib=own_mib + other_mib,
        device_total_mib=32_768,
        own_tree_mib=own_mib,
        other_mib=other_mib,
        other_process_count=1,
        per_pid_total_mib=own_mib + other_mib,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )


def _phase(**over) -> PhaseMeasurement:
    payload = dict(
        phase="training",
        status="COMPLETED",
        started_at=1000.0,
        ended_at=1010.0,
        elapsed_seconds=10.0,
        driver_tree_peak_mib=4_096,
        allocator_peak_mib=3_000,
        coverage=SamplingCoverage(interval_seconds=0.25, samples_taken=40),
        own_pids=(4242,),
        max_concurrent_own_processes=1,
    )
    payload.update(over)
    return PhaseMeasurement(**payload)  # type: ignore[arg-type]


def _run(**over) -> PrephaseMeasurementRun:
    payload = dict(
        label="c2-o7",
        request=REQUEST,
        worker_status="COMPLETED",
        report_present=True,
        observed_device_uuid=UUID,
        realized_identity=REALIZED,
        reported_request_id=REQUEST.request_id,
        phases=(_phase(),),
        deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=12.0),
        host_memory=HostMemoryBound(limit_bytes=24 * 1024**3, peak_tree_rss_bytes=2 * 1024**3),
        process=ProcessEvidence(worker_pid=4242, worker_pgid=4242, exit_code=0),
    )
    payload.update(over)
    return PrephaseMeasurementRun(**payload)  # type: ignore[arg-type]


def _decide(run=None, **over):
    kwargs = dict(snapshot=_snapshot(), mode="formal", ceiling_gib=24.0)
    kwargs.update(over)
    return decide_prephase_admission(run or _run(), **kwargs)  # type: ignore[arg-type]


class _Sandbox:
    """Stands in for the executor's sandbox: the object the requirement is
    attached to and later read from."""


class TestTheProvenanceCategoryPrBActuallyAccepts:
    def test_the_entry_carries_the_accepted_category_not_a_description(self):
        """A descriptive provenance string would be delivered, judged
        non-authoritative at `admission.py:429`, and refused as
        `policy_unavailable` -- the exact failure C2 exists to fix, one
        layer deeper and harder to see, because the requirement would be
        PRESENT and still not count."""
        entry = _authoritative().as_admission_entry()
        assert entry["provenance"] == MEASURED_PROVENANCE

    def test_the_description_survives_beside_it(self):
        entry = _authoritative().as_admission_entry()
        assert "isolated_prephase_measurement:training" in str(entry["measurement_detail"])

    def test_the_category_is_taken_from_admissions_own_frozen_set(self):
        from core.runtime_control.admission import AUTHORITATIVE_PROVENANCE

        assert MEASURED_PROVENANCE in AUTHORITATIVE_PROVENANCE


def _authoritative(**over) -> MeasuredGpuRequirement:
    payload = dict(
        request=REQUEST,
        outcome="COMPLETED_MEASUREMENT",
        driver_tree_peak_mib=4_096,
        allocator_peak_mib=3_000,
        observed_device_uuid=UUID,
        realized_identity=REALIZED,
        coverage=SamplingCoverage(interval_seconds=0.25, samples_taken=40),
        deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=12.0),
    )
    payload.update(over)
    return MeasuredGpuRequirement(**payload)  # type: ignore[arg-type]


class TestOnlyAnAuthoritativeMeasurementBecomesATable:
    def test_an_authoritative_measurement_assembles(self):
        table = MeasuredRequirementTable.from_measurements(_authoritative())
        assert table.for_phase("training") == (4_096, MEASURED_PROVENANCE)

    def test_a_refused_measurement_cannot_be_assembled(self):
        """Refusing must raise rather than skip. Skipping would produce a
        table missing a phase, which `_phase_requirement` reads as
        `(None, None)` -- indistinguishable from never having measured,
        and in trial mode that proceeds."""
        with pytest.raises(ValueError, match=r"not\s+authoritative"):
            MeasuredRequirementTable.from_measurements(
                _authoritative(observed_device_uuid="GPU-elsewhere")
            )

    def test_a_setup_measurement_never_reaches_the_table(self):
        setup = _authoritative(
            request=REQUEST.model_copy(update={"phase": "setup"}),
        )
        assert MeasuredRequirementTable.from_measurements(setup).entries == {}
        assert "setup" not in ADMISSIBLE_PHASES

    def test_a_missing_phase_is_never_answered_by_the_other_one(self):
        """B-G0 measured one PUNet candidate 1.8x apart across the two
        phases. There is deliberately no fallback."""
        table = MeasuredRequirementTable.from_measurements(_authoritative())
        assert table.for_phase("inference") == (None, None)


class TestTheChainReachesPrBsGate:
    def test_the_requirement_reaches_the_executors_read(self):
        """The whole point: `_phase_requirement` returns a real figure,
        where before C2 it returned `(None, None)` for every run."""
        from core.sandbox_executor import _phase_requirement

        sandbox = _Sandbox()
        assert attach_measured_requirements(sandbox, _decide()) is True
        assert _phase_requirement(sandbox, "training") == (4_096, MEASURED_PROVENANCE)

    def test_without_the_attach_step_the_gate_sees_nothing(self):
        """Cuts the producer->consumer edge: the measurement succeeded and
        was simply never delivered. Before C2 this was production's
        permanent state."""
        from core.sandbox_executor import _phase_requirement

        outcome = _decide()
        assert outcome.proceeds is True
        assert _phase_requirement(_Sandbox(), "training") == (None, None)

    def test_a_stop_attaches_nothing(self):
        outcome = _decide(_run(worker_status="WORKER_FAILURE", phases=()))
        assert attach_measured_requirements(_Sandbox(), outcome) is False

    def test_the_typed_table_outranks_a_duck_typed_dict(self):
        """Both channels exist -- the typed one for production, the plain
        dict for the B-G validation harness. When both are present the
        typed one wins, so the requirement cannot be read from two
        disagreeing places."""
        from core.sandbox_executor import _phase_requirement

        sandbox = _Sandbox()
        sandbox.measured_requirements = {  # type: ignore[attr-defined]
            "training": {"requirement_mib": 999, "provenance": "measured"}
        }
        attach_measured_requirements(sandbox, _decide())
        assert _phase_requirement(sandbox, "training") == (4_096, MEASURED_PROVENANCE)

    def test_the_harness_channel_still_works_on_its_own(self):
        """The B-G runs are evidence about this gate's behaviour; removing
        their injection seam would invalidate them."""
        from core.sandbox_executor import _phase_requirement

        sandbox = _Sandbox()
        sandbox.measured_requirements = {  # type: ignore[attr-defined]
            "training": {"requirement_mib": 999, "provenance": "measured"}
        }
        assert _phase_requirement(sandbox, "training") == (999, "measured")


class TestFormalAdmissionNoLongerReportsPolicyUnavailable:
    def test_an_authoritative_requirement_is_admitted_in_formal_mode(self):
        """Before C2, formal admission reported `policy_unavailable` on
        every run because nothing produced a requirement."""
        outcome = _decide()
        assert outcome.disposition == "PROCEED"
        assert outcome.admission is not None
        assert outcome.admission.admitted is True
        assert outcome.admission.reason_code is None

    def test_a_requirement_that_does_not_fit_the_device_is_refused(self):
        """Separate question from the cap: a candidate that fits the card
        may still not fit beside what is already on it."""
        outcome = _decide(snapshot=_snapshot(other_mib=30_000), ceiling_gib=24.0)
        assert outcome.disposition == "STOP_OVER_CAP"
        assert outcome.admission is not None and outcome.admission.admitted is False


class TestTheDispositionMapping:
    @pytest.mark.parametrize(
        "run_over,expected",
        [
            ({"worker_status": "CUDA_OOM", "phases": ()}, "STOP_MEASURED_OOM"),
            ({"worker_status": "WORKER_FAILURE", "phases": ()}, "STOP_INFRASTRUCTURE_FAILURE"),
            ({"worker_status": "DEVICE_UNAVAILABLE", "phases": ()}, "STOP_INFRASTRUCTURE_FAILURE"),
            ({"worker_status": "CONFIG_REJECTED", "phases": ()}, "STOP_INFRASTRUCTURE_FAILURE"),
            (
                {"worker_status": "COMPLETED", "phases": (_phase(driver_tree_peak_mib=None),)},
                "STOP_MEASUREMENT_UNAVAILABLE",
            ),
            (
                {"observed_device_uuid": "GPU-elsewhere"},
                "STOP_MEASUREMENT_UNAVAILABLE",
            ),
        ],
        ids=["oom", "crash", "no-device", "bad-config", "unobserved", "wrong-card"],
    )
    def test_each_outcome_maps_to_its_disposition(self, run_over, expected):
        assert _decide(_run(**run_over)).disposition == expected

    def test_a_timeout_maps_to_stop_timeout(self):
        outcome = _decide(
            _run(
                report_present=False,
                worker_status=None,
                phases=(),
                deadline=MeasurementDeadline(budget_seconds=120.0, elapsed_seconds=121.0),
            )
        )
        assert outcome.disposition == "STOP_TIMEOUT"

    def test_a_host_memory_excess_is_not_phrased_as_a_gpu_cap(self):
        """PR A is emphatic that a HOST result must never be phrased as a
        VRAM verdict -- the candidate may fit the GPU perfectly. Mapping it
        to `STOP_OVER_CAP` inside a GPU-admission boundary would read as
        exactly that (see D-C2-6)."""
        outcome = _decide(
            _run(
                host_memory=HostMemoryBound(
                    limit_bytes=24 * 1024**3, peak_tree_rss_bytes=25 * 1024**3, exceeded=True
                ),
                report_present=False,
                worker_status=None,
                phases=(),
            )
        )
        assert outcome.disposition == "STOP_PROBE_HOST_MEMORY_EXCEEDED"

    def test_an_above_cap_measurement_stops_over_cap(self):
        assert _decide(vram_cap_mib=1_000).disposition == "STOP_OVER_CAP"


_STOPS = [
    "STOP_MEASUREMENT_UNAVAILABLE",
    "STOP_OVER_CAP",
    "STOP_MEASURED_OOM",
    "STOP_TIMEOUT",
    "STOP_PROBE_HOST_MEMORY_EXCEEDED",
    "STOP_INFRASTRUCTURE_FAILURE",
]


class TestOSevenHoldsForEveryStop:
    """Asserted per disposition, not for a representative one. The rules
    are identical across them by design, and a table is the only shape that
    catches one of them drifting."""

    @pytest.mark.parametrize("disposition", _STOPS)
    def test_the_frozen_accounting(self, disposition):
        outcome = _decide(_run(worker_status="WORKER_FAILURE", phases=())).model_copy(
            update={"disposition": disposition}
        )
        assert outcome.attempt_consumed is True
        assert outcome.records_completed_round is False
        assert outcome.carries_candidate_blame is False
        assert outcome.permits_shrink_advice is False
        assert outcome.permits_same_attempt_retry is False
        assert outcome.may_launch_formal_phase is False

    def test_proceed_is_the_positive_control(self):
        """Without this the assertions above would pass on a boundary that
        stops for everything."""
        outcome = _decide()
        assert outcome.may_launch_formal_phase is True
        assert outcome.attempt_consumed is False

    def test_a_measured_oom_records_insufficiency_without_issuing_advice(self):
        """The fact is preserved; the instruction is not issued. O-7
        freezes this boundary as no proposal shrinking, and the evidence
        stays available for whoever is allowed to act on it."""
        outcome = _decide(_run(worker_status="CUDA_OOM", phases=()))
        assert outcome.requirement.establishes_insufficient_capacity is True
        assert outcome.permits_shrink_advice is False

    def test_every_stop_explains_itself(self):
        for over in ({"worker_status": "CUDA_OOM"}, {"worker_status": "WORKER_FAILURE"}):
            outcome = _decide(_run(phases=(), **over))
            assert outcome.detail, "a stop with no detail is unactionable"
            assert outcome.requirement is not None


def test_the_boundary_never_raises_for_a_measurement_result():
    """The control-flow rule. Exceptions are reserved for programming
    errors; every outcome O-7 has a rule for arrives as a value."""
    for status in ("CUDA_OOM", "WORKER_FAILURE", "DEVICE_MISMATCH", "CONFIG_REJECTED", None):
        outcome = _decide(_run(worker_status=status, report_present=status is not None, phases=()))
        assert outcome.disposition.startswith("STOP_")


class TestIdentityIntegrityIsCheckedBeforeAuthority:
    """D-C2-7. The parent must be able to prove the result answers the
    request it sent. A mismatch is an integrity failure of the measurement
    SYSTEM -- never candidate blame, never capacity evidence."""

    def test_a_stale_or_misrouted_result_is_refused(self):
        outcome = _decide(_run(reported_request_id="req-from-another-attempt"))
        assert outcome.disposition == "STOP_INFRASTRUCTURE_FAILURE"
        assert "request_id_mismatch" in outcome.detail
        assert outcome.requirement.authoritative is False

    def test_a_worker_that_built_something_else_is_refused(self):
        """Every overlapping planned/realized field is compared. Here the
        worker constructed a different batch size from the one requested --
        a real figure attributed to the wrong subject."""
        other = build_realized_identity(
            model_type="punet",
            optimizer_type="adamw",
            seg_size=40_000,
            batch_size=64,
            precision="float32",
            parameter_count=1_000_000,
            trainable_parameter_count=1_000_000,
        )
        outcome = _decide(_run(realized_identity=other))
        assert outcome.disposition == "STOP_INFRASTRUCTURE_FAILURE"
        assert "batch_size_mismatch" in outcome.detail

    def test_a_missing_realized_identity_is_refused(self):
        """The parent cannot compute one -- isolation forbids it building
        the candidate -- so an absent realized identity leaves the subject
        unverified, and an unverified subject cannot carry a requirement."""
        outcome = _decide(_run(realized_identity=None))
        assert outcome.requirement.authoritative is False
        assert outcome.disposition == "STOP_INFRASTRUCTURE_FAILURE"

    def test_an_identity_failure_is_never_candidate_blame(self):
        from agent.skills.evaluate_vram_skill.isolated_probe import NO_DOWNSIZING_AUTHORITY

        outcome = _decide(_run(reported_request_id="wrong"))
        assert outcome.requirement.outcome in NO_DOWNSIZING_AUTHORITY
        assert outcome.requirement.establishes_insufficient_capacity is False
        assert outcome.carries_candidate_blame is False

    def test_an_exact_match_reaches_pr_b(self):
        """Positive control: the check must refuse mismatches, not every
        measurement."""
        outcome = _decide()
        assert outcome.disposition == "PROCEED"
        assert outcome.admission is not None

    def test_the_authoritative_identity_is_the_realized_one(self):
        """The planned hash is request-binding and audit evidence; the
        realized hash identifies what was measured. Both are recorded, and
        the provenance names which is which."""
        entry = _decide().requirement.as_admission_entry()
        detail = str(entry["measurement_detail"])
        assert f"realized={REALIZED.realized_config_hash}" in detail
        assert f"planned={REQUEST.planned_identity.planned_config_hash}" in detail

    def test_the_realized_hash_uses_c1s_canonical_builder(self):
        """One definition of "same realized configuration", so a C2
        requirement and a C1 duration observation are comparable rather
        than merely similarly shaped -- the D-4 divergence, avoided."""
        from core.runtime_control.calibration_context import (
            CalibrationContextInputs,
            build_calibration_context,
            candidate_config_hash,
        )

        expected = candidate_config_hash(
            build_calibration_context(
                CalibrationContextInputs(
                    precision="float32",
                    optimizer_type="adamw",
                    model_family="punet",
                    param_count=1_000_000,
                    seg_size=40_000,
                    batch_size=1,
                )
            )
        )
        assert REALIZED.realized_config_hash == expected


class TestAHostMemoryStopNeverReachesPrB:
    """Host RSS is not VRAM demand. On 2026-07-31 a candidate reached
    60.5 GB of host RSS with the GPU at 273 MiB; delivering that figure to
    a GPU capacity gate would admit a CPU number as a VRAM one."""

    def _host_run(self):
        return _run(
            host_memory=HostMemoryBound(
                limit_bytes=24 * 1024**3, peak_tree_rss_bytes=25 * 1024**3, exceeded=True
            ),
            report_present=False,
            worker_status=None,
            phases=(),
        )

    def test_pr_bs_capacity_gate_is_never_called(self, monkeypatch):
        import core.runtime_control.prephase_admission as boundary

        def forbidden(**_kw):
            raise AssertionError("a host-memory figure was sent to GPU capacity admission")

        monkeypatch.setattr(boundary, "evaluate_gpu_admission", forbidden)
        outcome = decide_prephase_admission(
            self._host_run(), snapshot=_snapshot(), mode="formal", ceiling_gib=24.0
        )
        assert outcome.disposition == "STOP_PROBE_HOST_MEMORY_EXCEEDED"
        assert outcome.admission is None

    def test_no_gpu_requirement_is_produced(self):
        outcome = _decide(self._host_run())
        assert outcome.table is None
        assert outcome.carries_gpu_capacity_authority is False
        assert outcome.requirement.authoritative is False

    def test_the_host_figure_cannot_enter_measured_requirements(self):
        """Structural: the attach step refuses, so `_phase_requirement`
        sees nothing."""
        from core.sandbox_executor import _phase_requirement

        sandbox = _Sandbox()
        assert attach_measured_requirements(sandbox, _decide(self._host_run())) is False
        assert _phase_requirement(sandbox, "training") == (None, None)

    def test_it_is_not_a_gpu_capacity_verdict(self):
        outcome = _decide(self._host_run())
        assert outcome.requirement.establishes_insufficient_capacity is False, (
            "MEASURED_HOST_MEMORY_EXCEEDED says nothing about whether the candidate fits the GPU"
        )

    def test_it_still_carries_the_frozen_o7_accounting(self):
        outcome = _decide(self._host_run())
        assert outcome.attempt_consumed is True
        assert outcome.records_completed_round is False
        assert outcome.permits_shrink_advice is False
        assert outcome.permits_same_attempt_retry is False
        assert outcome.may_launch_formal_phase is False


class TestInferenceAuthorityIsBoundToItsBatch:
    """A measurement at batch 1 must not become authoritative for a formal
    inference phase running at batch 25 (Gate attempt 6: 1050 vs 3642 MiB)."""

    def _identities(self, planned_batch, realized_batch):
        planned = build_planned_identity(
            model_type="punet",
            model_config={},
            train_config={},
            inference_batch_size=planned_batch,
        )
        realized = build_realized_identity(
            model_type="punet",
            optimizer_type="adamw",
            seg_size=40_000,
            batch_size=1,  # the TRAINING batch, identical on both sides
            precision="float32",
            parameter_count=1_000_000,
            trainable_parameter_count=1_000_000,
            inference_batch_size=realized_batch,
        )
        return planned, realized

    def _compare(self, planned, realized, phase):
        from core.runtime_control.gpu_measurement_identity import compare_identities

        return compare_identities(planned, realized, requested_id="r", reported_id="r", phase=phase)

    def test_a_batch_mismatch_fails_closed_on_the_inference_phase(self):
        planned, realized = self._identities(25, 1)
        assert self._compare(planned, realized, "inference") == "inference_batch_size_mismatch"

    def test_a_matching_batch_passes(self):
        """Positive control."""
        planned, realized = self._identities(25, 25)
        assert self._compare(planned, realized, "inference") is None

    def test_an_absent_inference_batch_fails_closed(self):
        planned, realized = self._identities(None, None)
        assert self._compare(planned, realized, "inference") == "inference_batch_size_absent"

    def test_an_inference_field_never_invalidates_a_training_measurement(self):
        """Phase-aware on purpose: the validated 1474/1476 MiB training
        result must not be disturbed by an inference-only field."""
        planned, realized = self._identities(25, 1)
        assert self._compare(planned, realized, "training") is None

    def test_the_workload_hash_changes_with_the_batch(self):
        """Two inference measurements differing only in batch must not share
        an identity."""
        a, _ = self._identities(1, 1)
        b, _ = self._identities(25, 25)
        assert a.inference_workload_hash != b.inference_workload_hash

    def test_the_training_config_hash_is_untouched_by_the_batch(self):
        """C1's definition of "same realized configuration" describes a
        TRAINING configuration and must not be redefined here."""
        a, _ = self._identities(None, None)
        b, _ = self._identities(25, 25)
        assert a.planned_config_hash == b.planned_config_hash
