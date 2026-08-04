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
        out = _sourced(
            'echo "$WAVE_STATE"; echo "$LOGF"', CAMPAIGN_ID="camp1", WS_ROOT=str(tmp_path)
        )
        assert all("camp1_" in line for line in out.splitlines())

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
    DOCS = (
        "docs/running_chain_test.md",
        "docs/design/runtime_estimation_and_calibration.md",
    )

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
