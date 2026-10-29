"""Explicit graph declarations over the existing synthetic candidate fixture."""

import json
import re
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


# Pinned on base 14d03254 (before skip semantics): sha256 of the receipt's trace,
# status, validation flag and output index, with the workspace and native record
# digests (which embed tmp paths) masked. New enum values must not move these bytes.
UNROUTED_TRACE_SHA256 = {
    "accepted": "3b0b62a412e76632c6a9ad1929afa94d24df5a271a35d6e70fba3764af1ac36e",
    "rejected": "cbab7a78fe3a41f46a643bafddce480def9db486500874fde8334353f4fd2da6",
    "failed": "77752ff7436e08173a39c3e2d82ffa09f5780538d97f4d014ad846a23ffba105",
}


def trace_projection(receipt) -> str:
    """The pinned projection, with tmp workspace and record digests masked."""
    payload = receipt.model_dump_json(
        include={"status", "validation_passed", "graph_trace", "native_output_paths"}
    ).replace(receipt.workspace, "<ws>")
    return re.sub(r'"record_sha256":"[0-9a-f]{64}"', '"record_sha256":"<sha>"', payload)


SELECTION_PROFILE = "native-proposal-fanout-selection/v1"
TRAINING_OWNED_SEED_FIELDS = (
    "trial_time_budget_minutes",
    "formal_time_budget_minutes",
    "workflow_parameter_rules",
    "sampling_seed",
    "is_trial",
    "allowed_output_types",
    "baseline_isolation",
    "data_scope",
    "trial_portion",
    "train_portion",
    "enable_structured_health_feedback",
    "vram_budget_gb",
    "hardware_context",
    "constraint_context",
)


def selection_request(request, branches=2, *, bindings=None, node_order=None):
    """S1: fanout branches -> first-admissible adaptor ``pick`` -> one tuner ``train``.

    ``bindings`` is the adaptor's declared validator order (default ``check0..``);
    ``node_order`` permutes node declaration (and so execution) order.
    """
    request = fanout_request(request, branches)
    raw = request.preview.model_dump(mode="json")
    definition = raw["document"]["definition"]
    project = Path(request.preview.project_root)
    validators = bindings or [f"check{index}" for index in range(branches)]
    definition["externals"].append(
        {"id": "settings", "contract": "native-training.settings", "location": "training.json"}
    )
    definition["nodes"].append(
        {
            "id": "train",
            "capability": "tuning",
            "request": {
                "kind": "protocol",
                "protocol": "validated-candidate-to-tuning",
                "arguments": [
                    {"name": "proposal", "source": {"kind": "result", "node": "propose"}},
                    {"name": "validation", "source": {"kind": "adaptor", "adaptor": "pick"}},
                    {"name": "settings", "source": {"kind": "external", "binding": "settings"}},
                ],
            },
        }
    )
    if node_order is not None:
        nodes = {node["id"]: node for node in definition["nodes"]}
        definition["nodes"] = [nodes[key] for key in node_order]
    definition["adaptor_format"] = "siderius.adaptors/v1"
    definition["adaptors"] = [
        {
            "id": "pick",
            "inputs": [{"name": "checks", "contract": "validation.output", "cardinality": "many"}],
            "bindings": [
                {
                    "port": "checks",
                    "sources": [{"kind": "result", "node": node} for node in validators],
                }
            ],
            "combine": {"kind": "pass/v1"},
            "select": {"kind": "first-admissible/v1"},
            "distribute": {"kind": "single/v1"},
        }
    ]
    raw["execution_profile"] = SELECTION_PROFILE
    # Training owns these seed facts; the native admission fills them when omitted.
    seed = json.loads((project / "seed.json").read_bytes())
    for name in TRAINING_OWNED_SEED_FIELDS:
        seed.pop(name, None)
    (project / "seed.json").write_text(json.dumps(seed))
    config = json.loads((project / "llm.json").read_bytes())
    config["tune"] = {"planner_strategy": "native-timing-v1"}
    (project / "llm.json").write_text(json.dumps(config))
    (project / "training.json").write_text(
        json.dumps(
            {
                "launch": {
                    "healthgate_mode": "observe_only",
                    "result_authority": "diagnostic",
                    # Trial/formal: single_file (is_trial false) cannot train this task.
                    "is_trial": True,
                    "allowed_output_types": ["classifier"],
                    "trial_time_budget_minutes": 7,
                    "formal_time_budget_minutes": 19,
                    "max_rounds": 2,
                    "trial_max_epochs": 3,
                    "formal_max_epochs": 8,
                }
            }
        )
    )
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


# Captured on base 405d7aaf (before routed execution, B1-PR5) with the same
# projection as above, for the S1 selection profile keyed by the rejected review
# ordinals; routed execution must not move these bytes.
SELECTION_TRACE_SHA256 = {
    (): "73305fcceb04633985819dab674bba8c69cde2599b770f43048fae6b39a8070c",
    (0,): "8c16e12033ae0096cf656e88ce5569fe3af848e4f86fdc95a53fb5193baf619d",
    (0, 1): "cbd7eb79176f94d47bca69115d8bd041a57a9cc6b104ac725d5c22dbb3c6607f",
}

ROUTED_PROFILE = "native-routed-candidate/v1"
FALLBACK_ROUTE = {
    "id": "fallback",
    "source": {"kind": "result", "node": "check0"},
    "cases": [
        {
            "when": {"kind": "bool_is", "observable": "validation.passed", "value": False},
            "targets": ["build1"],
        }
    ],
}


def routed_request(request, *, routes=(FALLBACK_ROUTE,), profile=ROUTED_PROFILE):
    """B1-Q1(a) over S1: branch 1 (build1/check1) runs only when check0 rejects."""
    request = selection_request(request)
    raw = request.preview.model_dump(mode="json")
    raw["document"]["definition"]["routes"] = list(routes)
    raw["execution_profile"] = profile
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
