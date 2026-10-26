"""The actual CLI and authenticated HTTP endpoint share native token observations."""

import json
import subprocess
import sys

from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_console.test_native_chain import native_config
from tests.unit.tools.candidate_operations.test_native_chain import chain
from tests.unit.tools.candidate_operations.test_native_resume import history, reserve
from tests.unit.tools.candidate_operations.test_native_tokens import native_usage, read
from tools.candidate_console import CandidateConsole
from tools.candidate_operations import read_operation


def test_native_token_cli_http_parity(native_usage, console_config, tmp_path):
    record, _, _ = native_usage
    store = tmp_path / "store.json"
    store.write_text(record.config.model_dump_json())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.candidate_operations",
            "tokens",
            "--store-config",
            str(store),
            "--operation-id",
            str(record.submission.request_id),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    cli = json.loads(result.stdout)
    response = client(native_config(console_config, record)).get(
        f"/api/operations/{record.submission.request_id}/tokens"
    )
    assert response.status_code == 200, response.text
    http, direct = response.json(), read(record).model_dump(mode="json")
    for value in (cli, http, direct):
        value.pop("observed_at")
    assert cli == http == direct


def test_linked_native_status_http_preserves_current_scientific_evidence(
    history, console_config, monkeypatch
):
    """A missing resume kind returns 422; projecting retained evidence hides current drift."""
    root, _, successor, _, _ = history
    monkeypatch.undo()  # Exercise actual current science observation, not fixture evidence.
    reserve(successor, adopt=True)
    config = native_config(console_config, root, choices=False)
    api = client(config)
    service = CandidateConsole(config)
    for record, kind in ((root, "native_chain"), (successor, "native_chain_resume")):
        operation_id = record.submission.request_id
        direct = read_operation(record.config, operation_id)
        response = api.get(f"/api/operations/{operation_id}")
        assert response.status_code == 200, response.text
        view = service.status(operation_id)
        http = response.json()
        http.pop("observed_at")
        assert http == view.model_dump(mode="json", exclude={"observed_at"})
        assert view.operation_id == operation_id and view.kind == kind
        assert view.state == direct.state
        assert view.native_chain == direct.native_chain
        assert view.native_chain.evidence.availability == "integrity_failure"
