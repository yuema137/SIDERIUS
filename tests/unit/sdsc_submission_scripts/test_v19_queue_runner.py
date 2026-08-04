"""V19 pairwise queue runner — frozen-plan tests (zero launch, no GPU).

Operator revision 2026-07-29: four waves of two concurrent chains
(arch+loss, same band), band order 15-19 -> 10-14 -> 4-9 -> 0-3.

The runner exposes `V19_QUEUE_NO_MAIN=1 source ...` to load the wave
definitions and helper functions without parsing args or launching.
Error paths run the real script with a temp WS_ROOT and exit before any
launch work.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"

WAVE_PAIRS = [
    ("1", "15-19", "v19_arch_15_19", "v19_loss_15_19"),
    ("2", "10-14", "v19_arch_10_14", "v19_loss_10_14"),
    ("3", "4-9", "v19_arch_04_09", "v19_loss_04_09"),
    ("4", "0-3", "v19_arch_00_03", "v19_loss_00_03"),
]

EXPECTED_ORDERS = {
    "0-3": "0,1,2,3",
    "4-9": "4,5,6,7,8,9",
    "10-14": "10,11,12,13,14",
    "15-19": "15,16,17,18,19",
}


def _sourced(snippet: str, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    full_env = dict(os.environ, **(env or {}))
    return subprocess.run(
        ["bash", "-c", f"V19_QUEUE_NO_MAIN=1 source '{RUNNER}'; {snippet}"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=full_env,
    )


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ, WS_ROOT=str(tmp_path))
    return subprocess.run(
        ["bash", str(RUNNER), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
    )


class TestFrozenWaves:
    def test_syntax(self):
        r = subprocess.run(["bash", "-n", str(RUNNER)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_exact_wave_order_and_pairing(self):
        """Four waves, band order 15-19 -> 10-14 -> 4-9 -> 0-3; each wave
        derives exactly its arch+loss pair (same band)."""
        r = _sourced(
            'for w in "${WAVES[@]}"; do IFS=: read -r n s f <<< "$w"; '
            'TAG="$(band_tag "$s")"; echo "$n $s v19_arch_$TAG v19_loss_$TAG"; done'
        )
        assert r.returncode == 0, r.stderr
        got = [tuple(line.split()) for line in r.stdout.splitlines()]
        assert got == WAVE_PAIRS

    def test_exactly_two_chains_per_wave_max_conc(self):
        r = _sourced('echo "$MAX_CONC"')
        assert r.stdout.strip() == "2"

    def test_roster_covers_all_eight_exactly_once_in_wave_order(self):
        r = _sourced('for q in "${ROSTER[@]}"; do echo "${q%%:*}"; done')
        names = r.stdout.split()
        expected = [n for (_, _, arch, loss) in WAVE_PAIRS for n in (arch, loss)]
        assert names == expected
        assert len(set(names)) == 8  # no duplicates → no duplicate workspaces

    def test_file_orders_ascending_and_explicit(self):
        for scope, expected in EXPECTED_ORDERS.items():
            r = _sourced(f"file_order_for_scope {scope}")
            assert r.returncode == 0
            assert r.stdout.strip() == expected, scope

    def test_unknown_scope_fails(self):
        assert _sourced("file_order_for_scope 2-7").returncode != 0


class TestWaveStateMachine:
    """Completed-chain skip + per-chain exit preservation (authoritative
    persisted status, not log text)."""

    def _state_env(self, tmp_path: Path, records: list[dict]) -> dict:
        # E-C2: the queue state moved from a campaign-PREFIXED file under
        # the shared root to a campaign-scoped DIRECTORY. The defect class
        # here is unchanged — a completed chain must be recognised as
        # completed — only the path it is recognised from.
        state = tmp_path / "v19" / "queue_state" / "wave_state.jsonl"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            "".join(
                f'{{"run": "{r["run"]}", "wave": {r["wave"]}, "exit": {r["exit"]}, '
                f'"start": "s", "end": "e"}}\n'
                for r in records
            )
        )
        return {"WS_ROOT": str(tmp_path)}

    def test_completed_chain_detected(self, tmp_path):
        env = self._state_env(tmp_path, [{"run": "v19_arch_15_19", "wave": 1, "exit": 0}])
        r = _sourced("chain_completed v19_arch_15_19 && echo YES || echo NO", env)
        assert r.stdout.strip() == "YES"

    def test_failed_chain_not_completed(self, tmp_path):
        env = self._state_env(tmp_path, [{"run": "v19_loss_15_19", "wave": 1, "exit": 137}])
        r = _sourced("chain_completed v19_loss_15_19 && echo YES || echo NO", env)
        assert r.stdout.strip() == "NO"

    def test_absent_chain_not_completed(self, tmp_path):
        env = self._state_env(tmp_path, [])
        r = _sourced("chain_completed v19_arch_10_14 && echo YES || echo NO", env)
        assert r.stdout.strip() == "NO"

    def test_mixed_wave_distinguishes_success_and_failure(self, tmp_path):
        """One successful + one failed chain in the same wave are told
        apart — the successful one is skippable, the failed one is not."""
        env = self._state_env(
            tmp_path,
            [
                {"run": "v19_arch_15_19", "wave": 1, "exit": 0},
                {"run": "v19_loss_15_19", "wave": 1, "exit": 1},
            ],
        )
        r = _sourced(
            "chain_completed v19_arch_15_19 && echo A_DONE; "
            "chain_completed v19_loss_15_19 || echo L_INCOMPLETE",
            env,
        )
        assert "A_DONE" in r.stdout and "L_INCOMPLETE" in r.stdout

    def test_failed_then_recovered_chain_completed(self, tmp_path):
        """A later exit-0 record after a failure marks the chain complete
        (targeted --only recovery appends a new record)."""
        env = self._state_env(
            tmp_path,
            [
                {"run": "v19_loss_15_19", "wave": 1, "exit": 1},
                {"run": "v19_loss_15_19", "wave": '"only"', "exit": 0},
            ],
        )
        r = _sourced("chain_completed v19_loss_15_19 && echo YES || echo NO", env)
        assert r.stdout.strip() == "YES"

    def test_record_chain_appends_valid_json(self, tmp_path):
        env = {"WS_ROOT": str(tmp_path)}
        r = _sourced(
            'WAVE_STATE="$WS_ROOT/v19_wave_state.jsonl"; '
            "record_chain v19_arch_15_19 1 0 2026-07-30T00:00:00 2026-07-30T01:00:00; "
            'cat "$WAVE_STATE"',
            env,
        )
        rec = json.loads(r.stdout.strip())
        assert rec == {
            "run": "v19_arch_15_19",
            "wave": 1,
            "exit": 0,
            "start": "2026-07-30T00:00:00",
            "end": "2026-07-30T01:00:00",
            "pid": "unknown",  # no pid file in this fixture
        }

    def test_wave_summary_record_has_all_operator_fields(self, tmp_path):
        """§5.1: the wave summary persists wave/band/both runs/both pids/
        both exits/start/end/disposition as one valid JSON record."""
        env = {"WS_ROOT": str(tmp_path)}
        r = _sourced(
            'WAVE_STATE="$WS_ROOT/v19_wave_state.jsonl"; '
            "record_wave_summary 1 15-19 v19_arch_15_19 v19_loss_15_19 "
            "1111 2222 0 137 2026-07-30T00:00:00 2026-07-30T05:00:00 failed; "
            'cat "$WAVE_STATE"',
            env,
        )
        rec = json.loads(r.stdout.strip())
        assert rec == {
            "wave_summary": 1,
            "band": "15-19",
            "arch_run": "v19_arch_15_19",
            "loss_run": "v19_loss_15_19",
            "arch_pid": "1111",
            "loss_pid": "2222",
            "arch_exit": 0,
            "loss_exit": 137,
            "start": "2026-07-30T00:00:00",
            "end": "2026-07-30T05:00:00",
            "disposition": "failed",
        }


class TestLaunchCommandContent:
    SRC = RUNNER.read_text()

    def test_v19_deltas_present(self):
        for flag in (
            "--enable_chain_incumbent_formal_gates",
            "--order_strategy_override sequential",
            "--file_order_override '$ORDER'",
            "--enable_structured_health_feedback",
            "--health_feedback_history_window_iterations 3",
            "--health_feedback_history_max_entries_per_model 8",
            "--runtime_watchdog_safety_factor 3.5",
        ):
            assert flag in self.SRC, flag

    def test_v18_settings_unchanged(self):
        for flag in (
            # 20 -> 10 (operator 2026-07-31): the fresh campaign runs a
            # 10-iteration treatment to bound cost, wall time and GPU use.
            # Rendered from CAMPAIGN_ITERATIONS, deliberately NOT
            # NUM_ITERATIONS — _chain_common.sh sets that to 2, and a
            # `${NUM_ITERATIONS:-10}` here silently resolved to 2.
            "--num_iterations $CAMPAIGN_ITERATIONS",
            "--max_rounds 3",
            "--max_epochs 1",
            "--skip_formal_min_delta 0.0",
            "--bypass_formal_time_budget_min_delta 0.5",
            "--trial_time_budget_minutes 20",
            "--formal_time_budget_minutes 120",
            "--trial_vram_budget_gb 12",
            "--formal_vram_budget_gb 12",
            "--runtime_watchdog \\",
            "--runtime_safety_factor 1.5",
            "--runtime_trial_safety_factor 3.0",
            # 2.0 -> 2.25 (operator 2026-07-31): C12 measured pairwise
            # slowdowns to 2.13x, which 2.0 does not cover.
            "--runtime_formal_safety_factor 2.25",
            "--runtime_watchdog_floor_seconds 120",
            "--formal_strategy snapshot",
            "--formal_round_strategy inherit_best_trial",
            "--exploration_mode explore",
            "--ml_lit_review_enabled",
            "--llm_config llm_configs/openai_tiered_v1.json",
            "advice/workflow/v18r_${FLAVOR}_explorer.json",
            "configs/health_checks_baseline_observe_mode.yaml",
        ):
            assert flag in self.SRC, flag

    def test_wave_gating_and_stop_policy_present(self):
        """The queue waits for BOTH chains (individual markers) and stops
        before the next wave on any failure."""
        assert "wait_and_record" in self.SRC
        assert "marker_exit" in self.SRC
        assert "QUEUE STOPPED before the next wave" in self.SRC
        assert "--only executions run the selection SERIALLY" in self.SRC

    def test_old_h100_profiles_untouched(self):
        """The V18/H100 launch surfaces keep their own values — no 3.5
        watchdog override leaks into them."""
        for script in ("launch_v18_wave1.sh", "v18r_queue_runner.sh"):
            src = (REPO_ROOT / "sdsc_submission_scripts" / script).read_text()
            assert "--runtime_watchdog_safety_factor" not in src, script
            assert "--runtime_trial_safety_factor 3.0" in src, script
            assert "--runtime_formal_safety_factor 2.0" in src, script


class TestOnlySelection:
    def test_unknown_name_fails_before_any_launch(self, tmp_path):
        r = _run(tmp_path, "--only", "v19_bogus")
        assert r.returncode == 1
        assert "unknown name" in r.stderr
        assert "v19_arch_15_19" in r.stderr
        assert not (tmp_path / "v19" / "queue_state" / "wave_state.jsonl").exists()

    def test_duplicate_fails(self, tmp_path):
        r = _run(tmp_path, "--only", "v19_arch_15_19,v19_arch_15_19")
        assert r.returncode == 1
        assert "duplicate" in r.stderr

    def test_only_without_value_fails(self, tmp_path):
        r = _run(tmp_path, "--only")
        assert r.returncode == 1
        assert "--only requires" in r.stderr

    def test_unknown_argument_fails(self, tmp_path):
        r = _run(tmp_path, "--bogus")
        assert r.returncode == 1
        assert "unknown argument" in r.stderr

    def test_completed_only_selection_skips_and_exits_clean(self, tmp_path):
        """A targeted run of an already-completed chain skips it (never
        relaunched) and exits 0 without touching screens.

        That is the defect this test catches, and E-C2 did not change it:
        relaunching a completed chain clobbers its finished workspace.
        Only the state and log LOCATIONS moved — from campaign-prefixed
        files under the shared root into the campaign's own directory.
        The legacy-filename variant of this scenario arrives in E-C3,
        where adoption exists to read it.
        """
        state = tmp_path / "v19" / "queue_state" / "wave_state.jsonl"
        state.parent.mkdir(parents=True)
        state.write_text(
            '{"run": "v19_arch_15_19", "wave": 1, "exit": 0, "start": "s", "end": "e"}\n'
        )
        r = _run(tmp_path, "--only", "v19_arch_15_19")
        assert r.returncode == 0, r.stderr
        log = (tmp_path / "v19" / "queue_state" / "queue_runner.log").read_text()
        assert "SKIP v19_arch_15_19: already completed" in log
        assert "LAUNCHED" not in log
