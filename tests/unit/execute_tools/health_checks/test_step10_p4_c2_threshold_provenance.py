# tests/unit/execute_tools/health_checks/test_step10_p4_c2_threshold_provenance.py
"""Step 10 / P4 — C2: threshold provenance (Q-P4-1) and unit resolution (R-2).

Q-P4-1 = (a), FALLBACK-ONLY. The two branches are asserted as a PAIR, because
the ruling is precisely about their difference:

    config value present  ->  persist exactly as today, NO source label
    config key absent     ->  persist the check's OWN default,
                              labelled source = "check_default"

The absent branch is not a hypothetical tidy-up. Before P4 the framework
carried its own copy of each check's default, so an absent key rendered a
number that merely *happened* to equal what the check used. Rendering it as
"absent" would have misreported a gate that ran and thresholded; failing there
would have crashed on a check that executed legally. The label is the only
honest option, and it is confined to the branch that is actually ambiguous.
"""

from __future__ import annotations

import pytest

from execute_tools.health_checks import registry
from execute_tools.health_checks.evaluation import _resolve_unit, _threshold
from execute_tools.health_checks.schemas import EvidenceUnit


def _declaration(check_name: str):
    return registry.get(check_name).declaration


class TestConfiguredValueBranch:
    def test_configured_value_carries_no_source_label(self):
        """TIDMAD's shipped path. Byte-identical to pre-P4."""
        row = _threshold(_declaration("output_diversity"), {"min_unique_int8_values": 25})
        assert row == {
            "metric": "n_unique_int8_values",
            "operator": ">",
            "value": 25,
            "unit": "count",
        }
        assert "source" not in row

    def test_configured_value_keeps_the_declared_numeric_type(self):
        """Reproduces the per-branch int()/float() casts the removed table
        applied — derived from the declaration, not hardcoded per check name.

        A count threshold must persist as an int: the fingerprint's integer
        rendering keys off exactly that.
        """
        counted = _threshold(_declaration("output_diversity"), {"min_unique_int8_values": 25.0})
        assert counted is not None and isinstance(counted["value"], int)
        scaled = _threshold(_declaration("output_std"), {"min_std_mv": 1})
        assert scaled is not None and isinstance(scaled["value"], float)


class TestCheckDefaultFallbackBranch:
    @pytest.mark.parametrize(
        "check_name, expected_value",
        [
            ("output_diversity", 5),
            ("output_std", 1.0),
            ("amplitude_collapse", 0.95),
            ("categorical_distinct_symbols", 2),
        ],
    )
    def test_absent_key_persists_the_checks_own_default_labelled(self, check_name, expected_value):
        row = _threshold(_declaration(check_name), {})
        assert row is not None
        assert row["value"] == expected_value
        assert row["source"] == "check_default"

    def test_the_labelled_default_is_the_value_run_would_actually_use(self):
        """The whole point of the label: it must describe what the gate DID.

        Asserted against the check's own private default rather than a
        transcribed literal — a transcription would be another copy of the
        number P4 exists to de-duplicate.
        """
        from execute_tools.health_checks.output_diversity import OutputDiversityCheck

        row = _threshold(_declaration("output_diversity"), {})
        assert row is not None
        assert row["value"] == OutputDiversityCheck._DEFAULT_MIN_UNIQUE

    def test_absent_key_is_never_rendered_as_absent(self):
        """Explicitly forbidden by Q-P4-1: the check thresholded on something."""
        row = _threshold(_declaration("output_diversity"), {})
        assert row is not None
        assert row["value"] is not None

    def test_absent_key_does_not_raise(self):
        """Explicitly forbidden by Q-P4-1: a check that legally executed must
        not have its evidence construction crash."""
        assert _threshold(_declaration("sample_dispersion_floor"), {}) is not None


class TestNoThresholdDeclared:
    @pytest.mark.parametrize(
        "check_name", ["pearson_dispersion", "spectral_peak_ratio", "per_file_output_std"]
    )
    def test_recording_only_checks_persist_no_row(self, check_name):
        assert _threshold(_declaration(check_name), {"anything": 1}) is None

    def test_absent_declaration_persists_no_row(self):
        """A pre-08a or externally supplied check without a declaration keeps
        pre-P4 behaviour — no row, and nothing invented."""
        assert _threshold(None, {"min_unique_int8_values": 25}) is None


class TestUnitResolution:
    """R-2: task-owned units are RESOLVED, never copied onto the framework."""

    def test_task_owned_unit_resolves_from_the_runs_config(self):
        row = _threshold(_declaration("output_std"), {"min_std_mv": 1.0, "value_scale_unit": "mV"})
        assert row is not None and row["unit"] == "mV"

    def test_a_different_task_scale_renders_that_task_s_unit(self):
        """The property the literal "mV" could never have: the same framework
        check under a task whose scale is µV renders µV."""
        row = _threshold(_declaration("output_std"), {"min_std_mv": 1.0, "value_scale_unit": "µV"})
        assert row is not None and row["unit"] == "µV"

    def test_unresolvable_task_owned_unit_renders_nothing(self):
        """DAVIS declares no value_scale. No unit is rendered rather than a
        defaulted one — absence of a task scale is a real state."""
        row = _threshold(_declaration("sample_dispersion_floor"), {"min_dispersion": 0.04})
        assert row is not None and row["unit"] is None

    def test_check_owned_literal_is_used_verbatim(self):
        assert _resolve_unit(EvidenceUnit(literal="count"), {}) == "count"

    def test_config_sourced_unit_reads_the_declared_key(self):
        assert _resolve_unit(EvidenceUnit(config_key="value_scale_unit"), {}) is None
        assert (
            _resolve_unit(EvidenceUnit(config_key="value_scale_unit"), {"value_scale_unit": "mV"})
            == "mV"
        )
