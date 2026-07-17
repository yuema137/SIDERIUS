# execute_tools/health_checks/registry.py
"""
Runtime registry of health-check skills.

Populated at import time via side effects in
``execute_tools/health_checks/__init__.py``. Tests that need registry
isolation call ``_REGISTRY.clear()`` via the pytest fixture in
``tests/unit/execute_tools/health_checks/conftest.py``.

See ``docs/design/pluggable_health_checks.md`` §7.
"""

from __future__ import annotations

from execute_tools.health_checks.protocol import HealthCheckSkill

_REGISTRY: dict[str, HealthCheckSkill] = {}


def register(check: HealthCheckSkill) -> None:
    """Register a check under its declared ``name``. Duplicate names raise.

    Raising on duplicates makes accidental double-registration audible:
    two modules importing each other in different orders could otherwise
    silently win a race.
    """
    if check.name in _REGISTRY:
        raise ValueError(
            f"Health check {check.name!r} is already registered. "
            f"Currently registered: {sorted(_REGISTRY)}. "
            f"If this is a test that needs a clean registry, use the "
            f"``clean_registry`` fixture in tests/unit/execute_tools/"
            f"health_checks/conftest.py."
        )
    _REGISTRY[check.name] = check


def get(name: str) -> HealthCheckSkill:
    """Look up a registered check by name.

    Raises ``KeyError`` with a helpful message listing available checks
    and pointing at the __init__.py registration site.
    """
    if name not in _REGISTRY:
        raise KeyError(
            f"Health check {name!r} not registered. "
            f"Available: {sorted(_REGISTRY)}. To add a new check, import "
            f"it in execute_tools/health_checks/__init__.py."
        )
    return _REGISTRY[name]


def all_registered() -> list[str]:
    """Sorted list of currently-registered check names."""
    return sorted(_REGISTRY)
