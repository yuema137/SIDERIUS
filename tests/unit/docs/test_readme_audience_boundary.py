"""Keep public README pages human-facing.

README files are navigation surfaces.  This guard catches the specific
regression where one of the public landing pages describes itself as a
coding-agent instruction surface, without imposing a fixed heading or prose
template on legitimate technical documentation.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

PUBLIC_READMES = tuple(
    Path(path)
    for path in subprocess.check_output(
        ["git", "ls-files", "--", "*README*"], cwd=REPO_ROOT, text=True
    ).splitlines()
    if Path(path).name.lower().startswith("readme")
)

_AGENT_SURFACE_DECLARATION = re.compile(
    r"(?i)(?:audience|purpose|this\s+readme|this\s+page)[^\n]{0,100}"
    r"(?:coding\s+agent|automated\s+coding\s+tools|agent\s+instruction\s+surface|agent-facing)"
)


def _declares_agent_surface(text: str) -> bool:
    """Return whether prose declares the README itself to be agent-facing."""

    return _AGENT_SURFACE_DECLARATION.search(text) is not None


def test_public_readmes_do_not_declare_an_agent_instruction_surface() -> None:
    """A README remains a human landing page rather than an agent contract."""

    offending = [
        str(path)
        for path in PUBLIC_READMES
        if _declares_agent_surface((REPO_ROOT / path).read_text(encoding="utf-8"))
    ]
    assert not offending, (
        "public README(s) declare themselves a coding-agent surface; move the "
        "contract to a non-README document: " + ", ".join(sorted(offending))
    )


def test_boundary_pattern_is_specific_to_a_self_declaration() -> None:
    """Technical mentions of agents alone are valid README vocabulary."""

    assert not _declares_agent_surface(
        "The agent calls the deterministic execution engine through a typed API."
    )
    assert _declares_agent_surface("**Audience**: a coding agent about to modify this directory.")
