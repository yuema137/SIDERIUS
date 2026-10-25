"""Explicit graph declarations over the existing synthetic candidate fixture."""

import json
from pathlib import Path

from tools.workflow_preview import preview_workflow
from tools.workflow_preview.models import WorkflowPreviewRequest
from workflows.definition import WorkflowDocument


def fanout_request(request, branches=2):
    raw = request.preview.document.model_dump(mode="json")
    definition = raw["definition"]
    definition["nodes"] = definition["nodes"][:1]
    definition["externals"] = definition["externals"][:1]
    project = Path(request.preview.project_root)
    workspace = Path(definition["task"]["workspace"])
    for index in range(branches):
        impl, valid, storage = f"build{index}", f"check{index}", f"slot{index}"
        path = project / f"{storage}.json"
        path.write_text(
            json.dumps(
                {
                    "backend": "local",
                    "local": {
                        "workspace": str(
                            workspace
                            / request.run_name
                            / "graph_instances"
                            / impl
                            / "iteration_001/attempt_001/impl_001"
                        ),
                        "run_name": request.run_name,
                    },
                }
            )
        )
        definition["externals"].append(
            {"id": storage, "contract": "storage", "location": path.name}
        )
        for name, capability, protocol, refs in (
            (impl, "implementation", "proposal-to-implementation", {"output": "propose"}),
            (
                valid,
                "validation",
                "proposed-implementation-to-validation",
                {"proposal": "propose", "implementation": impl},
            ),
        ):
            definition["nodes"].append(
                {
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
                            {"name": "storage", "source": {"kind": "external", "binding": storage}},
                        ],
                    },
                }
            )
    preview = WorkflowPreviewRequest.model_validate_json(
        json.dumps(
            {
                **request.preview.model_dump(mode="json"),
                "document": WorkflowDocument.model_validate_json(json.dumps(raw)).model_dump(
                    mode="json"
                ),
                "execution_profile": "native-proposal-fanout/v1",
            }
        )
    )
    observed = preview_workflow(preview)
    return request.model_copy(
        update={
            "preview": preview,
            "files": observed.files,
            "declaration_digest": preview.document.definition.declaration_digest(),
            "selected_constructor_routes": observed.selected_constructor_routes,
        }
    )
