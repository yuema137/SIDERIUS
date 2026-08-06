"""Terminal-state semantics for the V20 orchestrator.

The scheduler policy is tested in `tests/unit/core/test_v20_slot_scheduler.py`.
What is tested HERE is the one thing the process layer decides: when a
chain counts as terminal, and what happens when it dies without saying so.

**Failure is terminal too.** A chain killed by an OOM, a Python crash or a
dead screen never writes its marker. If that does not release a slot, one
crash leaves the campaign at half concurrency and two deadlock all eight
chains with nothing active — which is worse than the band barrier this
scheduler was written to remove.

The scheduler must never learn about scores, incumbents or HealthGate
verdicts; those belong to each chain. Nothing here reads them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "v20_queue_runner", REPO_ROOT / "sdsc_submission_scripts" / "v20_queue_runner.py"
)
assert _spec and _spec.loader
runner = importlib.util.module_from_spec(_spec)
sys.modules["v20_queue_runner"] = runner
_spec.loader.exec_module(runner)

from core.campaign.slot_scheduler import CampaignJob  # noqa: E402


@pytest.fixture
def job():
    return CampaignJob(run_name="v20_loss_15_19", band="15-19", chain_type="loss")


@pytest.fixture
def proc(job, tmp_path):
    return runner.ChainProcess(job, ws_root=tmp_path, iterations=3)


def _no_session(monkeypatch, proc):
    monkeypatch.setattr(type(proc), "session_alive", lambda self: False)


def _live_session(monkeypatch, proc):
    monkeypatch.setattr(type(proc), "session_alive", lambda self: True)


class TestTerminalClassification:
    def test_a_live_session_is_running_even_with_a_marker(self, proc, monkeypatch):
        # The marker may be stale from an earlier campaign; the live
        # session is authoritative.
        proc.marker.parent.mkdir(parents=True, exist_ok=True)
        proc.marker.write_text("EXIT=0\n")
        _live_session(monkeypatch, proc)
        assert proc.classify() == "running"
        assert proc.is_terminal() is False

    def test_marker_plus_dead_session_is_completed(self, proc, monkeypatch):
        proc.marker.parent.mkdir(parents=True, exist_ok=True)
        proc.marker.write_text("EXIT=0\n")
        _no_session(monkeypatch, proc)
        assert proc.classify() == "completed"

    def test_a_nonzero_exit_is_still_completed(self, proc, monkeypatch):
        # The chain recorded its own exit. A scientific failure is a
        # finished chain, not a crashed one.
        proc.marker.parent.mkdir(parents=True, exist_ok=True)
        proc.marker.write_text("EXIT=3\n")
        _no_session(monkeypatch, proc)
        assert proc.classify() == "completed"

    def test_no_marker_and_no_session_is_an_unexpected_exit(self, proc, monkeypatch):
        _no_session(monkeypatch, proc)
        assert proc.classify() == "unexpected_process_exit"

    def test_an_unexpected_exit_is_terminal_and_frees_the_slot(self, proc, monkeypatch):
        # THE defect this guards: if a crash is not terminal, the slot is
        # stranded and the campaign silently loses concurrency.
        _no_session(monkeypatch, proc)
        assert proc.is_terminal() is True

    def test_a_just_launched_chain_is_not_mistaken_for_a_crash(self, proc, monkeypatch):
        import time

        _no_session(monkeypatch, proc)
        proc.started_at = time.time()
        assert proc.classify() == "running", (
            "the gap between screen -dmS returning and the session appearing "
            "must not read as an unexpected exit"
        )


class TestUnexpectedExitEvidence:
    def test_it_records_scheduler_status_not_a_scientific_result(self, proc):
        proc.record_unexpected_exit()
        written = json.loads(
            (proc.marker.parent / f"{proc.job.run_name}.unexpected_exit.json").read_text()
        )
        assert written["scheduler_status"] == "unexpected_process_exit"
        assert written["scientific_status"] == "not_established"
        assert written["retried"] is False

    def test_it_never_fabricates_a_score_or_verdict(self, proc):
        # Inventing a round, a score or a HealthGate verdict for a process
        # that died would put a result into the campaign that no
        # measurement produced.
        proc.record_unexpected_exit()
        blob = (proc.marker.parent / f"{proc.job.run_name}.unexpected_exit.json").read_text()
        for forbidden in (
            "denoising_score",
            "verdict",
            "healthgate",
            "incumbent",
            "formal",
            "round",
        ):
            assert forbidden not in blob.lower()

    def test_the_workspace_is_preserved_for_a_deliberate_resume(self, proc):
        proc.record_unexpected_exit()
        written = json.loads(
            (proc.marker.parent / f"{proc.job.run_name}.unexpected_exit.json").read_text()
        )
        assert written["workspace"] == str(proc.workspace)


class TestPerJobIsolation:
    def test_every_job_gets_a_distinct_workspace_log_and_session(self, tmp_path):
        from core.campaign.slot_scheduler import v20_campaign_jobs

        procs = runner.build_processes(v20_campaign_jobs(), tmp_path, 3)
        assert len({p.workspace for p in procs.values()}) == 8
        assert len({p.logfile for p in procs.values()}) == 8
        assert len({p.session for p in procs.values()}) == 8
        assert len({p.marker for p in procs.values()}) == 8

    # Deliberately NOT tested here: cross-band incumbent contamination.
    # The code audit found no shared storage and no global lookup —
    # `restore_prior_state(workspace, ...)` resolves each prior iteration
    # by explicit path under its OWN workspace. With distinct workspaces
    # (asserted above), contamination has no mechanism, and a test for it
    # would guard a defect that cannot occur. Within-run inheritance and
    # resume are already covered by tests/unit/core/test_resume_incumbent.py.


class TestTheLaunchCommandCarriesOnlyJobSpecificInputs:
    def test_the_command_passes_band_and_chain_type(self, proc):
        cmd = proc.command()
        assert "--data_scope" in cmd and cmd[cmd.index("--data_scope") + 1] == "15-19"
        assert "--chain_type" in cmd and cmd[cmd.index("--chain_type") + 1] == "loss"
        assert "--run_name" in cmd and cmd[cmd.index("--run_name") + 1] == "v20_loss_15_19"

    def test_the_scheduler_does_not_restate_scientific_policy(self, proc):
        # Scientific policy has ONE home: launch_v20_campaign.sh. If the
        # orchestrator started passing these too, the two would drift and
        # the campaign's posture would depend on which one you read.
        cmd = " ".join(proc.command())
        for owned_by_the_launcher in (
            "--healthgate_mode",
            "--result_authority",
            "--llm_config",
            "--skip_formal_min_delta",
            "--bypass_formal_time_budget_min_delta",
            "--runtime_watchdog",
            "--gpu_admission_enforcement",
        ):
            assert owned_by_the_launcher not in cmd
