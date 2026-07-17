"""Shared fixtures for the health-check test suite."""

from __future__ import annotations

import pytest

from execute_tools.health_checks import registry
from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.output_diversity import OutputDiversityCheck
from execute_tools.health_checks.registry import _REGISTRY


@pytest.fixture
def clean_registry():
    """Snapshot the process-wide registry, clear it for the test, restore after.

    Every test that mutates the registry (register a new check, unregister an
    existing one) must depend on this fixture so state does not leak across
    tests. See ``docs/design/pluggable_health_checks.md`` §11 open question 5
    (registration model).
    """
    snapshot = dict(_REGISTRY)
    _REGISTRY.clear()
    try:
        yield _REGISTRY
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(snapshot)


@pytest.fixture
def rebootstrapped_registry(clean_registry):
    """Registry cleared then re-populated with the two built-in checks."""
    registry.register(OutputDiversityCheck())
    registry.register(AmplitudeCollapseCheck())
    return _REGISTRY
