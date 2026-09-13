"""A wrapped provider refusal must not become scientific Health ERROR evidence."""

from __future__ import annotations

import pytest

from core.local_code import (
    CodePackageDeclaration,
    LocalCodeError,
    acquire_module,
    bind_code_package,
    capture_package,
)
from execute_tools.health_checks import _plugin_binding, runner
from execute_tools.health_checks.registry import register, register_view_provider
from execute_tools.health_checks.schemas import CheckVerdict
from tests.unit.execute_tools.health_checks.test_view_provider import (
    _config,
    _ctx,
    _gate,
    _SpyProvider,
    _ViewConsumingCheck,
)


@pytest.fixture(autouse=True)
def isolated_scope(clean_registry):
    _plugin_binding.reset_run_scope()
    yield
    _plugin_binding.reset_run_scope()


@pytest.mark.parametrize("integrity", [True, False])
def test_provider_failure_keeps_package_identity_but_ordinary_failure_is_health_error(
    tmp_path, monkeypatch, integrity
):
    source = tmp_path / "provider.py"
    source.write_text("def materialize(*args):\n from .undeclared import view\n return view\n")
    package = capture_package(CodePackageDeclaration(root=".", files=("provider.py",)), tmp_path)
    check = _ViewConsumingCheck()
    provider = _SpyProvider(raises=not integrity)
    with bind_code_package(package), acquire_module(source) as module:
        if integrity:
            monkeypatch.setattr(provider, "materialize", module.materialize)
        register_view_provider(provider)
        register(check)
        _plugin_binding.resolve_task_health_bindings(
            _config(
                providers=[{"provider_id": provider.provider_id}],
                roster=[{"gate_id": "g", "check": check.name, "disposition": "blocking"}],
            )
        )
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: _gate(check.name))
        if integrity:
            with pytest.raises(LocalCodeError, match="undeclared relative import"):
                runner.evaluate_gate("g", _ctx())
        else:
            result = runner.evaluate_gate("g", _ctx())
            assert result.check_results[0].verdict is CheckVerdict.ERROR
        assert check.received_views == []
