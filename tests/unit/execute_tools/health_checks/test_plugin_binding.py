"""Step 08b C2 — run-scoped external Health plugin loading and registration.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08b_extension_architecture.md`` §3.2,
§3.5, §4.2.

Defect classes owned here:

* **The extension path silently requiring a SIDERIUS edit** — the whole point
  of the seam. A check registered from an out-of-tree file must resolve
  through the same ``registry.get`` the built-ins use, with its name absent
  from every central import list.
* **Scan tolerance leaking into declared-binding tolerance** — the amendment
  §3.2 exists to prevent. An explicitly named file that fails to load must
  fail the run closed; an unrelated member of a configured directory must
  not. These are asserted as a PAIR, because either one alone is satisfied by
  a loader that is uniformly strict or uniformly lax.
* **A run inheriting another run's registrations** — registration is
  process-global, so a second, different plugin set must fail closed. This
  is exactly the class no behavioural test can see: the check names would
  resolve perfectly and produce confident, wrong evidence.
* **A half-loaded plugin satisfying a binding** — a module that registers one
  check and then raises must contribute nothing.

These are integration-style unit tests: they build a real external package
under ``tmp_path``, outside the repository, and load it through the
production entry point. No fixture id appears in production source.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from execute_tools.health_checks import _plugin_binding, registry
from execute_tools.health_checks._plugin_binding import (
    HealthPluginError,
    HealthPluginRunScopeError,
    ResolvedHealthPlugin,
    externally_registered_checks,
    load_task_health_plugins,
    loaded_plugin_set,
)
from execute_tools.health_checks._task_health_config import TaskHealthConfig

BUILTIN_CHECK_NAMES = (
    "amplitude_collapse",
    "categorical_distinct_symbols",
    "categorical_dominant_fraction",
    "output_diversity",
    "output_std",
    "pearson_dispersion",
    "per_file_output_std",
    "sample_dispersion_floor",
    "spectral_peak_ratio",
)
"""The nine checks ``__init__._bootstrap_registry`` registers, hardcoded.

Seven from 08a/08b plus the two Step-08c generic categorical checks —
framework-shipped built-ins, configured by no shipped YAML. Read back from
``all_registered()`` this would compare the registry to itself and pass
for any bootstrap, including an empty one."""


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    """Every test in this module starts with no plugin set loaded.

    Without this the module's own tests would trip the run-scope guard they
    exist to verify — and would do so in an order-dependent way, which is the
    worst possible failure for a test suite that is itself about state leaking
    between runs.
    """
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _plugin_binding.reset_run_scope()


def _check_source(name: str, *, extra_body: str = "") -> str:
    """An external check that registers itself through the PUBLIC API.

    Deliberately imports only ``execute_tools.health_checks``' public surface
    — the same ``register`` the built-ins use — so the test cannot pass by
    reaching into an internal the seam does not actually expose.
    """
    return textwrap.dedent(f"""
        from typing import Any, ClassVar

        from execute_tools.health_checks import register
        from execute_tools.health_checks.schemas import (
            CheckInputDeclaration,
            HealthCheckContext,
            HealthCheckResult,
        )


        class _ExternalCheck:
            name: ClassVar[str] = "{name}"
            declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
                consumes_view="vendor.some_capability",
            )

            def run(
                self,
                ctx: HealthCheckContext,
                config: dict[str, Any] | None = None,
            ) -> HealthCheckResult:
                return HealthCheckResult(
                    check_name="{name}", passed=True, reason="external"
                )


        register(_ExternalCheck())
        {extra_body}
    """)


def _package(tmp_path: Path, *, files: dict[str, str]) -> Path:
    """Write an external task package outside the repository."""
    root = tmp_path / "external_task"
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _config(**kwargs) -> TaskHealthConfig:
    return TaskHealthConfig.model_validate(kwargs)


class TestAnOutOfTreeFileRegistersACheck:
    """The seam itself: external code reaches the registry with no infra edit."""

    def test_a_registered_external_check_resolves_through_the_public_registry(
        self, tmp_path, clean_registry
    ):
        root = _package(tmp_path, files={"plugins/vendor.py": _check_source("vendor_check")})
        config = _config(plugins=[{"kind": "file", "ref": "./plugins/vendor.py"}])

        resolved = load_task_health_plugins(config, str(root))

        skill = registry.get("vendor_check")
        assert skill.name == "vendor_check"
        assert externally_registered_checks() == ("vendor_check",)
        assert len(resolved) == 1
        assert resolved[0].configured_ref == "plugins/vendor.py"
        assert resolved[0].member == ""

    def test_the_fixture_check_name_appears_nowhere_in_the_central_import_list(self):
        """No external registration path requires editing ``__init__.py``.

        The census C7 generalises. Here it is the minimum honest form: the
        check that just resolved is not mentioned by the module whose import
        list used to BE the extension mechanism.
        """
        init = Path(__file__).resolve().parents[4] / "src/execute_tools/health_checks/__init__.py"

        assert "vendor_check" not in init.read_text()

    def test_a_directory_ref_loads_its_members_in_deterministic_order(
        self, tmp_path, clean_registry
    ):
        root = _package(
            tmp_path,
            files={
                "plugins/b_second.py": _check_source("second_check"),
                "plugins/a_first.py": _check_source("first_check"),
                "plugins/_private.py": _check_source("never_loaded"),
                "plugins/notes.txt": "not a plugin",
            },
        )
        config = _config(plugins=[{"kind": "directory", "ref": "./plugins"}])

        resolved = load_task_health_plugins(config, str(root))

        assert [p.member for p in resolved] == ["a_first.py", "b_second.py"]
        assert externally_registered_checks() == ("first_check", "second_check")
        # "_"-prefixed members stay dormant, matching the existing loader idiom.
        assert "never_loaded" not in registry.all_registered()

    def test_registering_nothing_is_tolerated_and_recorded_as_nothing(
        self, tmp_path, clean_registry
    ):
        """Loading is not resolution: an empty plugin is not itself an error.

        Whether anything is MISSING is Phase B's question (C3), and its error
        names the unresolved binding — a far better message than one from a
        loader that has no idea what the config declared.
        """
        root = _package(tmp_path, files={"plugins/inert.py": "VALUE = 1\n"})
        config = _config(plugins=[{"kind": "file", "ref": "./plugins/inert.py"}])

        before = registry.all_registered()
        load_task_health_plugins(config, str(root))

        assert registry.all_registered() == before
        assert externally_registered_checks() == ()


class TestScanToleranceIsNotDeclaredBindingTolerance:
    """§3.2's operator amendment, asserted as a PAIR.

    Either half alone is satisfied by a loader that is uniformly strict or
    uniformly lax; only the contrast shows the distinction is real.
    """

    BROKEN = "raise RuntimeError('plugin exploded')\n"

    def test_an_explicitly_named_broken_file_fails_the_run_closed(self, tmp_path, clean_registry):
        root = _package(tmp_path, files={"plugins/broken.py": self.BROKEN})
        config = _config(plugins=[{"kind": "file", "ref": "./plugins/broken.py"}])

        with pytest.raises(HealthPluginError) as excinfo:
            load_task_health_plugins(config, str(root))

        assert "plugins/broken.py" in str(excinfo.value)
        assert "plugin exploded" in str(excinfo.value)

    def test_a_broken_member_of_a_configured_directory_only_warns(self, tmp_path, clean_registry):
        root = _package(
            tmp_path,
            files={
                "plugins/broken.py": self.BROKEN,
                "plugins/good.py": _check_source("survivor_check"),
            },
        )
        config = _config(plugins=[{"kind": "directory", "ref": "./plugins"}])

        with pytest.warns(RuntimeWarning, match="broken.py"):
            load_task_health_plugins(config, str(root))

        # The unrelated member's failure did not stop the one that works.
        assert registry.get("survivor_check").name == "survivor_check"

    @pytest.mark.parametrize(
        "files, ref, fragment",
        [
            pytest.param({}, "./plugins/absent.py", "does not exist", id="missing-file"),
            pytest.param(
                {"plugins/bad.py": "def broken(:\n"},
                "./plugins/bad.py",
                "raised while importing",
                id="unparseable-file",
            ),
        ],
    )
    def test_every_explicit_file_failure_mode_fails_closed(
        self, tmp_path, clean_registry, files, ref, fragment
    ):
        root = _package(tmp_path, files=files)
        config = _config(plugins=[{"kind": "file", "ref": ref}])

        with pytest.raises(HealthPluginError) as excinfo:
            load_task_health_plugins(config, str(root))

        assert fragment in str(excinfo.value)

    def test_a_missing_configured_directory_fails_closed(self, tmp_path, clean_registry):
        """Per-member tolerance covers members, not the directory itself.

        The task named this directory; nothing it declares could resolve, so
        continuing would silently run a different set of gates.
        """
        root = _package(tmp_path, files={"placeholder.txt": "x"})
        config = _config(plugins=[{"kind": "directory", "ref": "./no_such_dir"}])

        with pytest.raises(HealthPluginError) as excinfo:
            load_task_health_plugins(config, str(root))

        assert "no_such_dir" in str(excinfo.value)

    def test_a_name_colliding_with_a_builtin_fails_closed(self, tmp_path):
        """A duplicate name must never silently win or silently lose.

        Runs against the REAL bootstrapped registry — colliding with a
        built-in is only meaningful when the built-in is actually there.
        """
        root = _package(tmp_path, files={"plugins/clash.py": _check_source("output_diversity")})
        config = _config(plugins=[{"kind": "file", "ref": "./plugins/clash.py"}])

        with pytest.raises(HealthPluginError) as excinfo:
            load_task_health_plugins(config, str(root))

        assert "already registered" in str(excinfo.value)

    def test_a_plugin_that_raises_after_registering_contributes_nothing(
        self, tmp_path, clean_registry
    ):
        """Half-loaded is not loaded.

        A check left behind by a module that never finished executing could
        satisfy a binding while the code defining its behaviour never ran.
        """
        root = _package(
            tmp_path,
            files={
                "plugins/partial.py": _check_source(
                    "half_registered", extra_body="raise RuntimeError('after registering')"
                )
            },
        )
        config = _config(plugins=[{"kind": "file", "ref": "./plugins/partial.py"}])

        with pytest.raises(HealthPluginError):
            load_task_health_plugins(config, str(root))

        assert "half_registered" not in registry.all_registered()


class TestRunScopeIsEnforcedNotAssumed:
    """§3.5 — the two-run counterfactual.

    Production happens to host one run per process, but that is emergent, not
    guaranteed. Without the ledger a second run's checks resolve perfectly
    against the FIRST run's registrations and every record looks healthy.
    """

    def test_a_different_plugin_set_in_the_same_process_fails_closed(
        self, tmp_path, clean_registry
    ):
        root = _package(
            tmp_path,
            files={
                "plugins/a.py": _check_source("run_a_check"),
                "plugins/b.py": _check_source("run_b_check"),
            },
        )
        load_task_health_plugins(
            _config(plugins=[{"kind": "file", "ref": "./plugins/a.py"}]), str(root)
        )

        with pytest.raises(HealthPluginRunScopeError) as excinfo:
            load_task_health_plugins(
                _config(plugins=[{"kind": "file", "ref": "./plugins/b.py"}]), str(root)
            )

        message = str(excinfo.value)
        assert "plugins/a.py" in message and "plugins/b.py" in message

    def test_reloading_the_identical_set_is_idempotent(self, tmp_path, clean_registry):
        """Re-entrant startup and resume must not be punished."""
        root = _package(tmp_path, files={"plugins/a.py": _check_source("idempotent_check")})
        config = _config(plugins=[{"kind": "file", "ref": "./plugins/a.py"}])

        first = load_task_health_plugins(config, str(root))
        second = load_task_health_plugins(config, str(root))

        assert first == second
        assert externally_registered_checks() == ("idempotent_check",)

    def test_the_same_package_at_a_different_absolute_path_is_the_same_set(
        self, tmp_path, clean_registry
    ):
        """Identity is canonical, not host-specific (§3.6).

        A relocated checkout must not read as a different run — and must not
        re-execute the module, which would raise on duplicate registration.
        """
        source = _check_source("relocatable_check")
        first_root = _package(tmp_path / "one", files={"plugins/a.py": source})
        second_root = _package(tmp_path / "two", files={"plugins/a.py": source})
        config = _config(plugins=[{"kind": "file", "ref": "./plugins/a.py"}])

        load_task_health_plugins(config, str(first_root))
        load_task_health_plugins(config, str(second_root))

        assert externally_registered_checks() == ("relocatable_check",)

    def test_the_same_ref_with_changed_bytes_is_a_different_set(self, tmp_path, clean_registry):
        """Content is part of identity — the property C4's pin depends on."""
        root = _package(tmp_path, files={"plugins/a.py": _check_source("mutable_check")})
        config = _config(plugins=[{"kind": "file", "ref": "./plugins/a.py"}])
        load_task_health_plugins(config, str(root))

        (root / "plugins/a.py").write_text(_check_source("mutable_check") + "\n# edited\n")

        with pytest.raises(HealthPluginRunScopeError):
            load_task_health_plugins(config, str(root))


class TestBackwardCompatibility:
    """Nothing changes for a run that declares no plugins."""

    def test_with_no_plugins_declared_the_registry_is_exactly_the_builtins(self):
        assert tuple(registry.all_registered()) == BUILTIN_CHECK_NAMES

    def test_loading_an_empty_plugin_set_registers_nothing(self, tmp_path):
        resolved = load_task_health_plugins(_config(), str(tmp_path))

        assert resolved == ()
        assert loaded_plugin_set() == ()
        assert tuple(registry.all_registered()) == BUILTIN_CHECK_NAMES


class TestCanonicalIdentityExcludesTheHost:
    """§3.6 — what C4 folds into the pinned run identity, and what it must not."""

    def test_canonical_identity_is_ref_member_and_digest_only(self):
        plugin = ResolvedHealthPlugin(
            configured_ref="plugins/a.py",
            member="",
            content_sha256="abc",
            absolute_path="/some/host/specific/path/plugins/a.py",
        )

        assert plugin.canonical_identity() == {
            "configured_ref": "plugins/a.py",
            "member": "",
            "content_sha256": "abc",
        }

    def test_a_cosmetically_different_ref_spelling_is_one_identity(self, tmp_path, clean_registry):
        """``./plugins/a.py`` and ``plugins/a.py`` name the same file.

        Leaving both spellings alive would make a purely cosmetic config edit
        invalidate a workspace on resume.
        """
        root = _package(tmp_path, files={"plugins/a.py": _check_source("normalized_check")})

        load_task_health_plugins(
            _config(plugins=[{"kind": "file", "ref": "./plugins/a.py"}]), str(root)
        )
        load_task_health_plugins(
            _config(plugins=[{"kind": "file", "ref": "plugins/a.py"}]), str(root)
        )

        assert loaded_plugin_set()[0].configured_ref == "plugins/a.py"
