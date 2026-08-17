"""B-C4a — the pre-phase admission decision.

A6 measured a candidate admitted on a 6.43 GB predicted estimate go on
to hold 12.52 GiB. Comparing a predicted *allocated* figure against a
driver-visible ceiling is the defect PR B exists to remove, rebuilt
behind a guard that would then look like it was working. So these tests
are mostly about what the guard **refuses to conclude**.

The commit deliberately has no production caller; wiring is B-C4b.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.runtime_control.admission import (
    AUTHORITATIVE_PROVENANCE,
    AdmissionDecision,
    evaluate_gpu_admission,
)
from core.runtime_control.gpu_accounting import DeviceIdentity, GpuAccountingSnapshot
from tests.helpers.tuner_source import tuner_node_source

SOURCE = Path(__file__).resolve().parents[3] / "core" / "runtime_control" / "admission.py"
EXECUTOR = Path(__file__).resolve().parents[3] / "core" / "sandbox_executor.py"
TUNER = (
    Path(__file__).resolve().parents[3]
    / "nodes"
    / "ml_hyperparameter_tune_agent"
    / "ml_hyperparameter_tune_agent.py"
)
DEV = DeviceIdentity(uuid="GPU-aaaa-0000", physical_index=0)
MODES = ["formal", "trial"]


def _snap(total=32_000, used=1_000, other=1_000, own=0, ok=True):
    if not ok:
        return GpuAccountingSnapshot(device=DEV, telemetry_available=False)
    return GpuAccountingSnapshot(
        device=DEV,
        telemetry_available=True,
        device_total_mib=total,
        device_used_mib=used,
        own_tree_mib=own,
        other_mib=other,
        other_process_count=1 if other else 0,
        per_pid_total_mib=own + other,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )


def _decide(mode="formal", *, snapshot=None, mib=4_000, prov="measured", **kw):
    return evaluate_gpu_admission(
        snapshot=_snap() if snapshot is None else snapshot,
        requirement_mib=mib,
        requirement_provenance=prov,
        mode=mode,
        **kw,
    )


class TestHeadroomIsAFactNotAPosture:
    """The modes differ only where safety is *unproven*. Where occupancy
    is measured and the requirement does not fit, both refuse — a
    trial run does not get to disbelieve arithmetic."""

    @pytest.mark.parametrize("mode", MODES)
    def test_a_requirement_that_does_not_fit_is_refused_in_both_modes(self, mode):
        d = _decide(mode, mib=40_000)
        assert d.admitted is False
        assert d.reason_code == "insufficient_headroom"

    @pytest.mark.parametrize("mode", MODES)
    def test_a_requirement_that_fits_is_admitted_in_both_modes(self, mode):
        assert _decide(mode, mib=4_000).admitted is True

    def test_other_occupancy_is_counted_against_the_ceiling(self):
        """The V19 shape: the candidate alone fits, the pair does not."""
        alone = _decide(snapshot=_snap(total=32_000, used=0, other=0), mib=20_000)
        crowded = _decide(snapshot=_snap(total=32_000, used=20_000, other=20_000), mib=20_000)
        assert alone.admitted is True
        assert crowded.admitted is False
        assert crowded.reason_code == "insufficient_headroom"

    def test_the_ceiling_is_the_stricter_of_policy_and_hardware(self):
        """A configured ceiling above the card's capacity would admit
        work the card cannot hold."""
        d = _decide(snapshot=_snap(total=8_000, used=0, other=0), mib=6_000, ceiling_gib=999.0)
        assert d.evidence["effective_ceiling_gib"] == pytest.approx(8_000 / 1024)
        assert d.admitted is True
        assert (
            _decide(
                snapshot=_snap(total=8_000, used=0, other=0), mib=9_000, ceiling_gib=999.0
            ).admitted
            is False
        )


class TestUnprovenSafetyDividesTheModes:
    @pytest.mark.parametrize("mib,prov", [(None, None), (4_000, "estimate"), (0, "measured")])
    def test_formal_refuses_a_non_authoritative_requirement(self, mib, prov):
        """Occupancy WAS measured; what is missing is the authoritative
        requirement needed to decide on it. That is a policy gap, not a
        measurement gap."""
        d = _decide("formal", mib=mib, prov=prov)
        assert d.admitted is False
        assert d.reason_code == "policy_unavailable"
        assert d.detail is None

    @pytest.mark.parametrize("mib,prov", [(None, None), (4_000, "estimate"), (0, "measured")])
    def test_trial_proceeds_but_records_that_it_proved_nothing(self, mib, prov):
        d = _decide("trial", mib=mib, prov=prov)
        assert d.admitted is True
        assert d.requirement_source == "unavailable"

    def test_a_missing_requirement_is_never_treated_as_zero(self):
        """Zero fits anywhere. That is the shortcut this must refuse."""
        d = _decide("formal", mib=None, prov=None)
        assert d.reason_code == "policy_unavailable"
        assert "aggregate_gib" not in d.evidence

    @pytest.mark.parametrize("prov", sorted(AUTHORITATIVE_PROVENANCE))
    def test_only_declared_provenances_count_as_measurement(self, prov):
        assert _decide("formal", mib=4_000, prov=prov).admitted is True

    def test_a_predicted_estimate_is_not_promoted_to_a_resource_fact(self):
        """A6: 6.43 GB predicted, 12.52 GiB actually held — 1.95x."""
        d = _decide("formal", mib=6_584, prov="predicted_allocated_estimate")
        assert d.admitted is False
        assert d.reason_code == "policy_unavailable"


class TestTelemetryPolicy:
    def test_formal_refuses_when_occupancy_cannot_be_measured(self):
        """A successful query that reports unavailable telemetry is still
        a measurement problem, not a policy one."""
        d = _decide("formal", snapshot=_snap(ok=False))
        assert d.admitted is False
        assert d.reason_code == "measurement_unavailable"
        assert d.detail == "telemetry_unavailable"

    def test_trial_proceeds_with_no_safety_claim(self):
        d = _decide("trial", snapshot=_snap(ok=False))
        assert d.admitted is True
        assert d.requirement_source == "unavailable"
        assert "no safety claim" in d.reason

    @pytest.mark.parametrize("mode", MODES)
    def test_impossible_telemetry_is_refused_in_both_modes(self, mode):
        """used > total yields negative headroom, which would otherwise
        manufacture an admission or a refusal out of a driver glitch."""
        d = _decide(mode, snapshot=_snap(total=32_000, used=33_000, other=0))
        assert d.admitted is False
        assert d.reason_code == "measurement_unavailable"
        assert d.detail == "inconsistent_accounting"
        assert "cannot be true" in d.reason


class TestDecisionIntegrity:
    def test_an_admission_cannot_carry_a_refusal_reason(self):
        with pytest.raises(ValidationError):
            AdmissionDecision(
                admitted=True,
                reason_code="insufficient_headroom",
                requirement_source="measured",
                reason="r",
            )

    def test_a_refusal_must_say_why(self):
        with pytest.raises(ValidationError):
            AdmissionDecision(
                admitted=False, reason_code=None, requirement_source="measured", reason="r"
            )

    def test_the_reason_vocabulary_is_closed(self):
        with pytest.raises(ValidationError):
            AdmissionDecision(
                admitted=False,
                reason_code="made_up",
                requirement_source="measured",
                reason="r",
            )

    def test_every_figure_used_is_preserved(self):
        d = _decide("formal", snapshot=_snap(total=32_000, used=5_000, other=5_000), mib=4_000)
        for key in (
            "device_total_mib",
            "device_used_mib",
            "other_mib",
            "requirement_mib",
            "requirement_provenance",
            "effective_ceiling_gib",
            "aggregate_gib",
            "headroom_gib",
            "device_uuid",
            "mode",
        ):
            assert key in d.evidence, key
        assert d.evidence["other_mib"] == 5_000
        assert d.evidence["requirement_mib"] == 4_000

    def test_a_refusal_records_the_figures_that_refused_it(self):
        d = _decide("formal", mib=40_000)
        assert d.evidence["aggregate_gib"] > d.evidence["effective_ceiling_gib"]

    def test_the_decision_is_immutable(self):
        d = _decide()
        with pytest.raises(ValidationError):
            d.admitted = False  # type: ignore[misc]


class TestReasonCodeSplit:
    """`measurement_unavailable` means no trustworthy device fact was
    obtained. `policy_unavailable` means facts exist but what is needed
    to decide on them does not. Corrected by operator review 2026-08-02;
    the first mapping had them the wrong way round for telemetry and
    inconsistent accounting."""

    @pytest.mark.parametrize(
        "snapshot,detail",
        [
            (_snap(ok=False), "telemetry_unavailable"),
            (_snap(total=32_000, used=33_000, other=0), "inconsistent_accounting"),
        ],
    )
    def test_a_bad_reading_is_a_measurement_problem(self, snapshot, detail):
        d = _decide("formal", snapshot=snapshot)
        assert d.reason_code == "measurement_unavailable"
        assert d.detail == detail

    def test_a_missing_requirement_is_a_policy_problem(self):
        d = _decide("formal", mib=None, prov=None)
        assert d.reason_code == "policy_unavailable"

    def test_a_sampler_failure_is_a_measurement_problem(self):
        from core.runtime_control.admission import evaluate_gpu_admission

        d = evaluate_gpu_admission(
            snapshot=None,
            requirement_mib=None,
            requirement_provenance=None,
            mode="formal",
            sampling_error="RuntimeError: boom",
        )
        assert d.reason_code == "measurement_unavailable"
        assert d.detail == "sampler_error"

    def test_detail_is_meaningless_outside_measurement_unavailable(self):
        with pytest.raises(ValidationError):
            AdmissionDecision(
                admitted=False,
                reason_code="insufficient_headroom",
                detail="sampler_error",
                requirement_source="measured",
                reason="r",
            )

    @pytest.mark.parametrize("mode", MODES)
    def test_every_refusal_reason_refuses_in_formal(self, mode):
        """trial proceeds only where safety is unproven; formal refuses
        on every one."""
        cases = [
            _decide(mode, snapshot=_snap(ok=False)),
            _decide(mode, mib=None, prov=None),
            _decide(mode, mib=40_000),
        ]
        if mode == "formal":
            assert all(c.admitted is False for c in cases)
        else:
            # only the measured-headroom failure survives trial mode
            assert [c.admitted for c in cases] == [True, True, False]


class TestInvalidAdmissionMode:
    """An unrecognised posture refuses like formal — but the record must
    not SAY formal. Conflating a configuration error with a deliberate
    choice would make the audit trail lie about what was configured."""

    @pytest.mark.parametrize(
        "raw", ["formL", "FORMAL", "diagnostic", "Trial", "", "single_file", None, 1, True]
    )
    def test_an_invalid_mode_is_a_policy_misconfiguration(self, raw):
        d = _decide(raw)
        assert d.admitted is False
        assert d.reason_code == "policy_unavailable"
        assert d.detail == "invalid_admission_mode"

    def test_diagnostic_is_rejected_rather_than_aliased(self):
        """`diagnostic` was an earlier spelling of this same posture.
        Supporting both would put two words for one policy into every
        record that carries it, and provenance would stop being able to
        say which policy ran."""
        d = _decide("diagnostic")
        assert d.reason_code == "policy_unavailable"
        assert d.detail == "invalid_admission_mode"
        assert "diagnostic" in d.reason

    def test_the_raw_value_is_kept_for_audit(self):
        d = _decide("formL")
        assert d.evidence["mode"] == "formL"
        assert d.evidence["accepted_modes"] == ["formal", "trial"]

    def test_an_invalid_mode_never_reads_as_a_deliberate_formal(self):
        formal = _decide("formal", mib=None, prov=None)
        invalid = _decide("formL")
        assert formal.reason_code == "policy_unavailable"
        assert formal.detail is None
        assert invalid.detail == "invalid_admission_mode"

    def test_a_detail_may_not_ride_the_wrong_reason_code(self):
        with pytest.raises(ValidationError):
            AdmissionDecision(
                admitted=False,
                reason_code="policy_unavailable",
                detail="sampler_error",
                requirement_source="unavailable",
                reason="r",
            )


class TestWhoMayCallIt:
    """B-C4a shipped the decision with no caller at all; B-C4b added the
    executor's. This test was written to catch exactly that and did, so
    it is **retargeted rather than deleted** — the remaining invariant is
    that the tuner must not reach the decision directly. The tuner's job
    is to consume a refusal (B-C4c), never to make one, or admission
    policy would live in two places.
    """

    def test_the_executor_gates_both_phases(self):
        tree = ast.parse(EXECUTOR.read_text())
        gates = [
            fn.name
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "evaluate_gpu_admission"
                for n in ast.walk(fn)
            )
        ]
        assert gates == ["_admission_refusal"], (
            f"admission is decided in {gates}; it must be decided in exactly one "
            "place, or two call sites can disagree about the same device"
        )

    def test_the_tuner_never_decides_admission_itself(self):
        called = {
            n.func.id
            for n in ast.walk(ast.parse(tuner_node_source()))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "evaluate_gpu_admission" not in called


class TestGenericity:
    FORBIDDEN = ("tidmad", "denois", "segmentation_size", "batch_size", "model size")

    def test_no_task_vocabulary_anywhere_including_prose(self):
        text = SOURCE.read_text().lower()
        assert [t for t in self.FORBIDDEN if t in text] == []

    def test_it_imports_no_task_module(self):
        tree = ast.parse(SOURCE.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = ("nodes", "agent", "ml_models", "execute_tools", "dashboard", "scripts")
        assert [m for m in imported if m.split(".")[0] in forbidden] == []

    def test_every_numeric_constant_is_accounted_for(self):
        """An allowlist: a denylist cannot see a constant nobody
        anticipated, which is how a 12/28 GiB literal would arrive."""
        allowed_ints = {0, 1}
        allowed_floats: set[float] = set()
        unexpected = []
        for node in ast.walk(ast.parse(SOURCE.read_text())):
            if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
                continue
            if isinstance(node.value, int) and node.value not in allowed_ints:
                unexpected.append(node.value)
            elif isinstance(node.value, float) and node.value not in allowed_floats:
                unexpected.append(node.value)
        assert unexpected == []
