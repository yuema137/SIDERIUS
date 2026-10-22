"""Real sandbox/native chain with an offline provider-construction harness."""

import importlib
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

from tests.unit.tools.candidate_worker.conftest import prepared
from tests.unit.tools.candidate_worker.test_native import Provider
from tools.candidate_worker import launch_candidate
from tools.workspace_sandbox.runner import run

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)


@pytest.mark.parametrize("reject", [False, True])
def test_sandbox_native_candidate_records_and_read_only_source(prepared, monkeypatch, reject):
    """Real child imports, native nodes, generated CPU tests and terminal handoff.

    The harness changes only provider construction; no public fake execution
    flag, provider request, GPU, node substitute or subprocess-result substitute.
    """
    project = Path(prepared.preview.project_root)
    harness = project / "offline_provider_harness.py"
    harness.write_text(
        f"""import builtins, runpy, sys
from typing import ClassVar
{inspect.getsource(Provider)}
Provider.reject = {reject!r}
original = builtins.__import__
def offline_import(name, globals=None, locals=None, fromlist=(), level=0):
    result = original(name, globals, locals, fromlist, level)
    if name == "agent.llm_bridge":
        sys.modules[name].LLMBridge = Provider
    return result
builtins.__import__ = offline_import
sys.argv = ["tools.candidate_worker.child", sys.argv[1]]
runpy.run_module("tools.candidate_worker.child", run_name="__main__")
"""
    )
    before = {item.path: Path(item.path).read_bytes() for item in prepared.files}

    def supervised(profile, argv):
        return run(profile, [sys.executable, str(harness), argv[-1]])

    monkeypatch.setattr(importlib.import_module("tools.candidate_worker.launch"), "run", supervised)
    receipt = launch_candidate(prepared)
    log = Path(receipt.log_path).read_text() if Path(receipt.log_path).exists() else "no child log"
    assert receipt.status == ("rejected" if reject else "accepted"), (receipt.error, log)
    assert receipt.validation_passed is not reject
    assert all(Path(path).is_file() for path in receipt.native_output_paths)
    assert "Proposal saved" in log
    validation = json.loads(Path(receipt.native_output_paths[-1]).read_text())
    assert validation["tests_passed"] is True
    assert validation["instantiation_passed"] is True
    assert validation["gradient_check_passed"] is True
    assert "passed" in validation["test_output"]
    assert all(Path(path).read_bytes() == content for path, content in before.items())
    assert not (Path(receipt.workspace) / "generated_library/_capability_index.json").exists()
