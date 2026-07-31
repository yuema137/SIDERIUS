"""Campaign token accounting — the number a cost cap depends on.

A ledger record carries TWO totals:

    {"tokens": {"prompt": 3892, "completion": 585, "total": 4477},
     "chars":  {"system": 7888, "user": 9777, "total": 17665}}

Both mistakes available here were made on 2026-07-31 while reporting
C14: summing `tokens.values()` double-counts, because `total` already
contains `prompt` and `completion` (it reported 1,996,208 for a real
998,104), and any text scan for `"total"` also picks up the character
count. Since the campaign stops when this number crosses a cap, an
inflated figure ends a campaign early and a deflated one overspends.
"""

from __future__ import annotations

import json

import pytest

from scripts.campaign_spend import (
    DEFAULT_COST_PER_MTOK_USD,
    campaign_tokens,
    estimated_cost_usd,
    record_tokens,
)

REAL_RECORD = {
    "ts": "2026-07-31T06:47:55.630Z",
    "run_name": "v19_c14_arch_15_19",
    "model": "gpt-5.4",
    "tokens": {"prompt": 3892, "completion": 585, "total": 4477},
    "chars": {"system": 7888, "user": 9777, "total": 17665},
}


class TestRecordTokens:
    def test_the_nested_total_is_used_once(self):
        assert record_tokens(REAL_RECORD) == 4477

    def test_prompt_and_completion_are_not_added_to_the_total(self):
        """The C14 mis-report: 3892 + 585 + 4477 = 8954, exactly double."""
        assert record_tokens(REAL_RECORD) != 3892 + 585 + 4477

    def test_the_character_count_is_never_counted(self):
        assert record_tokens(REAL_RECORD) < REAL_RECORD["chars"]["total"]

    def test_a_bare_integer_still_works(self):
        """An older ledger wrote a plain int."""
        assert record_tokens({"tokens": 1234}) == 1234

    def test_a_missing_total_falls_back_to_the_parts(self):
        assert record_tokens({"tokens": {"prompt": 10, "completion": 5}}) == 15

    @pytest.mark.parametrize(
        "record", [{}, {"tokens": None}, {"tokens": "many"}, {"tokens": {}}, {"tokens": -5}]
    )
    def test_an_unusable_record_contributes_nothing(self, record):
        assert record_tokens(record) == 0


class TestCampaignTokens:
    def _ledger(self, root, name, totals):
        ws = root / name
        ws.mkdir(parents=True)
        (ws / "token_usage.jsonl").write_text(
            "".join(
                json.dumps({"tokens": {"prompt": t - 1, "completion": 1, "total": t}}) + "\n"
                for t in totals
            )
        )

    def test_it_sums_across_the_campaign(self, tmp_path):
        self._ledger(tmp_path, "camp_arch_15_19", [100, 200])
        self._ledger(tmp_path, "camp_loss_15_19", [50])
        assert campaign_tokens(tmp_path, "camp") == 350

    def test_another_campaign_in_the_same_root_is_excluded(self, tmp_path):
        self._ledger(tmp_path, "camp_arch_15_19", [100])
        self._ledger(tmp_path, "other_arch_15_19", [999999])
        assert campaign_tokens(tmp_path, "camp") == 100

    def test_an_empty_root_is_zero_not_an_error(self, tmp_path):
        assert campaign_tokens(tmp_path, "camp") == 0

    def test_a_torn_final_line_is_a_gap_not_a_crash(self, tmp_path):
        ws = tmp_path / "camp_arch_15_19"
        ws.mkdir()
        (ws / "token_usage.jsonl").write_text(
            json.dumps({"tokens": {"total": 100}}) + '\n{"tokens": {"tot'
        )
        assert campaign_tokens(tmp_path, "camp") == 100


class TestCost:
    def test_the_estimator_is_linear_and_documented(self):
        assert DEFAULT_COST_PER_MTOK_USD == 3.00
        assert estimated_cost_usd(1_000_000) == pytest.approx(3.00)
        assert estimated_cost_usd(0) == 0.0

    def test_the_campaign_cap_would_trip_where_expected(self):
        """60M tokens at the documented rate is $180 — the two operator
        caps are consistent with each other, not independently chosen."""
        assert estimated_cost_usd(60_000_000) == pytest.approx(180.0)
