"""M5 — a resource rejection must stop production; an evidence gap must not.

The pre-launch audit (2026-08-06) found the production GPU admission gate
recording `WOULD BE REFUSED` and continuing, so "admission" was telemetry
rather than admission. The operator froze the correction:

    external activity                          -> observation / provenance
    measurement integrity                      -> MeasurementValidity
    current resources + demand + safety policy -> Admission
        insufficient current resources -> production must NOT continue

These tests guard the two halves of that rule and the boundary between
them. Each names a defect no schema, type checker or Gate can catch,
because every one of them is about which *branch* the executor takes.
"""

from __future__ import annotations

import pytest

from core.runtime_control.admission import (
    ACCEPTED_ENFORCEMENT,
    RESOURCE_REJECTIONS,
    stops_phase,
)


class TestTheEnforcementQuestionHasOneHome:
    """`stops_phase` is the only place the posture is interpreted."""

    def test_observe_only_never_stops_anything(self):
        for reason in ("insufficient_headroom", "policy_unavailable", "measurement_unavailable"):
            assert stops_phase("observe_only", reason) is False

    def test_enforce_still_stops_on_every_adverse_decision(self):
        # B-G1/B-G2 are evidence about THIS behaviour. If a future change
        # narrows `enforce`, those runs stop describing the shipped guard
        # and the harness silently loses its teeth.
        for reason in ("insufficient_headroom", "policy_unavailable", "measurement_unavailable"):
            assert stops_phase("enforce", reason) is True

    def test_resource_posture_stops_only_the_resource_verdict(self):
        assert stops_phase("enforce_resource_limits", "insufficient_headroom") is True
        assert stops_phase("enforce_resource_limits", "policy_unavailable") is False
        assert stops_phase("enforce_resource_limits", "measurement_unavailable") is False

    def test_an_unrecognised_posture_does_not_enforce_here(self):
        # Validation belongs to GpuAdmissionPolicy. This function must not
        # invent enforcement for a value the policy layer would refuse.
        assert stops_phase("nonsense", "insufficient_headroom") is False

    def test_the_production_posture_is_an_accepted_value(self):
        assert "enforce_resource_limits" in ACCEPTED_ENFORCEMENT

    def test_only_headroom_is_classified_as_a_resource_verdict(self):
        # Hardcoded, not read back from the module under test: adding an
        # evidence gap here would refuse every formal INFERENCE phase,
        # because the prephase table carries `training` only.
        assert RESOURCE_REJECTIONS == frozenset({"insufficient_headroom"})


class _Decision:
    def __init__(self, reason_code: str):
        self.admitted = False
        self.reason_code = reason_code
        self.reason = f"synthetic {reason_code}"

    def model_dump(self, mode: str = "python"):
        return {"admitted": False, "reason_code": self.reason_code, "reason": self.reason}


class _Sandbox:
    """Enough of a sandbox for the executor's admission branch."""

    def __init__(self, enforcement: str):
        from core.runtime_control.admission import GpuAdmissionPolicy
        from core.runtime_control.gpu_accounting import DeviceIdentity

        self.device_identity = DeviceIdentity(
            uuid="GPU-00000000-0000-0000-0000-000000000000",
            physical_index=0,
            logical_index=0,
        )
        self.admission_policy = GpuAdmissionPolicy(
            mode="formal", enforcement=enforcement, provenance={}
        )
        self.run_name = "m5_probe"
        self.admission_observations: list[dict] = []


def _run_gate(monkeypatch, *, enforcement: str, reason_code: str):
    """Drive the REAL executor branch with a synthetic adverse decision.

    Patching `evaluate_gpu_admission` (not the branch) keeps the test
    about what the executor DOES with a verdict, which is the thing that
    regressed. If the production path stopped calling the gate at all,
    `_admission_refusal` would return None here and the resource test
    below would fail — that is its reachability half.
    """
    import core.runtime_control.admission as admission_mod
    import core.sandbox_executor as executor

    monkeypatch.setattr(admission_mod, "evaluate_gpu_admission", lambda **_: _Decision(reason_code))
    monkeypatch.setattr("core.runtime_control.gpu_accounting.sample", lambda *_a, **_k: object())
    sandbox = _Sandbox(enforcement)
    return sandbox, executor._admission_refusal(sandbox, phase="training")


class TestTheExecutorConsumesTheVerdict:
    def test_a_resource_rejection_stops_the_phase_in_production(self, monkeypatch):
        sandbox, refusal = _run_gate(
            monkeypatch,
            enforcement="enforce_resource_limits",
            reason_code="insufficient_headroom",
        )
        assert refusal is not None, (
            "a valid measurement rejecting the candidate for insufficient current "
            "resources must not launch the phase — this is the M5 defect"
        )
        assert refusal["status"] == "skipped_resource_admission"
        assert sandbox.admission_observations == []

    @pytest.mark.parametrize("reason_code", ["policy_unavailable", "measurement_unavailable"])
    def test_an_evidence_gap_is_observed_not_enforced(self, monkeypatch, reason_code):
        # Enforcing this would refuse every formal inference phase, because
        # the prephase table has no `inference` entry by construction.
        sandbox, refusal = _run_gate(
            monkeypatch, enforcement="enforce_resource_limits", reason_code=reason_code
        )
        assert refusal is None
        assert len(sandbox.admission_observations) == 1
        assert (
            sandbox.admission_observations[0]["not_enforced_because"]
            == "reason_code_is_not_a_resource_rejection"
        )

    def test_observe_only_records_why_it_did_not_enforce(self, monkeypatch):
        sandbox, refusal = _run_gate(
            monkeypatch, enforcement="observe_only", reason_code="insufficient_headroom"
        )
        assert refusal is None
        assert (
            sandbox.admission_observations[0]["not_enforced_because"] == "enforcement_observe_only"
        )

    def test_the_observation_carries_the_reason_code(self, monkeypatch):
        # Without this an audit cannot tell a resource verdict from an
        # evidence gap in the observe-only record, which is the whole
        # basis on which the posture is judged after a campaign.
        sandbox, _ = _run_gate(
            monkeypatch, enforcement="observe_only", reason_code="policy_unavailable"
        )
        assert sandbox.admission_observations[0]["reason_code"] == "policy_unavailable"
