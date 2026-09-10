"""
RT4 unit tests: runtime watchdog (§4).

Pins: orphan-free process-GROUP kill (the §11 checkpoint test — a child
that spawns its own children leaves zero survivors), natural-exit and
error passthrough, the §4 deadline formula (min(budget, verified ×
safety) with the configurable floor) including mid-flight tightening
from the live observation sidecar, and executor-level kill handling
(status, partial-artifact cleanup, observation attachment).
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

import core.sandbox_executor as sandbox_executor
from core.runtime_control.session import (
    RuntimeControlPolicy,
    RuntimeVerificationSession,
    WatchdogConfig,
)
from core.sandbox_executor import (
    TidmadSandbox,
    _run_observed_subprocess,
    _watchdog_deadline_provider,
)


def _run(cmd: list[str], *, deadline: float | None, grace: float = 0.5, poll: float = 0.1):
    return _run_observed_subprocess(
        cmd,
        env=os.environ.copy(),
        preexec_fn=None,
        capture_stdout=True,
        deadline_provider=lambda: (deadline, "operator_budget"),
        grace_seconds=grace,
        poll_seconds=poll,
        label="test",
    )


class TestKillTree:
    def test_kill_leaves_no_orphans(self, tmp_path):
        # The subprocess spawns background children of its own — the §4
        # process-group kill must take the WHOLE tree down.
        #
        # The group is observed from OUTSIDE. This previously asserted
        # `kill_info["survivors_detected"] is False`, which is a value the
        # code under test produced: delete the orphan probe at
        # `core/sandbox_executor.py:995-1003`, hardcode `survivors = False`,
        # and the assertion still passed. `test_probe_hard_timeout.py:126-130`
        # already does it the honest way, and this now matches — the child
        # reports its own process-group id and the test asks the kernel.
        pgid_file = tmp_path / "pgid"
        result, kill_info = _run(
            ["bash", "-c", f"echo $$ > {pgid_file}; sleep 60 & sleep 60 & wait"],
            deadline=0.4,
        )
        assert result is None
        assert kill_info is not None

        pgid = int(pgid_file.read_text().strip())
        with pytest.raises(ProcessLookupError):
            # The leader IS the group (start_new_session), so a surviving
            # grandchild would keep the group alive and this would not raise.
            os.killpg(pgid, 0)

        assert kill_info["survivors_detected"] is False  # and production agrees
        assert kill_info["elapsed_s"] > 0.4
        assert kill_info["deadline_s"] == pytest.approx(0.4)
        assert kill_info["estimate_source"] == "operator_budget"

    def test_term_ignoring_child_is_killed(self):
        # A child that traps SIGTERM must be escalated to SIGKILL after
        # the grace period — and still leave no survivors.
        script = "trap '' TERM; sleep 60"
        result, kill_info = _run(["bash", "-c", script], deadline=0.3, grace=0.3)
        assert result is None
        assert kill_info is not None
        assert kill_info["escalated_to_kill"] is True
        assert kill_info["survivors_detected"] is False

    def test_natural_exit_passthrough(self):
        result, kill_info = _run(["bash", "-c", "echo done"], deadline=30.0)
        assert kill_info is None
        assert result is not None
        assert result.returncode == 0
        assert "done" in result.stdout

    def test_nonzero_exit_raises_calledprocesserror(self):
        with pytest.raises(subprocess.CalledProcessError):
            _run(["bash", "-c", "echo boom >&2; exit 3"], deadline=30.0)

    def test_no_deadline_never_kills(self):
        result, kill_info = _run(["bash", "-c", "sleep 0.3; echo ok"], deadline=None)
        assert kill_info is None
        assert result is not None and "ok" in result.stdout


class TestDeadlineFormula:
    def _policy(self, **kw) -> RuntimeControlPolicy:
        return RuntimeControlPolicy(
            watchdog=WatchdogConfig(
                enabled=True,
                floor_seconds=kw.pop("floor", 0.0),
                max_phase_seconds=kw.pop("watchdog_max_phase_seconds", None),
            ),
            **kw,
        )

    def test_operator_budget_only(self, tmp_path):
        provider = _watchdog_deadline_provider(
            self._policy(operator_budget_seconds=100.0), str(tmp_path / "absent.json")
        )
        assert provider() == (100.0, "operator_budget")

    def test_no_inputs_disables(self, tmp_path):
        provider = _watchdog_deadline_provider(self._policy(), str(tmp_path / "absent.json"))
        assert provider() == (None, "none")

    def test_verified_estimate_tightens_mid_flight(self, tmp_path):
        # §4 component-deadline interface: once the in-subprocess
        # verification lands predictions in the sidecar, the deadline
        # tightens below the operator budget.
        sidecar = str(tmp_path / "rv.json")
        policy = self._policy(operator_budget_seconds=10_000.0, safety_factor=2.0)
        provider = _watchdog_deadline_provider(policy, sidecar)
        assert provider() == (10_000.0, "operator_budget")

        session = RuntimeVerificationSession(sidecar)
        session.complete_setup(storage_provenance={"expected_raw_bytes": 1})
        payload = json.loads((tmp_path / "rv.json").read_text(encoding="utf-8"))
        payload["components"]["training"] = payload["components"]["setup"]
        payload["components"]["training"]["prediction"]["source"] = "real_training_verification"
        (tmp_path / "rv.json").write_text(json.dumps(payload), encoding="utf-8")
        deadline, source = provider()
        assert source == "verified_components"
        # setup prediction ≈ its tiny actual; × safety 2.0, well below budget
        assert deadline < 10_000.0

    def test_validation_fuse_arms_a_deadline_where_a_trial_round_has_none(self, tmp_path):
        """A trial round ships ``operator_budget_seconds=None``, so before
        any component verifies there is nothing to enforce at all.

        The Gate fuse is the only non-forecast candidate on that path.
        Fails when it stops reaching the provider — and the symptom would
        be a Gate that believes it has a hard ceiling and has none.
        """
        policy = self._policy(watchdog_max_phase_seconds=900.0)
        provider = _watchdog_deadline_provider(policy, str(tmp_path / "absent.json"))

        assert provider() == (900.0, "validation_max_phase")

    def test_validation_fuse_only_ever_tightens(self, tmp_path):
        """A candidate, never a replacement.

        Fails when the fuse is made authoritative and starts RAISING a
        deadline that the operator budget or a verified estimate had
        already set lower — turning a safety net into a licence to run
        longer.
        """
        policy = self._policy(operator_budget_seconds=100.0, watchdog_max_phase_seconds=5_000.0)

        assert _watchdog_deadline_provider(policy, str(tmp_path / "absent.json"))() == (
            100.0,
            "operator_budget",
        )

    def test_floor_prevents_degenerate_deadlines(self, tmp_path):
        sidecar = str(tmp_path / "rv.json")
        session = RuntimeVerificationSession(sidecar)
        session.complete_setup(storage_provenance={"expected_raw_bytes": 1})
        payload = json.loads((tmp_path / "rv.json").read_text(encoding="utf-8"))
        payload["components"]["training"] = payload["components"]["setup"]
        payload["components"]["training"]["prediction"]["source"] = "real_training_verification"
        (tmp_path / "rv.json").write_text(json.dumps(payload), encoding="utf-8")
        policy = RuntimeControlPolicy(
            operator_budget_seconds=10_000.0,
            watchdog=WatchdogConfig(enabled=True, floor_seconds=120.0),
        )
        deadline, _source = _watchdog_deadline_provider(policy, sidecar)()
        assert deadline == pytest.approx(120.0)  # near-zero estimate floored (§4)


@pytest.mark.usefixtures("synthetic_run_authorities", "synthetic_physical_data_root")
class TestExecutorKillHandling:
    def test_training_kill_cleans_partials_and_reports(self, tmp_path, monkeypatch):
        sandbox = TidmadSandbox(run_name="rt4", workspace=str(tmp_path))
        # Pre-create the partial artifacts a killed run leaves behind.
        model_p = os.path.join(sandbox.dirs["models"], "model_wavenet_exp_w_agent.pth")
        sentinel_p = os.path.join(sandbox.dirs["models"], "_OK_exp_w")
        res_dir = os.path.join(sandbox.dirs["records"], "rt4")
        os.makedirs(res_dir, exist_ok=True)
        results_p = os.path.join(res_dir, "experiment_results_wavenet_exp_w.json")
        for p in (model_p, sentinel_p, results_p):
            with open(p, "w") as f:
                f.write("{}")

        kill_info = {
            "elapsed_s": 12.0,
            "deadline_s": 10.0,
            "estimate_source": "verified_components",
            "escalated_to_kill": False,
            "survivors_detected": False,
        }

        def fake_watchdog(cmd, **kwargs):
            # Partial observation staged by the (killed) subprocess.
            rv = cmd[cmd.index("--runtime_observation_out") + 1]
            RuntimeVerificationSession(rv).complete_setup(
                storage_provenance={"expected_raw_bytes": 1}
            )
            return None, kill_info

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", fake_watchdog)
        out = sandbox.execute_training(
            exp_id="exp_w",
            run_name="rt4",
            model_type="wavenet",
            m_cfg={"model_type": "wavenet", "segmentation_size": 1000},
            t_cfg={"epochs": 1, "batch_size": 1, "device": "cpu"},
            l_cfg={},
            sample_set={"0": [0]},
            runtime_policy={"watchdog": {"enabled": True}},
        )
        assert out["status"] == "wall_clock_timeout"
        assert out["watchdog"]["deadline_s"] == 10.0
        # §4 partial-artifact cleanup.
        assert not os.path.exists(model_p)
        assert not os.path.exists(sentinel_p)
        assert not os.path.exists(results_p)
        # Killed attempt's partial observation still surfaces (§6.2).
        assert out["runtime_verification"]["final_status"] == "setup_complete"

    def test_watchdog_disabled_arms_no_deadline(self, tmp_path, monkeypatch):
        """Disabled watchdog means no deadline is armed.

        This asserted `used == {"watchdog": 0, "run": 1}` until B-C2a2 —
        the `run` half meaning "the plain implementation underneath is
        still subprocess.run". That is false by construction now that
        plain mode is on Popen, and worse, the old assertion would only
        have failed *after* a real training subprocess had launched.

        The durable property is the one the test was always really
        about: the seam is entered without a deadline_provider.
        """
        sandbox = TidmadSandbox(run_name="rt4b", workspace=str(tmp_path))
        used = {"with_deadline": 0, "without_deadline": 0}

        def recording_seam(cmd, **kwargs):
            if kwargs.get("deadline_provider") is not None:
                used["with_deadline"] += 1
            else:
                used["without_deadline"] += 1
            with open(os.path.join(sandbox.dirs["models"], "_OK_exp_p"), "wb"):
                pass
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

        monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", recording_seam)
        out = sandbox.execute_training(
            exp_id="exp_p",
            run_name="rt4b",
            model_type="wavenet",
            m_cfg={"model_type": "wavenet", "segmentation_size": 1000},
            t_cfg={"epochs": 1, "batch_size": 1, "device": "cpu"},
            l_cfg={},
            sample_set={"0": [0]},
            runtime_policy={"operator_budget_seconds": 60.0},  # watchdog default off
        )
        assert out["status"] == "success"
        assert used == {"with_deadline": 0, "without_deadline": 1}
