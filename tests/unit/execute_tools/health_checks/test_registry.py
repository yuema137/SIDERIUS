"""Registry semantics — register, get, all_registered, duplicate rejection."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from execute_tools.health_checks.registry import (
    _REGISTRY,
    all_registered,
    get,
    register,
)
from execute_tools.health_checks.schemas import HealthCheckContext, HealthCheckResult


class _FakeCheck:
    """Minimal check that satisfies the rev-6 Protocol for registry tests."""

    def __init__(self, name: str):
        # dynamic-attr assignment matches the class-level ClassVar contract
        # closely enough for registration; real checks use ClassVar.
        self.name = name

    name: ClassVar[str] = "fake"  # overwritten in __init__

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        return HealthCheckResult(check_name=self.name, passed=True)


class TestRegistry:
    def test_register_and_get_roundtrip(self, clean_registry):
        check = _FakeCheck("alpha")
        register(check)
        assert get("alpha") is check

    def test_duplicate_registration_raises(self, clean_registry):
        register(_FakeCheck("beta"))
        with pytest.raises(ValueError, match="already registered"):
            register(_FakeCheck("beta"))

    def test_get_missing_raises_with_helpful_message(self, clean_registry):
        register(_FakeCheck("gamma"))
        with pytest.raises(KeyError) as exc_info:
            get("does_not_exist")
        message = str(exc_info.value)
        # KeyError repr wraps the message in quotes; look for the substring.
        assert "does_not_exist" in message
        assert "gamma" in message  # lists what IS available

    def test_all_registered_returns_sorted_names(self, clean_registry):
        for name in ("delta", "alpha", "charlie"):
            register(_FakeCheck(name))
        assert all_registered() == ["alpha", "charlie", "delta"]

    def test_all_registered_empty_after_clear(self, clean_registry):
        assert all_registered() == []

    def test_registry_isolation_between_tests_via_fixture(self, clean_registry):
        register(_FakeCheck("leak_test"))
        assert "leak_test" in _REGISTRY
        # Fixture teardown restores the pre-test snapshot — next test does
        # not see this entry. Verified by the test suite running clean twice.
