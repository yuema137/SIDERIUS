"""Pin source identity: an unrelated repository must never become the checkout."""

from pathlib import Path

import pytest

from core.layout import _checkout_for, require_checkout


def test_exact_declared_layout_survives_foreign_cwd_and_symlink(tmp_path, monkeypatch):
    prefix = "src"
    root = tmp_path / "checkout"
    source = root / prefix / "core/layout.py"
    source.parent.mkdir(parents=True)
    source.touch()
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nname="siderius"\n[tool.setuptools.packages.find]\nwhere=["{prefix}"]\n'
    )
    monkeypatch.chdir(tmp_path)
    link = tmp_path / "linked.py"
    link.symlink_to(source)
    assert _checkout_for(link) == root
    (root / "pyproject.toml").write_text('[project]\nname="foreign"\n')
    assert _checkout_for(source) is None


def test_missing_checkout_and_unrelated_ancestor_refuse(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="siderius"\n[tool.setuptools.packages.find]\nwhere=["src"]\n'
    )
    source = tmp_path / "environment/lib/site-packages/core/layout.py"
    source.parent.mkdir(parents=True)
    source.touch()
    assert _checkout_for(source) is None
    with pytest.raises(FileNotFoundError, match="source checkout"):
        require_checkout(_checkout_for(source))


def test_package_location_must_match_declared_source(tmp_path):
    source = tmp_path / "core/layout.py"
    source.parent.mkdir()
    source.touch()
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="siderius"\n[tool.setuptools.packages.find]\nwhere=["src"]\n'
    )
    assert _checkout_for(source) is None


def test_optional_checkout_absence_keeps_package_source_available(monkeypatch):
    """A wheel must retain built-in source while skipping legacy checkout reads."""
    from core.runtime_control import watchdog_profile
    from dashboard import settings
    from nodes import proposal_helpers

    monkeypatch.setattr(proposal_helpers, "_SIDERIUS_ROOT", None)
    monkeypatch.setattr(watchdog_profile, "SHIPPED_PROFILES_PATH", None)
    monkeypatch.setattr(settings, "DEFAULT_CONFIG_PATH", None)
    assert "class AE" in proposal_helpers.load_model_source("fcnet")
    assert watchdog_profile._load_shipped() == {}
    assert settings.load_settings().server.port == 8000
