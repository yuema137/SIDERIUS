"""Real offline task observation and authenticated authoring fixture for browser tests."""

import json
import socket
import tempfile
from pathlib import Path

import pytest
import uvicorn

from tests.integration.tools.test_setup_composition_check import _external_hook_request
from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.workflows.reusable_fixture import reusable
from tools.candidate_console.app import create_app
from tools.setup_review.composition_check import check_task
from tools.workflow_authoring.models import Project
from workflows.definition import ReusableTaskReferences, TaskBinding, render_workflow_source


def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="siderius-task-versions-") as directory,
        pytest.MonkeyPatch.context() as patch,
    ):
        root = Path(directory)
        config = console_config.__wrapped__(selection.__wrapped__(root), root)
        setup = _external_hook_request(root, patch, "")
        observed = check_task(setup)
        assert observed.result.outcome == "passed", observed.result.failure
        facts = observed.result.task
        assert facts is not None
        pin = TaskBinding(
            package_id="synthetic-quickstart",
            revision="snapshot-one",
            semantic_fingerprint=facts.semantic_fingerprint,
            task_data_path_id=facts.task_data_path_id,
        )
        task = config.tasks[0].model_copy(
            update={
                "task_revision": pin,
                "task_manifest": observed.job.manifest,
                "llm_config_file": str(root / "agents.json"),
                "task_read_only": tuple(str(path) for path in setup.read_only),
            }
        )
        incompatible = task.model_copy(
            update={
                "task_id": "changed",
                "label": "Changed native identity",
                "task_revision": pin.model_copy(
                    update={"revision": "snapshot-two", "semantic_fingerprint": "b" * 64}
                ),
            }
        )
        document = reusable()
        document = document.model_copy(update={"execution_profile": "native-proposal-fanout/v1"})
        document = document.model_copy(
            update={
                "definition": document.definition.model_copy(
                    update={
                        "task": ReusableTaskReferences(
                            manifest=task.task_manifest, data_root=task.data_root
                        ),
                    }
                )
            }
        )
        source = root / "workflow.py"
        source.write_text(render_workflow_source(document))
        other = root / "other.py"
        other.write_text(source.read_text())
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
                "tasks": (task, incompatible),
                "editor_projects": tuple(
                    Project(
                        project_id=name,
                        project_root=root,
                        source_file=path,
                        recovery_directory=recovery,
                    )
                    for name, path in (("versioned", source), ("other", other))
                ),
            }
        )
        app = create_app(config)
        print(
            json.dumps(
                {
                    "origin": origin,
                    "token": Path(config.auth_token_file).read_text(),
                    "source": str(source),
                    "other": str(other),
                    "binding": pin.model_dump(mode="json"),
                }
            ),
            flush=True,
        )
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            proxy_headers=False,
            access_log=False,
            log_level="error",
        )


if __name__ == "__main__":
    main()
