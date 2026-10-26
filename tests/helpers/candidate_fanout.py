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


def families_request(request, families=2):
    """Independent seeds and one branch per family; validators declared before producers."""
    request = fanout_request(request, families)
    raw = request.preview.model_dump(mode="json")
    definition = raw["document"]["definition"]
    project = Path(request.preview.project_root)
    workspace = Path(definition["task"]["workspace"])
    seed = json.loads((project / "seed.json").read_text())
    # The native debug dump exists only on its explicit pipeline route.
    seed["reasoning_pipeline"] = {
        "stages": [
            {
                "name": "comparison",
                "system_prompt_key": "COMPARATIVE_ANALYSIS",
                "output_mode": "text",
            }
        ]
    }
    nodes = []
    definition["externals"] = definition["externals"][1:]
    for index in range(families):
        proposal = f"propose{index}"
        binding = f"seed{index}"
        path = project / f"{binding}.json"
        path.write_text(
            json.dumps(
                {
                    **seed,
                    "debug_dump_proposing_prompt_path": str(
                        workspace / "candidate_run" / "debug" / proposal / "prompt.md"
                    ),
                }
            )
        )
        definition["externals"].append(
            {"id": binding, "contract": "proposal.input", "location": path.name}
        )
        implementation, validation = definition["nodes"][1 + 2 * index : 3 + 2 * index]
        for node in (implementation, validation):
            for arg in node["request"]["arguments"]:
                if arg["source"].get("node") == "propose":
                    arg["source"]["node"] = proposal
        nodes.extend(
            (
                validation,
                implementation,
                {
                    "id": proposal,
                    "capability": "proposal",
                    "request": {"kind": "external", "binding": binding},
                },
            )
        )
    # Interleave families as well as reversing predecessor declaration order.
    if families == 2:
        nodes = [nodes[index] for index in (0, 4, 2, 3, 1, 5)]
    definition["nodes"] = nodes
    raw["execution_profile"] = "native-proposal-families/v1"
    preview = WorkflowPreviewRequest.model_validate_json(json.dumps(raw))
    observed = preview_workflow(preview)
    return request.model_copy(
        update={
            "preview": preview,
            "files": observed.files,
            "declaration_digest": preview.document.definition.declaration_digest(),
            "selected_constructor_routes": observed.selected_constructor_routes,
        }
    )
