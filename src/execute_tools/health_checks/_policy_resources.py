"""Filesystem resources adjacent to the installed Health package.

Location lookup is inert; only a selected default opens the required asset.
Ordinary source/editable and unpacked wheel installations share this owner.
"""

from pathlib import Path
from typing import Any

import yaml

DEFAULT_POLICY_LABEL = "execute_tools/health_checks/resources/health_checks.yaml"


def default_policy_path() -> str:
    """Locate the default without requiring an optional source checkout."""
    return str(Path(__file__).resolve().parent / "resources" / "health_checks.yaml")


def read_default_policy() -> Any:
    """Read the required distribution asset; never rescue from another path."""
    with open(default_policy_path(), encoding="utf-8") as handle:
        return yaml.safe_load(handle)
