"""Fresh read-only console app configured for one external recorded candidate."""

import argparse
import hashlib
import json
import secrets
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
        (directory / "after.json").write_text(json.dumps(tree_digest(workspace), sort_keys=True))


if __name__ == "__main__":
    main()
