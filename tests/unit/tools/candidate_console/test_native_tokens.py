"""The actual CLI and authenticated HTTP endpoint share native token observations."""

import json
import subprocess
import sys

from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_console.test_native_chain import native_config
from tests.unit.tools.candidate_operations.test_native_chain import chain
from tests.unit.tools.candidate_operations.test_native_tokens import native_usage, read


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
