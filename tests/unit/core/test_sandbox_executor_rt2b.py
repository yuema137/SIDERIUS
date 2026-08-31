"""
RT2-B unit tests: executor-side runtime-verification plumbing.

Pins `TidmadSandbox.execute_training`'s sidecar contract with a faked
subprocess (no GPU, no real training):

- a clean in-subprocess REJECTION (exit 0, sidecar decision=rejected,
  no sentinel) returns ``status="rejected_time_risk"`` — and is NOT
  misclassified by the silent-crash sentinel check;
- an admitted run returns success with the observation attached;
- no sidecar → exact legacy behavior (``runtime_verification=None``);
- a crashed subprocess still surfaces partial observation evidence;
- stale sidecars from a previous attempt are removed before launch;
- ``runtime_policy`` is Pydantic-validated and forwarded via argv;
- ``StubSandbox`` mirrors the signature and explicit-absence shape.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.sandbox_executor import StubSandbox, TidmadSandbox
from execute_tools.data_paths import bind_physical_data_root
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

QUICKSTART = Path(__file__).resolve().parents[3] / "configs/task_composition/quickstart.yaml"

_STORAGE = {
    "dataset_root": "/data",
    "file_count": 1,
    "files_present": 1,
    "expected_raw_bytes": 1000,
    "filesystem_type": "ext4",
}

_CFGS = {
    "m_cfg": {"model_type": "wavenet", "segmentation_size": 1000},
    "t_cfg": {"epochs": 1, "batch_size": 1, "device": "cpu"},
    "l_cfg": {"loss_type": "ce"},
}


@pytest.fixture(autouse=True)
def _bound_data_root(tmp_path):
    with bind_physical_data_root(str(tmp_path)):
        yield


@pytest.fixture
def sandbox(tmp_path):
    composition = compose_run_task_bindings(str(QUICKSTART))
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        yield TidmadSandbox(run_name="rt2b_test", workspace=str(tmp_path))


def _argv_value(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def _write_sidecar(path: str, *, rejected: bool) -> None:
    """Produce a REAL observation sidecar via the session (schema-true)."""
    policy = (
        RuntimeControlPolicy(operator_budget_seconds=1e-9) if rejected else RuntimeControlPolicy()
    )
    session = RuntimeVerificationSession(path, policy=policy)
    session.complete_setup(storage_provenance=_STORAGE)
    session.decide_admission()
    if not rejected:
        session.record_phase_actual("training", 1.0)
        session.finalize("completed")


def _fake_run(sandbox: TidmadSandbox, *, sidecar: str | None, sentinel: bool, results: bool):
    """Build a subprocess.run stand-in emulating the trainer's exit state."""

    def run(cmd, **kwargs):
        rv_path = _argv_value(cmd, "--runtime_observation_out")
        if sidecar is not None:
            assert rv_path is not None
            _write_sidecar(rv_path, rejected=(sidecar == "rejected"))
        if sentinel:
            with open(os.path.join(sandbox.dirs["models"], "_OK_exp_x"), "wb"):
                pass
        if results:
            res_dir = os.path.join(sandbox.dirs["records"], "rt2b_test")
            os.makedirs(res_dir, exist_ok=True)
            with open(os.path.join(res_dir, "experiment_results_wavenet_exp_x.json"), "w") as f:
                json.dump({"final_loss": 0.5, "loss_history": [0.5], "model_params": 10}, f)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

    return run


def _execute(sandbox, **kwargs):
    return sandbox.execute_training(
        exp_id="exp_x",
        run_name="rt2b_test",
        model_type="wavenet",
        sample_set={"0": [0]},
        **_CFGS,
        **kwargs,
    )


class TestRejectionPlumbing:
    def test_clean_rejection_is_not_a_silent_crash(self, sandbox, monkeypatch):
        # Exit 0, sidecar says rejected, NO sentinel, NO results — the
        # pre-RT2-B executor would misclassify this as a silent crash.
        monkeypatch.setattr(
            "core.sandbox_executor._run_observed_subprocess",
            _fake_run(sandbox, sidecar="rejected", sentinel=False, results=False),
        )
        out = _execute(sandbox)
        assert out["status"] == "rejected_time_risk"
        assert out["runtime_verification"]["admission"]["decision"] == "rejected"
        assert "error_training" not in out["message"]

    def test_rejection_carries_cost_model(self, sandbox, monkeypatch):
        monkeypatch.setattr(
            "core.sandbox_executor._run_observed_subprocess",
            _fake_run(sandbox, sidecar="rejected", sentinel=False, results=False),
        )
        adm = _execute(sandbox)["runtime_verification"]["admission"]
        assert adm["stage"] == "post_setup_runtime_verification"
        assert adm["setup_cost_seconds"] > 0.0


class TestSuccessPlumbing:
    def test_admitted_run_attaches_observation(self, sandbox, monkeypatch):
        monkeypatch.setattr(
            "core.sandbox_executor._run_observed_subprocess",
            _fake_run(sandbox, sidecar="admitted", sentinel=True, results=True),
        )
        out = _execute(sandbox)
        assert out["status"] == "success"
        rv = out["runtime_verification"]
        assert rv["admission"]["decision"] == "admitted"
        assert rv["final_status"] == "completed"
        assert out["results"]["final_loss"] == 0.5

    def test_no_sidecar_is_legacy_behavior(self, sandbox, monkeypatch):
        monkeypatch.setattr(
            "core.sandbox_executor._run_observed_subprocess",
            _fake_run(sandbox, sidecar=None, sentinel=True, results=True),
        )
        out = _execute(sandbox)
        assert out["status"] == "success"
        assert out["runtime_verification"] is None

    def test_stale_sidecar_removed_before_launch(self, sandbox, monkeypatch):
        # A rejected sidecar from a previous attempt must not resurface.
        stale_path = os.path.join(sandbox.dirs["configs"], "runtime_verification_exp_x.json")
        _write_sidecar(stale_path, rejected=True)
        monkeypatch.setattr(
            "core.sandbox_executor._run_observed_subprocess",
            _fake_run(sandbox, sidecar=None, sentinel=True, results=True),
        )
        out = _execute(sandbox)
        assert out["status"] == "success"
        assert out["runtime_verification"] is None


class TestCrashPlumbing:
    def test_crash_surfaces_partial_observation(self, sandbox, monkeypatch):
        def crashing_run(cmd, **kwargs):
            rv_path = _argv_value(cmd, "--runtime_observation_out")
            assert rv_path is not None
            # Trainer got through setup, then died.
            session = RuntimeVerificationSession(rv_path)
            session.complete_setup(storage_provenance=_STORAGE)
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="boom")

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", crashing_run)
        out = _execute(sandbox)
        assert out["status"] == "error"
        assert out["runtime_verification"]["final_status"] == "setup_complete"
        assert out["runtime_verification"]["components"]["setup"]["actual_seconds"] > 0.0

    def test_malformed_sidecar_degrades_to_absent(self, sandbox, monkeypatch):
        def run(cmd, **kwargs):
            rv_path = _argv_value(cmd, "--runtime_observation_out")
            assert rv_path is not None
            with open(rv_path, "w") as f:
                f.write("{not json")
            with open(os.path.join(sandbox.dirs["models"], "_OK_exp_x"), "wb"):
                pass
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", run)
        out = _execute(sandbox)
        assert out["status"] == "success"
        assert out["runtime_verification"] is None


class TestPolicyForwarding:
    def test_policy_validated_and_forwarded(self, sandbox, monkeypatch):
        seen: dict = {}

        def run(cmd, **kwargs):
            seen["rp_path"] = _argv_value(cmd, "--runtime_policy_json")
            seen["rv_path"] = _argv_value(cmd, "--runtime_observation_out")
            with open(os.path.join(sandbox.dirs["models"], "_OK_exp_x"), "wb"):
                pass
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", run)
        out = _execute(sandbox, runtime_policy={"operator_budget_seconds": 120.0})
        assert out["status"] == "success"
        assert seen["rv_path"] is not None
        assert seen["rp_path"] is not None
        with open(seen["rp_path"]) as f:
            written = json.load(f)
        # Validated full-policy dump: the budget survives verbatim and the
        # RT2-C stopping-policy defaults are materialized alongside it.
        assert written["operator_budget_seconds"] == 120.0
        assert written["safety_factor"] == 1.0
        assert "verification" in written

    def test_invalid_policy_rejected_before_launch(self, sandbox, monkeypatch):
        launched = {"n": 0}

        def run(cmd, **kwargs):  # pragma: no cover - must not be reached
            launched["n"] += 1
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", run)
        out = _execute(sandbox, runtime_policy={"operator_budget_seconds": -5.0})
        assert out["status"] == "error"
        assert launched["n"] == 0


class TestStubParity:
    def test_stub_accepts_policy_and_reports_explicit_absence(self, tmp_path):
        stub = StubSandbox(run_name="rt2b_stub", workspace=str(tmp_path))
        out = stub.execute_training(
            exp_id="exp_s",
            run_name="rt2b_stub",
            model_type="wavenet",
            sample_set={"0": [0]},
            runtime_policy={"operator_budget_seconds": 60.0},
            **_CFGS,
        )
        assert out["status"] == "success"
        assert out["runtime_verification"] is None
