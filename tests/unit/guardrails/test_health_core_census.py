# tests/unit/guardrails/test_health_core_census.py
"""Step 08c C6 — the health-core structural census + the three-task rung.

Parent §13's strengthened structural items, executable over the ENUMERATED
generic health modules (the TIDMAD-family surfaces excluded BY LISTED
NAME, so the census can neither silently widen nor narrow):

* zero task-name tokens in generic code — with exactly ONE quarantined
  allowance, the `LEGACY_DEFAULT_TASK_HEALTH_CONFIG` constant;
* zero `examples` imports anywhere in the package;
* no task-science literals (`37`, `int8`, `channel0001/2`, `mV`) in
  generic code;
* no closed view-kind enumeration — the standard keys/payloads appear
  only in their vocabulary module and enumerated consumers;
* no metric-scalar consumption as check evidence (the carrier definition
  in `schemas.py` and the record-eligibility read in
  `candidate_eligibility.py` are the two named non-check allowances);
* the CORRECTED registration claim (amendment 10): the central bootstrap
  enumerates ONLY framework-shipped built-ins — no Pets id, no DAVIS id,
  no synthetic external-task id in the bootstrap, the package, or the
  framework policy YAMLs. External registration needs no central edit
  (the 08b out-of-tree proof keeps owning the live half).

Census discipline: AST code-level (identifiers, definitions, imports and
non-docstring strings, with `description=` keyword strings excluded as
field documentation), every pattern anti-vacuous via planted-offender
probes — including one planted in the bootstrap.

The three-task rung composes TIDMAD (state A), Pets (state C) and DAVIS
(state C) in ONE module with `reset_run_scope` between: disjoint rosters,
the generic family firing for B/C, the int8 family inapplicable under
B/C facts, and state A byte-stable across the interleaving.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HEALTH_CORE = REPO_ROOT / "src/execute_tools" / "health_checks"

#: TIDMAD-family surfaces, excluded from the GENERIC census BY LISTED NAME.
#: The six check modules + the peek/regime-A readers own TIDMAD's science
#: (int8 keys, mV thresholds, profile derivation) by design.
#:
#: **``evaluation.py`` was removed from this set by Step 10 / P4 (C2).** It was
#: excluded as "the pre-08a campaign-persistence adapter whose per-check-name
#: threshold tables predate declarations — recorded 08c out-of-scope finding,
#: owner Step 9/10, NOT silently generic". P4 is that owner: the tables, the
#: duplicated defaults and the TIDMAD sampling literal are gone, the evidence
#: is rendered from each check's own declaration, and the module now passes
#: this census unchanged. That promotion IS P4's structural acceptance — a
#: regression puts a check name or an `mV` back into generic code and turns
#: the census RED without anyone having to remember why.
TIDMAD_FAMILY_MODULES = frozenset(
    {
        "amplitude_collapse.py",
        "output_diversity.py",
        "output_std.py",
        "per_file_output_std.py",
        "pearson_dispersion.py",
        "spectral_peak_ratio.py",
        "_peek.py",
        "_multi_file_peek.py",
        "_regime_a_facts.py",
    }
)

#: The generic modules the census walks — everything else in the package.
GENERIC_MODULES = tuple(
    sorted(p.name for p in HEALTH_CORE.glob("*.py") if p.name not in TIDMAD_FAMILY_MODULES)
)

TASK_TOKENS = ("tidmad", "pets", "davis", "oxford", "acme")
SCIENCE_LITERALS = ("int8", "channel0001", "channel0002", "mV")

FRAMEWORK_POLICY_YAMLS = (
    REPO_ROOT / "configs" / "health_checks.yaml",
    REPO_ROOT / "configs" / "health_checks_baseline_observe_mode.yaml",
)

#: The nine framework-shipped built-ins the bootstrap may enumerate —
#: hardcoded (read back from the registry this would compare the bootstrap
#: to itself).
BUILTIN_CHECK_CLASSES = (
    "OutputDiversityCheck",
    "AmplitudeCollapseCheck",
    "OutputStdCheck",
    "PearsonDispersionCheck",
    "SpectralPeakRatioCheck",
    "PerFileOutputStdCheck",
    "SampleDispersionFloorCheck",
    "CategoricalDistinctSymbolsCheck",
    "CategoricalDominantFractionCheck",
)

EXTERNAL_PACK_IDS = (
    "acme.window_provider",
    "acme_window_dispersion",
)


def _code_level_names(tree: ast.Module) -> set[str]:
    """Identifiers, definitions, imports and non-documentation strings.

    Docstrings AND ``description=`` keyword strings are excluded: both are
    prose carried in code (pydantic field documentation names 'mV' and
    'int8_symbol_stream' as EXAMPLES without the module consuming either).
    """
    documentation: set[int] = set()
    for node in ast.walk(tree):
        # ANY bare string expression statement is documentation: module,
        # class and function docstrings AND the attribute-docstring idiom
        # (a bare string after a constant assignment). A bare string has no
        # runtime effect, so it cannot be a code reference.
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            documentation.add(id(node.value))
        elif isinstance(node, ast.keyword) and node.arg == "description":
            for constant in ast.walk(node.value):
                if isinstance(constant, ast.Constant) and isinstance(constant.value, str):
                    documentation.add(id(constant))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            found.add(node.name)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.alias):
            found.add(node.name)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in documentation
        ):
            found.add(node.value)
    return found


def _module_names(name: str) -> set[str]:
    return _code_level_names(ast.parse((HEALTH_CORE / name).read_text(encoding="utf-8")))


def _token_hits(found: set[str], token: str) -> list[str]:
    lowered = token.lower()
    return sorted(item for item in found if lowered in item.lower())


class TestCensusScope:
    def test_the_enumerated_partition_is_exhaustive_and_current(self):
        """Guards the census: a NEW package module lands in the GENERIC set
        by default (fail closed toward being censused), and every excluded
        name still exists — a renamed TIDMAD module would otherwise leave
        the census silently narrowed."""
        actual = {p.name for p in HEALTH_CORE.glob("*.py")}
        assert TIDMAD_FAMILY_MODULES <= actual, sorted(TIDMAD_FAMILY_MODULES - actual)
        assert set(GENERIC_MODULES) == actual - TIDMAD_FAMILY_MODULES
        assert "__init__.py" in GENERIC_MODULES
        assert "standard_views.py" in GENERIC_MODULES

    def test_the_collector_sees_code_and_skips_documentation(self):
        """Anti-vacuity for the collector itself."""
        tree = ast.parse(
            textwrap.dedent(
                '''
                """Docstring naming tidmad."""
                from pydantic import Field
                x = Field(description="documentation naming mV and int8")
                KEY = "real_code_string"
                '''
            )
        )
        found = _code_level_names(tree)
        assert "real_code_string" in found
        assert not _token_hits(found, "tidmad")
        assert not _token_hits(found, "mV")


class TestNoTaskTokensInGenericCore:
    @pytest.mark.parametrize("module_name", GENERIC_MODULES)
    def test_no_task_token_beyond_the_quarantined_constant(self, module_name):
        found = _module_names(module_name)
        for token in TASK_TOKENS:
            hits = _token_hits(found, token)
            assert hits == [], f"{module_name}: task token {token!r} in code: {hits}"

    def test_a_planted_task_comparison_is_detected(self, tmp_path):
        offender = tmp_path / "offender.py"
        offender.write_text('if task == "pets":\n    pass\n')
        found = _code_level_names(ast.parse(offender.read_text()))
        assert _token_hits(found, "pets") == ["pets"]


class TestNoExamplesImports:
    @pytest.mark.parametrize("module_name", sorted(p.name for p in HEALTH_CORE.glob("*.py")))
    def test_no_module_imports_examples(self, module_name):
        tree = ast.parse((HEALTH_CORE / module_name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("examples"), module_name
            elif isinstance(node, ast.Import):
                assert not any(a.name.startswith("examples") for a in node.names), module_name

    def test_a_planted_examples_import_is_detected(self):
        tree = ast.parse("from examples.some_pack.plugins import thing\n")
        modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert modules == ["examples.some_pack.plugins"]


class TestNoTaskScienceLiteralsInGenericCore:
    @pytest.mark.parametrize("module_name", GENERIC_MODULES)
    def test_no_cardinality_37_literal(self, module_name):
        tree = ast.parse((HEALTH_CORE / module_name).read_text(encoding="utf-8"))
        hits = [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and n.value == 37 and not isinstance(n.value, bool)
        ]
        assert hits == [], f"{module_name}: literal 37 in generic core"

    @pytest.mark.parametrize("module_name", GENERIC_MODULES)
    def test_no_int8_channel_or_mv_literal(self, module_name):
        found = _module_names(module_name)
        for literal in SCIENCE_LITERALS:
            assert _token_hits(found, literal) == [], (
                f"{module_name}: task-science literal {literal!r} in code"
            )

    def test_a_planted_science_literal_is_detected(self):
        found = _code_level_names(ast.parse('UNIT = "mV"\nfamily = "int8_symbol_stream"\n'))
        assert _token_hits(found, "mV") and _token_hits(found, "int8")


class TestNoClosedViewKindEnumeration:
    """The standard keys/payloads live in the vocabulary module and its
    enumerated consumers ONLY (the C1/C2 census, restated over the C6
    generic partition so the two lists cannot drift apart silently)."""

    VOCABULARY_AND_CONSUMERS = frozenset(
        {
            "standard_views.py",
            "__init__.py",  # the public export
            "_categorical_validity.py",
            "categorical_distinct_symbols.py",
            "categorical_dominant_fraction.py",
            "sample_dispersion_floor.py",
        }
    )

    @pytest.mark.parametrize("module_name", GENERIC_MODULES)
    def test_no_other_generic_module_touches_the_standard_vocabulary(self, module_name):
        if module_name in self.VOCABULARY_AND_CONSUMERS:
            return
        found = _module_names(module_name)
        offenders = [
            name
            for name in (
                "categorical_predictions",
                "continuous_samples",
                "CATEGORICAL_PREDICTIONS",
                "CONTINUOUS_SAMPLES",
                "CategoricalPredictionsPayload",
                "ContinuousSamplesPayload",
            )
            if name in found
        ]
        offenders += ["standard_views"] if any("standard_views" in i for i in found) else []
        assert offenders == [], f"{module_name}: {offenders}"


class TestNoMetricScalarConsumption:
    """Checks never read the golden metric as Health evidence.

    Two named NON-check allowances: ``schemas.py`` (the context carrier
    and its presence predicates) and ``candidate_eligibility.py`` (record
    ELIGIBILITY policy — it classifies persisted records, it is not a
    check reading evidence).
    """

    ALLOWED = frozenset({"schemas.py", "candidate_eligibility.py"})

    @pytest.mark.parametrize("module_name", GENERIC_MODULES)
    def test_no_generic_module_reads_the_scalar(self, module_name):
        if module_name in self.ALLOWED:
            return
        found = _module_names(module_name)
        offenders = [t for t in ("denoising_score", "file_vector") if t in found]
        assert offenders == [], f"{module_name}: {offenders}"

    def test_every_registered_check_source_is_scalar_free(self):
        """The existing invariant-16 census, re-run here over the grown
        registry so the C6 claim is self-contained."""
        import inspect

        from execute_tools.health_checks import registry

        for name in registry.all_registered():
            source = inspect.getsource(type(registry.get(name)))
            assert "denoising_score" not in source, name
            assert "ctx.file_vector" not in source, name


def _bootstrap_registered_classes(init_source: str) -> list[str]:
    """Class names instantiated inside ``_bootstrap_registry``'s loop."""
    tree = ast.parse(init_source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_bootstrap_registry":
            return [
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            ]
    raise AssertionError("_bootstrap_registry not found")


class TestCorrectedRegistrationClaim:
    """Amendment 10: built-ins may bootstrap; EXTERNAL needs no central edit."""

    def test_the_bootstrap_enumerates_exactly_the_framework_builtins(self):
        registered = _bootstrap_registered_classes(
            (HEALTH_CORE / "__init__.py").read_text(encoding="utf-8")
        )
        instantiated = [n for n in registered if n.endswith("Check")]
        assert instantiated == list(BUILTIN_CHECK_CLASSES), instantiated

    def test_no_pack_or_external_id_in_the_package(self):
        for module in sorted(HEALTH_CORE.glob("*.py")):
            found = _code_level_names(ast.parse(module.read_text(encoding="utf-8")))
            offenders = [pack_id for pack_id in EXTERNAL_PACK_IDS if pack_id in found]
            assert offenders == [], f"{module.name}: {offenders}"

    def test_no_pack_or_external_id_in_the_framework_policy_yamls(self):
        for policy in FRAMEWORK_POLICY_YAMLS:
            text = policy.read_text(encoding="utf-8")
            offenders = [pack_id for pack_id in EXTERNAL_PACK_IDS if pack_id in text]
            assert offenders == [], f"{policy.name}: {offenders}"

    def test_a_fixture_id_planted_in_the_bootstrap_is_detected(self):
        """Anti-vacuity for the registration claim itself."""
        planted = textwrap.dedent(
            """
            def _bootstrap_registry():
                for check in (
                    OutputDiversityCheck(),
                    AcmeWindowDispersionCheck(),
                ):
                    register(check)
            """
        )
        registered = _bootstrap_registered_classes(planted)
        assert "AcmeWindowDispersionCheck" in registered
        assert [n for n in registered if n.endswith("Check")] != list(BUILTIN_CHECK_CLASSES)
