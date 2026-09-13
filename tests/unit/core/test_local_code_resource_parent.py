"""Both live resource parents retain a real CPU-only child's named refusal."""

from __future__ import annotations

import sys

import pytest

from agent.skills.evaluate_vram_skill.isolated_probe import run_isolated_preflight
from core.local_code import LocalCodeError, bind_code_package
from core.runtime_control.gpu_measurement_runner import run_prephase_measurement
from tests.unit.agent.evaluate_vram_skill.test_isolated_preflight import _spec as isolated_spec
from tests.unit.core.test_gpu_measurement_runner import DEVICE, _Driver
from tests.unit.core.test_gpu_measurement_runner import _spec as measurement_spec
from tests.unit.core.test_local_code_failure import package_and_env


@pytest.mark.parametrize("parent", ["prephase", "isolated"])
def test_resource_parent_refuses_before_generic_missing_report_classification(
    tmp_path, monkeypatch, parent
):
    package = package_and_env(tmp_path, monkeypatch)
    target = tmp_path / "worker.py"
    target.write_text(
        "import importlib\nfrom core.local_code import acquire_module\n"
        f"with acquire_module({str(tmp_path / 'helper.py')!r}) as module:\n"
        " importlib.import_module('.undeclared', module.__package__)\n"
    )
    command = [sys.executable, str(target)]
    with (
        bind_code_package(package),
        pytest.raises(LocalCodeError, match="undeclared relative import") as raised,
    ):
        if parent == "prephase":
            run_prephase_measurement(
                measurement_spec(tmp_path),
                device=DEVICE,
                command=command,
                device_sampler=_Driver([0]),
                poll_seconds=0.01,
            )
        else:
            run_isolated_preflight(
                isolated_spec(tmp_path),
                command=command,
                deadline_seconds=20,
                poll_seconds=0.01,
            )
    assert raised.value.report.package_digest == package.identity.digest
    assert not (tmp_path / "result.json").exists()
