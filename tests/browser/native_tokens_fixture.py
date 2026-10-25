"""Serve actual token endpoints for linked native records; never execute science."""

import argparse
import json
import secrets
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn

from tests.unit.tools.candidate_operations.test_native_resume import history, reserve
from tests.unit.tools.candidate_operations.test_native_tokens import ledger
from tools.candidate_console import ConsoleConfig
from tools.candidate_console.app import create_app
from tools.candidate_operations import read_operation_tokens


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir()
    patch = pytest.MonkeyPatch()
    root, _, successor, _, _ = history.__wrapped__(directory, patch, SimpleNamespace(param=None))
    patch.undo()  # Public status and token reads both use real owners.
    workspace = Path(root.native_chain_admission.workspace)
    ledger(workspace, "fixture")
    reserve(successor, adopt=True)
    # Fixture retains valid control/identity anchors but no scientific outputs:
    # token monitoring must not claim scientific validity or depend on that view.
    expected = read_operation_tokens(root.config, root.submission.request_id)
    token = directory / "auth"
    token.write_text(secrets.token_urlsafe(32))
    token.chmod(0o600)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = ConsoleConfig(
        operation_store=root.config,
        port=port,
        browser_origin=f"http://127.0.0.1:{port}",
        auth_token_file=str(token),
    )
    (directory / "store.json").write_text(root.config.model_dump_json())
    print(
        json.dumps(
            dict(
                origin=config.browser_origin,
                token=token.read_text(),
                root_id=str(root.submission.request_id),
                successor_id=str(successor.submission.request_id),
                expected=expected.model_dump(mode="json"),
            )
        ),
        flush=True,
    )
    uvicorn.run(
        create_app(config),
        host="127.0.0.1",
        port=port,
        proxy_headers=False,
        access_log=False,
        log_level="error",
    )


if __name__ == "__main__":
    main()
