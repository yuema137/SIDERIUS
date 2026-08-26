"""``core/generated_library.py`` — the ONE resolved library-root authority.

arXiv P1 (user-contract audit §H): generated runtime artifacts move OFF the
repository checkout to a resolved, durable, non-checkout root. These tests
guard the resolution semantics that every repointed family (capability
index, promotion writers, loss union, legacy fallbacks) leans on.

Per the repository test rule, each test names the defect only it can catch.
Nothing here re-tests what the Pydantic declarations already enforce
(``source`` being a Literal, ``root`` being a str).
"""

from __future__ import annotations

import os

import pytest

from core.generated_library import (
    GENERATED_LIBRARY_ENV_VAR,
    GeneratedLibraryResolution,
    MalformedGeneratedLibraryOverride,
    capability_index_path,
    generated_library_provenance,
    generated_library_root,
    generated_losses_dir,
    generated_models_dir,
    resolve_generated_library,
)

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


class TestResolution:
    def test_default_is_home_siderius_generated_library(self, monkeypatch):
        """Defect caught: the default root drifting back into the repository
        checkout (or to any cwd-relative location). The whole migration rests
        on the unset-env default being a non-checkout, per-user path."""
        monkeypatch.delenv(GENERATED_LIBRARY_ENV_VAR, raising=False)
        res = resolve_generated_library()
        assert res.source == "default"
        # Hardcoded expectation (never read back from the module constants):
        assert res.root == os.path.join(os.path.expanduser("~"), ".siderius", "generated_library")
        assert os.path.isabs(res.root)

    def test_default_is_not_inside_the_repository_checkout(self, monkeypatch):
        """Defect caught: a future edit re-rooting the default under the
        checkout (e.g. back to ``agent_generated/``) — the regression that
        would silently restore checkout pollution for every env-less run."""
        monkeypatch.delenv(GENERATED_LIBRARY_ENV_VAR, raising=False)
        root = os.path.realpath(generated_library_root())
        assert not root.startswith(os.path.realpath(_REPO_ROOT) + os.sep)

    def test_env_override_wins_and_reports_env_source(self, monkeypatch, tmp_path):
        """Defect caught: the override being ignored — a collaborator who
        redirects the library (shared checkout, scratch quota) would silently
        keep writing into the default and cross-contaminate runs."""
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, str(tmp_path / "lib"))
        res = resolve_generated_library()
        assert res == GeneratedLibraryResolution(root=str(tmp_path / "lib"), source="env")

    def test_env_override_expands_user(self, monkeypatch):
        """Defect caught: ``~/scratch_lib`` refused (or taken literally as a
        relative dir named '~') instead of expanding — the documented
        calibration-store idiom is that ``~`` works in these variables."""
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, "~/scratch_lib")
        res = resolve_generated_library()
        assert res.root == os.path.join(os.path.expanduser("~"), "scratch_lib")
        assert res.source == "env"

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty_or_whitespace_env_treated_as_unset(self, monkeypatch, raw):
        """Defect caught: ``VAR= python …`` (the shell unset idiom shared by
        SIDERIUS_CALIBRATION_DIR / SIDERIUS_LOSS_DIRS / SIDERIUS_PLUGIN_DIRS)
        either crashing or resolving to a relative-'' cwd root."""
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, raw)
        res = resolve_generated_library()
        assert res.source == "default"

    def test_relative_override_refused_loudly(self, monkeypatch):
        """Defect caught: a relative override silently anchored to the cwd.
        Launched from the checkout, ``SIDERIUS_GENERATED_LIBRARY_DIR=agent_generated``
        would write generated artifacts back INTO the checkout — the exact
        pollution the module removes. Fails when the refusal is replaced by
        ``os.path.abspath`` coercion."""
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, "agent_generated")
        with pytest.raises(MalformedGeneratedLibraryOverride, match="relative"):
            resolve_generated_library()

    def test_explicit_environ_mapping_beats_ambient(self, monkeypatch, tmp_path):
        """Defect caught: the ``environ=`` parameter silently falling through
        to ``os.environ`` — a caller resolving against a transported child
        environment would record the parent's root as the child's."""
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, str(tmp_path / "ambient"))
        res = resolve_generated_library(
            environ={GENERATED_LIBRARY_ENV_VAR: str(tmp_path / "explicit")}
        )
        assert res.root == str(tmp_path / "explicit")


class TestDerivedPaths:
    def test_all_derived_paths_share_one_root(self, monkeypatch, tmp_path):
        """Defect caught: the derived helpers resolving against DIFFERENT
        roots (one reading env, another the default) — the one-authority
        property the operator boundary requires. Layout is pinned to mirror
        the legacy checkout layout (models/ · losses/ · _capability_index.json)
        so every consumer keeps its shape."""
        lib = tmp_path / "lib"
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, str(lib))
        assert generated_models_dir() == str(lib / "models")
        assert generated_losses_dir() == str(lib / "losses")
        assert capability_index_path() == str(lib / "_capability_index.json")

    def test_resolution_does_not_create_the_directory(self, monkeypatch, tmp_path):
        """Defect caught: resolution acquiring a mkdir side effect. Readers
        rely on 'missing dir == empty library' (preload returns [] on a fresh
        host) and writers mkdir on demand; an eager mkdir would also make a
        read-only probe mutate the filesystem."""
        lib = tmp_path / "never_created"
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, str(lib))
        resolve_generated_library()
        generated_models_dir()
        assert not lib.exists()


class TestProvenance:
    def test_provenance_is_flat_json_native_root_and_source(self, monkeypatch, tmp_path):
        """Defect caught: the lock's ``generated_library`` field recording a
        shape an auditor needs code to interpret, or omitting which layer
        resolved the root (env vs default) — the R-11-6 representation rule
        the ``execution_calibration`` precedent sets."""
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, str(tmp_path / "lib"))
        prov = generated_library_provenance()
        assert prov == {"root": str(tmp_path / "lib"), "source": "env"}
        monkeypatch.delenv(GENERATED_LIBRARY_ENV_VAR)
        assert generated_library_provenance()["source"] == "default"


class TestRunInvariantsProvenance:
    """Matrix B — the lock RECORDS the resolved library, and only records it."""

    @staticmethod
    def _build(tmp_path):
        from core.run_invariants import build_run_invariants

        inv, _ = build_run_invariants(
            resolved_data_scope=[4, 5, 6],
            health_gate_enabled=False,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path),
        )
        return inv

    def test_builder_stamps_the_ambient_resolution(self, monkeypatch, tmp_path):
        """Defect caught: the field existing on the model while NOTHING
        stamps it — every lock would then record nothing and the migration
        would have no durable provenance (the declared purpose of the
        field). Stamped at the ONE shared builder, like execution_calibration."""
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, str(tmp_path / "lib"))
        inv = self._build(tmp_path / "ws")
        assert inv.generated_library == {"root": str(tmp_path / "lib"), "source": "env"}

    def test_omitted_from_serialized_lock_when_none(self, tmp_path):
        """Defect caught: a legacy-shaped lock gaining `"generated_library":
        null` — the established byte-stability rule (P1 §5.9 lineage) says a
        pre-feature lock file must stay byte-identical rather than gain a
        null for a concept it predates."""
        import json

        from core.run_invariants import RunInvariants, write_run_invariants

        inv = RunInvariants(
            resolved_data_scope=[0],
            health_gate_enabled=False,
            health_config_sha256=None,
            runtime_estimator_identity="e",
            runtime_policy_identity="p",
        )
        path = write_run_invariants(str(tmp_path / "ws"), inv)
        payload = json.loads(open(path, encoding="utf-8").read())
        assert "generated_library" not in payload

    def test_provenance_never_compared_on_resume(self, monkeypatch, tmp_path):
        """Defect caught: the field migrating into _CANONICAL — a workspace
        resumed on a host whose library lives elsewhere would then refuse,
        which is exactly what R-11-6 forbids for host-layout provenance
        (same science, different host layout)."""
        from core.run_invariants import validate_run_invariants

        ws = tmp_path / "ws"
        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, str(tmp_path / "lib_a"))
        inv_a = self._build(ws)
        from core.run_invariants import write_run_invariants

        write_run_invariants(str(ws), inv_a)

        monkeypatch.setenv(GENERATED_LIBRARY_ENV_VAR, str(tmp_path / "lib_b"))
        inv_b = self._build(ws)
        assert inv_b.generated_library != inv_a.generated_library
        # Must NOT raise: provenance is recorded, never equality-enforced.
        validate_run_invariants(str(ws), inv_b)
