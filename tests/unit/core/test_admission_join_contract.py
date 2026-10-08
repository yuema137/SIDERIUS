"""B-C4d — the executor's refusal, understood by the tuner unchanged.

Every other admission test drives one side against a fixture. The
executor is checked against a dict the test wrote; the tuner is checked
against a dict the test wrote. Both stay green if the shape between them
drifts.

The concrete failure that would hide there: rename the `admission` key
and the tuner's `status.get("admission") or {}` yields `{}`, so
`reason_code` falls back to `policy_unavailable`. A refusal caused by
measured insufficient headroom is then recorded as a missing policy —
the environment blamed for the wrong thing, silently, with both unit
suites passing.

So nothing here rebuilds the payload. The executor's real output object
is handed to the tuner's real handler, and the assertions are on the
`ExperimentRecord` that comes out the far end.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord
from agent.schemas.ordering import resolve_ordering
from core.runtime_control.gpu_accounting import DeviceIdentity, GpuAccountingSnapshot
from core.sandbox_executor import _admission_refusal
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    RESOURCE_ADMISSION_STATUS,
    _handle_admission_refusal,
    _may_advise_resource_reduction,
)
from tests.helpers.gpu_requirement import ended_worker_ownership

DEV = DeviceIdentity(uuid="GPU-aaaa-0000", physical_index=0)
PHASES = ["training", "inference"]

#: The exact production strings a refusal must never carry.
TRAIN_SHRINK = "reduce model size, batch_size, or segmentation_size."
INFER_SHRINK = "reduce batch_size or model size."


def _crowded_snapshot():
    """20 GiB held by somebody else on a 31.25 GiB card."""
    return GpuAccountingSnapshot(
        device=DEV,
        telemetry_available=True,
        device_total_mib=32_000,
        device_used_mib=20_000,
        own_tree_mib=0,
        other_mib=20_000,
        other_process_count=1,
        per_pid_total_mib=20_000,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )


class _Sandbox:
    """The attributes the gate reads, plus a record sink."""

    def __init__(self, **kw):
        self.device_identity = DEV
        self.run_name = "join_contract"
        self.admission_mode = "trial"
        self.measured_requirements = {
            "training": {
                "requirement_mib": 20_000,
                "provenance": "measured",
                "ownership": ended_worker_ownership(DEV.uuid).model_dump(),
            },
            "inference": {
                "requirement_mib": 20_000,
                "provenance": "measured",
                "ownership": ended_worker_ownership(DEV.uuid).model_dump(),
            },
        }
        self.saved: list[dict] = []
        for k, v in kw.items():
            setattr(self, k, v)

    def save_record(self, record):
        self.saved.append(record)


def _real_refusal(sandbox, phase):
    """The executor's genuine output.

    Only the sampler is substituted — `evaluate_gpu_admission` runs for
    real, so the dict below is the one production would produce.
    """
    with (
        patch("core.runtime_control.gpu_accounting.sample", return_value=_crowded_snapshot()),
        patch.object(subprocess, "Popen") as popen,
        patch.object(subprocess, "run") as run,
    ):
        status = _admission_refusal(sandbox, phase=phase)
    return status, popen, run


def _joined(phase, sandbox=None):
    """Executor -> tuner, with nothing rewritten in between."""
    sandbox = sandbox or _Sandbox()
    status, popen, run = _real_refusal(sandbox, phase)
    assert status is not None, "the fixture must actually be refused"
    handled = _handle_admission_refusal(
        status,
        phase=phase,
        sandbox=sandbox,
        exp_id="e1",
        model_type="wavenet",
        file_index=0,
        record_params={"batch_size": 4},
        expert_advice_str="none",
        hypothesis="fixture",
        round_index=2,
        attempt_in_round=1,
        ordering=resolve_ordering(resolved_scope=[0]),
        is_trial=False,
    )
    return status, handled, sandbox, popen, run


class TestTheRefusalSurvivesTheJoin:
    @pytest.mark.parametrize("phase", PHASES)
    def test_the_executor_really_refuses_this_fixture(self, phase):
        """Guards the test itself: if admission stopped refusing, every
        assertion below would pass vacuously against an empty run."""
        status, _, _ = _real_refusal(_Sandbox(), phase)
        assert status is not None
        assert status["status"] == RESOURCE_ADMISSION_STATUS
        assert status["admission"]["reason_code"] == "insufficient_headroom"

    @pytest.mark.parametrize("phase", PHASES)
    def test_the_tuner_handles_the_executors_own_output(self, phase):
        _, handled, sandbox, _, _ = _joined(phase)
        assert handled is True
        assert len(sandbox.saved) == 1
        assert sandbox.saved[0]["status"] == RESOURCE_ADMISSION_STATUS

    @pytest.mark.parametrize("phase", PHASES)
    def test_the_reason_code_is_not_silently_downgraded(self, phase):
        """The defect this file exists for. A key rename between the
        layers turns a measured capacity shortfall into a missing
        policy, and no single-sided test can see it."""
        status, _, sandbox, _, _ = _joined(phase)
        assert status["admission"]["reason_code"] == "insufficient_headroom"
        assert sandbox.saved[0]["memory"]["reason_code"] == "insufficient_headroom"
        assert sandbox.saved[0]["memory"]["reason_code"] != "policy_unavailable"

    @pytest.mark.parametrize("phase", PHASES)
    def test_the_detail_field_survives(self, phase):
        """`detail` is `None` for a headroom refusal — carried through as
        `None`, not dropped, so the two are distinguishable downstream."""
        status, _, sandbox, _, _ = _joined(phase)
        evidence = sandbox.saved[0]["memory"]["admission_evidence"]
        assert "detail" in evidence
        assert evidence["detail"] == status["admission"]["detail"]

    @pytest.mark.parametrize("phase", PHASES)
    def test_the_audit_figures_survive(self, phase):
        """Mode and the measured figures must reach the record, or a
        later reader cannot re-derive why the phase was refused."""
        status, _, sandbox, _, _ = _joined(phase)
        recorded = sandbox.saved[0]["memory"]["admission_evidence"]["evidence"]
        produced = status["admission"]["evidence"]
        assert recorded == produced
        assert recorded["mode"] == "trial"
        assert recorded["other_mib"] == 20_000
        assert recorded["requirement_mib"] == 20_000
        assert recorded["requirement_provenance"] == "measured"

    @pytest.mark.parametrize("phase", PHASES)
    def test_an_invalid_mode_arrives_as_a_misconfiguration_not_a_shortfall(self, phase):
        """The other direction of the same risk: a policy problem must
        not be recorded as a capacity one."""
        sandbox = _Sandbox(admission_mode="formL")
        status, _, sandbox, _, _ = _joined(phase, sandbox)
        assert status["admission"]["reason_code"] == "policy_unavailable"
        memory = sandbox.saved[0]["memory"]
        assert memory["reason_code"] == "policy_unavailable"
        assert memory["admission_evidence"]["detail"] == "invalid_admission_mode"
        assert memory["admission_evidence"]["evidence"]["mode"] == "formL"


class TestTheJoinedRecordIsSafe:
    @pytest.mark.parametrize("phase", PHASES)
    def test_no_gpu_subprocess_is_started(self, phase):
        _, _, _, popen, run = _joined(phase)
        assert popen.call_count == 0
        assert run.call_count == 0

    @pytest.mark.parametrize("phase", PHASES)
    def test_the_record_validates(self, phase):
        _, _, sandbox, _, _ = _joined(phase)
        rec = ExperimentRecord.model_validate(sandbox.saved[0])
        assert rec.status == RESOURCE_ADMISSION_STATUS
        assert rec.denoising_score is None

    @pytest.mark.parametrize("phase", PHASES)
    def test_it_carries_no_shrink_advice(self, phase):
        _, _, sandbox, _, _ = _joined(phase)
        memory = sandbox.saved[0]["memory"]
        blob = f"{memory['conclusion']} {memory['discovery']} {memory['memory_update']}"
        assert TRAIN_SHRINK not in blob
        assert INFER_SHRINK not in blob
        assert "Do NOT reduce model" in memory["memory_update"]

    @pytest.mark.parametrize("phase", PHASES)
    def test_it_carries_no_reduction_authority(self, phase):
        _, _, sandbox, _, _ = _joined(phase)
        assert _may_advise_resource_reduction(sandbox.saved[0]) is False

    @pytest.mark.parametrize("phase", PHASES)
    def test_the_budget_accounting_survives_the_join(self, phase):
        _, _, sandbox, _, _ = _joined(phase)
        assert sandbox.saved[0]["counts_toward_attempt_budget"] is True
        assert sandbox.saved[0]["counts_toward_completed_rounds"] is False


def _measured() -> dict:
    """B-G0's real per-phase figures, rebuilt per call.

    A module-level dict would be shared mutable state across tests, and
    these are handed to production code that could in principle mutate
    them.
    """
    return {
        "training": {
            "requirement_mib": 1_476,
            "provenance": "measured",
            "ownership": ended_worker_ownership(DEV.uuid).model_dump(),
        },
        "inference": {
            "requirement_mib": 2_716,
            "provenance": "measured",
            "ownership": ended_worker_ownership(DEV.uuid).model_dump(),
        },
    }


class TestPhaseSpecificRequirement:
    """B-G0 measured the same candidate at 1,476 MiB training and
    2,716 MiB inference — 1.8x apart, one card, one run. A single figure
    shared by both gates judges each phase by a measurement of the
    other."""

    @staticmethod
    def _packed_snapshot():
        """Crowded enough that even the small training figure refuses, so
        the decision's evidence is inspectable. With headroom to spare
        admission would (correctly) return None and expose nothing."""
        return GpuAccountingSnapshot(
            device=DEV,
            telemetry_available=True,
            device_total_mib=32_000,
            device_used_mib=31_500,
            own_tree_mib=0,
            other_mib=31_500,
            other_process_count=1,
            per_pid_total_mib=31_500,
            unattributed_mib=0,
            accounting_skew_mib=0,
        )

    def _decide(self, phase, requirements, mode="formal"):
        from core.sandbox_executor import _admission_refusal

        sandbox = _Sandbox(admission_mode=mode, measured_requirements=requirements)
        with (
            patch(
                "core.runtime_control.gpu_accounting.sample",
                return_value=self._packed_snapshot(),
            ),
            patch.object(subprocess, "Popen"),
        ):
            return _admission_refusal(sandbox, phase=phase)

    @pytest.mark.parametrize("phase,expected", [("training", 1_476), ("inference", 2_716)])
    def test_each_gate_reads_its_own_phase(self, phase, expected):
        status = self._decide(phase, _measured())
        assert status is not None
        assert status["admission"]["evidence"]["requirement_mib"] == expected

    @pytest.mark.parametrize(
        "missing,present", [("training", "inference"), ("inference", "training")]
    )
    def test_a_missing_phase_is_policy_unavailable_in_formal(self, missing, present):
        """No cross-phase fallback: the other phase's figure must not
        stand in, and neither may the larger of the two."""
        status = self._decide(missing, {present: _measured()[present]})
        assert status is not None
        assert status["admission"]["reason_code"] == "policy_unavailable"
        # Present but None — the gate must record that it had no figure,
        # not silently omit the field.
        assert status["admission"]["evidence"]["requirement_mib"] is None

    def test_no_phase_at_all_is_policy_unavailable(self):
        status = self._decide("training", {})
        assert status is not None
        assert status["admission"]["reason_code"] == "policy_unavailable"

    def test_the_larger_figure_is_not_substituted(self):
        """Supplying only inference (the larger) must not satisfy the
        training gate, however 'safe' that would appear."""
        status = self._decide("training", {"inference": _measured()["inference"]})
        assert status["admission"]["reason_code"] == "policy_unavailable"

    def test_trial_still_proceeds_when_a_phase_is_unmeasured(self):
        status = self._decide("training", {}, mode="trial")
        assert status is None

    def test_a_malformed_entry_does_not_leak_a_number(self):
        for bad in (
            {"training": None},
            {"training": {"provenance": "measured"}},
            {"training": 1476},
        ):
            status = self._decide("training", bad)
            assert status is not None
            assert status["admission"]["reason_code"] == "policy_unavailable"
