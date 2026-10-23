"""Actual offline reusable child mounts and existing resolved-v1 worker admission."""

import os
from pathlib import Path

import pytest

from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable
from tools.candidate_prepare import prepare_reusable_candidate
from tools.candidate_worker import CandidateRunRequest
from tools.candidate_worker.preflight import fresh_preview

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)


def test_real_reusable_offline_sandbox(reusable):
    """Exact capture-file mounts coexist with writable inputs; native graph feeds worker admission."""
    result = prepare_reusable_candidate(reusable)
    log = Path(result.envelope) / "inputs/preparation/worker.log"
    assert result.status == "prepared", (result.error, log.read_text() if log.exists() else "")
    request = CandidateRunRequest.model_validate_json(
        Path(result.candidate_request_path).read_bytes()
    )
    assert not Path(request.preview.document.definition.task.workspace).exists()
    fresh_preview(request)


def test_reusable_request_reaches_worker_with_mocked_provider(reusable, monkeypatch):
    """Pseudo effects: real worker transport with fake provider and CPU checks, no API/GPU."""
    import importlib
    import inspect
    import json
    import sys

    from tests.unit.tools.candidate_worker.test_native import Provider
    from tools.candidate_worker import launch_candidate
    from tools.workspace_sandbox.runner import run

    reusable = reusable.model_copy(update={"candidate_environment_names": ("OPENAI_API_KEY",)})
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-placeholder")
    result = prepare_reusable_candidate(reusable)
    assert result.status == "prepared", result.error
    request = CandidateRunRequest.model_validate_json(
        Path(result.candidate_request_path).read_bytes()
    )
    harness = Path(result.envelope) / "inputs/offline_provider_harness.py"
    harness.write_text(f"""import builtins, runpy, sys
from typing import ClassVar
{inspect.getsource(Provider)}
original = builtins.__import__
def offline_import(name, globals=None, locals=None, fromlist=(), level=0):
    result = original(name, globals, locals, fromlist, level)
    if name == 'agent.llm_bridge':
        sys.modules[name].LLMBridge = Provider
    return result
builtins.__import__ = offline_import
sys.argv = ['tools.candidate_worker.child', sys.argv[1]]
runpy.run_module('tools.candidate_worker.child', run_name='__main__')
""")

    def supervised(profile, argv):
        assert not profile.network and not profile.devices
        return run(profile, [sys.executable, str(harness), argv[-1]])

    monkeypatch.setattr(importlib.import_module("tools.candidate_worker.launch"), "run", supervised)
    receipt = launch_candidate(request)
    assert receipt.status == "accepted", (receipt.error, Path(receipt.log_path).read_text())
    assert receipt.node_ids == ("hypothesis", "build", "check")
    checked = json.loads(Path(receipt.native_output_paths[-1]).read_bytes())
    assert (
        checked["tests_passed"]
        and checked["instantiation_passed"]
        and checked["gradient_check_passed"]
    )
