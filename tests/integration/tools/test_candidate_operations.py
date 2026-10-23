"""Real detached process topology; explicit fixtures replace only the native workload."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_operations.conftest import admitted
from tests.unit.tools.candidate_prepare.conftest import selection
from tools.candidate_operations import read_operation, submit_operation
from tools.candidate_operations.models import OperationFailure
from tools.candidate_operations.process import environment
from tools.candidate_operations.read import releasable


@pytest.fixture
def topology(admitted, tmp_path):
    config, submission, _ = admitted
    config_path = tmp_path / "store.json"
    request_path = tmp_path / "submission.json"
    config_path.write_text(config.model_dump_json())
    request_path.write_text(submission.model_dump_json())
    worker = tmp_path / "fixture_worker.py"
    worker.write_text("""import os, sys, time
from pathlib import Path
from uuid import uuid4
from tools.candidate_operations import child
from tools.candidate_operations.submit import capture_inputs
from tools.candidate_prepare.models import PreparationControl, CandidatePreparationReceipt
from tools.candidate_prepare.launch import publish

def prepare(request):
    root = Path(request.output_dir).parent
    with (root / 'calls').open('a') as stream:
        stream.write('called\\n')
    assert 'UNRELATED_SENTINEL' not in os.environ
    assert 'OPENAI_API_KEY' not in os.environ
    time.sleep(1.0)
    control = Path(request.output_dir) / 'preparation'
    control.mkdir(parents=True)
    from tools.candidate_operations import PrepareOperation
    sources = capture_inputs(PrepareOperation(request_id=uuid4(), request=request))
    saved = PreparationControl(preparation_id=uuid4(), request=request, sources=sources)
    publish(control / 'request.json', saved)
    receipt = CandidatePreparationReceipt(preparation_id=saved.preparation_id, status='prepared',
        output_dir=request.output_dir, request_path=str(control / 'request.json'),
        log_path=str(control / 'worker.log'), source_observations=sources)
    (control / 'worker.log').write_text('fixture completed\\n')
    publish(control / 'receipt.json', receipt)
    return receipt
child.prepare_candidate = prepare
if sys.argv[2] == 'no_completion':
    original = child.publish
    def publish_without_completion(path, value):
        if path.name == 'completion.json':
            os._exit(0)
        original(path, value)
    child.publish = publish_without_completion
raise SystemExit(child.execute(Path(sys.argv[1])))
""")
    submitter = tmp_path / "submitter.py"
    submitter.write_text("""import os, sys, time
from pathlib import Path
from tools.candidate_operations import submit_operation, OperationStoreConfig
from tools.candidate_operations.models import SUBMISSION
from tools.candidate_operations import process
original = process.subprocess.Popen
mode = sys.argv[4]
def spawn(argv, **kwargs):
    operation = 'tools.candidate_operations.child' in argv
    if operation:
        argv = [argv[0], sys.argv[3], argv[-1], mode]
    result = original(argv, **kwargs)
    if operation and mode == 'crash':
        os._exit(0)
    if operation and mode == 'hold':
        time.sleep(30)
    return result
process.subprocess.Popen = spawn
config = OperationStoreConfig.model_validate_json(Path(sys.argv[1]).read_bytes())
request = SUBMISSION.validate_json(Path(sys.argv[2]).read_bytes())
print(submit_operation(config, request, launch_environment=os.environ).model_dump_json())
""")
    return (
        config,
        submission,
        [sys.executable, str(submitter), str(config_path), str(request_path), str(worker)],
    )


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.03)
    raise AssertionError("bounded process checkpoint was not reached")


@pytest.mark.parametrize("mode", ["normal", "crash", "hold", "no_completion"])
def test_submitter_exit_and_crash_do_not_replay_or_kill_operation(topology, mode):
    """Real child session survives caller exit/TERM and receipt precedes completion."""
    config, submission, argv = topology
    env = {**environment((), {}), "UNRELATED_SENTINEL": "secret", "OPENAI_API_KEY": "secret"}
    caller = subprocess.Popen(
        [*argv, mode], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if mode == "hold":
        wait_for(
            lambda: (
                read_operation(config, submission.request_id).state == "active"
                if Path(config.state_root).exists()
                and (
                    Path(config.state_root)
                    / "operations"
                    / str(submission.request_id)
                    / "process.json"
                ).exists()
                else False
            )
        )
        caller.terminate()
    stdout, stderr = caller.communicate(timeout=5)
    assert caller.returncode == (-signal.SIGTERM if mode == "hold" else 0), stderr
    if mode == "normal":
        assert json.loads(stdout)["observation"] == "starting"
    wait_for(lambda: releasable(config, submission.request_id))
    result = read_operation(config, submission.request_id)
    assert result.state == "completed" and result.receipt.status == "prepared"
    assert submit_operation(config, submission, launch_environment={}).observation == "existing"
    assert (Path(submission.request.output_dir).parent / "calls").read_text() == "called\n"


def test_concurrent_submitters_dispatch_once_and_busy_rejects(topology):
    config, submission, argv = topology
    callers = [
        subprocess.Popen(
            [*argv, "normal"],
            env=environment((), {}),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    outputs = [caller.communicate(timeout=5) for caller in callers]
    assert all(caller.returncode == 0 for caller in callers), outputs
    assert sorted(json.loads(output[0])["observation"] for output in outputs) == [
        "existing",
        "starting",
    ]
    with pytest.raises(OperationFailure, match="unresolved"):
        submit_operation(
            config, submission.model_copy(update={"request_id": uuid4()}), launch_environment={}
        )
    wait_for(lambda: releasable(config, submission.request_id))
    assert (Path(submission.request.output_dir).parent / "calls").read_text() == "called\n"


def test_killed_operation_is_unknown_and_never_relaunched(topology):
    config, submission, argv = topology
    subprocess.run(
        [*argv, "normal"], env=environment((), {}), capture_output=True, timeout=5, check=True
    )
    marker = Path(config.state_root) / "operations" / str(submission.request_id) / "process.json"
    wait_for(marker.exists)
    identity = json.loads(marker.read_text())
    os.kill(identity["pid"], signal.SIGTERM)
    wait_for(lambda: read_operation(config, submission.request_id).process.status == "exited")
    assert read_operation(config, submission.request_id).state == "unknown"
    assert not releasable(config, submission.request_id)
    assert submit_operation(config, submission, launch_environment={}).observation == "existing"
