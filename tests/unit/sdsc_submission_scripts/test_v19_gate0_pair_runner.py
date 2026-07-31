"""V19 Gate 0 pair runner — hardening tests (zero launch, no GPU, no LLM).

Covers the Gate 0 attempt-1 findings (2026-07-29):

* the frozen chain command is a single source of truth
  (``gate_chain_args``) consumed by both the launch path and these
  parity tests, so arch/loss can only differ in workspace, run_name,
  and advice path;
* the 90 s stagger health check stops the Gate (loss NEVER launched)
  when the arch chain fails first;
* identifier capture is self-reported from inside the chain screen
  (wrapper PID) instead of parsed from ``screen -ls`` (the attempt-1
  parse silently returned empty);
* both exit codes are preserved independently and the pair summary is
  written on EVERY exit path.

The full-flow tests replace ``screen`` with a PATH shim that "runs" each
chain by writing its exit marker, so the runner's real main flow —
launch, stagger, wait, summary, final exit code — executes end to end
deterministically.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_gate0_pair_runner.sh"
CHAIN_LIB = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"

# The ONLY fields allowed to differ between the arch and loss commands.
ALLOWED_DIFF_FLAGS = {"--workspace", "--run_name", "--advice"}

# Frozen Gate 0 values (operator spec) — parity-checked against
# gate_chain_args output flag-by-flag.
FROZEN_VALUES = {
    "--mode": "lilab",
    "--num_iterations": "2",
    "--max_rounds": "2",
    "--max_proposal_attempts": "3",
    "--max_epochs": "1",
    "--data_scope": "15-19",
    "--health_gate_files": "15,16,17,18,19",
    "--order_strategy_override": "sequential",
    "--file_order_override": "15,16,17,18,19",
    "--health_feedback_history_window_iterations": "3",
    "--health_feedback_history_max_entries_per_model": "8",
    "--skip_formal_min_delta": "0.0",
    "--bypass_formal_time_budget_min_delta": "0.5",
    "--trial_portion": "0.02",
    "--train_portion": "1.0",
    "--eval_portion": "0.01",
    "--formal_portion": "0.02",
    "--formal_train_portion": "1.0",
    "--formal_eval_portion": "0.01",
    "--trial_time_budget_minutes": "5",
    "--formal_time_budget_minutes": "30",
    # 24 -> 16 (operator 2026-07-31): this final Gate mirrors formal V19
    # admission rather than the generic Gate-standard generous values.
    "--trial_vram_budget_gb": "12",
    "--formal_vram_budget_gb": "12",
    "--runtime_safety_factor": "1.5",
    "--runtime_trial_safety_factor": "3.0",
    "--runtime_formal_safety_factor": "2.25",
    "--runtime_watchdog_safety_factor": "3.5",
    "--runtime_watchdog_floor_seconds": "120",
    "--formal_strategy": "snapshot",
    "--formal_round_strategy": "inherit_best_trial",
    "--exploration_mode": "explore",
    "--llm_config": "llm_configs/openai_tiered_v1.json",
    "--health_checks_config": "configs/health_checks_baseline_observe_mode.yaml",
}
FROZEN_SWITCHES = {
    "--auto_resume",
    "--enable_chain_incumbent_formal_gates",
    "--enable_structured_health_feedback",
    "--runtime_watchdog",
    "--ml_lit_review_enabled",
}
FORBIDDEN_FLAGS = {"--seed_paths", "--no-force_formal_round", "--file_index"}


def _sourced(snippet: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Source the runner definitions and run a snippet. GATE_ROOT/EXIT_DIR
    always point at a temp sandbox: helpers like log() write to
    $GATE_ROOT, and a bare source must NEVER touch the production Gate
    evidence directory (or a nonexistent /home path on CI)."""
    sandbox = tempfile.mkdtemp(prefix="gate0_sourced_")
    full_env = dict(os.environ, GATE_ROOT=sandbox, EXIT_DIR=sandbox, **(env or {}))
    return subprocess.run(
        ["bash", "-c", f"V19_GATE0_NO_MAIN=1 source '{RUNNER}'; {snippet}"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=full_env,
    )


def _chain_args(flavor: str) -> list[str]:
    r = _sourced(f"gate_chain_args {flavor}")
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def _as_dict(args: list[str]) -> tuple[dict[str, str], set[str]]:
    """Split an arg line list into {flag: value} and the set of bare switches."""
    values: dict[str, str] = {}
    switches: set[str] = set()
    i = 0
    while i < len(args):
        flag = args[i]
        assert flag.startswith("--"), f"positional arg in chain command: {flag}"
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            values[flag] = args[i + 1]
            i += 2
        else:
            switches.add(flag)
            i += 1
    return values, switches


class TestFrozenCommand:
    def test_syntax(self):
        r = subprocess.run(["bash", "-n", str(RUNNER)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_arch_loss_differ_only_in_intended_fields(self):
        av, asw = _as_dict(_chain_args("arch"))
        lv, lsw = _as_dict(_chain_args("loss"))
        assert asw == lsw  # switches identical
        diff = {k for k in set(av) | set(lv) if av.get(k) != lv.get(k)}
        assert diff == ALLOWED_DIFF_FLAGS, f"unintended drift: {sorted(diff - ALLOWED_DIFF_FLAGS)}"

    def test_frozen_values_exact(self):
        for flavor in ("arch", "loss"):
            values, switches = _as_dict(_chain_args(flavor))
            for flag, expected in FROZEN_VALUES.items():
                assert values.get(flag) == expected, (
                    f"{flavor}: {flag} = {values.get(flag)!r}, frozen {expected!r}"
                )
            assert switches == FROZEN_SWITCHES, f"{flavor}: switches {sorted(switches)}"
            assert values["--run_name"] == f"v19_c14_{flavor}_15_19"
            assert values["--advice"] == f"advice/workflow/v19_gate0_{flavor}.json"
            assert values["--workspace"].endswith(f"/v19_c14_{flavor}_15_19")

    def test_no_forbidden_flags(self):
        for flavor in ("arch", "loss"):
            flags = {a for a in _chain_args(flavor) if a.startswith("--")}
            bad = flags & FORBIDDEN_FLAGS
            assert not bad, f"{flavor}: forbidden flags present: {sorted(bad)}"

    def test_every_flag_recognized_by_chain_parser(self):
        """Every emitted flag must be in _chain_common.sh's parse_chain_args
        case statement — an unrecognized flag would kill the launch at parse
        time (the attempt-1 class of failure, one layer up)."""
        lib_src = CHAIN_LIB.read_text()
        for flavor in ("arch", "loss"):
            for flag in {a for a in _chain_args(flavor) if a.startswith("--")}:
                assert f"{flag})" in lib_src or f"{flag}|" in lib_src, (
                    f"{flag} not recognized by parse_chain_args"
                )


def _write_screen_shim(shim_dir: Path, exits: dict[str, str]) -> None:
    """A PATH `screen` shim: `-ls` lists nothing; `-dmS siderius-<run> …`
    simulates the chain by writing <run>.wrapperpid and <run>.exit with the
    scenario's exit code. The runner's real flow runs unmodified."""
    lines = [
        "#!/bin/bash",
        'if [ "$1" = "-ls" ]; then echo "No Sockets found."; exit 1; fi',
        "session=''; prev=''",
        'for a in "$@"; do [ "$prev" = "-dmS" ] && session="$a"; prev="$a"; done',
        'run="${session#siderius-}"',
        'echo 4242 > "$EXIT_DIR/$run.wrapperpid"',
    ]
    for run, code in exits.items():
        lines.append(f'[ "$run" = "{run}" ] && echo "EXIT={code}" > "$EXIT_DIR/$run.exit"')
    lines.append("exit 0")
    shim = shim_dir / "screen"
    shim.write_text("\n".join(lines) + "\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)


def _run_main(tmp_path: Path, exits: dict[str, str]) -> tuple[subprocess.CompletedProcess, dict]:
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    _write_screen_shim(shim_dir, exits)
    gate_root = tmp_path / "gate0"
    exit_dir = tmp_path / "markers"
    exit_dir.mkdir()
    env = dict(
        os.environ,
        PATH=f"{shim_dir}:{os.environ['PATH']}",
        GATE_ROOT=str(gate_root),
        EXIT_DIR=str(exit_dir),
        STAGGER_SECONDS="1",
        POLL_SECONDS="1",
        LAUNCH_SETTLE_SECONDS="0",
        WALL_CAP_SECONDS="60",
    )
    r = subprocess.run(
        ["bash", str(RUNNER)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=60,
    )
    summary_path = gate_root / "gate0_pair_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    return r, summary


class TestMainFlow:
    def test_both_pass(self, tmp_path):
        r, s = _run_main(tmp_path, {"v19_c14_arch_15_19": "0", "v19_c14_loss_15_19": "0"})
        assert r.returncode == 0, r.stderr
        assert s["arch_exit"] == 0 and s["loss_exit"] == 0
        assert s["loss_launched"] is True
        assert s["disposition"] == "pass_pending_analysis"
        assert s["arch_wrapper_pid"] == "4242"  # self-reported, not parsed

    def test_arch_failure_during_stagger_blocks_loss(self, tmp_path):
        r, s = _run_main(tmp_path, {"v19_c14_arch_15_19": "1"})
        assert r.returncode != 0
        assert s["arch_exit"] == 1
        assert s["loss_launched"] is False
        assert s["loss_exit"] is None
        assert s["disposition"] == "arch_failed_before_stagger"
        # the loss chain must never have been "run" by the shim
        assert not (tmp_path / "markers" / "v19_c14_loss_15_19.exit").exists()

    def test_one_chain_failure_not_masked(self, tmp_path):
        r, s = _run_main(tmp_path, {"v19_c14_arch_15_19": "0", "v19_c14_loss_15_19": "7"})
        assert r.returncode != 0  # overall non-zero when either chain fails
        assert s["arch_exit"] == 0 and s["loss_exit"] == 7  # both preserved
        assert s["disposition"] == "chain_failure"

    def test_summary_written_even_on_launch_refusal(self, tmp_path):
        """A pre-existing workspace refuses the cold-start launch; the pair
        summary is still written (trap path)."""
        (tmp_path / "gate0" / "v19_c14_arch_15_19").mkdir(parents=True)
        r, s = _run_main(tmp_path, {})
        assert r.returncode != 0
        assert s["disposition"] == "arch_launch_error"
        assert s["loss_launched"] is False


class TestHelpers:
    def test_stagger_check_passes_on_arch_exit_zero(self, tmp_path):
        r = _sourced(
            'STAGGER_SECONDS=1; EXIT_DIR="$TD"; '
            'echo "EXIT=0" > "$TD/v19_c14_arch_15_19.exit"; '
            "stagger_health_check; echo rc=$?",
            env={"TD": str(tmp_path)},
        )
        assert "rc=0" in r.stdout

    def test_marker_exit_missing_and_present(self, tmp_path):
        r = _sourced(
            'EXIT_DIR="$TD"; echo "EXIT=3" > "$TD/x.exit"; echo $(marker_exit x) $(marker_exit y)',
            env={"TD": str(tmp_path)},
        )
        assert r.stdout.split() == ["3", "missing"]

    def test_wrapper_pid_unknown_when_absent(self, tmp_path):
        r = _sourced('EXIT_DIR="$TD"; wrapper_pid nope', env={"TD": str(tmp_path)})
        assert r.stdout.strip() == "unknown"
