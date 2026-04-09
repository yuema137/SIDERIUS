"""
Unit tests for execute_tools/regime_aggregator.py.

Verifies:
  - Seed regime keys always present in output (cross-experiment safety).
  - Correct mean calculation across regime members.
  - None entries are skipped, not counted as zero.
  - All-None regime returns 0.0 (not None).
  - Empty / None / short input handled defensively.
  - Output is a plain dict[str, float] (no numpy types leaking through).
"""
import pytest

from execute_tools.regime_aggregator import (
    REGIME_DEFINITIONS,
    aggregate_regime_scores,
)


SEED_REGIMES = {"low_freq_kHz", "mid_freq_10kHz", "high_freq_MHz", "global"}


class TestRegimeDefinitions:
    def test_seed_regimes_present(self):
        assert SEED_REGIMES.issubset(REGIME_DEFINITIONS.keys())

    def test_global_covers_all_20_files(self):
        assert REGIME_DEFINITIONS["global"] == list(range(20))

    def test_low_mid_high_partition_files_0_to_19(self):
        union = (
            set(REGIME_DEFINITIONS["low_freq_kHz"])
            | set(REGIME_DEFINITIONS["mid_freq_10kHz"])
            | set(REGIME_DEFINITIONS["high_freq_MHz"])
        )
        assert union == set(range(20)), (
            "low+mid+high should partition files 0..19"
        )

    def test_no_overlap_between_low_mid_high(self):
        low = set(REGIME_DEFINITIONS["low_freq_kHz"])
        mid = set(REGIME_DEFINITIONS["mid_freq_10kHz"])
        high = set(REGIME_DEFINITIONS["high_freq_MHz"])
        assert low.isdisjoint(mid)
        assert mid.isdisjoint(high)
        assert low.isdisjoint(high)


class TestAggregateRegimeScores:
    def test_all_ones(self):
        result = aggregate_regime_scores([1.0] * 20)
        assert result == {
            "low_freq_kHz": 1.0,
            "mid_freq_10kHz": 1.0,
            "high_freq_MHz": 1.0,
            "global": 1.0,
        }

    def test_all_zeros(self):
        result = aggregate_regime_scores([0.0] * 20)
        for regime in SEED_REGIMES:
            assert result[regime] == 0.0

    def test_distinct_values_per_file(self):
        # file_index → score; non-trivial pattern so means are easy to verify
        file_vector = [float(i) for i in range(20)]
        result = aggregate_regime_scores(file_vector)
        assert result["low_freq_kHz"] == pytest.approx(sum(range(0, 5)) / 5)
        assert result["mid_freq_10kHz"] == pytest.approx(sum(range(5, 11)) / 6)
        assert result["high_freq_MHz"] == pytest.approx(sum(range(11, 20)) / 9)
        assert result["global"] == pytest.approx(sum(range(20)) / 20)

    def test_none_entries_are_skipped(self):
        # files 0-4: valid; files 5-19: None
        file_vector = [0.5, 0.5, 0.5, 0.5, 0.5] + [None] * 15
        result = aggregate_regime_scores(file_vector)
        assert result["low_freq_kHz"] == 0.5
        assert result["mid_freq_10kHz"] == 0.0  # all-None → 0.0, not None
        assert result["high_freq_MHz"] == 0.0
        assert result["global"] == 0.5  # mean of the 5 valid entries

    def test_single_valid_file_in_regime(self):
        # Only file 0 has a score
        file_vector = [0.7] + [None] * 19
        result = aggregate_regime_scores(file_vector)
        assert result["low_freq_kHz"] == pytest.approx(0.7)
        assert result["global"] == pytest.approx(0.7)
        assert result["mid_freq_10kHz"] == 0.0
        assert result["high_freq_MHz"] == 0.0

    def test_empty_input_returns_zeroed_seed_regimes(self):
        result = aggregate_regime_scores([])
        assert result == {regime: 0.0 for regime in REGIME_DEFINITIONS}

    def test_none_input_returns_zeroed_seed_regimes(self):
        result = aggregate_regime_scores(None)
        assert result == {regime: 0.0 for regime in REGIME_DEFINITIONS}

    def test_short_input_does_not_crash(self):
        # Defensive: malformed input shorter than 20 elements
        file_vector = [1.0, 1.0, 1.0]  # only 3 entries
        result = aggregate_regime_scores(file_vector)
        # low_freq_kHz expects files 0-4; only 0,1,2 valid → mean is 1.0
        assert result["low_freq_kHz"] == pytest.approx(1.0)
        assert result["mid_freq_10kHz"] == 0.0
        assert result["high_freq_MHz"] == 0.0
        assert result["global"] == pytest.approx(1.0)

    def test_output_is_plain_floats(self):
        result = aggregate_regime_scores([1.5] * 20)
        for value in result.values():
            assert isinstance(value, float), (
                f"value {value!r} is {type(value).__name__}, expected float"
            )

    def test_all_seed_regimes_always_present(self):
        # Even an entirely-None input must yield all four seed keys
        result = aggregate_regime_scores([None] * 20)
        assert set(result.keys()) == set(REGIME_DEFINITIONS.keys())
        for key in SEED_REGIMES:
            assert key in result
