"""Real entry-guard and nested pool refusal; no handwritten child error reports."""

from __future__ import annotations

import subprocess
import sys

import pytest

from core.local_code import LocalCodeError, bind_code_package
from core.local_code.child import prepare_child
from core.local_code.failure import REFUSAL_EXIT
from core.subprocess_env import subprocess_env
from tests.unit.core.test_local_code_failure import package_and_env


def execute(invocation, tmp_path):
    return subprocess.run(
        invocation.argv,
        env=invocation.env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("case", ["early-pin", "ordinary-reserved-exit", "module"])
def test_actual_child_guard_refuses_before_import_and_preserves_ordinary_exit(
    tmp_path, monkeypatch, case
):
    package = package_and_env(tmp_path, monkeypatch)
    marker = tmp_path / "executed"
    target = tmp_path / "target.py"
    target.write_text(
        "import sys\nfrom pathlib import Path\n"
        "assert __name__ == '__main__'\nassert sys.argv[1] == 'target-arg'\n"
        "assert __spec__ is None\n"
        f"Path({str(marker)!r}).write_text('yes')\nraise SystemExit({REFUSAL_EXIT})\n"
    )
    command = [sys.executable, str(target), "target-arg"]
    if case == "module":
        source = tmp_path / "input.json"
        source.write_text('{"value":3}')
        command = [sys.executable, "-m", "json.tool", str(source), "--compact"]
    with bind_code_package(package):
        invocation = prepare_child(command, subprocess_env())
        if case == "early-pin":
            (tmp_path / "helper.py").write_text("raise AssertionError('changed source')\n")
        result = execute(invocation, tmp_path)
    if case == "early-pin":
        assert result.returncode == REFUSAL_EXIT, result.stderr
        with pytest.raises(LocalCodeError, match="digest mismatch"):
            invocation.check(result.returncode)
        assert not marker.exists()
    elif case == "ordinary-reserved-exit":
        assert result.returncode == 1 and "ordinary target exit 78" in result.stderr
        invocation.check(result.returncode)
        assert marker.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == '{"value":3}'
        invocation.check(result.returncode)


def test_nested_pool_bootstrap_reports_original_failure_to_framework_parent(tmp_path, monkeypatch):
    package = package_and_env(tmp_path, monkeypatch)
    target = tmp_path / "pool.py"
    target.write_text(
        "if __name__ == '__main__':\n"
        " from concurrent.futures import ProcessPoolExecutor\n"
        " from multiprocessing import get_context\n"
        " from pathlib import Path\nimport os\n"
        "if __name__ == '__main__':\n"
        " from core.local_code import bootstrap_code_package\n"
        f" Path({str(tmp_path / 'helper.py')!r}).write_text('VALUE = 9\\n')\n"
        " with ProcessPoolExecutor(max_workers=1, mp_context=get_context('spawn'),\n"
        "     initializer=bootstrap_code_package, initargs=(os.environ['SIDERIUS_TASK_CODE_MANIFEST'],\n"
        "     os.environ['SIDERIUS_TASK_CODE_SHA256'])) as pool:\n"
        "  pool.submit(int, '3').result(timeout=30)\n"
    )
    with bind_code_package(package):
        invocation = prepare_child([sys.executable, str(target)], subprocess_env())
        result = execute(invocation, tmp_path)
    assert result.returncode != 0
    with pytest.raises(LocalCodeError, match="digest mismatch") as raised:
        invocation.check(result.returncode)
    assert raised.value.report.launch_id == invocation.channel.launch_id
    assert raised.value.report.package_digest == package.identity.digest
