"""Fresh read-only console app configured for one external recorded candidate."""

import argparse
import hashlib
import json
import secrets
import shutil
import socket
from pathlib import Path

import uvicorn

from tools.candidate_console import ConsoleConfig, RecordedExampleChoice
from tools.candidate_console.app import create_app
from tools.candidate_operations import OperationStoreConfig


def tree_digest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    invalid_workspace = workspace.parent / f".recorded-view-fixture-{secrets.token_hex(8)}"
    shutil.copytree(workspace, invalid_workspace)
    request_path = invalid_workspace / "candidate_run" / "request.json"
    request = json.loads(request_path.read_text())
    request["preview"]["document"]["definition"]["task"]["workspace"] = str(invalid_workspace)
    request["declaration_digest"] = "0" * 64
    request_path.write_text(json.dumps(request))
    for filename in ("launch.json", "receipt.json"):
        receipt_path = invalid_workspace / "candidate_run" / filename
        receipt = json.loads(receipt_path.read_text())
        receipt["declaration_digest"] = "0" * 64
        receipt["workspace"] = str(invalid_workspace)
        receipt["ledger_path"] = str(invalid_workspace / "token_usage.jsonl")
        receipt["log_path"] = str(invalid_workspace / "candidate_run" / "worker.log")
        receipt["native_output_paths"] = [
            value.replace(str(workspace), str(invalid_workspace))
            for value in receipt.get("native_output_paths", [])
        ]
        receipt_path.write_text(json.dumps(receipt))
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    preparations, state = directory / "preparations", directory / "state"
    preparations.mkdir()
    state.mkdir()
    token = directory / "auth"
    token.write_text(secrets.token_urlsafe(32))
    token.chmod(0o600)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = ConsoleConfig(
        operation_store=OperationStoreConfig(
            state_root=str(state),
            preparation_roots=(str(preparations),),
            candidate_roots=(str(workspace.parent),),
        ),
        recorded_examples=(
            RecordedExampleChoice(
                example_id="tess-recorded",
                label="TESS candidate validation example",
                workspace=str(workspace),
                expected_run_id=args.run_id,
            ),
            RecordedExampleChoice(
                example_id="tess-recorded-b",
                label="TESS candidate validation example B",
                workspace=str(workspace),
                expected_run_id=args.run_id,
            ),
            RecordedExampleChoice(
                example_id="tess-invalid-declaration",
                label="TESS mismatched declaration digest fixture",
                workspace=str(invalid_workspace),
                expected_run_id=args.run_id,
            ),
        ),
        port=port,
        browser_origin=f"http://127.0.0.1:{port}",
        auth_token_file=str(token),
    )
    before = tree_digest(workspace)
    print(
        json.dumps(
            {
                "origin": config.browser_origin,
                "token": token.read_text(),
                "example_id": "tess-recorded",
                "workspace": str(workspace),
                "before": before,
                "invalid_workspace": str(invalid_workspace),
                "invalid_before": tree_digest(invalid_workspace),
            }
        ),
        flush=True,
    )

    import tools.candidate_console.service as service_module

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only historical viewing must not launch or load credentials")

    service_module.credentials = forbidden
    service_module.submit_operation = forbidden
    try:
        uvicorn.run(
            create_app(config),
            host="127.0.0.1",
            port=port,
            proxy_headers=False,
            access_log=False,
            log_level="error",
        )
    finally:
        (directory / "after.json").write_text(
            json.dumps(
                {
                    "workspace": tree_digest(workspace),
                    "invalid_workspace": tree_digest(invalid_workspace),
                },
                sort_keys=True,
            )
        )
        shutil.rmtree(invalid_workspace)


if __name__ == "__main__":
    main()
