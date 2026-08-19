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

from execute_tools.health_checks._view_provider import HealthViewProvider
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


# ---------------------------------------------------------------------------
# View providers (Step 08b C3)
#
# A second flat ``id → implementation`` map, kept HERE rather than in its own
# module so there is one registration surface to reason about: a task plugin
# registers checks and providers through the same import, and the loader
# learns what it produced by diffing both maps. Providers are a separate
# namespace from checks because they answer a different question — a check
# decides health, a provider supplies what health is decided FROM — and
# collapsing them would let one shadow the other.
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: dict[str, HealthViewProvider] = {}


def register_view_provider(provider: HealthViewProvider) -> None:
    """Register a provider under its declared ``provider_id``. Duplicates raise.

    Same reasoning as :func:`register`: two providers claiming one id would
    silently resolve by import order, and the losing task's checks would be
    handed another task's data.
    """
    if provider.provider_id in _PROVIDER_REGISTRY:
        raise ValueError(
            f"Health view provider {provider.provider_id!r} is already "
            f"registered. Currently registered: {sorted(_PROVIDER_REGISTRY)}. "
            f"If this is a test that needs a clean registry, use the "
            f"``clean_registry`` fixture in tests/unit/execute_tools/"
            f"health_checks/conftest.py."
        )
    _PROVIDER_REGISTRY[provider.provider_id] = provider


def get_view_provider(provider_id: str) -> HealthViewProvider:
    """Look up a registered provider. Raises ``KeyError`` listing what exists."""
    if provider_id not in _PROVIDER_REGISTRY:
        raise KeyError(
            f"Health view provider {provider_id!r} not registered. "
            f"Available: {sorted(_PROVIDER_REGISTRY)}. A provider is "
            f"registered by a task's own plugin file, named in its task "
            f"health config."
        )
    return _PROVIDER_REGISTRY[provider_id]


def all_registered_view_providers() -> list[str]:
    """Sorted list of currently-registered provider ids."""
    return sorted(_PROVIDER_REGISTRY)
