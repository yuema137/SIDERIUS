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


def reusable_families(request):
    """Two proposal families, first with two branches, deliberately interleaved."""
    import copy

    request = reusable_fanout(request)
    source = Path(request.source_path)
    raw = parse_workflow_source(source.read_text()).model_dump(mode="json")
    raw["execution_profile"] = "native-proposal-families/v1"
    definition = raw["definition"]
    proposal = next(node for node in definition["nodes"] if node["capability"] == "proposal")
    definition["externals"].extend(
        [
            {"id": "alternate_seed", "contract": "proposal.input", "kind": "managed_candidate"},
            {"id": "slot_other", "contract": "storage", "kind": "managed_candidate"},
        ]
    )
    extras = []
    for node in definition["nodes"]:
        if node["id"] not in {"build_right", "check_right", proposal["id"]}:
            continue
        copied = copy.deepcopy(node)
        if copied["capability"] == "proposal":
            copied["id"] = "alternate"
            copied["request"]["binding"] = "alternate_seed"
        else:
            copied["id"] = copied["id"].replace("right", "other")
            for arg in copied["request"]["arguments"]:
                source_ref = arg["source"]
                if source_ref.get("node") == proposal["id"]:
                    source_ref["node"] = "alternate"
                elif "node" in source_ref:
                    source_ref["node"] = source_ref["node"].replace("right", "other")
                elif "binding" in source_ref:
                    source_ref["binding"] = "slot_other"
        extras.append(copied)
    definition["nodes"] = [extras[0], *definition["nodes"], *extras[1:]]
    document = ReusableWorkflowDocument.model_validate_json(json.dumps(raw))
    source.write_text("# reusable independent families\n" + render_workflow_source(document))
    return request.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )
