"""Shared fixtures for the health-check test suite."""

from __future__ import annotations

import pytest

from execute_tools.health_checks import registry
from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.output_diversity import OutputDiversityCheck
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY


@pytest.fixture
def clean_registry():
    """Snapshot the process-wide registries, clear them, restore after.

    Every test that mutates a registry (register a new check or view
    provider, unregister an existing one) must depend on this fixture so
    state does not leak across tests. See
    ``docs/design/pluggable_health_checks.md`` §11 open question 5
    (registration model).

    Covers the view-provider registry too (Step 08b C3): a leaked provider is
    worse than a leaked check, because it would silently satisfy another
    test's capability binding and make a fail-closed test pass.
    """
    snapshot = dict(_REGISTRY)
    provider_snapshot = dict(_PROVIDER_REGISTRY)
    _REGISTRY.clear()
    _PROVIDER_REGISTRY.clear()
    try:
        yield _REGISTRY
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(snapshot)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(provider_snapshot)


@pytest.fixture
def preserved_registry():
    """Snapshot and restore the registries WITHOUT clearing them.

    For tests that register something extra while still needing the
    built-ins present — since Step 08b C5, composing the legacy default task
    config resolves its roster against the registry, so a cleared registry
    makes state A fail closed for a reason the test is not about.
    ``clean_registry`` remains correct for tests that must start empty.
    """
    snapshot = dict(_REGISTRY)
    provider_snapshot = dict(_PROVIDER_REGISTRY)
    try:
        yield _REGISTRY
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(snapshot)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(provider_snapshot)


@pytest.fixture
def rebootstrapped_registry(clean_registry):
    """Registry cleared then re-populated with the two built-in checks."""
    registry.register(OutputDiversityCheck())
    registry.register(AmplitudeCollapseCheck())
    return _REGISTRY
