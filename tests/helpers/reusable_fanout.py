"""Authored reusable fanout over existing managed preparation selections."""

import hashlib
import json
from pathlib import Path

from workflows.definition import (
    ReusableWorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)


def reusable_fanout(request):
    source = Path(request.source_path)
    raw = parse_workflow_source(source.read_text()).model_dump(mode="json")
    raw["execution_profile"] = "native-proposal-fanout/v1"
    definition = raw["definition"]
    proposal = next(node for node in definition["nodes"] if node["capability"] == "proposal")
    definition["externals"] = [
        {
            "id": proposal["request"]["binding"],
            "contract": "proposal.input",
            "kind": "managed_candidate",
        },
        *(
            {"id": "slot_" + side, "contract": "storage", "kind": "managed_candidate"}
            for side in ("left", "right")
        ),
    ]
    nodes = {proposal["id"]: proposal}
    for side in ("left", "right"):
        impl, valid = "build_" + side, "check_" + side
        for name, capability, protocol, refs in (
            (impl, "implementation", "proposal-to-implementation", {"output": proposal["id"]}),
            (
                valid,
                "validation",
                "proposed-implementation-to-validation",
                {"proposal": proposal["id"], "implementation": impl},
            ),
        ):
            nodes[name] = {
                "id": name,
                "capability": capability,
                "request": {
                    "kind": "protocol",
                    "protocol": protocol,
                    "arguments": [
                        *(
                            {"name": key, "source": {"kind": "result", "node": value}}
                            for key, value in refs.items()
                        ),
                        {
                            "name": "storage",
                            "source": {"kind": "external", "binding": "slot_" + side},
                        },
                    ],
                },
            }
    # Validators precede their implementations; their storage must follow the edge.
    definition["nodes"] = [
        nodes[key]
        for key in ("check_right", "build_left", proposal["id"], "check_left", "build_right")
    ]
    raw["positions"] = []
    document = ReusableWorkflowDocument.model_validate_json(json.dumps(raw))
    source.write_text("# reusable graph stays authored\n" + render_workflow_source(document))
    return request.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )
