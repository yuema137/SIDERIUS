"""One source-owned native review feeding the existing reusable candidate."""

import hashlib
import json
from pathlib import Path

from tests.helpers.reusable_fanout import reusable_fanout
from workflows.definition import (
    ReusableWorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)


def reusable_literature(request, settings=None):
    request = reusable_fanout(request)
    config = Path(request.llm_config_file)
    values = json.loads(config.read_text())
    values["lit_review"] = {
        "main": {"provider": "openai", "model_id": "literature-test", "max_retries": 0},
        "search": {"provider": "openai", "model_id": "literature-test", "max_retries": 0},
    }
    config.write_text(json.dumps(values))
    path = Path(request.source_path)
    raw = parse_workflow_source(path.read_text()).model_dump(mode="json")
    raw["execution_profile"] = "native-literature-candidate/v1"
    definition = raw["definition"]
    definition["nodes"] = [
        node for node in definition["nodes"] if node["id"] not in {"build_right", "check_right"}
    ]
    definition["externals"] = [
        item for item in definition["externals"] if item["id"] != "slot_right"
    ]
    proposal = next(node for node in definition["nodes"] if node["capability"] == "proposal")
    seed = proposal["request"]["binding"]
    proposal["request"] = {
        "kind": "protocol",
        "protocol": "literature-to-proposal",
        "arguments": [
            {"name": "output", "source": {"kind": "result", "node": "review"}},
            {"name": "proposal_input", "source": {"kind": "external", "binding": seed}},
        ],
    }
    definition["externals"].append(
        {
            "id": "review_input",
            "contract": "literature.input",
            "kind": "managed_candidate",
            "literature_settings": {"dynamic_search": {"enabled": False}}
            if settings is None
            else settings,
        }
    )
    definition["nodes"].append(
        {
            "id": "review",
            "capability": "literature",
            "request": {"kind": "external", "binding": "review_input"},
        }
    )
    path.write_text(
        render_workflow_source(ReusableWorkflowDocument.model_validate_json(json.dumps(raw)))
    )
    return request.model_copy(
        update={"expected_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    )
