"""Distribution ownership checks for the framework/experiment boundary."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_PACKAGE_ROOTS = {
    "agent*",
    "nodes*",
    "core*",
    "execute_tools*",
    "ml_models*",
    "tools*",
    "workflows*",
    "dashboard*",
}


def test_distribution_excludes_workspace_state_and_diagnostic_scripts():
    """Catch generated capability state or experiment diagnostics entering wheels.

    Setuptools namespace discovery can include ``agent_generated`` through the
    broad ``agent*`` pattern, and including ``scripts*`` packages historical
    task studies as framework modules. Neither defect is visible to imports or
    ordinary unit tests.
    """
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    discovery = config["tool"]["setuptools"]["packages"]["find"]

    assert "scripts*" not in discovery["include"]
    assert set(discovery["exclude"]) >= {"agent_generated*", "scripts*"}

    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    assert "prune agent_generated" in manifest
    assert "prune scripts" in manifest


def test_production_never_imports_the_legacy_generated_tree():
    """Catch installed-wheel imports of files excluded from the distribution.

    The legacy generated tree is runtime state, not an importable framework
    package.  If production imports it again, editable checkouts may pass while
    installed wheels fail because that tree is intentionally excluded.
    """
    production_roots = tuple(path.removesuffix("*") for path in EXPECTED_PACKAGE_ROOTS)
    offenders: list[str] = []
    for root_name in production_roots:
        root = REPO_ROOT / "src" / root_name
        sources = sorted(root.rglob("*.py"))
        assert root.is_dir() and sources, f"missing production scan subject: {root}"
        for source in sources:
            text = source.read_text(encoding="utf-8")
            if "from agent_generated" in text or "import agent_generated" in text:
                offenders.append(str(source.relative_to(REPO_ROOT)))
    assert offenders == []


def test_distribution_scan_detects_a_forbidden_import_and_a_missing_root(tmp_path, monkeypatch):
    """A retired-root scan or ignored forbidden import must turn this control red."""
    monkeypatch.setitem(globals(), "REPO_ROOT", tmp_path)
    for pattern in EXPECTED_PACKAGE_ROOTS:
        package = tmp_path / "src" / pattern.removesuffix("*")
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
    test_production_never_imports_the_legacy_generated_tree()
    plant = tmp_path / "src/core/rogue.py"
    plant.write_text("import agent_generated\n")
    with pytest.raises(AssertionError):
        test_production_never_imports_the_legacy_generated_tree()
    plant.unlink()
    (tmp_path / "src/core/__init__.py").unlink()
    (tmp_path / "src/core").rmdir()
    with pytest.raises(AssertionError, match="missing production scan subject"):
        test_production_never_imports_the_legacy_generated_tree()


def test_distribution_roots_are_an_explicit_framework_allowlist():
    """Catch a task, campaign, deployment, or workspace package entering the wheel.

    Exclusions alone are porous: a newly added top-level package is harmless
    until somebody broadens discovery to include it. Pinning the complete
    allowlist makes that packaging decision reviewable at the exact boundary.
    """
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    discovery = config["tool"]["setuptools"]["packages"]["find"]
    assert discovery["where"] == ["src"]
    assert set(discovery["include"]) == EXPECTED_PACKAGE_ROOTS
