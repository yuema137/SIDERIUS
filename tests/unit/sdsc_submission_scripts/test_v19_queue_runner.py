"""V19 queue runner — frozen-plan tests (zero launch, no GPU, no screen).

The runner exposes a test hook (`V19_QUEUE_NO_MAIN=1 source …`) that loads
the frozen QUEUE and helper functions without parsing args or entering the
launch loop. Error paths (--only validation) run the real script with a
temp WS_ROOT and exit before any launch work.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"

FROZEN_ORDER = [
    "v19_arch_00_03",
    "v19_arch_04_09",
    "v19_arch_10_14",
    "v19_arch_15_19",
    "v19_loss_00_03",
    "v19_loss_04_09",
    "v19_loss_10_14",
    "v19_loss_15_19",
]

EXPECTED_ORDERS = {
    "0-3": "0,1,2,3",
    "4-9": "4,5,6,7,8,9",
    "10-14": "10,11,12,13,14",
    "15-19": "15,16,17,18,19",
}


def _sourced(snippet: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f"V19_QUEUE_NO_MAIN=1 source '{RUNNER}'; {snippet}"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
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


class TestFrozenQueue:
    def test_syntax(self):
        r = subprocess.run(["bash", "-n", str(RUNNER)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_queue_is_the_frozen_eight_chain_order(self):
        r = _sourced('for q in "${QUEUE[@]}"; do echo "${q%%:*}"; done')
        assert r.returncode == 0, r.stderr
        assert r.stdout.split() == FROZEN_ORDER

    def test_single_gpu_serial_concurrency(self):
        r = _sourced('echo "$MAX_CONC"')
        assert r.stdout.strip() == "1"

    def test_file_orders_ascending_and_explicit(self):
        for scope, expected in EXPECTED_ORDERS.items():
            r = _sourced(f"file_order_for_scope {scope}")
            assert r.returncode == 0
            assert r.stdout.strip() == expected, scope

    def test_unknown_scope_fails(self):
        r = _sourced("file_order_for_scope 2-7")
        assert r.returncode != 0

    def test_queue_scopes_map_to_orders(self):
        """Every queue entry's scope has an explicit ascending order."""
        r = _sourced(
            'for q in "${QUEUE[@]}"; do IFS=: read -r n s f a <<< "$q"; '
            'echo "$n $(file_order_for_scope "$s")"; done'
        )
        assert r.returncode == 0, r.stderr
        lines = dict(line.split(" ", 1) for line in r.stdout.splitlines())
        assert lines["v19_arch_00_03"] == "0,1,2,3"
        assert lines["v19_loss_15_19"] == "15,16,17,18,19"


class TestLaunchCommandContent:
    """Static assertions on the frozen chain command (source of truth for
    the launch report): V19 deltas present, V18-identical values intact."""

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
            "--num_iterations 20",
            "--max_rounds 3",
            "--max_epochs 1",
            "--skip_formal_min_delta 0.0",
            "--bypass_formal_time_budget_min_delta 0.5",
            "--trial_time_budget_minutes 20",
            "--formal_time_budget_minutes 120",
            "--trial_vram_budget_gb 16",
            "--formal_vram_budget_gb 16",
            "--runtime_watchdog \\",
            "--runtime_safety_factor 1.5",
            "--runtime_trial_safety_factor 3.0",
            "--runtime_formal_safety_factor 2.0",
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


class TestOnlySelection:
    def test_unknown_name_fails_before_any_launch(self, tmp_path):
        r = _run(tmp_path, "--only", "v19_bogus")
        assert r.returncode == 1
        assert "unknown name" in r.stderr
        assert "v19_arch_00_03" in r.stderr  # valid names listed
        assert not (tmp_path / "v19_queue_state").exists()

    def test_duplicate_fails(self, tmp_path):
        r = _run(tmp_path, "--only", "v19_arch_00_03,v19_arch_00_03")
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

    def test_targeted_run_uses_transient_state(self):
        """--only runs must not consume the persistent full-queue index:
        the script switches STATE to a per-invocation file (static
        assertion on the guard block)."""
        src = RUNNER.read_text()
        assert 'STATE="$WS_ROOT/v19_queue_state_only.$$"' in src
        assert "must never suppress" in src
