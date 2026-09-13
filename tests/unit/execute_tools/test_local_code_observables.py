"""Optional callback errors stay optional; named package refusal is not a value."""

from __future__ import annotations

import pytest

from core.local_code import (
    CodePackageDeclaration,
    LocalCodeError,
    acquire_module,
    bind_code_package,
    capture_package,
)
from execute_tools.observables import (
    DeclaredDynamicObservable,
    DeclaredStaticObservable,
    DynamicObservableEpoch,
    compute_static_observations,
)


@pytest.mark.parametrize("phase", ["reset", "update", "value", "compute"])
@pytest.mark.parametrize("integrity", [True, False])
def test_callback_refusal_is_not_recorded_as_optional_diagnostic(tmp_path, phase, integrity):
    source = tmp_path / "callback.py"
    body = "from .undeclared import value" if integrity else "raise ValueError('ordinary callback')"
    source.write_text(
        "from execute_tools.observables import DynamicObservable, StaticObservable\n"
        f"def fail():\n {body}\n"
        "class Dynamic(DynamicObservable):\n"
        " def reset(self): return fail()\n"
        " def update(self, output, target): return fail()\n"
        " def value(self): return fail()\n"
        "class Static(StaticObservable):\n"
        " def compute(self, model): return fail()\n"
    )
    package = capture_package(CodePackageDeclaration(root=".", files=("callback.py",)), tmp_path)
    with bind_code_package(package), acquire_module(source) as module:
        epoch = DynamicObservableEpoch((DeclaredDynamicObservable("callback", module.Dynamic()),))
        calls = {
            "reset": epoch.start_epoch,
            "update": lambda: epoch.observe(None, None),
            "value": epoch.finish_epoch,
            "compute": lambda: compute_static_observations(
                (DeclaredStaticObservable("callback", module.Static()),), None
            ),
        }
        if integrity:
            with pytest.raises(LocalCodeError, match="undeclared relative import"):
                calls[phase]()
            assert epoch.failures == {}
        else:
            result = calls[phase]()
            failures = result[1] if phase == "compute" else epoch.failures
            assert "ordinary callback" in failures["callback"]
