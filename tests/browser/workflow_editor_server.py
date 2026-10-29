"""Offline real-API browser fixture; start with this checkout's frozen Python."""

import json
import os
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
    ManagedCandidateBinding,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    ReusableWorkflowDocument,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
    parse_workflow_source,
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


def interpretation_profile_source() -> str:
    """A real editable five-node source for the focused editor round-trip witness."""
    training_example = Path(__file__).resolve().parents[2] / (
        "examples/workflow_declarations/reusable_training.py"
    )
    document = parse_workflow_source(training_example.read_text())
    assert isinstance(document, ReusableWorkflowDocument)
    raw = document.model_dump(mode="json")
    raw["execution_profile"] = "native-interpretation-candidate/v1"
    raw["definition"]["loop"] = AuthoredLoop(
        final_iteration=2,
        feedback=LoopFeedback(
            source=ResultSource(node="fit"),
            target="interpret",
            protocol="tuning-to-interpretation",
            history="native-research/v1",
        ),
    ).model_dump(mode="json")
    raw["definition"]["externals"] = [
        item for item in raw["definition"]["externals"] if item["id"] != "initial"
    ]
    raw["definition"]["externals"].extend(
        item.model_dump(mode="json")
        for item in (
            ManagedCandidateBinding(id="interpret_input", contract="interpretation.input"),
            ManagedCandidateBinding(id="proposal_store", contract="storage"),
            ManagedCandidateBinding(id="data_dir", contract="optional.text"),
            ManagedCandidateBinding(id="task_ref", contract="optional.task-composition-ref"),
            ManagedCandidateBinding(id="advice", contract="optional.expert-advice"),
            ManagedCandidateBinding(id="expert_context", contract="optional.expert-context"),
            ManagedCandidateBinding(id="constraints", contract="optional.constraint-context"),
            ManagedCandidateBinding(id="rules", contract="optional.parameter-rules"),
        )
    )
    candidate_nodes = [
        NodeInstance.model_validate_json(json.dumps(node))
        for node in raw["definition"]["nodes"]
        if node["id"] != "hypothesis"
    ]
    validation = NodeInstance(
        id="check",
        capability="validation",
        request=ProtocolRequest(
            protocol="proposed-implementation-to-validation",
            arguments=(
                ArgumentBinding(name="proposal", source=ResultSource(node="hypothesis")),
                ArgumentBinding(name="implementation", source=ResultSource(node="build")),
                ArgumentBinding(name="storage", source=ExternalSource(binding="check_store")),
            ),
        ),
    )
    candidate_nodes = [validation if node.id == "check" else node for node in candidate_nodes]
    raw["definition"]["nodes"] = [
        NodeInstance(
            id="interpret",
            capability="interpretation",
            request=ExternalRequest(binding="interpret_input"),
        ).model_dump(mode="json"),
        NodeInstance(
            id="hypothesis",
            capability="proposal",
            request=ProtocolRequest(
                protocol="interpretation-to-proposal",
                arguments=(
                    ArgumentBinding(name="output", source=ResultSource(node="interpret")),
                    ArgumentBinding(
                        name="storage", source=ExternalSource(binding="proposal_store")
                    ),
                    ArgumentBinding(name="data_dir", source=ExternalSource(binding="data_dir")),
                    ArgumentBinding(
                        name="task_composition_ref", source=ExternalSource(binding="task_ref")
                    ),
                    ArgumentBinding(name="human_advice", source=ExternalSource(binding="advice")),
                    ArgumentBinding(
                        name="expert_context", source=ExternalSource(binding="expert_context")
                    ),
                    ArgumentBinding(
                        name="constraint_context", source=ExternalSource(binding="constraints")
                    ),
                    ArgumentBinding(
                        name="workflow_parameter_rules", source=ExternalSource(binding="rules")
                    ),
                ),
            ),
        ).model_dump(mode="json"),
        *(node.model_dump(mode="json") for node in candidate_nodes),
    ]
    # Complete, disjoint saved layout. The example's partial set (build at x=120)
    # plus interpret at x=-80 overlapped by 15 px and left two cards on fallback
    # placement off to the right (UX walkthrough 2026-10-27).
    raw["positions"] = [{"node": node, "x": x, "y": y} for node, x, y in FIVE_NODE_POSITIONS]
    validated = ReusableWorkflowDocument.model_validate_json(json.dumps(raw))
    return render_workflow_source(validated)


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
        interpretation_source = root / "reusable_interpretation.py"
        interpretation_source.write_text(interpretation_profile_source())
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
                # A witness may mark configured projects runnable (comma-separated ids);
                # by default none is, as before.
                "runnable_editor_projects": tuple(
                    item
                    for item in os.environ.get("EDITOR_RUNNABLE_PROJECTS", "").split(",")
                    if item
                ),
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
                    Project(
                        project_id="interpretation",
                        project_root=root,
                        source_file=interpretation_source,
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
                    "interpretation_source": str(interpretation_source),
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
