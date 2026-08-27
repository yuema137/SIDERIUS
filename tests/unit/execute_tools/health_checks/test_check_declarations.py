"""Step 08a C4 — what the six shipped checks declare they consume.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08a_check_input_contract.md`` §3.2, §4.4.

C3 wired the applicability ENGINE; this module owns the declaration
CONTENT, which is a scientific claim about each check rather than a
mechanism. The defect classes here:

* a declaration that does not match what the check actually reads — either
  too strict (the check becomes inapplicable where it would have worked and
  a production check silently stops running) or too loose (the check is
  invoked on data it cannot interpret);
* ``threshold_parameter_names`` naming a config key the check never reads,
  which would send 08b's ownership migration after a parameter that does
  not exist;
* a production constructor quietly relying on the C1 compatibility bridge
  instead of stating its verdict, leaving two sources of verdict truth;
* the whole int8 family staying applicable under a task that declares a
  different encoding — the 8.4-B claim, now against the REAL declarations.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from execute_tools.health_checks import runner
from execute_tools.health_checks._regime_a_facts import resolve_health_facts
from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.config import (
    ActionConfig,
    CheckRef,
    GateConfig,
    HealthChecksConfig,
)
from execute_tools.health_checks.output_diversity import OutputDiversityCheck
from execute_tools.health_checks.output_std import OutputStdCheck
from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
from execute_tools.health_checks.per_file_output_std import PerFileOutputStdCheck
from execute_tools.health_checks.runner import evaluate_gate
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    GateAction,
    HealthCheckContext,
    TaskHealthFacts,
    applicability,
)
from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck

SHIPPED_CHECKS = (
    OutputDiversityCheck,
    OutputStdCheck,
    AmplitudeCollapseCheck,
    PerFileOutputStdCheck,
    SpectralPeakRatioCheck,
    PearsonDispersionCheck,
)

# What each check declares, hardcoded. Never read back from the class —
# comparing a declaration to itself would pass for any content.
EXPECTED = {
    "output_diversity": {
        "consumes_view": "tidmad.int8_prefix_peek",
        "required_context_inputs": ("denoised_source",),
        "fact_axes": (("encoding_family", "int8_symbol_stream"),),
        "threshold_parameter_names": ("min_unique_int8_values",),
    },
    "output_std": {
        "consumes_view": "tidmad.int8_prefix_peek",
        "required_context_inputs": ("denoised_source",),
        "fact_axes": (
            ("encoding_family", "int8_symbol_stream"),
            ("value_scale_unit", None),
        ),
        "threshold_parameter_names": ("min_std_mv",),
    },
    "amplitude_collapse": {
        "consumes_view": "tidmad.int8_prefix_peek",
        "required_context_inputs": ("denoised_source",),
        "fact_axes": (("encoding_family", "int8_symbol_stream"),),
        "threshold_parameter_names": ("collapse_threshold",),
    },
    "per_file_output_std": {
        "consumes_view": "tidmad.int8_prefix_peek",
        "required_context_inputs": ("denoised_source",),
        "fact_axes": (
            ("encoding_family", "int8_symbol_stream"),
            ("file_group_size", None),
            ("value_scale_unit", None),
        ),
        "threshold_parameter_names": (),
    },
    "spectral_peak_ratio": {
        # Reads ONLY the denoised stream — verified end-to-end at C4.
        "consumes_view": "tidmad.int8_prefix_peek",
        "required_context_inputs": ("denoised_source",),
        "fact_axes": (
            ("encoding_family", "int8_symbol_stream"),
            ("sampling_frequency_hz", None),
            ("value_scale_unit", None),
        ),
        "threshold_parameter_names": (),
    },
    "pearson_dispersion": {
        "consumes_view": "tidmad.target_comparison_peek",
        "required_context_inputs": ("denoised_source", "target_source"),
        "fact_axes": (
            ("encoding_family", "int8_symbol_stream"),
            ("file_group_size", None),
            ("value_scale_unit", None),
        ),
        "threshold_parameter_names": (),
    },
}


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


def _bound_tidmad_facts() -> TaskHealthFacts:
    """TIDMAD's DECLARED health facts, read from its task health config."""
    import yaml

    from execute_tools.health_checks._composition import LEGACY_DEFAULT_TASK_HEALTH_CONFIG
    from execute_tools.health_checks._task_health_config import TaskHealthConfig

    with open(LEGACY_DEFAULT_TASK_HEALTH_CONFIG) as handle:
        return TaskHealthConfig.model_validate(yaml.safe_load(handle)).resolved_facts()


def _full_ctx() -> HealthCheckContext:
    return _ctx(
        denoised_filename_fn=lambda fi: f"/tmp/denoised_{fi:04d}.h5",
        target_path_fn=lambda fi: f"/tmp/target_{fi:04d}.h5",
    )


class TestDeclarationContent:
    @pytest.mark.parametrize("check_cls", SHIPPED_CHECKS, ids=lambda c: c.name)
    def test_declaration_matches_the_hardcoded_expectation(self, check_cls):
        expected = EXPECTED[check_cls.name]
        declaration = check_cls.declaration
        assert declaration.consumes_view == expected["consumes_view"]
        assert declaration.required_context_inputs == expected["required_context_inputs"]
        assert (
            tuple((r.axis, r.equals) for r in declaration.required_facts) == expected["fact_axes"]
        )
        assert declaration.threshold_parameter_names == expected["threshold_parameter_names"]

    def test_only_pearson_needs_the_target_signal(self):
        """The census that catches a copy-pasted declaration.

        ``spectral_peak_ratio`` reads only CH1 and computes a PSD; the C4
        source read corrected a design expectation that it peeked the
        target. If someone later gives it ``target_source``, it would go
        inapplicable on any task without a target channel for no reason.
        """
        needs_target = {
            cls.name
            for cls in SHIPPED_CHECKS
            if "target_source" in cls.declaration.required_context_inputs
        }
        assert needs_target == {"pearson_dispersion"}

    def test_exactly_the_scale_consuming_checks_declare_the_value_scale_axis(self):
        """08a's guard, INVERTED at 08b C5 rather than deleted.

        08a asserted that NO check declared this axis, because the mV factor
        was a check-local literal that nothing declared — requiring the axis
        would have flipped TIDMAD's std checks to inapplicable. C5 moved the
        factor and its unit into the task's own config, so the requirement
        is now both true and load-bearing.

        The invariant is a BICONDITIONAL, which is what makes it worth
        keeping: a check that scales samples must declare the axis, and a
        check that does not must not — otherwise it would report itself
        inapplicable for a property it never uses.
        """
        scale_consuming = {
            "output_std",
            "per_file_output_std",
            "pearson_dispersion",
            "spectral_peak_ratio",
        }
        for cls in SHIPPED_CHECKS:
            axes = {r.axis for r in cls.declaration.required_facts}
            declares = "value_scale_unit" in axes
            assert declares is (cls.name in scale_consuming), cls.name


class TestDeclarationsMatchWhatTheCheckReads:
    """``threshold_parameter_names`` must name keys ``run`` actually reads."""

    @staticmethod
    def _config_keys_read(check_cls) -> set[str]:
        """Every ``cfg.get("literal")`` key inside the check's ``run``."""
        # ``getsource`` of a method keeps its class indentation, which is
        # not parseable on its own.
        tree = ast.parse(textwrap.dedent(inspect.getsource(check_cls.run)))
        keys: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "cfg"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
        return keys

    @pytest.mark.parametrize("check_cls", SHIPPED_CHECKS, ids=lambda c: c.name)
    def test_declared_thresholds_are_a_subset_of_keys_actually_read(self, check_cls):
        read = self._config_keys_read(check_cls)
        declared = set(check_cls.declaration.threshold_parameter_names)
        assert declared <= read, f"{check_cls.name} declares unread keys: {declared - read}"

    @pytest.mark.parametrize("check_cls", SHIPPED_CHECKS, ids=lambda c: c.name)
    def test_the_key_extractor_actually_finds_keys(self, check_cls):
        """Guards the guard: an extractor returning ∅ makes ⊆ vacuous."""
        assert self._config_keys_read(check_cls)

    def test_framework_policy_keys_are_deliberately_not_declared(self):
        """``peek_file_indices`` is run-level DataScope policy and
        ``aggregation`` is gate policy — neither is a TASK threshold, so
        08b must not migrate them to task ownership."""
        for cls in SHIPPED_CHECKS:
            declared = set(cls.declaration.threshold_parameter_names)
            assert "peek_file_indices" not in declared, cls.name
            assert "aggregation" not in declared, cls.name


class TestProductionNeverReliesOnTheCompatibilityBridge:
    """R-08a-1: the C1 derivation must not linger as a second truth source.

    Asserted statically over EVERY production constructor rather than by
    counting hits at runtime — a runtime counter only covers the calls a
    test happens to execute, while this covers all of them, and it needs no
    instrumentation inside production code.
    """

    PRODUCTION_FILES = tuple(
        Path("execute_tools/health_checks") / name
        for name in (
            "output_diversity.py",
            "output_std.py",
            "amplitude_collapse.py",
            "per_file_output_std.py",
            "spectral_peak_ratio.py",
            "pearson_dispersion.py",
            "runner.py",
        )
    )

    def _constructor_calls(self, path: Path) -> list[ast.Call]:
        root = Path(__file__).resolve().parents[4]
        tree = ast.parse((root / path).read_text())
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "HealthCheckResult"
        ]

    def test_every_production_constructor_states_its_verdict(self):
        missing: list[str] = []
        total = 0
        for path in self.PRODUCTION_FILES:
            for call in self._constructor_calls(path):
                total += 1
                if not any(kw.arg == "verdict" for kw in call.keywords):
                    missing.append(f"{path}:{call.lineno}")
        assert total >= 14, f"expected the audited constructor census, found {total}"
        assert not missing, "constructors relying on the C1 bridge:\n  " + "\n  ".join(missing)


class TestTheAxisCutsBothWays:
    """8.4-B against the REAL declarations, plus its positive control.

    The pair is the point: the same fixture under TIDMAD facts must leave
    every check applicable. Without the positive half, a bug that made
    everything inapplicable would look like success.
    """

    CONTRAST_FACTS = TaskHealthFacts(
        encoding_family="continuous_float",
        value_scale_unit="mV",
        file_group_size=4,
        sampling_frequency_hz=25.0,
    )

    @pytest.mark.parametrize("check_cls", SHIPPED_CHECKS, ids=lambda c: c.name)
    def test_every_shipped_check_applies_under_the_bound_tidmad_facts(self, check_cls):
        """The parity claim: no shipped TIDMAD check may stop running.

        Reads the facts TIDMAD now DECLARES in its own health config, which
        is what production resolves since C5. The regime-A derivation cannot
        establish `value_scale_unit` — nothing in the dataset profile says
        what a sample is worth — which is precisely why ownership moved.
        """
        verdict = applicability(check_cls.declaration, _bound_tidmad_facts(), _full_ctx())
        assert verdict.applicable is True, verdict.reason

    def test_the_regime_a_derivation_still_cannot_establish_the_scale(self):
        """Records WHY the facts above are declared rather than derived.

        If this ever starts passing, some profile field began claiming a
        physical scale it does not own, and the task config would no longer
        be the single source.
        """
        assert resolve_health_facts().value_scale_unit is None

    @pytest.mark.parametrize("check_cls", SHIPPED_CHECKS, ids=lambda c: c.name)
    def test_every_shipped_check_is_inapplicable_under_a_declared_float_task(self, check_cls):
        verdict = applicability(check_cls.declaration, self.CONTRAST_FACTS, _full_ctx())
        assert verdict.applicable is False
        assert verdict.axis == "encoding_family"

    def test_a_six_check_gate_under_contrast_facts_passes_without_opening_a_file(
        self, monkeypatch, clean_registry
    ):
        """The whole shipped roster, one gate, one declared-float task."""
        import h5py

        from execute_tools.health_checks.registry import register

        def _boom(*args, **kwargs):
            raise AssertionError("an inapplicable check opened an HDF5 file")

        monkeypatch.setattr(h5py, "File", _boom)
        monkeypatch.setattr(runner, "_resolve_task_facts", lambda: self.CONTRAST_FACTS)
        for cls in SHIPPED_CHECKS:
            register(cls())
        gate = GateConfig(
            id="all_six",
            after_round=1,
            short_circuit=True,
            checks=[CheckRef(name=cls.name) for cls in SHIPPED_CHECKS],
            on_pass=ActionConfig(action=GateAction.CONTINUE),
            on_fail=ActionConfig(action=GateAction.INVALIDATE_ROUND),
        )
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: HealthChecksConfig(health_gates=[gate]),
        )

        result = evaluate_gate("all_six", _full_ctx())

        assert [r.check_name for r in result.check_results] == [c.name for c in SHIPPED_CHECKS]
        assert all(r.verdict is CheckVerdict.INAPPLICABLE for r in result.check_results)
        # Q-08a-2: takes on_pass, never blocks — but nothing "passed".
        assert result.passed is True
        assert result.action is GateAction.CONTINUE
        assert not any(r.verdict is CheckVerdict.PASSED for r in result.check_results)


# ---------------------------------------------------------------------------
# Threshold SEMANTICS — what the subset test structurally cannot establish
# ---------------------------------------------------------------------------

# The pass/fail boundary of each check, transcribed from its predicate by
# reading the source. `output_diversity` fails on `m > min_unique`;
# `output_std` on `m >= min_std_mv`; `amplitude_collapse` on
# `m <= collapse_threshold`. The three recording checks have NO predicate at
# all — they pass on numeric completion and fail only when every file failed
# I/O — so their threshold set is empty.
THRESHOLDS_BY_CHECK = {
    "output_diversity": ("min_unique_int8_values",),
    "output_std": ("min_std_mv",),
    "amplitude_collapse": ("collapse_threshold",),
    "per_file_output_std": (),
    "spectral_peak_ratio": (),
    "pearson_dispersion": (),
}

# Read by every check, decisive for none of them.
NON_THRESHOLD_PARAMETERS = frozenset({"peek_samples", "peek_file_indices", "aggregation"})


class TestThresholdParameterNamesMeansThreshold:
    """`threshold_parameter_names` declares THRESHOLDS, not "parameters read".

    **The defect this owns, and why nothing else can.**
    `TestDeclarationsMatchWhatTheCheckReads` asserts only

        threshold_parameter_names ⊆ keys run() actually reads

    which is satisfied by ANY read key. It cannot distinguish a threshold
    from a sampling width, so it passed while the three recording checks —
    which apply no threshold whatsoever — each declared `("peek_samples",)`.

    That is not a cosmetic mislabel. 08b consumes this field to migrate
    parameters into task-owned config as thresholds; a wrong classification
    here becomes a wrong ownership decision frozen into a task config, and
    it quietly widens the frozen field's meaning to
    `threshold_parameter_names ≈ task_parameter_names`, polluting the
    contract for every future task.
    """

    @pytest.mark.parametrize("check_cls", SHIPPED_CHECKS, ids=lambda c: c.name)
    def test_declared_thresholds_are_exactly_the_pass_fail_boundary(self, check_cls):
        assert (
            check_cls.declaration.threshold_parameter_names == THRESHOLDS_BY_CHECK[check_cls.name]
        )

    @pytest.mark.parametrize("check_cls", SHIPPED_CHECKS, ids=lambda c: c.name)
    def test_no_check_declares_a_non_threshold_parameter_as_a_threshold(self, check_cls):
        """`peek_samples` is sampling width; the other two are framework policy.

        Stated as its own assertion so the failure message names the concept
        rather than just showing an unequal tuple.
        """
        declared = set(check_cls.declaration.threshold_parameter_names)
        offenders = sorted(declared & NON_THRESHOLD_PARAMETERS)
        assert not offenders, (
            f"{check_cls.name} declares non-threshold parameter(s) {offenders} as "
            f"thresholds. These are read by the check but decide no pass/fail "
            f"boundary; 08b would migrate them into task-owned config as "
            f"thresholds."
        )

    def test_recording_only_checks_declare_no_threshold(self):
        """The class of checks the original defect got wrong, named as a class."""
        recording = ("per_file_output_std", "spectral_peak_ratio", "pearson_dispersion")
        for cls in SHIPPED_CHECKS:
            if cls.name in recording:
                assert cls.declaration.threshold_parameter_names == (), cls.name

    def test_every_blocking_check_declares_exactly_one_real_threshold(self):
        """The complement: a blocking check without a threshold would be the
        opposite error — a gate that can fail but declares no boundary."""
        blocking = ("output_diversity", "output_std", "amplitude_collapse")
        for cls in SHIPPED_CHECKS:
            if cls.name in blocking:
                declared = cls.declaration.threshold_parameter_names
                assert len(declared) == 1, cls.name
                assert declared[0] not in NON_THRESHOLD_PARAMETERS, cls.name

    def test_the_fixture_check_declares_its_real_threshold(self):
        """`sample_dispersion_floor` DOES have one (`dispersion >= floor`)."""
        from execute_tools.health_checks.sample_dispersion_floor import (
            SampleDispersionFloorCheck,
        )

        assert SampleDispersionFloorCheck.declaration.threshold_parameter_names == (
            "min_dispersion",
        )

    def test_the_threshold_name_appears_in_the_checks_predicate_region(self):
        """Ties the declaration to the code that USES it, not to this table.

        A declared threshold must appear in the check's `run` source; an
        empty declaration must have no comparison against a config-derived
        bound. This is the weakest honest link between the metadata and the
        arithmetic without re-implementing the predicate.
        """
        for cls in SHIPPED_CHECKS:
            source = textwrap.dedent(inspect.getsource(cls.run))
            for name in cls.declaration.threshold_parameter_names:
                assert name in source, f"{cls.name} declares {name!r} but never reads it"
