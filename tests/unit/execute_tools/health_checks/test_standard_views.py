# tests/unit/execute_tools/health_checks/test_standard_views.py
"""Step 08c C1 — the standard view payload ABI, opacity and inertness.

Owns the frozen §3.1 ABI of the two framework-standard capabilities:

* exact key spellings (parent §6.3, hardcoded — never read back from the
  module under test's derivations);
* strict dtype-kind acceptance with NO coercion, every rejection naming the
  offender;
* read-only no-copy view semantics, asserted as ``np.shares_memory``
  (deliberately NOT ``.base`` identity, which NumPy does not guarantee for
  an input that is itself a view), with the provider array's contents and
  writeability preserved in BOTH directions;
* engine opacity — no engine module CODE references the keys or payload
  types;
* C1 inertness — the vocabulary has NO production consumer beyond the
  package export. **INVERTED in C2**, when the three generic checks become
  its first consumers.

The censuses are CODE-level: identifiers, imports and non-docstring string
literals. Prose is excluded on purpose — ``_view_provider.py``'s own 08b
docstring names the standard keys while the module remains perfectly opaque
to them, and ``sample_dispersion_floor``'s plugin-local key
``step08.fixture_continuous_samples`` contains a standard key as a mere
substring. A raw-text census would cry wolf on both; an AST census cannot.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from execute_tools.health_checks.standard_views import (
    CATEGORICAL_PREDICTIONS,
    CONTINUOUS_SAMPLES,
    CategoricalPredictionsPayload,
    ContinuousSamplesPayload,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

# Mirrors the out-of-tree extension census: every package a production
# reference could hide in, configs included (a YAML naming a standard key
# would be a production consumer too).
PRODUCTION_PACKAGES = (
    "src/execute_tools",
    "src/nodes",
    "src/agent",
    "src/core",
    "scripts",
    "src/workflows",
    "configs",
)


class TestKeySpellings:
    """The two capability keys, frozen to the parent §6.3 spellings."""

    def test_categorical_key_is_the_parent_spelling(self):
        assert CATEGORICAL_PREDICTIONS == "categorical_predictions"

    def test_continuous_key_is_the_parent_spelling(self):
        assert CONTINUOUS_SAMPLES == "continuous_samples"

    def test_package_root_exports_the_vocabulary(self):
        """Pack plugins import the public surface, never the submodule."""
        import execute_tools.health_checks as hc

        assert hc.CATEGORICAL_PREDICTIONS is CATEGORICAL_PREDICTIONS
        assert hc.CONTINUOUS_SAMPLES is CONTINUOUS_SAMPLES
        assert hc.CategoricalPredictionsPayload is CategoricalPredictionsPayload
        assert hc.ContinuousSamplesPayload is ContinuousSamplesPayload


class TestCategoricalPayloadABI:
    """symbols: 1-D integer ndarray, kinds {'i', 'u'}, no coercion."""

    @pytest.mark.parametrize("dtype", [np.int8, np.int64, np.uint8, np.uint32])
    def test_accepts_integer_dtypes_and_preserves_them(self, dtype):
        arr = np.array([0, 3, 3, 36], dtype=dtype)
        payload = CategoricalPredictionsPayload(symbols=arr)
        assert payload.symbols.dtype == np.dtype(dtype)
        assert payload.symbols.tolist() == [0, 3, 3, 36]

    def test_accepts_an_empty_integer_array(self):
        # Emptiness is a CHECK-level ERROR (§3.2a) — the payload must let a
        # provider say honestly "I read the artifact and it was empty".
        payload = CategoricalPredictionsPayload(symbols=np.array([], dtype=np.int64))
        assert payload.symbols.size == 0

    @pytest.mark.parametrize(
        ("bad", "named"),
        [
            (np.array([True, False]), "bool"),
            (np.array(["cat", "dog"]), "<U3"),
            (np.array([None, None], dtype=object), "object"),
            (np.array([0.5, 1.5]), "float64"),
        ],
    )
    def test_rejects_wrong_dtype_kind_naming_the_dtype(self, bad, named):
        with pytest.raises(ValidationError, match="symbols") as excinfo:
            CategoricalPredictionsPayload(symbols=bad)
        assert named in str(excinfo.value)

    def test_rejects_a_2d_array_naming_the_shape(self):
        with pytest.raises(ValidationError, match="1-D") as excinfo:
            CategoricalPredictionsPayload(symbols=np.zeros((2, 3), dtype=np.int64))
        assert "(2, 3)" in str(excinfo.value)

    @pytest.mark.parametrize("bad", [[0, 1, 2], (0, 1, 2)])
    def test_rejects_python_sequences_no_coercion(self, bad):
        with pytest.raises(ValidationError, match=r"numpy\.ndarray") as excinfo:
            CategoricalPredictionsPayload(symbols=bad)
        assert type(bad).__name__ in str(excinfo.value)


class TestContinuousPayloadABI:
    """samples: 1-D floating ndarray, kind 'f', native dtype preserved."""

    @pytest.mark.parametrize("dtype", [np.float32, np.float64])
    def test_accepts_floating_dtypes_and_preserves_them(self, dtype):
        # Native-dtype preservation is load-bearing (§3.5a): a float32
        # artifact must ARRIVE as float32 — float64 enters only inside the
        # consuming check's estimator.
        arr = np.array([0.1, 0.2, 0.3], dtype=dtype)
        payload = ContinuousSamplesPayload(samples=arr)
        assert payload.samples.dtype == np.dtype(dtype)

    def test_accepts_an_empty_float_array(self):
        payload = ContinuousSamplesPayload(samples=np.array([], dtype=np.float32))
        assert payload.samples.size == 0

    def test_accepts_non_finite_values(self):
        # §3.2a: non-finite is an OBSERVABLE pathology the CHECK condemns as
        # FAILED; the payload transports what the provider read.
        arr = np.array([np.nan, np.inf, -np.inf, 1.0])
        payload = ContinuousSamplesPayload(samples=arr)
        assert payload.samples.size == 4

    def test_rejects_an_integer_array_naming_the_dtype(self):
        with pytest.raises(ValidationError, match="samples") as excinfo:
            ContinuousSamplesPayload(samples=np.array([1, 2, 3], dtype=np.int64))
        assert "int64" in str(excinfo.value)

    @pytest.mark.parametrize(
        ("bad", "named"),
        [
            (np.array([True, False]), "bool"),
            (np.array(["0.5"]), "<U3"),
            (np.array([None], dtype=object), "object"),
        ],
    )
    def test_rejects_wrong_dtype_kind_naming_the_dtype(self, bad, named):
        with pytest.raises(ValidationError) as excinfo:
            ContinuousSamplesPayload(samples=bad)
        assert named in str(excinfo.value)

    def test_rejects_a_2d_array_naming_the_shape(self):
        with pytest.raises(ValidationError, match="1-D"):
            ContinuousSamplesPayload(samples=np.zeros((3, 4), dtype=np.float32))

    @pytest.mark.parametrize("bad", [[0.5, 1.5], (0.5, 1.5)])
    def test_rejects_python_sequences_no_coercion(self, bad):
        with pytest.raises(ValidationError, match=r"numpy\.ndarray"):
            ContinuousSamplesPayload(samples=bad)


class TestReadOnlyNoCopySemantics:
    """The stored view is read-only and shares the provider's memory."""

    @staticmethod
    def _payloads():
        cat_arr = np.array([1, 2, 3], dtype=np.int64)
        cont_arr = np.array([0.5, 1.5], dtype=np.float32)
        return (
            (cat_arr, CategoricalPredictionsPayload(symbols=cat_arr).symbols),
            (cont_arr, ContinuousSamplesPayload(samples=cont_arr).samples),
        )

    def test_stored_view_is_read_only_and_mutation_raises(self):
        for _, stored in self._payloads():
            assert stored.flags.writeable is False
            with pytest.raises(ValueError, match="read-only"):
                stored[0] = 99

    def test_no_copy_via_shares_memory(self):
        # Deliberately NOT ``stored.base is supplied`` — NumPy does not
        # guarantee base identity for an input that is itself a view.
        for supplied, stored in self._payloads():
            assert np.shares_memory(stored, supplied)

    def test_a_writable_input_stays_writable(self):
        arr = np.array([1, 2, 3], dtype=np.int64)
        assert arr.flags.writeable is True
        CategoricalPredictionsPayload(symbols=arr)
        assert arr.flags.writeable is True

    def test_a_readonly_input_stays_readonly_and_is_accepted(self):
        arr = np.array([0.5, 1.5], dtype=np.float64)
        arr.flags.writeable = False
        payload = ContinuousSamplesPayload(samples=arr)
        assert arr.flags.writeable is False
        assert payload.samples.flags.writeable is False

    def test_construction_leaves_contents_unchanged(self):
        arr = np.array([7, 8, 9], dtype=np.int32)
        before = arr.copy()
        CategoricalPredictionsPayload(symbols=arr)
        np.testing.assert_array_equal(arr, before)


# --- code-level census machinery -------------------------------------------
#
# Capability keys are EXACT strings (frozen invariant: "standard view keys
# are exact"), so a key reference is an exact-match string literal or the
# exact constant identifier. The module name travels inside dotted import
# paths, so it is matched as a substring.

EXACT_STANDARD_NAMES = (
    "categorical_predictions",
    "continuous_samples",
    "CATEGORICAL_PREDICTIONS",
    "CONTINUOUS_SAMPLES",
    "CategoricalPredictionsPayload",
    "ContinuousSamplesPayload",
)

SUBSTRING_STANDARD_NAMES = ("standard_views",)

ENGINE_MODULES = (
    "src/execute_tools/health_checks/runner.py",
    "src/execute_tools/health_checks/_view_provider.py",
    "src/execute_tools/health_checks/_plugin_binding.py",
    "src/execute_tools/health_checks/_composition.py",
)

DEFINITION_MODULE = "src/execute_tools/health_checks/standard_views.py"
EXPORT_MODULE = "src/execute_tools/health_checks/__init__.py"


def _git_grep(pattern: str) -> list[str]:
    proc = subprocess.run(
        # --untracked: a brand-new production module is exactly the case
        # this census must catch, and git grep skips untracked files by
        # default.
        ["git", "grep", "-nF", "--untracked", pattern, "--", *PRODUCTION_PACKAGES],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # 0 = matches, 1 = no matches. Anything else means the search did not
    # run, which must not be read as "no consumers".
    assert proc.returncode in (0, 1), (
        f"git grep failed (rc={proc.returncode}) in {REPO_ROOT}: {proc.stderr.strip()}"
    )
    return proc.stdout.splitlines()


def _code_level_names(path: Path) -> set[str]:
    """Every identifier, attribute, import path and NON-docstring string."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_nodes.add(id(body[0].value))
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
            and id(node) not in docstring_nodes
        ):
            found.add(node.value)
    return found


def _references(found: set[str], name: str, *, exact: bool) -> bool:
    return (name in found) if exact else any(name in item for item in found)


def _production_files_referencing(name: str, *, exact: bool) -> set[str]:
    """Production files with a CODE reference to ``name``.

    git grep (substring, --untracked) prefilters candidates; each candidate
    ``.py`` is then AST-verified so docstrings, comments and
    substring-containing OTHER keys do not count. A non-Python candidate
    (YAML, JSON, shell) counts on the raw hit — there is no prose there to
    excuse.
    """
    candidates = {hit.split(":", 1)[0] for hit in _git_grep(name)}
    offenders: set[str] = set()
    for rel in sorted(candidates):
        if rel.endswith(".py"):
            if _references(_code_level_names(REPO_ROOT / rel), name, exact=exact):
                offenders.add(rel)
        elif rel.endswith(".md"):
            # Documentation is PROSE — the same principle that excludes .py
            # docstrings above ("Prose is excluded on purpose"). This branch
            # was added when the S4 onboarding stream shipped module READMEs
            # inside the swept packages: a README that NAMES a capability key
            # is describing it, not defining or consuming it, and cannot be
            # imported by an engine.
            continue
        else:
            offenders.add(rel)
    return offenders


class TestEngineOpacity:
    """No engine module CODE references the standard keys or payload types.

    The contract binds provider↔check ONLY (§3.1). An engine that imported
    a payload type or branched on a standard key would make standard views
    privileged over plugin-local ones — the exact asymmetry 08b's opaque
    transport forbids. This census is PERMANENT (C2's inversion does not
    touch it).
    """

    def test_engine_modules_exist(self):
        """Guards the guard: a renamed module would make the census vacuous."""
        for rel in ENGINE_MODULES:
            assert (REPO_ROOT / rel).is_file(), rel

    def test_the_collector_sees_definitions(self):
        """Positive probes: the collector sees identifiers and string
        literals on the vocabulary module, and dotted import paths on the
        package export — so an empty engine result is evidence, not
        blindness."""
        definition_names = _code_level_names(REPO_ROOT / DEFINITION_MODULE)
        for name in EXACT_STANDARD_NAMES:
            assert _references(definition_names, name, exact=True), name
        export_names = _code_level_names(REPO_ROOT / EXPORT_MODULE)
        assert _references(export_names, "standard_views", exact=False)

    @pytest.mark.parametrize("rel", ENGINE_MODULES)
    def test_engine_module_is_opaque_to_standard_views(self, rel):
        found = _code_level_names(REPO_ROOT / rel)
        offenders = [n for n in EXACT_STANDARD_NAMES if _references(found, n, exact=True)]
        offenders += [n for n in SUBSTRING_STANDARD_NAMES if _references(found, n, exact=False)]
        assert not offenders, f"{rel} code references standard-view vocabulary: {offenders}"


#: The enumerated production consumers of the standard-view vocabulary —
#: the C1 inertness census, INVERTED at C2 (upgraded, never deleted): the
#: generic check family and its shared validity module are the only
#: production code allowed to consume the standard payloads. The ENGINE
#: stays out of this set permanently (TestEngineOpacity).
CONSUMER_MODULES = frozenset(
    {
        "src/execute_tools/health_checks/_categorical_validity.py",
        "src/execute_tools/health_checks/categorical_distinct_symbols.py",
        "src/execute_tools/health_checks/categorical_dominant_fraction.py",
        "src/execute_tools/health_checks/sample_dispersion_floor.py",
    }
)


class TestStandardViewsConsumerCensus:
    """The vocabulary's production consumers are exactly the generic family.

    C1 shipped the vocabulary inert; C2 inverted the census to this
    enumerated consumer set. A new consumer must be added HERE deliberately
    — an engine module acquiring one would instead trip TestEngineOpacity.
    """

    def test_repo_root_resolves_to_this_checkout(self):
        assert (REPO_ROOT / ".git").exists()
        assert (REPO_ROOT / DEFINITION_MODULE).is_file()

    def test_the_grep_probe_actually_finds_things(self):
        hits = _git_grep("CategoricalPredictionsPayload")
        assert any(hit.startswith(DEFINITION_MODULE) for hit in hits), hits

    def test_every_enumerated_consumer_exists_and_consumes(self):
        """Anti-vacuity: a stale entry here would silently shrink the census."""
        for rel in sorted(CONSUMER_MODULES):
            names = _code_level_names(REPO_ROOT / rel)
            assert _references(names, "standard_views", exact=False), rel

    @pytest.mark.parametrize("key", ["categorical_predictions", "continuous_samples"])
    def test_key_string_is_defined_in_exactly_one_production_module(self, key):
        files = _production_files_referencing(key, exact=True)
        assert files == {DEFINITION_MODULE}, (
            f"the capability key {key!r} must be defined exactly once, found in: {sorted(files)}"
        )

    @pytest.mark.parametrize(
        ("name", "exact"),
        [
            ("CATEGORICAL_PREDICTIONS", True),
            ("CONTINUOUS_SAMPLES", True),
            ("CategoricalPredictionsPayload", True),
            ("ContinuousSamplesPayload", True),
            ("standard_views", False),
        ],
    )
    def test_no_production_consumer_beyond_the_enumerated_set(self, name, exact):
        files = _production_files_referencing(name, exact=exact)
        allowed = {DEFINITION_MODULE, EXPORT_MODULE} | CONSUMER_MODULES
        assert files <= allowed, (
            f"{name!r} referenced outside the enumerated vocabulary surface: "
            f"{sorted(files - allowed)}"
        )
