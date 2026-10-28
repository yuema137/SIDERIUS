"""Temporary authenticated project with an author-commented source for the node palette witness."""

import json
import socket
import tempfile
from pathlib import Path

import uvicorn

from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.test_workflow_node_edits import commented_canonical
from tools.candidate_console.app import create_app
from tools.workflow_authoring.models import Project


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="siderius-node-palette-browser-") as directory:
        root = Path(directory)
        config = console_config.__wrapped__(selection.__wrapped__(root), root)
        source = root / "workflow.py"
        source.write_text(commented_canonical())
        recovery = root / "recovery"
        recovery.mkdir(mode=0o700)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        config = config.model_copy(
            update={
                "port": port,
                "browser_origin": origin,
                "editor_projects": (
                    Project(
                        project_id="example",
                        project_root=root,
                        source_file=source,
                        recovery_directory=recovery,
                    ),
                ),
            }
        )
        print(
            json.dumps(
                {
                    "origin": origin,
                    "source": str(source),
                    "token": Path(config.auth_token_file).read_text(),
                }
            ),
            flush=True,
        )
        uvicorn.run(
            create_app(config), host="127.0.0.1", port=port, proxy_headers=False, log_level="error"
        )


if __name__ == "__main__":
    main()
