"""Pin packaging declarations to actual runtime readers, before artifact builds.

The manual installed-package witness owns build/install and child execution.
This guard localizes omitted package-data declarations: editable readers alone
would stay green if a distribution stopped including their adjacent assets.
"""

import fnmatch
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _required_assets() -> list[Path]:
    source = REPO / "src"
    groups = (
        [source / "agent/schemas/vocab_seed.json"],
        [p for p in (source / "agent/prompt_templates").rglob("*.md") if p.name != "README.md"],
        list((source / "agent/skills").glob("*/skill_config.json")),
        list((source / "ml_models").glob("*/description.md")),
        [p for p in (source / "nodes").rglob("*.md") if p.name != "README.md"],
        [source / "dashboard/static" / name for name in ("index.html", "app.js", "style.css")],
        [source / "tools/ci/weights.json"],
        list((source / "tools/claude_hooks/templates").glob("*.md")),
    )
    assert all(groups), "a runtime resource family disappeared before packaging"
    return [path.relative_to(source) for group in groups for path in group]


def _assert_declared(data: dict) -> None:
    for asset in _required_assets():
        assert (REPO / "src" / asset).is_file(), f"missing resource: {asset}"
        owner, *parts = asset.parts
        assert any(fnmatch.fnmatchcase("/".join(parts), p) for p in data.get(owner, [])), (
            f"runtime resource omitted from package-data: {asset}"
        )


def test_package_data_covers_runtime_readers():
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    _assert_declared(config["tool"]["setuptools"]["package-data"])


def test_removed_prompt_declaration_is_detected():
    """A packaging-only deletion must fail even while editable prompt reads work."""
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    data = config["tool"]["setuptools"]["package-data"]
    data["agent"] = [p for p in data["agent"] if "prompt_templates" not in p]
    with pytest.raises(AssertionError, match="omitted from package-data: agent/prompt_templates"):
        _assert_declared(data)
