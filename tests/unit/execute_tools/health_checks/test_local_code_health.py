"""Real modular Health registration/materialization and failed-import rollback."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from core.local_code import CodePackageDeclaration, bind_code_package, capture_package
from execute_tools.health_checks import _plugin_binding, registry
from execute_tools.health_checks.config import materialize_effective_config


@pytest.fixture(autouse=True)
def health_scope(preserved_registry):
    _plugin_binding.reset_run_scope()
    yield
    _plugin_binding.reset_run_scope()


def fixture_package(tmp_path: Path, *, fail: bool):
    (tmp_path / "helper.py").write_text(
        "from execute_tools.health_checks.schemas import CheckInputDeclaration, HealthCheckResult\n"
        "class Check:\n name = 'local_package_health'\n declaration = CheckInputDeclaration(consumes_view='synthetic')\n"
        " def run(self, ctx, config=None):\n  return HealthCheckResult(check_name=self.name, passed=True, reason='synthetic')\n"
    )
    (tmp_path / "entry.py").write_text(
        "from .helper import Check\nfrom execute_tools.health_checks import register\nregister(Check())\n"
        + ("raise RuntimeError('after registration')\n" if fail else "")
    )
    health = tmp_path / "health.yaml"
    health.write_text(
        yaml.safe_dump(
            {
                "plugins": [{"kind": "file", "ref": "entry.py"}],
                "roster": [
                    {
                        "gate_id": "package_check",
                        "check": "local_package_health",
                        "disposition": "blocking",
                    }
                ],
            }
        )
    )
    captured = capture_package(
        CodePackageDeclaration(root=".", files=("entry.py", "helper.py")), tmp_path
    )
    return captured, health


def test_real_modular_health_materialization_and_reload_keep_helper_pin(tmp_path):
    captured, health = fixture_package(tmp_path, fail=False)
    output = tmp_path / "output"
    with bind_code_package(captured):
        path, _ = materialize_effective_config(
            None, None, str(output), task_health_binding=str(health)
        )
        identity = yaml.safe_load(Path(path).read_text())["resolved_plugins"][0]["local_code"]
        assert identity["member"] == "entry.py"
        assert len(identity["package"]["members"]) == 2
        # Re-materializing effective provenance must not lose package markers.
        other_path, _ = materialize_effective_config(path, None, str(tmp_path / "reloaded"))
        # The omitted caller binding keeps its existing legacy_default marker;
        # provenance reload preserves identities, not the caller's old binding.
        assert (
            yaml.safe_load(Path(other_path).read_text())["task_health_binding"] == "legacy_default"
        )
        assert (
            yaml.safe_load(Path(other_path).read_text())["resolved_plugins"][0]["local_code"]
            == identity
        )


def test_failed_health_import_rolls_back_helper_and_registration(tmp_path):
    captured, health = fixture_package(tmp_path, fail=True)
    before = set(registry.all_registered())
    modules_before = set(sys.modules)
    with (
        bind_code_package(captured),
        pytest.raises(_plugin_binding.HealthPluginError, match="after registration"),
    ):
        materialize_effective_config(
            None, None, str(tmp_path / "failed"), task_health_binding=str(health)
        )
    assert set(registry.all_registered()) == before
    assert not {
        name for name in set(sys.modules) - modules_before if name.startswith("_siderius_task_")
    }
    repaired, health = fixture_package(tmp_path, fail=False)
    with bind_code_package(repaired):
        materialize_effective_config(
            None, None, str(tmp_path / "repaired"), task_health_binding=str(health)
        )
    assert "local_package_health" in registry.all_registered()
