"""B-C4b — the admission gate is reachable, and changes nothing when it admits.

The failure this guards against is the one the whole PR was opened
about: a component built, tested, and never actually called. So the
central assertion is made at the real launch boundary — `Popen` is not
called — rather than inferred from a returned status, which a bug could
produce while still spawning the child.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from core.runtime_control.admission import AdmissionDecision
from core.runtime_control.gpu_accounting import DeviceIdentity, GpuAccountingSnapshot
from tests.helpers.tuner_source import tuner_node_source

EXECUTOR = Path(__file__).resolve().parents[3] / "core" / "sandbox_executor.py"
DEV = DeviceIdentity(uuid="GPU-aaaa-0000", physical_index=0)

REFUSED = AdmissionDecision(
    admitted=False,
    reason_code="insufficient_headroom",
    requirement_source="measured",
    reason="fixture refusal",
    evidence={"other_mib": 30000},
)
ADMITTED = AdmissionDecision(
    admitted=True, reason_code=None, requirement_source="measured", reason="fixture admit"
)


def _snapshot():
    return GpuAccountingSnapshot(
        device=DEV,
        telemetry_available=True,
        device_total_mib=32_000,
        device_used_mib=1_000,
        own_tree_mib=0,
        other_mib=1_000,
        other_process_count=1,
        per_pid_total_mib=1_000,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )


class _Sandbox:
    """Only what `_admission_refusal` reads off a sandbox."""

    def __init__(self, **kw):
        self.device_identity = kw.pop("device_identity", DEV)
        self.run_name = "r1"
        for k, v in kw.items():
            setattr(self, k, v)


def _gate(sandbox, *, decision=REFUSED, phase="training"):
    from core.sandbox_executor import _admission_refusal

    with (
        patch("core.runtime_control.gpu_accounting.sample", return_value=_snapshot()),
        patch("core.runtime_control.admission.evaluate_gpu_admission", return_value=decision) as ev,
    ):
        return _admission_refusal(sandbox, phase=phase), ev


class TestTheGateItself:
    def test_a_refusal_returns_the_frozen_status(self):
        result, _ = _gate(_Sandbox())
        assert result is not None
        assert result["status"] == "skipped_resource_admission"
        assert result["admission"]["reason_code"] == "insufficient_headroom"

    def test_an_admission_returns_none_so_the_caller_proceeds(self):
        result, _ = _gate(_Sandbox(), decision=ADMITTED)
        assert result is None

    def test_no_device_identity_leaves_behaviour_unchanged(self):
        """The pre-PR-B path: nothing to decide on, so nothing is
        refused. Refusing here would break every machine without
        telemetry."""
        result, ev = _gate(_Sandbox(device_identity=None))
        assert result is None
        assert ev.call_count == 0

    def test_the_run_configuration_reaches_the_decision(self):
        _, ev = _gate(
            _Sandbox(
                admission_mode="formal",
                measured_requirements={
                    "training": {"requirement_mib": 4_000, "provenance": "measured"}
                },
            ),
            decision=ADMITTED,
        )
        kwargs = ev.call_args.kwargs
        assert kwargs["mode"] == "formal"
        assert kwargs["requirement_mib"] == 4_000
        assert kwargs["requirement_provenance"] == "measured"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("trial", "trial"),
            ("formal", "formal"),
        ],
    )
    def test_a_supported_mode_reaches_the_policy_verbatim(self, raw, expected):
        _, ev = _gate(_Sandbox(admission_mode=raw), decision=ADMITTED)
        assert ev.call_args.kwargs["mode"] == expected

    def test_an_absent_mode_is_the_compatibility_default(self):
        _, ev = _gate(_Sandbox(), decision=ADMITTED)
        assert ev.call_args.kwargs["mode"] == "trial"

    def test_absent_and_explicit_none_are_distinguishable(self):
        """The default must be the string, not `None`.

        `getattr(sandbox, "admission_mode", None)` would merge "the field
        was never set" with "the field was set to None", and the tests
        below would claim a distinction production could not make.
        """

        class _NoAttr:
            device_identity = DEV
            run_name = "r1"

        with (
            patch("core.runtime_control.gpu_accounting.sample", return_value=_snapshot()),
            patch(
                "core.runtime_control.admission.evaluate_gpu_admission", return_value=ADMITTED
            ) as ev,
        ):
            from core.sandbox_executor import _admission_refusal

            _admission_refusal(_NoAttr(), phase="training")
            absent = ev.call_args.kwargs["mode"]
            _admission_refusal(_Sandbox(admission_mode=None), phase="training")
            explicit_none = ev.call_args.kwargs["mode"]

        assert absent == "trial"
        assert explicit_none is None
        assert absent != explicit_none

    def test_the_default_is_not_none(self):
        """Structural guard on the same thing: the getattr default must
        be the compatibility mode itself."""
        tree = ast.parse(EXECUTOR.read_text())
        defaults = [
            node.args[2]
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) == 3
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "admission_mode"
        ]
        assert len(defaults) == 1
        assert isinstance(defaults[0], ast.Constant)
        assert defaults[0].value == "trial"

    def test_the_raw_value_is_passed_through_not_resolved_by_the_caller(self):
        """Mode policy has one home. The executor must not silently map
        a wrong value onto a valid posture — doing so would make the
        record say `formal` when the operator wrote a typo."""
        _, ev = _gate(_Sandbox(admission_mode="formL"), decision=ADMITTED)
        assert ev.call_args.kwargs["mode"] == "formL"

    def test_the_default_mode_is_trial(self):
        """No default moves in this commit — the fail-closed flip is
        D-B4, and only after B-G2."""
        _, ev = _gate(_Sandbox(), decision=ADMITTED)
        assert ev.call_args.kwargs["mode"] == "trial"


class TestNoSubprocessOnRefusal:
    """Asserted at the launch boundary, not on the returned status."""

    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_a_refusal_never_reaches_popen(self, phase):
        from core.sandbox_executor import _admission_refusal

        with (
            patch("core.runtime_control.gpu_accounting.sample", return_value=_snapshot()),
            patch("core.runtime_control.admission.evaluate_gpu_admission", return_value=REFUSED),
            patch.object(subprocess, "Popen") as popen,
            patch.object(subprocess, "run") as run,
        ):
            result = _admission_refusal(_Sandbox(), phase=phase)
        assert result is not None
        assert popen.call_count == 0
        assert run.call_count == 0


class TestGatePlacement:
    """Both launch branches must sit behind one gate. A branch outside it
    would be a hole that reads as coverage."""

    @staticmethod
    def _fn(name: str) -> ast.FunctionDef:
        tree = ast.parse(EXECUTOR.read_text())
        return next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == name and n.end_lineno - n.lineno > 50
        )

    @pytest.mark.parametrize("method", ["execute_training", "execute_inference"])
    def test_the_gate_precedes_every_launch_in_that_method(self, method):
        fn = self._fn(method)
        gate_lines = [
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_admission_refusal"
        ]
        launch_lines = [
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_run_observed_subprocess"
        ]
        assert len(gate_lines) == 1, f"{method}: expected one gate, found {gate_lines}"
        assert len(launch_lines) == 2, (
            f"{method}: expected the watchdog and plain branches, found {launch_lines}"
        )
        assert all(gate_lines[0] < line for line in launch_lines), (
            f"{method}: a launch at {launch_lines} precedes the gate at {gate_lines[0]}"
        )

    @pytest.mark.parametrize("method", ["execute_training", "execute_inference"])
    def test_the_refusal_returns_immediately(self, method):
        """The gate's result must be returned, not merely computed."""
        fn = self._fn(method)
        src = ast.unparse(fn)
        assert "_refusal = _admission_refusal" in src
        assert "if _refusal is not None:" in src
        assert "return _refusal" in src


class TestStubSandboxUnaffected:
    """Pseudo mode has no device, so it is neither admitted nor refused.
    Stated as a scope decision with a test, rather than left to the
    override to bypass the gate by accident."""

    def test_the_stub_overrides_both_methods(self):
        tree = ast.parse(EXECUTOR.read_text())
        stub = next(
            n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "StubSandbox"
        )
        overridden = {n.name for n in stub.body if isinstance(n, ast.FunctionDef)}
        assert {"execute_training", "execute_inference"} <= overridden

    def test_the_stub_never_calls_the_gate(self):
        tree = ast.parse(EXECUTOR.read_text())
        stub = next(
            n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "StubSandbox"
        )
        called = {
            n.func.id
            for n in ast.walk(stub)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_admission_refusal" not in called


class TestProduceAndConsumeStaySeparate:
    """B-C4b asserted the tuner had not consumed the status yet. B-C4c
    added that consumption, so the guard fired as designed and is
    **retargeted, not deleted**.

    The surviving invariant is the separation itself: the executor
    decides and produces the refusal, the task layer consumes it. An
    executor that built the agent-facing record would put task wording
    back into generic runtime infrastructure, which §8.5 forbids.
    """

    TUNER = (
        Path(__file__).resolve().parents[3]
        / "nodes"
        / "ml_hyperparameter_tune_agent"
        / "ml_hyperparameter_tune_agent.py"
    )

    def test_the_executor_does_not_build_the_agent_facing_record(self):
        called = {
            n.func.id
            for n in ast.walk(ast.parse(EXECUTOR.read_text()))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_build_resource_admission_record" not in called
        assert "_build_skip_record" not in called

    def test_the_tuner_consumes_it_through_the_approved_handler(self):
        tree = ast.parse(tuner_node_source())
        handlers = {
            fn.name
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_build_resource_admission_record"
                for n in ast.walk(fn)
            )
        }
        # V20 PR C2 / C2-8 added the second approved caller. The invariant
        # is that nobody HAND-ASSEMBLES this record, not that only one
        # function may ask for one -- a shared builder with two callers is
        # the builder doing its job. A third caller, or any hand-rolled
        # equivalent, still fails here.
        assert handlers == {"_handle_admission_refusal", "_handle_prephase_gpu_measurement"}

    def test_the_executor_owns_the_status_constant_it_emits(self):
        """The executor writes the status; the tuner reads it through
        its own frozen constant. Both must agree, and a test says so
        rather than leaving two string literals to drift."""
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            RESOURCE_ADMISSION_STATUS,
        )

        assert RESOURCE_ADMISSION_STATUS in EXECUTOR.read_text()
