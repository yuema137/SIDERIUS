"""Serve the real two-version C1 integration fixture without provider access."""

import json
import socket
import tempfile
from pathlib import Path

import pytest
import uvicorn

from tests.integration.tools.test_changed_task_candidate import changed_candidate
from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.tools.candidate_prepare.conftest import selection
from tools.candidate_console.app import create_app


def main():
    with (
        tempfile.TemporaryDirectory(prefix="changed-task-browser-") as directory,
        pytest.MonkeyPatch.context() as patch,
    ):
        root = Path(directory)
        author, targets, _ = changed_candidate.__wrapped__(root, patch, None)
        console = root / "console"
        console.mkdir()
        config = console_config.__wrapped__(selection.__wrapped__(console), console)
        tasks = tuple(
            config.tasks[0].model_copy(
                update={
                    "task_id": target.choice_id,
                    "label": f"Checked version {target.choice_id}",
                    "task_revision": target.binding,
                    "task_manifest": str(target.manifest),
                    "data_root": str(target.data_root),
                    "llm_config_file": str(target.llm_config_file),
                    "task_read_only": tuple(str(path) for path in target.read_only),
                }
            )
            for target in targets
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        config = config.model_copy(
            update={
                "tasks": tasks,
                "editor_projects": (author.project,),
                "port": port,
                "browser_origin": origin,
            }
        )
        print(
            json.dumps(
                {
                    "origin": origin,
                    "token": Path(config.auth_token_file).read_text(),
                    "source": str(author.project.source_file),
                    "binding": targets[1].binding.model_dump(mode="json"),
                    "plugin": str(targets[1].manifest.parent / "plugins/_quickstart_task.py"),
                }
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
