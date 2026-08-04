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
    RunNameError,
    estimated_cost_usd,
    record_tokens,
    roster_tokens,
    validate_run_names,
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


class TestRosterTokens:
    """Membership is the caller's explicit list, never a name pattern."""

    def _ledger(self, root, name, totals):
        ws = root / name
        ws.mkdir(parents=True)
        (ws / "token_usage.jsonl").write_text(
            "".join(
                json.dumps({"tokens": {"prompt": t - 1, "completion": 1, "total": t}}) + "\n"
                for t in totals
            )
        )

    def test_it_sums_exactly_the_named_runs(self, tmp_path):
        self._ledger(tmp_path, "camp_arch_15_19", [100, 200])
        self._ledger(tmp_path, "camp_loss_15_19", [50])
        assert roster_tokens(tmp_path, ["camp_arch_15_19", "camp_loss_15_19"]) == 350

    def test_an_unnamed_workspace_is_excluded(self, tmp_path):
        self._ledger(tmp_path, "camp_arch_15_19", [100])
        self._ledger(tmp_path, "other_arch_15_19", [999999])
        assert roster_tokens(tmp_path, ["camp_arch_15_19"]) == 100

    def test_a_named_run_with_no_ledger_contributes_zero(self, tmp_path):
        """Pre-existing semantics: a chain that has not written usage yet
        is not an error. Preserved deliberately."""
        self._ledger(tmp_path, "camp_arch_15_19", [100])
        assert roster_tokens(tmp_path, ["camp_arch_15_19", "camp_loss_15_19"]) == 100

    def test_a_torn_final_line_is_a_gap_not_a_crash(self, tmp_path):
        ws = tmp_path / "camp_arch_15_19"
        ws.mkdir()
        (ws / "token_usage.jsonl").write_text(
            json.dumps({"tokens": {"total": 100}}) + '\n{"tokens": {"tot'
        )
        assert roster_tokens(tmp_path, ["camp_arch_15_19"]) == 100


class TestTheUnderscorePrefixCollision:
    """THE DEFECT. `{campaign_id}_*` let one campaign absorb another whose
    id extends it with an underscore, and that total drives
    `token_cap_reached` — so `v20` could be stopped by `v20_extra`'s spend.

    Measured on a synthetic root before the fix: `v20` reported 600 tokens
    where it owned 100.
    """

    @pytest.fixture
    def root(self, tmp_path):
        for name, tok in (
            ("v20_arch_15_19", 100),
            ("v20_extra_arch_15_19", 500),
            ("v20a_arch_15_19", 700),
            ("v2_arch_15_19", 900),
        ):
            ws = tmp_path / name
            ws.mkdir()
            (ws / "token_usage.jsonl").write_text(json.dumps({"tokens": {"total": tok}}) + "\n")
        return tmp_path

    def test_v20_does_not_absorb_v20_extra(self, root):
        """MUTATION TARGET: restoring the `{campaign_id}_*` glob."""
        assert roster_tokens(root, ["v20_arch_15_19"]) == 100

    def test_v20_extra_is_independent(self, root):
        assert roster_tokens(root, ["v20_extra_arch_15_19"]) == 500

    def test_v20a_is_independent(self, root):
        """Recorded because it was the FIRST hypothesis and is disproved:
        the glob's underscore delimiter already separated these two."""
        assert roster_tokens(root, ["v20a_arch_15_19"]) == 700

    def test_v2_is_independent(self, root):
        assert roster_tokens(root, ["v2_arch_15_19"]) == 900

    def test_no_role_or_band_is_parsed_from_a_run_name(self, root):
        """MUTATION TARGET: a `{campaign_id}_{role}_{band}` matcher.

        A name with neither a role nor a band must still resolve, because
        membership is given, not decoded.
        """
        odd = root / "totally-nonstandard-name"
        odd.mkdir()
        (odd / "token_usage.jsonl").write_text(json.dumps({"tokens": {"total": 42}}) + "\n")
        assert roster_tokens(root, ["totally-nonstandard-name"]) == 42


class TestMembershipIsRefusedWhenUnusable:
    def test_no_run_names_is_refused_not_zero(self):
        """Zero would read as 'nothing spent' and disarm the cap."""
        with pytest.raises(RunNameError, match="at least one"):
            validate_run_names([])

    def test_a_duplicate_is_refused_not_deduplicated(self):
        """A caller repeating a name has a wrong membership list; charging
        it once would hide that."""
        with pytest.raises(RunNameError, match="duplicate"):
            validate_run_names(["a", "b", "a"])

    @pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "../escape", "a\\b"])
    def test_path_escape_and_empty_are_refused(self, bad):
        with pytest.raises(RunNameError):
            validate_run_names([bad])

    def test_a_legal_name_containing_dots_is_accepted(self):
        """Positive control: only exact `.`/`..` are refused, so the rule
        cannot silently tighten into rejecting any dot."""
        assert validate_run_names(["v20.pilot_arch_15_19"]) == ("v20.pilot_arch_15_19",)


class TestCost:
    def test_the_estimator_is_linear_and_documented(self):
        assert DEFAULT_COST_PER_MTOK_USD == 3.00
        assert estimated_cost_usd(1_000_000) == pytest.approx(3.00)
        assert estimated_cost_usd(0) == 0.0

    def test_the_campaign_cap_would_trip_where_expected(self):
        """60M tokens at the documented rate is $180 — the two operator
        caps are consistent with each other, not independently chosen."""
        assert estimated_cost_usd(60_000_000) == pytest.approx(180.0)
