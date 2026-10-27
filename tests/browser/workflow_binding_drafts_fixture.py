"""Temporary authenticated project for the binding-draft browser witness."""

import json
import socket
import tempfile
from pathlib import Path

import uvicorn

from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.workflows.test_workflow_definition import definition
from tools.candidate_console.app import create_app
from tools.workflow_authoring.models import Project
from workflows.definition import (
    ArgumentBinding,
    ExternalBinding,
    ExternalSource,
    ProtocolRequest,
    WorkflowDefinition,
    WorkflowDocument,
)
from workflows.definition.source import render_workflow_source


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="siderius-binding-draft-browser-") as directory:
        root = Path(directory)
        config = console_config.__wrapped__(selection.__wrapped__(root), root)
        original = definition()
        validate = original.nodes[2]
        request = validate.request
        assert isinstance(request, ProtocolRequest)
        validate = validate.model_copy(update={"request": request.model_copy(update={"arguments": request.arguments + (
            ArgumentBinding(name="llm_provider", source=ExternalSource(binding="provider")),
        )})})
        graph = original.model_copy(update={
            "externals": original.externals + (ExternalBinding(id="provider", contract="llm-provider", location="provider.json"),),
            "nodes": (*original.nodes[:2], validate),
        })
        source = root / "workflow.py"
        source.write_text(render_workflow_source(WorkflowDocument(definition=graph)))
        recovery = root / "recovery"
        recovery.mkdir(mode=0o700)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        config = config.model_copy(update={
            "port": port,
            "browser_origin": origin,
            "editor_projects": (Project(project_id="example", project_root=root,
                                         source_file=source, recovery_directory=recovery),),
        })
        print(json.dumps({"origin": origin, "source": str(source),
                          "token": Path(config.auth_token_file).read_text()}), flush=True)
        uvicorn.run(create_app(config), host="127.0.0.1", port=port, proxy_headers=False,
                    log_level="error")


if __name__ == "__main__":
    main()
