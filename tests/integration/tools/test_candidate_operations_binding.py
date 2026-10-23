"""Real competing native claims across stores cannot inherit each other's receipts."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from tests.integration.tools.test_candidate_operations import wait_for
from tests.integration.tools.test_candidate_operations_native import native_submitter
from tests.unit.tools.candidate_operations.conftest import admitted
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import CandidateOperation, read_operation
from tools.candidate_operations.process import environment
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import load_record

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)


@pytest.mark.parametrize("kind", ["prepare", "candidate"])
@pytest.mark.parametrize("same_id", [False, True])
def test_competing_stores_bind_only_their_own_native_result(
    admitted, prepared, tmp_path, kind, same_id
):
    config, submission, _ = admitted
    if kind == "candidate":
        submission = CandidateOperation(
            request_id=uuid4(),
            request=prepared.model_copy(
                update={"environment_names": ("EXPLICIT_TEST_KEY", "OPENAI_API_KEY")}
            ),
        )
        harness = native_submitter(tmp_path, Path(prepared.preview.project_root))
        command = [sys.executable, str(harness)]
    else:
        command = [sys.executable, "-m", "tools.candidate_operations"]
    second = submission if same_id else submission.model_copy(update={"request_id": uuid4()})
    other = config.model_copy(update={"state_root": str(tmp_path / "second-state")})
    selections = [(config, submission), (other, second)]
    processes = []
    for index, (store, request) in enumerate(selections):
        config_file = tmp_path / f"store-{index}.json"
        config_file.write_text(store.model_dump_json())
        request_file = tmp_path / f"request-{index}.json"
        request_file.write_text(request.model_dump_json())
        processes.append(
            subprocess.Popen(
                [
                    *command,
                    "submit",
                    "--store-config",
                    str(config_file),
                    "--request",
                    str(request_file),
                ],
                env={
                    **environment((), {}),
                    "EXPLICIT_TEST_KEY": "bound-value",
                    "OPENAI_API_KEY": "offline-test-key",
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        )
    results = [process.communicate(timeout=10) for process in processes]
    assert all(process.returncode == 0 for process in processes), results
    assert all(json.loads(output)["observation"] == "starting" for output, _ in results)
    for store, request in selections:
        wait_for(
            lambda store=store, request=request: (
                read_operation(store, request.request_id).process.status == "exited"
            ),
            timeout=60,
        )
    snapshots = [read_operation(store, request.request_id) for store, request in selections]
    assert sorted(snapshot.state for snapshot in snapshots) == ["completed", "unknown"]
    assert (
        load_record(config, submission.request_id).native_id
        != load_record(other, second.request_id).native_id
    )
    for (store, request), snapshot in zip(selections, snapshots, strict=True):
        assert releasable(store, request.request_id) is (snapshot.state == "completed")
        if snapshot.state == "completed":
            assert snapshot.receipt.status == ("prepared" if kind == "prepare" else "accepted")
            record = load_record(store, request.request_id)
            native_id = (
                snapshot.receipt.preparation_id if kind == "prepare" else snapshot.receipt.run_id
            )
            assert native_id == (record.native_id if kind == "prepare" else record.native_id.hex)
