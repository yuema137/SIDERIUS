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

    def test_each_wave_launches_exactly_the_roster_chains_for_its_band(self):
        """Replaces `test_exactly_two_chains_per_wave_max_conc`.

        That test asserted `MAX_CONC == 2`, a variable that gated nothing
        — deleting it changed no behaviour, which is what made it a
        decoration test. The defect it was REACHING for is real and is
        preserved here: a wave must not launch more chains than intended.
        The property that was actually true is that the chains of a wave
        are exactly the ROSTER entries for that wave's band, so that is
        what is asserted — against the ROSTER, not against a constant.
        """
        r = _sourced(
            'for w in "${WAVES[@]}"; do IFS=: read -r n s f <<< "$w"; '
            'TAG="$(band_tag "$s")"; '
            'for q in "${ROSTER[@]}"; do IFS=: read -r run _ _ _ <<< "$q"; '
            'case "$run" in *_"$TAG") echo "$n $run";; esac; done; done'
        )
        assert r.returncode == 0, r.stderr
        per_wave: dict[str, list[str]] = {}
        for line in r.stdout.splitlines():
            wave, run = line.split()
            per_wave.setdefault(wave, []).append(run)
        expected = {str(n): sorted([arch, loss]) for (n, _scope, arch, loss) in WAVE_PAIRS}
        assert {k: sorted(v) for k, v in per_wave.items()} == expected

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
        both exits/start/end/disposition as one valid JSON record.

        Same defect class as before E-C4 — an operator field silently
        dropped from the record. The SHAPE changed: the eleven-positional
        `printf` became a typed writer, chains moved into an array, and
        the six `arch_*`/`loss_*` keys are now a compatibility mirror. The
        mirror is asserted here precisely because the operator reports
        still read those names.

        Pids and exits come from the marker files rather than from
        positional arguments, so the fixture writes them.
        """
        markers = tmp_path / "markers"
        markers.mkdir()
        for run, pid, code in (
            ("v19_arch_15_19", "1111", "0"),
            ("v19_loss_15_19", "2222", "137"),
        ):
            (markers / f"{run}.pid").write_text(pid)
            (markers / f"{run}.exit").write_text(f"EXIT={code}\n")
        env = {"WS_ROOT": str(tmp_path), "EXIT_DIR": str(markers)}
        r = _sourced(
            'WAVE_STATE="$WS_ROOT/wave_state.jsonl"; '
            'PAIR_SUMMARY_DIR="$WS_ROOT/pair_summaries"; '
            'LOGF="$WS_ROOT/log"; '
            "record_wave_summary 1 15-19 15_19 "
            "2026-07-30T00:00:00 2026-07-30T05:00:00 failed "
            "v19_arch_15_19 v19_loss_15_19; "
            'cat "$WAVE_STATE"',
            env,
        )
        assert r.returncode == 0, r.stderr
        rec = json.loads(r.stdout.strip())
        assert rec == {
            "wave_summary": 1,
            "record_id": "v19:1:15_19:1",
            "campaign_id": "v19",
            "band": "15-19",
            "band_tag": "15_19",
            "chains": [
                {"run_name": "v19_arch_15_19", "role": "arch", "pid": "1111", "exit": 0},
                {"run_name": "v19_loss_15_19", "role": "loss", "pid": "2222", "exit": 137},
            ],
            "arch_run": "v19_arch_15_19",
            "arch_pid": "1111",
            "arch_exit": 0,
            "loss_run": "v19_loss_15_19",
            "loss_pid": "2222",
            "loss_exit": 137,
            "start": "2026-07-30T00:00:00",
            "end": "2026-07-30T05:00:00",
            "disposition": "failed",
        }

    def test_a_wave_summary_never_makes_a_failed_chain_look_complete(self, tmp_path):
        """MUTATION TARGET, and the reason `chains` says `run_name`.

        `chain_completed` greps the WHOLE LINE for `"run": "<X>"` and then
        for `"exit": 0`. A chains array spelled `{"run": …, "exit": 0}`
        lets a wave summary in which ONE chain succeeded satisfy that
        predicate for EVERY chain it names — so the chain that exited 137
        would be skipped as already complete on the next resume, and the
        failure would disappear from the science.

        Measured, not theorised: D-E-3's own example record reproduced
        exactly this.
        """
        markers = tmp_path / "markers"
        markers.mkdir()
        for run, code in (("v19_arch_15_19", "0"), ("v19_loss_15_19", "137")):
            (markers / f"{run}.exit").write_text(f"EXIT={code}\n")
        env = {"WS_ROOT": str(tmp_path), "EXIT_DIR": str(markers)}
        r = _sourced(
            'WAVE_STATE="$WS_ROOT/wave_state.jsonl"; '
            'PAIR_SUMMARY_DIR="$WS_ROOT/pair_summaries"; '
            'LOGF="$WS_ROOT/log"; '
            "record_wave_summary 1 15-19 15_19 s e failed "
            "v19_arch_15_19 v19_loss_15_19; "
            "chain_completed v19_loss_15_19 && echo COMPLETE || echo INCOMPLETE",
            env,
        )
        assert r.stdout.strip().endswith("INCOMPLETE"), (
            "a chain that exited 137 reads as complete from its wave summary"
        )


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


class TestTheLiveProcessGuardExcludesOnlyItself:
    """D-E-7 / E-C6. The guard's self-exclusion was the literal string
    `v19_queue_runner`, so a renamed or copied runner stopped excluding
    itself and refused to launch anything.

    Each case runs the real `launch_chain` against a fixture process
    whose argv contains this run's workspace path, and reads the guard's
    own message out of the log — so what is asserted is the guard's
    decision, not the shape of a pipeline.
    """

    RUN = "v19_arch_15_19"
    BLOCKED = "live process referencing"

    def _guard_says(self, tmp_path: Path, fixture_comment: str, runner: Path | None = None) -> str:
        """Run `launch_chain` with one background process on the system
        whose argv contains `$WS_ROOT/$RUN`, and return the log."""
        import os

        ws_root = tmp_path / "root"
        ws_root.mkdir()
        shim = tmp_path / "shim"
        shim.mkdir()
        # `screen -ls` lists nothing; anything else succeeds silently, so
        # a launch that gets past the guard does not start a real chain.
        (shim / "screen").write_text('#!/bin/bash\nif [ "$1" = "-ls" ]; then exit 1; fi\nexit 0\n')
        (shim / "screen").chmod(0o755)
        marker = f"{ws_root}/{self.RUN}"
        script = f"""
        set +e
        LOGF="{tmp_path}/log"
        EXIT_DIR="{tmp_path}/markers"; mkdir -p "$EXIT_DIR"
        # A process whose argv contains this run's workspace path.
        # `; true` matters: bash EXECs a lone simple command, replacing
        # its own argv, and the marker would vanish from `ps` — the
        # fixture would then prove nothing while passing.
        # Output redirected: killing the wrapper orphans its `sleep`,
        # which would otherwise hold the captured pipes open and make
        # every case wait out the full sleep.
        bash -c "sleep 20; true # {fixture_comment} {marker}" >/dev/null 2>&1 &
        FIXTURE=$!
        # DETERMINISTIC cleanup. Killing only on the happy path leaks a
        # 20-second process whenever `launch_chain` exits non-zero or the
        # subprocess times out — and a leaked fixture is not inert: its
        # argv carries a workspace marker, so it pollutes the very `ps`
        # scan these tests and the guard itself depend on. Observed: a
        # full-suite run reported 148 unrelated failures purely from
        # accumulated fixture processes.
        trap 'kill "$FIXTURE" 2>/dev/null; wait "$FIXTURE" 2>/dev/null' EXIT
        # POLL, do not sleep a fixed interval. A fixed wait is a race: under
        # a loaded suite the fixture may not be visible in `ps` yet, the
        # guard then sees nothing, and a "should block" case fails
        # intermittently.
        for _ in $(seq 1 100); do
            if ps -eo args | grep -qF -- "{marker}"; then break; fi
            sleep 0.05
        done
        launch_chain {self.RUN} 15-19 15,16,17,18,19 arch
        """
        subprocess.run(
            ["bash", "-c", f"V19_QUEUE_NO_MAIN=1 source '{runner or RUNNER}'; {script}"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=dict(os.environ, WS_ROOT=str(ws_root), PATH=f"{shim}:{os.environ['PATH']}"),
            timeout=60,
        )
        log = tmp_path / "log"
        return log.read_text() if log.exists() else ""

    def test_a_genuine_external_process_still_blocks_the_launch(self, tmp_path):
        """The guard's MEANING, unchanged: something else is already
        holding this workspace, so do not launch on top of it."""
        log = self._guard_says(tmp_path, "some_other_program")
        assert self.BLOCKED in log

    def test_the_fixture_leaves_no_process_behind(self, tmp_path):
        """MUTATION TARGET: dropping the fixture's EXIT trap.

        These cases spawn a 20-second process whose argv carries a
        workspace marker. A leak is not inert — it pollutes the `ps` scan
        that both the guard and every other case in this class read, and
        it outlives the test by design. Measured once: accumulated fixture
        processes produced 148 unrelated failures across a full run.

        Asserted against THIS test's own marker, so a leak from an
        unrelated run cannot make it pass or fail spuriously.
        """
        import subprocess as _sp

        marker = str(tmp_path / "root" / self.RUN)
        self._guard_says(tmp_path, "leak_probe")

        survivors = _sp.run(
            ["bash", "-c", f"ps -eo args | grep -vF -- 'grep' | grep -F -- {marker!r} || true"],
            capture_output=True,
            text=True,
        ).stdout.strip()

        assert survivors == "", f"the fixture leaked a live process: {survivors!r}"

    def test_the_runner_does_not_see_itself(self, tmp_path):
        """Behaviour under the CURRENT filename is unchanged: a process
        whose argv carries this script's name is this runner."""
        log = self._guard_says(tmp_path, "v19_queue_runner.sh")
        assert self.BLOCKED not in log, "the runner treated its own process as a competing chain"

    def test_a_process_that_is_not_this_runner_is_not_excluded(self, tmp_path):
        """The exclusion must be narrow: only THIS script's name."""
        log = self._guard_says(tmp_path, "renamed_queue_runner.sh")
        assert self.BLOCKED in log, "a process that is NOT this runner was excluded from the scan"

    def test_a_renamed_runner_still_excludes_itself(self, tmp_path):
        """THE REGRESSION, and it requires an actually-renamed runner.

        Under `grep -v v19_queue_runner` a copy running as
        `renamed_queue_runner.sh` no longer matched its own exclusion, so
        it saw its own process holding the workspace and refused to
        launch anything. Varying only the FIXTURE's name cannot
        distinguish the fix — that variant passes under both — so this
        copies the runner and `_chain_common.sh` into a temp tree and
        runs the copy under a different filename.
        """
        import shutil

        scripts = tmp_path / "sdsc_submission_scripts"
        scripts.mkdir()
        renamed = scripts / "renamed_queue_runner.sh"
        shutil.copy(RUNNER, renamed)
        shutil.copy(RUNNER.parent / "_chain_common.sh", scripts / "_chain_common.sh")

        log = self._guard_says(tmp_path, "renamed_queue_runner.sh", runner=renamed)

        assert self.BLOCKED not in log, (
            "a renamed runner saw its own process as a competing chain — "
            "the hardcoded self-exclusion is back"
        )

    def test_the_exclusion_is_fixed_string_not_a_regex(self, tmp_path):
        """MUTATION TARGET: dropping `-F`.

        The basename is `v19_queue_runner.sh` and `.` is a regex
        wildcard, so a plain `grep -v` also excludes
        `v19_queue_runnerXsh` — widening the exclusion to processes that
        are not this runner, which is the direction that silently skips
        the guard.
        """
        log = self._guard_says(tmp_path, "v19_queue_runnerXsh")
        assert self.BLOCKED in log, (
            "a regex wildcard in the script's own name excluded an "
            "unrelated process from the live-process scan"
        )

    def test_the_exclusion_derives_from_the_script_name(self):
        """MUTATION TARGET: restoring the literal, in any campaign's
        spelling — and there must be exactly ONE process scan."""
        src = RUNNER.read_text(encoding="utf-8")
        assert 'RUNNER_BASENAME="${BASH_SOURCE[0]##*/}"' in src
        live = [
            line.strip()
            for line in src.splitlines()
            if "grep -v" in line and not line.strip().startswith("#")
        ]
        assert live == [
            'LIVE_PROCS="$(ps -eo args | grep -v grep | grep -vF -- "$RUNNER_BASENAME" '
            '| grep -F -- "$WS_ROOT/$RUN" || true)"'
        ], live

    def test_the_scan_shape_does_not_fail_open_under_pipefail(self):
        """DETERMINISTIC reproduction of the fail-open, independent of load.

        The real defect only surfaces when `ps` output is long enough that
        the upstream grep is still writing when the final grep exits — so
        on a quiet box the behavioural tests above pass with the BROKEN
        code. This reproduces it on demand by putting the match at the
        very start of a large synthetic stream, which guarantees the early
        close.

        Both halves are asserted: the `-q` shape must fail open (proving
        the test exercises the real mechanism and is not vacuous), and the
        production shape must not.
        """
        stream = "printf 'MATCH_TOKEN\\n'; yes filler | head -200000"
        broken = (
            f"set -o pipefail; ({stream}) | grep -v grep "
            '| grep -vF -- "runner.sh" | grep -qF -- "MATCH_TOKEN"'
        )
        fixed = (
            f'set -o pipefail; FOUND="$(({stream}) | grep -v grep '
            '| grep -vF -- "runner.sh" | grep -F -- "MATCH_TOKEN" || true)"; '
            '[ -n "$FOUND" ]'
        )

        broken_rc = subprocess.run(["bash", "-c", broken], capture_output=True).returncode
        fixed_rc = subprocess.run(["bash", "-c", fixed], capture_output=True).returncode

        assert broken_rc != 0, (
            "the `grep -q` shape did NOT fail open here, so this test is not "
            "exercising the SIGPIPE mechanism and proves nothing"
        )
        assert fixed_rc == 0, (
            "the production scan shape failed to report a match that is "
            "present — the guard would fail OPEN"
        )

    def test_the_scan_never_uses_grep_q(self):
        """MUTATION TARGET: reverting the scan to `grep -q`.

        `-q` exits on its first match and closes the pipe; under
        `pipefail` (`_chain_common.sh:41`) the upstream grep is SIGPIPEd,
        the pipeline reports 141, and the `if` reads that as "no match" —
        the guard fails OPEN. It is load-dependent, so the revert would
        pass on a quiet box and silently stop guarding on a busy one.

        Structural because the behavioural tests can only catch it while
        the machine is loaded enough to trigger the SIGPIPE.
        """
        src = RUNNER.read_text(encoding="utf-8")
        scan_lines = [
            line
            for line in src.splitlines()
            if "$WS_ROOT/$RUN" in line and "grep" in line and not line.strip().startswith("#")
        ]
        assert scan_lines, "the live-process scan disappeared"
        for line in scan_lines:
            assert "grep -q" not in line, (
                f"the live-process scan uses `grep -q`, which fails OPEN under pipefail: {line!r}"
            )
