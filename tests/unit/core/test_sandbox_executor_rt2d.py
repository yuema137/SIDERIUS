"""
RT2-D unit tests: executor-side inference observation plumbing.

Pins `TidmadSandbox.execute_inference`'s sidecar contract with a faked
subprocess: the attempt sidecar path is forwarded (never deleted — it
carries the training components), the updated observation is attached
to success and error results, and `StubSandbox` mirrors the signature.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from core.runtime_control.session import RuntimeVerificationSession
from core.sandbox_executor import StubSandbox, TidmadSandbox

_CFGS = {
    "m_cfg": {"model_type": "wavenet", "segmentation_size": 1000},
    "l_cfg": {},
}


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name="rt2d_test", workspace=str(tmp_path))


def _argv_value(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def _execute(sandbox, **kwargs):
    return sandbox.execute_inference(
        exp_id="exp_i",
        run_name="rt2d_test",
        model_type="wavenet",
        sample_set={"0": [0]},
        **_CFGS,
        **kwargs,
    )


class TestInferencePlumbing:
    def test_sidecar_forwarded_and_not_deleted(self, sandbox, monkeypatch):
        # Pre-existing training evidence must survive the launch.
        sidecar_path = os.path.join(sandbox.dirs["configs"], "runtime_verification_exp_i.json")
        RuntimeVerificationSession(sidecar_path, attempt_id="exp_i").complete_setup(
            storage_provenance={"expected_raw_bytes": 10}
        )
        seen: dict = {}

        def run(cmd, **kwargs):
            seen["rv_path"] = _argv_value(cmd, "--runtime_observation_out")
            assert os.path.isfile(sidecar_path)  # NOT deleted pre-launch
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", run)
        out = _execute(sandbox)
        assert out["status"] == "success"
        assert seen["rv_path"] == sidecar_path
        # Read-back attached (the untouched training-only observation).
        assert out["runtime_verification"]["components"]["setup"] is not None

    def test_updated_observation_attached(self, sandbox, monkeypatch):
        def run(cmd, **kwargs):
            rv_path = _argv_value(cmd, "--runtime_observation_out")
            assert rv_path is not None
            session = RuntimeVerificationSession.resume_or_start(
                rv_path, resumed_status="inference_started"
            )
            session.record_phase_actual("inference", 2.0)
            session.finalize("inference_complete")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", run)
        out = _execute(sandbox)
        rv = out["runtime_verification"]
        assert rv["final_status"] == "inference_complete"
        assert rv["components"]["inference"]["actual_seconds"] == pytest.approx(2.0)

    def test_crash_still_attaches_partial_observation(self, sandbox, monkeypatch):
        def run(cmd, **kwargs):
            rv_path = _argv_value(cmd, "--runtime_observation_out")
            assert rv_path is not None
            RuntimeVerificationSession.resume_or_start(rv_path, resumed_status="inference_started")
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="boom")

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", run)
        out = _execute(sandbox)
        assert out["status"] == "error"
        assert out["runtime_verification"]["final_status"] == "inference_started"

    def test_policy_validated_and_forwarded(self, sandbox, monkeypatch):
        seen: dict = {}

        def run(cmd, **kwargs):
            seen["rp_path"] = _argv_value(cmd, "--runtime_policy_json")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", run)
        out = _execute(sandbox, runtime_policy={"operator_budget_seconds": 60.0})
        assert out["status"] == "success"
        assert seen["rp_path"] is not None
        with open(seen["rp_path"]) as f:
            assert json.load(f)["operator_budget_seconds"] == 60.0


class TestStubParity:
    def test_stub_accepts_policy_with_explicit_absence(self, tmp_path):
        stub = StubSandbox(run_name="rt2d_stub", workspace=str(tmp_path))
        out = stub.execute_inference(
            exp_id="exp_s",
            run_name="rt2d_stub",
            model_type="wavenet",
            sample_set={"0": [0]},
            runtime_policy={"operator_budget_seconds": 60.0},
            **_CFGS,
        )
        assert out["status"] == "success"
        assert out["runtime_verification"] is None
