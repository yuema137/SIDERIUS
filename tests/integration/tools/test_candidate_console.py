"""Real native sandbox/CPU candidate and loopback server-exit survival; provider is fake."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from tests.integration.tools.test_candidate_operations import wait_for
from tests.integration.tools.test_candidate_operations_native import native_submitter
from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_prepare.conftest import selection
from tools.candidate_console import CandidateConsole, PreparedSelection
from tools.candidate_operations.read import releasable

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)


def test_native_http_flow_survives_console_exit(console_config, tmp_path):
    credentials = tmp_path / "credentials.json"
    credentials.write_text(
        '{"EXPLICIT_TEST_KEY":"bound-value","OPENAI_API_KEY":"offline-test-key"}'
    )
    credentials.chmod(0o600)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    task = console_config.tasks[0].model_copy(
        update={"candidate_environment_names": ("EXPLICIT_TEST_KEY", "OPENAI_API_KEY")}
    )
    config = console_config.model_copy(
        update={
            "tasks": (task,),
            "credential_file": str(credentials),
            "port": port,
            "browser_origin": f"http://127.0.0.1:{port}",
        }
    )
    prepare_id = uuid4()
    with client(config) as api:
        response = api.post(
            "/api/preparations",
            json={
                "operation_id": str(prepare_id),
                "task_id": task.task_id,
                "run_name": "offline-console",
            },
        )
        assert response.status_code == 202, response.text
    wait_for(lambda: releasable(config.operation_store, prepare_id), timeout=60)
    service = CandidateConsole(config)
    review = service.review(PreparedSelection(prepare_operation_id=prepare_id))
    assert service.status(prepare_id).native_status == "prepared"
    bundle = Path(task.preparation_root) / str(prepare_id)
    submitter = native_submitter(tmp_path, bundle)
    config_path = tmp_path / "console.json"
    config_path.write_text(config.model_dump_json())
    harness = tmp_path / "console_server.py"
    harness.write_text(
        submitter.read_text().replace(
            "runpy.run_module('tools.candidate_operations', run_name='__main__')",
            f"""import uvicorn
from tools.candidate_console.app import create_app
from tools.candidate_console.config import load_config
uvicorn.run(create_app(load_config({str(config_path)!r})), host='127.0.0.1', port={port}, access_log=False, proxy_headers=False)
""",
        )
    )
    headers = {
        "Authorization": "Bearer " + Path(config.auth_token_file).read_text(),
        "Origin": config.browser_origin,
    }
    log_path = tmp_path / "console-server.log"
    with log_path.open("w") as log:
        server = subprocess.Popen([sys.executable, str(harness)], stdout=log, stderr=log)
        try:

            def serving():
                try:
                    return (
                        httpx.get(
                            config.browser_origin + "/api/choices", headers=headers
                        ).status_code
                        == 200
                    )
                except httpx.ConnectError:
                    return False

            wait_for(serving, timeout=15)
            candidate_id = uuid4()
            response = httpx.post(
                config.browser_origin + "/api/candidates",
                headers=headers,
                json={
                    "candidate_operation_id": str(candidate_id),
                    "prepare_operation_id": str(prepare_id),
                    "expected_prepared_digest": review.prepared_digest,
                },
                timeout=15,
            )
            assert response.status_code == 202, response.text
        finally:
            server.terminate()
            server.wait(timeout=15)
    wait_for(lambda: releasable(config.operation_store, candidate_id), timeout=90)
    with client(config) as reopened:
        status = reopened.get(f"/api/operations/{candidate_id}").json()
        assert status["native_status"] == "accepted" and status["validation_passed"] is True, status
        log = reopened.get(f"/api/operations/{candidate_id}/log").json()
        assert "Proposal saved" in log["text"] and log["next_offset"] > 0
        # Review remains observational after the real workspace is populated.
        assert reopened.get(f"/api/preparations/{prepare_id}/review").status_code == 200
    workspace = Path(task.candidate_root) / str(prepare_id)
    assert (workspace / "candidate_run/receipt.json").is_file()
    assert "bound-value" not in log_path.read_text()
