# tests/unit/execute_tools/health_checks/test_step10_p4_c1_declarations.py
"""Step 10 / P4 — C1: the evidence declaration, as inert data.

C1 moves the framework's per-check-NAME table CONTENT onto the checks that
know it. No consumer reads it yet — that is C2/C3' — so everything here is a
schema/declaration property.

What is worth pinning (and what is not): the ``EvidenceUnit`` exactly-one-of
rule and the R-5 derivation/agreement rule are VALIDATOR LOGIC with real
failure modes, so they are tested. A ``Literal`` rejecting an unknown operator
and an optional field defaulting to ``None`` are Pydantic declarations and are
NOT re-tested here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from execute_tools.health_checks import registry
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    EvidenceUnit,
    ThresholdDeclaration,
)

#: The migrated table content, hardcoded from the C0 goldens. This is the
#: cross-check CONCEPT test the project rule asks for: one table naming the
#: relation for every check that declares it, rather than nine per-field
#: assertions that cannot express "the tables moved intact".
#:
#: gate-facing evidence identity: check -> (metric, operator, config key,
#: default, unit-literal or "cfg:<key>")
EXPECTED_THRESHOLDS: dict[str, tuple[str, str, str, object, str]] = {
    "output_diversity": ("n_unique_int8_values", ">", "min_unique_int8_values", 5, "count"),
    "output_std": ("output_std_mv", ">=", "min_std_mv", 1.0, "cfg:value_scale_unit"),
    "amplitude_collapse": ("dominant_mode_fraction", "<=", "collapse_threshold", 0.95, "fraction"),
    "categorical_distinct_symbols": (
        "distinct_symbols",
        ">=",
        "min_distinct_symbols",
        2,
        "count",
    ),
    "categorical_dominant_fraction": (
        "dominant_fraction",
        "<=",
        "max_dominant_fraction",
        0.95,
        "fraction",
    ),
    "sample_dispersion_floor": (
        "dispersion",
        ">=",
        "min_dispersion",
        0.5,
        "cfg:value_scale_unit",
    ),
}

#: check -> (per-file metric name, unit-literal or "cfg:<key>", sampling label)
EXPECTED_PER_FILE: dict[str, tuple[str, str, str]] = {
    "output_diversity": ("n_unique_int8_values", "count", "channel0001_prefix_peek"),
    "output_std": ("output_std_mv", "cfg:value_scale_unit", "channel0001_prefix_peek"),
    "amplitude_collapse": ("dominant_mode_fraction", "fraction", "channel0001_prefix_peek"),
    "pearson_dispersion": ("pearson_correlation", "correlation", "channel0001_prefix_peek"),
    "spectral_peak_ratio": ("spectral_peak_ratio", "ratio", "channel0001_prefix_peek"),
    "per_file_output_std": ("output_std_mv", "cfg:value_scale_unit", "channel0001_prefix_peek"),
}

#: Checks with NO threshold row. The three TIDMAD recording-only checks — the
#: absences C0 froze and P4 must preserve.
NO_THRESHOLD = ("pearson_dispersion", "spectral_peak_ratio", "per_file_output_std")

#: Checks with NO per-file dimension: the 08c generic family emits scalars.
NO_PER_FILE = (
    "categorical_distinct_symbols",
    "categorical_dominant_fraction",
    "sample_dispersion_floor",
)


def _unit_tag(unit: EvidenceUnit | None) -> str | None:
    if unit is None:
        return None
    return unit.literal if unit.literal is not None else f"cfg:{unit.config_key}"


class TestMigratedTableContent:
    def test_every_declared_threshold_matches_the_migrated_table(self):
        actual = {}
        for name in registry.all_registered():
            for threshold in registry.get(name).declaration.evidence_thresholds:
                actual[name] = (
                    threshold.metric,
                    threshold.operator,
                    threshold.config_key,
                    threshold.default,
                    _unit_tag(threshold.unit),
                )
        assert actual == EXPECTED_THRESHOLDS

    def test_every_per_file_declaration_matches_the_migrated_table(self):
        actual = {}
        for name in registry.all_registered():
            declaration = registry.get(name).declaration
            if declaration.per_file_metric_name is None:
                continue
            actual[name] = (
                declaration.per_file_metric_name,
                _unit_tag(declaration.per_file_metric_unit),
                declaration.sampling_method_label,
            )
        assert actual == EXPECTED_PER_FILE

    def test_per_file_metrics_keys_are_declared_not_guessed(self):
        """The generic builder used to try three TIDMAD metrics keys in an
        `or` cascade. The key is NOT the evidence metric name — this check
        publishes `pearson_per_file` but reports `pearson_correlation` — so
        the check has to say where it put its data."""
        expected = {
            "pearson_dispersion": "pearson_per_file",
            "spectral_peak_ratio": "ratio_per_file",
            "per_file_output_std": "std_mv_per_file",
        }
        actual = {name: registry.get(name).declaration.per_file_metrics_key for name in expected}
        assert actual == expected
        # Everyone else uses the default, which is why it IS the default.
        for name in ("output_diversity", "output_std", "amplitude_collapse"):
            assert registry.get(name).declaration.per_file_metrics_key == "per_file", name

    @pytest.mark.parametrize("name", NO_THRESHOLD)
    def test_recording_only_checks_declare_no_threshold(self, name):
        """The honest absence C0 froze — never a gap to fill."""
        assert registry.get(name).declaration.evidence_thresholds == ()

    @pytest.mark.parametrize("name", NO_PER_FILE)
    def test_scalar_checks_declare_no_per_file_evidence(self, name):
        """No per-file name, unit or sampling label is fabricated for a check
        that has no per-file dimension."""
        declaration = registry.get(name).declaration
        assert declaration.per_file_metric_name is None
        assert declaration.per_file_metric_unit is None
        assert declaration.sampling_method_label is None

    def test_declared_defaults_are_the_checks_own_defaults(self):
        """R-3: ONE number, not two copies that happen to agree.

        The declaration must carry the SAME object the check's ``run`` falls
        back to — asserted against the private ClassVar rather than a
        transcribed literal, because a transcription would be a third copy.
        """
        import importlib

        pairs = {
            "output_diversity": ("output_diversity", "OutputDiversityCheck", "_DEFAULT_MIN_UNIQUE"),
            "output_std": ("output_std", "OutputStdCheck", "_DEFAULT_MIN_STD_MV"),
            "amplitude_collapse": (
                "amplitude_collapse",
                "AmplitudeCollapseCheck",
                "_DEFAULT_COLLAPSE_THRESHOLD",
            ),
            "categorical_distinct_symbols": (
                "categorical_distinct_symbols",
                "CategoricalDistinctSymbolsCheck",
                "_DEFAULT_MIN_DISTINCT_SYMBOLS",
            ),
            "categorical_dominant_fraction": (
                "categorical_dominant_fraction",
                "CategoricalDominantFractionCheck",
                "_DEFAULT_MAX_DOMINANT_FRACTION",
            ),
            "sample_dispersion_floor": (
                "sample_dispersion_floor",
                "SampleDispersionFloorCheck",
                "_DEFAULT_MIN_DISPERSION",
            ),
        }
        for check_name, (module_name, class_name, attribute) in pairs.items():
            module = importlib.import_module(f"execute_tools.health_checks.{module_name}")
            own_default = getattr(getattr(module, class_name), attribute)
            declared = registry.get(check_name).declaration.evidence_thresholds[0].default
            assert declared == own_default, check_name
            assert type(declared) is type(own_default), check_name

    def test_count_defaults_stay_integers(self):
        """A count threshold is an int and must persist as one; coercing every
        default to float would render 5.0 where evidence has always said 5."""
        for name in ("output_diversity", "categorical_distinct_symbols"):
            assert isinstance(registry.get(name).declaration.evidence_thresholds[0].default, int), (
                name
            )


class TestUnitSourceRule:
    """R-2: a unit has exactly one source, and a task-owned unit is REFERENCED
    rather than copied."""

    def test_task_owned_units_name_the_config_key_never_the_string(self):
        """The mV rows must not carry the string. Copying it onto a framework
        check would be a third declaration of one number's unit, and would
        render mV for a task whose scale is µV."""
        for name in ("output_std", "per_file_output_std"):
            declaration = registry.get(name).declaration
            units = [declaration.per_file_metric_unit] + [
                t.unit for t in declaration.evidence_thresholds
            ]
            for unit in [u for u in units if u is not None]:
                assert unit.literal is None, name
                assert unit.config_key == "value_scale_unit", name

    def test_dimensionless_units_are_check_owned_literals(self):
        for name, expected in (
            ("output_diversity", "count"),
            ("amplitude_collapse", "fraction"),
            ("pearson_dispersion", "correlation"),
            ("spectral_peak_ratio", "ratio"),
        ):
            declaration = registry.get(name).declaration
            unit = declaration.per_file_metric_unit
            assert unit is not None and unit.literal == expected, name

    def test_both_sources_is_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            EvidenceUnit(literal="count", config_key="value_scale_unit")

    def test_neither_source_is_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            EvidenceUnit()


class TestThresholdParameterNamesDerivation:
    """R-5: ONE authority for 'which config keys are thresholds'."""

    def _threshold(self, key: str = "min_x") -> ThresholdDeclaration:
        return ThresholdDeclaration(
            metric="x",
            operator=">",
            config_key=key,
            default=1,
            unit=EvidenceUnit(literal="count"),
        )

    def test_names_are_derived_when_not_authored(self):
        declaration = CheckInputDeclaration(
            consumes_view="v", evidence_thresholds=(self._threshold(),)
        )
        assert declaration.threshold_parameter_names == ("min_x",)

    def test_disagreement_fails_closed(self):
        with pytest.raises(ValidationError, match="disagrees"):
            CheckInputDeclaration(
                consumes_view="v",
                evidence_thresholds=(self._threshold(),),
                threshold_parameter_names=("something_else",),
            )

    def test_agreement_is_accepted(self):
        declaration = CheckInputDeclaration(
            consumes_view="v",
            evidence_thresholds=(self._threshold(),),
            threshold_parameter_names=("min_x",),
        )
        assert declaration.threshold_parameter_names == ("min_x",)

    def test_plugin_abi_is_unchanged_for_a_declaration_without_evidence(self):
        """A pre-P4 or out-of-tree check that declares only the 08a field keeps
        working: nothing is derived, nothing is required, no new field is
        mandatory."""
        declaration = CheckInputDeclaration(
            consumes_view="v", threshold_parameter_names=("min_window_spread",)
        )
        assert declaration.threshold_parameter_names == ("min_window_spread",)
        assert declaration.evidence_thresholds == ()
        assert declaration.per_file_metric_name is None

    def test_every_shipped_check_agrees_with_its_derivation(self):
        """The concept, across every registered check at once."""
        for name in registry.all_registered():
            declaration = registry.get(name).declaration
            if not declaration.evidence_thresholds:
                continue
            derived = tuple(t.config_key for t in declaration.evidence_thresholds)
            assert declaration.threshold_parameter_names == derived, name
