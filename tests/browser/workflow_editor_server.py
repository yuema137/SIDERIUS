"""Offline real-API browser fixture; start with this checkout's frozen Python."""

import json
import socket
import tempfile
from pathlib import Path

import uvicorn

from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.test_workflow_authoring import SOURCE
from tests.unit.workflows.reusable_fixture import EXAMPLE
from tools.candidate_console.app import create_app
from tools.workflow_authoring.models import Project
from workflows.definition import (
    ArgumentBinding,
    AuthoredLoop,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    LoopFeedback,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
    render_workflow_source,
)


def _protocol(node: str, capability: str, protocol: str, **arguments: str) -> NodeInstance:
    """A node whose arguments name a result node or, with an ``@`` prefix, an external."""
    return NodeInstance(
        id=node,
        capability=capability,
        request=ProtocolRequest(
            protocol=protocol,
            arguments=tuple(
                ArgumentBinding(
                    name=name,
                    source=ExternalSource(binding=value[1:])
                    if value.startswith("@")
                    else ResultSource(node=value),
                )
                for name, value in arguments.items()
            ),
        ),
    )


# Complete saved layout; the browser witness proves the rendered cards are disjoint.
FIVE_NODE_POSITIONS = (
    ("interpret", 0.0, 0.0),
    ("hypothesis", 320.0, 0.0),
    ("build", 640.0, 0.0),
    ("check", 960.0, 0.0),
    ("fit", 1280.0, 0.0),
)
# A code-authored partial set, as in the reusable training example.
PARTIAL_POSITIONS = (("build", 120.0, -30.0), ("fit", 520.0, 20.0))


def five_node_source(
    positions: tuple[tuple[str, float, float], ...] = FIVE_NODE_POSITIONS,
) -> str:
    """Interpret -> propose -> implement -> validate -> train & tune, with authored feedback."""
    externals = (
        ("evidence", "interpretation.input"),
        ("proposal_store", "storage"),
        ("build_store", "storage"),
        ("check_store", "storage"),
        ("training", "native-training.settings"),
    )
    document = WorkflowDocument(
        definition=WorkflowDefinition(
            task=TaskReferences(manifest="task.yaml", data_root="data", workspace="workspace"),
            externals=tuple(
                ExternalBinding(id=name, contract=contract, location=f"{name}.json")
                for name, contract in externals
            ),
            nodes=(
                NodeInstance(
                    id="interpret",
                    capability="interpretation",
                    request=ExternalRequest(binding="evidence"),
                ),
                _protocol(
                    "hypothesis",
                    "proposal",
                    "interpretation-to-proposal",
                    output="interpret",
                    storage="@proposal_store",
                ),
                _protocol(
                    "build",
                    "implementation",
                    "proposal-to-implementation",
                    output="hypothesis",
                    storage="@build_store",
                ),
                _protocol(
                    "check",
                    "validation",
                    "implementation-to-validation",
                    output="build",
                    storage="@check_store",
                ),
                _protocol(
                    "fit",
                    "tuning",
                    "validated-candidate-to-tuning",
                    proposal="hypothesis",
                    validation="check",
                    settings="@training",
                ),
            ),
            loop=AuthoredLoop(
                final_iteration=2,
                feedback=LoopFeedback(
                    source=ResultSource(node="fit"),
                    target="interpret",
                    protocol="tuning-to-interpretation",
                    history="native-research/v1",
                ),
            ),
        ),
        positions=tuple(NodePosition(node=node, x=x, y=y) for node, x, y in positions),
    )
    return render_workflow_source(document)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="siderius-editor-browser-") as directory:
        root = Path(directory)
        config = console_config.__wrapped__(selection.__wrapped__(root), root)
        source = root / "workflow.py"
        source.write_text(
            SOURCE.replace(
                'location="old.json"),)',
                'location="old.json"),ExternalBinding(id="other", contract="proposal.input", location="other.json"),)',
            )
        )
        other_source = root / "other.py"
        other_source.write_text(SOURCE)
        reusable_source = root / "reusable.py"
        reusable_source.write_text(EXAMPLE.read_text())
        five_node = root / "five_node.py"
        five_node.write_text(five_node_source())
        five_node_partial = root / "five_node_partial.py"
        five_node_partial.write_text(five_node_source(PARTIAL_POSITIONS))
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
                    Project(
                        project_id="other",
                        project_root=root,
                        source_file=other_source,
                        recovery_directory=recovery,
                    ),
                    Project(
                        project_id="reusable",
                        project_root=root,
                        source_file=reusable_source,
                        recovery_directory=recovery,
                    ),
                    Project(
                        project_id="five_node",
                        project_root=root,
                        source_file=five_node,
                        recovery_directory=recovery,
                    ),
                    Project(
                        project_id="five_node_partial",
                        project_root=root,
                        source_file=five_node_partial,
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
                    "reusable_source": str(reusable_source),
                    "five_node_source": str(five_node),
                    "five_node_partial_source": str(five_node_partial),
                    "token": Path(config.auth_token_file).read_text(),
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
