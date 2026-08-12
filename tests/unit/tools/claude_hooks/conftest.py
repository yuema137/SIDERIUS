"""Fixtures for the tracked continuity hooks.

Every test here runs against a THROWAWAY git repository in ``tmp_path``.
None of them may read or write the real SIDERIUS checkout: a hook test
that mutated the developer's own handoff would be worse than no test.

The fixture handoff is built FROM the tracked canonical template, which
is also exactly how a real PR starts — so the fixture cannot drift away
from the shipped contract without a test noticing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.claude_hooks import context_state as cs


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, check=False)
    assert out.returncode == 0, f"git {' '.join(args)} failed: {out.stderr}"
    return out.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repository with one commit."""
    root = tmp_path / "checkout"
    root.mkdir()
    # `git init -b <name>` needs git >= 2.28 and this repository's own CI
    # and dev boxes are not guaranteed to have it (locally: 2.25.1). The
    # default branch name is not load-bearing for any test here, so take
    # whatever the installed git provides rather than pinning it.
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Continuity Test")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    (root / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")
    return root


def fill(template: str) -> str:
    """Turn the canonical template into a COMPLETE, valid handoff.

    Derived from the shipped template rather than hand-written, so a new
    required field added to the template without a matching test value
    shows up as a failure instead of silently passing.
    """
    text = template.replace("TODO", "filled-in")
    text = text.replace("Design document synchronized: no", "Design document synchronized: yes")
    text = text.replace("Safe to compact: no", "Safe to compact: yes")
    return text.replace("PRIMARY DESIGN DOC: filled-in", "PRIMARY DESIGN DOC: DESIGN.md")


def set_field(text: str, field: str, value: str) -> str:
    """Overwrite a field's FIRST declaration."""
    return cs._field_re(field).sub(f"{field}: {value}", text, count=1)


@pytest.fixture
def handoff_factory(repo: Path):
    """Write a complete, current handoff into the fixture repo."""

    def _make(**overrides: str) -> str:
        # The design doc must exist before the handoff pins HEAD, because
        # the validator checks that the named design file is real.
        (repo / "DESIGN.md").write_text("# fixture design\n", encoding="utf-8")
        git(repo, "add", "DESIGN.md")
        git(repo, "commit", "-q", "-m", "design")

        text = fill(cs.template_path().read_text(encoding="utf-8"))
        text = set_field(text, cs.FIELD_HEAD, cs.head_sha(repo))
        text = set_field(text, cs.FIELD_FINGERPRINT, cs.working_tree_fingerprint(repo))
        # Overrides land LAST so a test asking for a stale value actually
        # gets one — applying them before the freshness pin silently
        # overwrote them, and every staleness test passed for the wrong
        # reason until the duplicate-field check exposed it.
        for key, value in overrides.items():
            text = set_field(text, getattr(cs, key), value)
        cs.atomic_write(cs.memory_path(repo), text)
        return text

    return _make
