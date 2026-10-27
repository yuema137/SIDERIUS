"""Task-bound authored project for the binding-draft task-selection witness."""

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
from workflows.definition import (
    ArgumentBinding,
    ExternalBinding,
    ExternalSource,
    ProtocolRequest,
    parse_workflow_source,
    render_workflow_source,
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="siderius-binding-draft-task-browser-") as directory:
        root = Path(directory)
        task_root = root / "task-data"
        task_root.mkdir()
        with pytest.MonkeyPatch.context() as monkeypatch:
            author, targets, _ = changed_candidate.__wrapped__(task_root, monkeypatch, None)
        source_path = author.project.source_file
        document = parse_workflow_source(source_path.read_text())
        definition = document.definition
        check = next(item for item in definition.nodes if item.id == "check")
        request = check.request
        assert isinstance(request, ProtocolRequest)
        check = check.model_copy(
            update={
                "request": request.model_copy(
                    update={
                        "arguments": (
                            *request.arguments,
                            ArgumentBinding(
                                name="llm_provider", source=ExternalSource(binding="provider")
                            ),
                        ),
                    }
                )
            }
        )
        definition = definition.model_copy(
            update={
                "externals": (
                    *definition.externals,
                    ExternalBinding(
                        id="provider", contract="llm-provider", location="provider.json"
                    ),
                ),
                "nodes": tuple(check if item.id == "check" else item for item in definition.nodes),
            }
        )
        document = document.model_copy(update={"definition": definition})
        source_path.write_text(render_workflow_source(document))

        console_root = root / "console"
        console_root.mkdir()
        config = console_config.__wrapped__(selection.__wrapped__(console_root), console_root)
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
        project = author.project.model_copy(update={"project_id": "bound"})
        recovery = project.recovery_directory
        recovery.mkdir(mode=0o700, parents=True, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        config = config.model_copy(
            update={
                "tasks": tasks,
                "port": port,
                "browser_origin": origin,
                "editor_projects": (project,),
            }
        )
        print(
            json.dumps(
                {
                    "origin": origin,
                    "source": str(source_path),
                    "token": Path(config.auth_token_file).read_text(),
                    "saved_binding": targets[0].binding.model_dump(mode="json"),
                    "choice_id": targets[0].choice_id,
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
