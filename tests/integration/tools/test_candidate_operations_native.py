"""Actual native sandbox checkpoint through detached CLI submission and fresh CLI reads."""

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from tests.integration.tools.test_candidate_operations import wait_for
from tests.unit.tools.candidate_operations.conftest import admitted
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_worker.test_native import Provider
from tools.candidate_operations import CandidateOperation, read_operation
from tools.candidate_operations.process import environment
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import load_record
from tools.candidate_worker import CandidateRunRequest

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)


def cli(config_path, *args, harness=None, env=None):
    argv = (
        [sys.executable, "-m", "tools.candidate_operations"]
        if harness is None
        else [sys.executable, str(harness)]
    )
    return subprocess.run(
        [*argv, *args, "--store-config", str(config_path)],
        env=env or environment((), {}),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )


@pytest.mark.parametrize("reject", [False, True])
def test_native_prepare_then_candidate_after_submitter_exit(admitted, tmp_path, reject):
    """Real native owners, sandbox, CPU validation, receipts and CLI; only provider is fake."""
    config, preparation, _ = admitted
    preparation = preparation.model_copy(
        update={
            "request": preparation.request.model_copy(
                update={"candidate_environment_names": ("EXPLICIT_TEST_KEY",)}
            )
        }
    )
    config_path = tmp_path / "store.json"
    config_path.write_text(config.model_dump_json())
    envelope = tmp_path / "prepare.json"
    envelope.write_text(preparation.model_dump_json())
    result = cli(config_path, "submit", "--request", str(envelope))
    assert json.loads(result.stdout)["observation"] == "starting"
    wait_for(lambda: releasable(config, preparation.request_id), timeout=45)
    status = json.loads(
        cli(config_path, "status", "--operation-id", str(preparation.request_id)).stdout
    )
    assert status["state"] == "completed" and status["receipt"]["status"] == "prepared", status
    request = CandidateRunRequest.model_validate_json(
        Path(status["receipt"]["candidate_request_path"]).read_bytes()
    )
    assert request.run_name == preparation.request.run_name
    assert not Path(preparation.request.candidate_workspace).exists()

    submitter = native_submitter(tmp_path, Path(preparation.request.output_dir), reject)
    candidate = CandidateOperation(request_id=uuid4(), request=request)
    envelope = tmp_path / "candidate.json"
    envelope.write_text(candidate.model_dump_json())
    source_env = {
        **environment((), {}),
        "EXPLICIT_TEST_KEY": "bound-value",
        "UNRELATED_SENTINEL": "do-not-pass",
    }
    result = cli(
        config_path, "submit", "--request", str(envelope), harness=submitter, env=source_env
    )
    assert json.loads(result.stdout)["observation"] == "starting"
    wait_for(lambda: releasable(config, candidate.request_id), timeout=60)
    status = json.loads(
        cli(config_path, "status", "--operation-id", str(candidate.request_id)).stdout
    )
    assert status["state"] == "completed", status
    assert status["receipt"]["status"] == ("rejected" if reject else "accepted"), status
    assert status["receipt"]["validation_passed"] is not reject
    receipt = read_operation(config, candidate.request_id).receipt
    validation = json.loads(Path(receipt.native_output_paths[-1]).read_text())
    assert (
        validation["tests_passed"]
        and validation["instantiation_passed"]
        and validation["gradient_check_passed"]
    )
    log = json.loads(
        cli(
            config_path,
            "log",
            "--operation-id",
            str(candidate.request_id),
            "--kind",
            "native",
            "--limit",
            "65536",
        ).stdout
    )
    assert "Proposal saved" in log["text"] and log["next_offset"] > 0
    for path in (Path(config.state_root) / "operations" / str(candidate.request_id)).iterdir():
        assert "bound-value" not in path.read_text() and "do-not-pass" not in path.read_text()

    for old in (preparation, candidate):
        old_nonce = load_record(config, old.request_id).native_id
        # Both a new UUID and the same caller UUID in another store need fresh native identity.
        for same_id in (False, True):
            other = config.model_copy(
                update={"state_root": str(tmp_path / f"stale-{old.kind}-{same_id}")}
            )
            stale = old if same_id else old.model_copy(update={"request_id": uuid4()})
            other_file = tmp_path / f"stale-store-{old.kind}-{same_id}.json"
            other_file.write_text(other.model_dump_json())
            stale_file = tmp_path / f"stale-request-{old.kind}-{same_id}.json"
            stale_file.write_text(stale.model_dump_json())
            cli(
                other_file,
                "submit",
                "--request",
                str(stale_file),
                harness=submitter if old.kind == "candidate" else None,
                env=source_env,
            )
            wait_for(
                lambda other=other, stale=stale: (
                    read_operation(other, stale.request_id).process.status == "exited"
                )
            )
            assert read_operation(other, stale.request_id).state == "unknown"
            assert not releasable(other, stale.request_id)
            assert load_record(other, stale.request_id).native_id != old_nonce
        original_file = tmp_path / f"same-{old.kind}.json"
        original_file.write_text(old.model_dump_json())
        assert (
            json.loads(cli(config_path, "submit", "--request", str(original_file)).stdout)[
                "observation"
            ]
            == "existing"
        )
        assert load_record(config, old.request_id).native_id == old_nonce


def test_native_timeout_is_preserved_by_detached_reader(admitted, tmp_path):
    config, preparation, _ = admitted
    preparation = preparation.model_copy(
        update={
            "request": preparation.request.model_copy(update={"preparation_timeout_seconds": 0.1})
        }
    )
    config_path = tmp_path / "store.json"
    config_path.write_text(config.model_dump_json())
    envelope = tmp_path / "prepare.json"
    envelope.write_text(preparation.model_dump_json())
    cli(config_path, "submit", "--request", str(envelope))
    wait_for(lambda: releasable(config, preparation.request_id), timeout=15)
    status = read_operation(config, preparation.request_id)
    assert status.state == "completed" and status.receipt.status == "timed_out"


def native_submitter(tmp_path, bundle, reject=False):
    # Test-only provider substitution inside the actual native sandbox. No production switch.
    provider = bundle / "offline_provider.py"
    provider.write_text(f"""import builtins, os, runpy, sys
from typing import ClassVar
{inspect.getsource(Provider)}
Provider.reject = {reject!r}
assert os.environ['EXPLICIT_TEST_KEY'] == 'bound-value'
assert 'UNRELATED_SENTINEL' not in os.environ
original = builtins.__import__
def offline(name, globals=None, locals=None, fromlist=(), level=0):
    result = original(name, globals, locals, fromlist, level)
    if name == 'agent.llm_bridge':
        sys.modules[name].LLMBridge = Provider
    return result
builtins.__import__ = offline
sys.argv = ['tools.candidate_worker.child', sys.argv[1]]
runpy.run_module('tools.candidate_worker.child', run_name='__main__')
""")
    operation = tmp_path / "native_operation.py"
    operation.write_text(f"""import importlib, os, sys
from pathlib import Path
from tools.candidate_operations.child import execute
from tools.workspace_sandbox.runner import run
assert os.environ['EXPLICIT_TEST_KEY'] == 'bound-value'
assert 'UNRELATED_SENTINEL' not in os.environ
def supervised(profile, argv):
    return run(profile, [sys.executable, {str(provider)!r}, argv[-1]])
importlib.import_module('tools.candidate_worker.launch').run = supervised
raise SystemExit(execute(Path(sys.argv[1])))
""")
    submitter = tmp_path / "native_submitter.py"
    submitter.write_text(f"""import runpy
from tools.candidate_operations import process
original = process.subprocess.Popen
def spawn(argv, **kwargs):
    if 'tools.candidate_operations.child' in argv:
        argv = [argv[0], {str(operation)!r}, argv[-1]]
    return original(argv, **kwargs)
process.subprocess.Popen = spawn
runpy.run_module('tools.candidate_operations', run_name='__main__')
""")
    return submitter
