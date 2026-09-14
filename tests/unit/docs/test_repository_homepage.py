"""Keep GitHub's repository homepage on the user-facing root README.

GitHub treats ``.github/README.md`` as a repository-level README when it is
present.  That silently shadows the actual homepage at ``README.md`` and can
show maintainer-only automation notes to new users instead of the framework
introduction and quickstart.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_repository_homepage_is_the_root_readme() -> None:
    """The root README exists and no .github README can shadow it."""

    homepage = REPO_ROOT / "README.md"
    shadow = REPO_ROOT / ".github" / "README.md"

    assert homepage.is_file()
    content = homepage.read_text(encoding="utf-8")
    assert "# SIDERIUS" in content
    assert "## Start without provider credentials or scientific data" in content
    assert "## The reference workflow" in content
    assert not shadow.exists(), "GitHub would use .github/README.md as the homepage"
