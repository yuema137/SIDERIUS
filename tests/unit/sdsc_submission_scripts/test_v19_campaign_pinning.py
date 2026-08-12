"""The formal V19 campaign must be pinned at its own launch surface.

Two failures this prevents, one of which already happened.

**Silent default drift.** The queue runner sources `_chain_common.sh`,
which assigns the chain defaults at load time. Anything the campaign
leaves unspecified therefore comes from that library, and an unrelated
edit to it would change V19's scientific scope mid-campaign without
touching the campaign. Every value that defines what the campaign
MEASURES is pinned in the rendered command and asserted here.

**Shadowing.** On 2026-07-31 the campaign's iteration count was written
`NUM_ITERATIONS="${NUM_ITERATIONS:-10}"` — after the source, where
`NUM_ITERATIONS` was already 2. The `:-` default never applied and the
campaign would have run 2 iterations instead of 10. The campaign now
uses names of its own that a library default cannot shadow.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"
COMMON = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"

#: What the campaign measures. Every one of these must appear in the
#: rendered command, not be inherited.
PINNED = {
    "--num_iterations": "$CAMPAIGN_ITERATIONS",
    "--max_rounds": "3",
    "--max_proposal_attempts": "3",
    "--max_epochs": "1",
    "--trial_portion": "0.1",
    "--train_portion": "0.1",
    "--eval_portion": "0.1",
    "--formal_portion": "0.1",
    "--formal_train_portion": "1.0",
    "--formal_eval_portion": "1.0",
    "--trial_time_budget_minutes": "20",
    "--formal_time_budget_minutes": "120",
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
    "--order_strategy_override": "sequential",
    "--health_feedback_history_window_iterations": "3",
    "--health_feedback_history_max_entries_per_model": "8",
    "--skip_formal_min_delta": "0.0",
    "--bypass_formal_time_budget_min_delta": "0.5",
    "--llm_config": "llm_configs/openai_tiered_v1.json",
    "--health_checks_config": "configs/health_checks_baseline_observe_mode.yaml",
}


def _launch_block(source: str) -> str:
    start = source.index("bash sdsc_submission_scripts/run_chain.sh")
    return source[start : source.index("status=\\$?", start)]


@pytest.mark.parametrize("flag,value", sorted(PINNED.items()))
def test_every_scientific_setting_is_pinned_in_the_command(flag, value):
    block = _launch_block(RUNNER.read_text())
    assert re.search(rf"{re.escape(flag)}\s+{re.escape(value)}(\s|\\|$)", block), (
        f"{flag} is not pinned to {value} in the rendered V19 command; it would "
        "be inherited from _chain_common.sh and could change without anyone "
        "touching the campaign"
    )


def _sourced(snippet: str, **env) -> str:
    result = subprocess.run(
        ["bash", "-c", f"V19_QUEUE_NO_MAIN=1 source '{RUNNER}'; {snippet}"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=dict(os.environ, **{k: str(v) for k, v in env.items()}),
    )
    return result.stdout.strip()


class TestLibraryDefaultsCannotChangeTheCampaign:
    """Perturb `_chain_common.sh` and prove nothing rendered moves."""

    PERTURBED: ClassVar[dict[str, str]] = {
        "NUM_ITERATIONS": "99",
        "MAX_ROUNDS": "99",
        "MAX_EPOCHS": "99",
        "TRIAL_PORTION": "0.99",
        "TRAIN_PORTION": "0.99",
        "EVAL_PORTION": "0.99",
        "FORMAL_PORTION": "0.99",
        "FORMAL_TRAIN_PORTION": "0.99",
        "FORMAL_EVAL_PORTION": "0.99",
        "MAX_PROPOSAL_ATTEMPTS": "99",
    }

    def test_perturbing_every_default_leaves_the_command_identical(self, tmp_path):
        """The whole point: the campaign is defined by the campaign."""
        scratch = tmp_path / "repo"
        shutil.copytree(REPO_ROOT / "sdsc_submission_scripts", scratch / "sdsc_submission_scripts")
        common = scratch / "sdsc_submission_scripts" / "_chain_common.sh"
        text = common.read_text()
        for name, bad in self.PERTURBED.items():
            text = re.sub(rf"^{name}=\S+", f"{name}={bad}", text, count=1, flags=re.M)
        common.write_text(text)

        original = _launch_block(RUNNER.read_text())
        perturbed = _launch_block(
            (scratch / "sdsc_submission_scripts" / "v19_queue_runner.sh").read_text()
        )
        assert perturbed == original

        # and none of the sabotage values reached the rendered command
        for bad in set(self.PERTURBED.values()):
            assert f" {bad}" not in perturbed

    def test_the_iteration_count_is_not_shadowed_by_the_library(self):
        """The 2026-07-31 bug, asserted directly: `_chain_common.sh` sets
        NUM_ITERATIONS=2, so the campaign must not read that name."""
        assert _sourced("echo $CAMPAIGN_ITERATIONS") == "10"
        library_default = _sourced("echo $NUM_ITERATIONS")
        assert library_default != "10", "test is meaningless if they already agree"
        block = _launch_block(RUNNER.read_text())
        assert "--num_iterations $CAMPAIGN_ITERATIONS" in block
        assert "--num_iterations $NUM_ITERATIONS" not in block

    def test_the_campaign_iteration_count_is_overridable_for_a_rerun(self):
        assert _sourced("echo $CAMPAIGN_ITERATIONS", CAMPAIGN_ITERATIONS=7) == "7"


class TestCampaignIdentity:
    def test_every_run_name_derives_from_the_campaign_id(self):
        names = _sourced('for r in "${ROSTER[@]}"; do echo "${r%%:*}"; done', CAMPAIGN_ID="camp1")
        assert names.splitlines() == [
            "camp1_arch_15_19",
            "camp1_loss_15_19",
            "camp1_arch_10_14",
            "camp1_loss_10_14",
            "camp1_arch_04_09",
            "camp1_loss_04_09",
            "camp1_arch_00_03",
            "camp1_loss_00_03",
        ]

    def test_queue_state_and_log_carry_the_campaign_id(self, tmp_path):
        """E-C2 changed the MECHANISM, not the property: identity used to
        be a filename prefix (`camp1_wave_state.jsonl`) and is now a
        directory segment (`camp1/queue_state/wave_state.jsonl`). The
        defect guarded is the same one — a queue-state path two campaigns
        can both resolve to — and the directory form is what fixed it, so
        the assertion asks for a path SEGMENT rather than a prefix."""
        out = _sourced(
            'echo "$WAVE_STATE"; echo "$LOGF"', CAMPAIGN_ID="camp1", WS_ROOT=str(tmp_path)
        )
        assert all("/camp1/" in line for line in out.splitlines()), out

    def test_a_fresh_campaign_cannot_collide_with_a_previous_one(self):
        """Distinct ids must produce entirely disjoint run names."""
        a = set(
            _sourced('for r in "${ROSTER[@]}"; do echo "${r%%:*}"; done', CAMPAIGN_ID="a").split()
        )
        b = set(
            _sourced('for r in "${ROSTER[@]}"; do echo "${r%%:*}"; done', CAMPAIGN_ID="b").split()
        )
        assert not (a & b)


class TestCampaignCaps:
    def test_the_operator_caps_are_configured(self):
        out = _sourced(
            "echo $WAVE_WALL_SECONDS $CAMPAIGN_WALL_SECONDS "
            "$CAMPAIGN_TOKEN_CAP $CAMPAIGN_COST_CAP_USD"
        )
        wave, campaign, tokens, cost = out.split()
        assert int(wave) == 72 * 3600, "per-wave cap must be 72 h"
        assert int(campaign) == 12 * 24 * 3600, "campaign cap must be 12 days"
        assert int(tokens) == 60_000_000
        assert int(cost) == 180

    def test_the_wave_cap_is_no_longer_the_gate_sized_24h(self):
        assert int(_sourced("echo $WAVE_WALL_SECONDS")) > 86400

    def test_spend_is_zero_on_an_empty_campaign_root(self, tmp_path):
        out = _sourced("campaign_spend", CAMPAIGN_ID="camp1", WS_ROOT=str(tmp_path))
        assert out.split() == ["0", "0.00"]

    def test_spend_sums_every_chain_ledger(self, tmp_path):
        """Real records nest the count and also carry a `chars.total`."""
        for name, rows in (("camp1_arch_15_19", [1000, 2000]), ("camp1_loss_15_19", [500])):
            ws = tmp_path / name
            ws.mkdir()
            (ws / "token_usage.jsonl").write_text(
                "".join(
                    json.dumps(
                        {
                            "tokens": {"prompt": n - 1, "completion": 1, "total": n},
                            "chars": {"total": 999999},
                        }
                    )
                    + "\n"
                    for n in rows
                )
            )
        out = _sourced("campaign_spend", CAMPAIGN_ID="camp1", WS_ROOT=str(tmp_path))
        tokens, cost = out.split()
        assert int(tokens) == 3500, "the chars total must not be counted as tokens"
        assert float(cost) == pytest.approx(3500 / 1_000_000 * 3.00, abs=0.01)

    def test_spend_ignores_other_campaigns(self, tmp_path):
        other = tmp_path / "someone_else_arch_15_19"
        other.mkdir()
        (other / "token_usage.jsonl").write_text('{"tokens": {"total": 999999}}\n')
        out = _sourced("campaign_spend", CAMPAIGN_ID="camp1", WS_ROOT=str(tmp_path))
        assert out.split()[0] == "0"

    def test_the_cost_estimator_is_documented_and_overridable(self):
        assert _sourced("echo $COST_PER_MTOK_USD") == "3.00"
        assert _sourced("echo $COST_PER_MTOK_USD", COST_PER_MTOK_USD="9.5") == "9.5"
        assert "ledger records no" in RUNNER.read_text(), "the estimator must say why it exists"


class TestWaveOrderUnchanged:
    def test_waves_and_sorted_file_order(self):
        out = _sourced(
            'for w in "${WAVES[@]}"; do IFS=: read -r n s f <<< "$w"; '
            'echo "$n $s $(file_order_for_scope $s)"; done'
        )
        assert out.splitlines() == [
            "1 15-19 15,16,17,18,19",
            "2 10-14 10,11,12,13,14",
            "3 4-9 4,5,6,7,8,9",
            "4 0-3 0,1,2,3",
        ]

    def test_each_scope_pairs_with_matching_health_gate_files(self):
        out = _sourced('for w in "${WAVES[@]}"; do echo "$w"; done')
        for line in out.splitlines():
            _, scope, files = line.split(":")
            low, high = (int(x) for x in scope.split("-"))
            assert [int(x) for x in files.split(",")] == list(range(low, high + 1))


class TestTheDocumentedDefaultsMatchTheCode:
    """A documented default that disagrees with the code is worse than an
    undocumented one: an operator plans around it.

    `WAVE_WALL_SECONDS` sat at `86400` in two operator-facing documents
    while the code shipped `259200` — a 3x difference in how long a stalled
    wave is tolerated. The existing cap test asserts only `> 86400`, which
    passes for any value above a day and so could not catch the drift.
    """

    #: Docs that state the default, and must therefore state the real one.
    #: ``docs/running_chain_test.md`` was removed by the operator-directed
    #: docs sweep (PR #195, commit 6bc1f536) — master CI has been red on
    #: this test since; the dangling entry is dropped here (inherited-red
    #: repair carried on the Step-00 branch, not Step-00 scope).
    DOCS = ("docs/design/runtime_estimation_and_calibration.md",)

    def _code_default(self) -> int:
        return int(_sourced("echo $WAVE_WALL_SECONDS"))

    def test_no_doc_states_a_wave_cap_the_code_does_not_use(self):
        from pathlib import Path

        repo = Path(__file__).resolve().parents[3]
        actual = self._code_default()
        for rel in self.DOCS:
            text = (repo / rel).read_text(encoding="utf-8")
            for line in text.splitlines():
                if "WAVE_WALL_SECONDS" not in line:
                    continue
                # Any bare seconds-magnitude number on the line must be the
                # real default. Anything else is a claim about a value the
                # code does not use.
                for token in re.findall(r"\b\d{4,7}\b", line):
                    assert int(token) == actual, (
                        f"{rel} states {token} for WAVE_WALL_SECONDS; the code default is {actual}"
                    )

    def test_the_code_default_is_the_72h_cap(self):
        """Hardcoded, not read back from the thing under test."""
        assert self._code_default() == 259200


class TestSpendMembershipIsExplicitInProduction:
    """The queue's budget authority must read exactly the campaign's runs.

    `campaign_spend.py` used to infer membership from a
    `{campaign_id}_*` glob, so a campaign whose id extended another's with
    an underscore absorbed it — `v20` counted `v20_extra_*` as its own, and
    that total is what `token_cap_reached` acts on at
    `v19_queue_runner.sh:432`. One campaign could be stopped by another's
    spend.
    """

    def _ledger(self, root, name: str, total: int) -> None:
        ws = root / name
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "token_usage.jsonl").write_text(
            json.dumps({"tokens": {"total": total}}) + "\n", encoding="utf-8"
        )

    def test_the_production_caller_passes_roster_members(self):
        """REACHABILITY. The shell must supply the names, not rely on the
        Python to guess them — otherwise the fix is unreached."""
        from pathlib import Path

        runner = (
            Path(__file__).resolve().parents[3] / "sdsc_submission_scripts" / "v19_queue_runner.sh"
        )
        text = runner.read_text(encoding="utf-8")
        body = text[text.index("campaign_spend() {") : text.index("# Launch one chain")]
        assert "--run-name" in body, "the caller does not pass explicit membership"
        assert 'for spec in "${ROSTER[@]}"' in body, "membership does not come from the ROSTER"
        assert "--campaign-id" in body, "campaign id is still passed, for provenance"

    def test_v20_does_not_absorb_v20_extra_through_the_real_caller(self, tmp_path):
        """THE DEFECT, at the production boundary rather than in the helper."""
        self._ledger(tmp_path, "v20_arch_15_19", 100)
        self._ledger(tmp_path, "v20_extra_arch_15_19", 500)
        out = _sourced("campaign_spend", CAMPAIGN_ID="v20", WS_ROOT=str(tmp_path))
        assert out.split()[0] == "100", (
            f"v20 reported {out.split()[0]} tokens; it owns 100 and must not absorb v20_extra's 500"
        )

    def test_v20a_stays_independent_through_the_real_caller(self, tmp_path):
        """Disproved first hypothesis, kept as a regression boundary."""
        self._ledger(tmp_path, "v20_arch_15_19", 100)
        self._ledger(tmp_path, "v20a_arch_15_19", 700)
        assert (
            _sourced("campaign_spend", CAMPAIGN_ID="v20", WS_ROOT=str(tmp_path)).split()[0] == "100"
        )
        assert (
            _sourced("campaign_spend", CAMPAIGN_ID="v20a", WS_ROOT=str(tmp_path)).split()[0]
            == "700"
        )


def _sourced_full(snippet: str, **env) -> subprocess.CompletedProcess[str]:
    """Like `_sourced`, but keeps rc and stderr — which is the point here."""
    return subprocess.run(
        ["bash", "-c", f"V19_QUEUE_NO_MAIN=1 source '{RUNNER}'; {snippet}"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=dict(os.environ, **{k: str(v) for k, v in env.items()}),
    )


class TestBudgetAccountingFailsClosed:
    """Unreadable spend must refuse the wave, never read as zero.

    `campaign_spend()` used to end `2>/dev/null || echo "0 0.00"`. Any
    failure of the helper — missing interpreter, unreadable root, refused
    membership — became "zero spent". Zero does not read as *unknown*: it
    reads as *budget available*, disarming both the token and cost caps at
    `v19_queue_runner.sh:446-453` and letting the queue launch more work
    with no authoritative accounting behind it.
    """

    def test_the_zero_fallback_is_gone_from_the_helper(self):
        """MUTATION TARGET: restoring `|| echo "0 0.00"`.

        Scanned over CODE lines only. The fix's own comment quotes the
        removed fallback verbatim, and a bare substring scan trips on the
        explanation — the same false positive that has now caught three
        guardrails in this work.
        """
        body = RUNNER.read_text(encoding="utf-8")
        fn = body[body.index("campaign_spend() {") : body.index("# Launch one chain")]
        code = [ln for ln in fn.splitlines() if not ln.strip().startswith("#")]
        joined = "\n".join(code)
        assert "0 0.00" not in joined, "the helper still substitutes zero for a failure"
        assert "2>/dev/null" not in joined, "the helper still discards stderr"

    def test_the_helper_propagates_a_nonzero_exit(self, tmp_path):
        """An unusable membership list must surface, not become zero.

        Injected with a duplicated ROSTER entry — a genuine refusal that
        keeps the array non-empty. Two earlier injections were inert or
        wrong: `REPO` cannot be overridden (the runner computes it at
        `:59`), and emptying the ROSTER trips `set -u` instead, killing the
        shell for an unrelated reason.
        """
        r = _sourced_full(
            'ROSTER+=("${ROSTER[0]}"); SPEND_OUT=""; SPEND_RC=0; '
            'SPEND_OUT="$(campaign_spend)" || SPEND_RC=$?; '
            'echo "rc=$SPEND_RC out=[$SPEND_OUT]"',
            WS_ROOT=str(tmp_path),
            CAMPAIGN_ID="camp1",
        )
        assert "rc=0 " not in r.stdout, f"a failed helper reported success: {r.stdout!r}"
        assert "out=[]" in r.stdout, "a failed helper still produced a spend total"
        assert "duplicate run name" in r.stderr, "stderr was discarded"

    def test_the_guard_survives_set_e(self):
        """MUTATION TARGET: `SPEND_OUT="$(campaign_spend)"; SPEND_RC=$?`.

        `set -e` is active — `_chain_common.sh:40` sets it and the runner
        sources it at `:61`. A bare assignment from a failing command
        substitution terminates the shell BEFORE the refusal runs, so the
        queue would stop with no diagnostic, no `record_queue_stop` and no
        recorded reason: fail-closed by accident, and indistinguishable in
        the artifacts from a crash. The first draft of this fix did exactly
        that, and this test is why it was found.
        """
        body = RUNNER.read_text(encoding="utf-8")
        block = body[body.index('SPEND_OUT=""') : body.index("WAVE $WAVE budget:")]
        assert 'SPEND_OUT="$(campaign_spend)" || SPEND_RC=$?' in block, (
            "the spend capture is not guarded against set -e"
        )
        # And prove set -e really is on, so the guard is not decoration.
        r = _sourced_full("case $- in *e*) echo ACTIVE;; *) echo OFF;; esac")
        assert r.stdout.strip() == "ACTIVE", "set -e is no longer active; re-check this guard"

    def test_the_caller_refuses_and_records_budget_accounting_unavailable(self):
        """The wave loop must stop on unreadable accounting, with a reason
        that is not a cap breach."""
        body = RUNNER.read_text(encoding="utf-8")
        block = body[body.index('SPEND_OUT="$(campaign_spend)"') : body.index("WAVE $WAVE budget:")]
        assert "budget_accounting_unavailable" in block
        assert "record_queue_stop" in block
        assert "exit 1" in block

    def test_the_failure_is_not_labelled_a_cap_breach(self):
        """MUTATION TARGET: relabelling it `token_cap_reached`.

        That would blame the campaign's own spend for an infrastructure
        failure and tell an operator to raise a cap that was never reached.
        """
        body = RUNNER.read_text(encoding="utf-8")
        block = body[body.index('SPEND_OUT="$(campaign_spend)"') : body.index("WAVE $WAVE budget:")]
        for wrong in ("token_cap_reached", "cost_cap_reached", "operator_stop_requested"):
            assert wrong not in block, f"accounting failure is being reported as {wrong}"

    def test_it_does_not_use_the_operator_stop_exit_code(self):
        """99 means 'stopped on request — not a fault to restart from'
        (`:376-378`). An accounting failure is a fault."""
        body = RUNNER.read_text(encoding="utf-8")
        block = body[body.index('SPEND_OUT="$(campaign_spend)"') : body.index("WAVE $WAVE budget:")]
        assert "CHAIN_STOP_EXIT_CODE" not in block

    @pytest.mark.parametrize("bad", ["", "not a number", "123", "12 abc", "0 0.0"])
    def test_malformed_output_does_not_satisfy_the_guard(self, bad):
        """The guard's own regex, exercised directly: only `<int> <n.nn>`
        may pass, so a truncated or garbled line cannot become a total."""
        r = _sourced_full(
            f'if [[ "{bad}" =~ ^[0-9]+[[:space:]]+[0-9]+\\.[0-9]{{2}}$ ]]; '
            "then echo ACCEPTED; else echo REFUSED; fi"
        )
        assert r.stdout.strip() == "REFUSED", f"{bad!r} would have been read as a spend total"

    def test_a_well_formed_total_still_passes(self):
        r = _sourced_full(
            'if [[ "4477 13.43" =~ ^[0-9]+[[:space:]]+[0-9]+\\.[0-9]{2}$ ]]; '
            "then echo ACCEPTED; else echo REFUSED; fi"
        )
        assert r.stdout.strip() == "ACCEPTED"

    def test_the_membership_arguments_are_still_passed(self):
        """The Phase-0 fix must survive this one."""
        body = RUNNER.read_text(encoding="utf-8")
        fn = body[body.index("campaign_spend() {") : body.index("# Launch one chain")]
        assert "--run-name" in fn and 'for spec in "${ROSTER[@]}"' in fn
