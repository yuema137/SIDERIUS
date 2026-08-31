"""Distribution ownership checks for the framework/experiment boundary."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


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
