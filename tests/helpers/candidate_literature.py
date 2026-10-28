"""One explicit native literature input connected to the existing candidate fixture."""

import json
from pathlib import Path

from tests.helpers.candidate_fanout import families_request, fanout_request
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow


def literature_request(request):
    request = fanout_request(request, 1)
    project = Path(request.preview.project_root)
    raw = request.preview.model_dump(mode="json")
    definition = raw["document"]["definition"]
    _add_review(request, raw, "review", "review_input", "review.json")
    definition["nodes"][0]["request"] = {
        "kind": "protocol",
        "protocol": "literature-to-proposal",
        "arguments": [
            {"name": "output", "source": {"kind": "result", "node": "review"}},
            {"name": "proposal_input", "source": {"kind": "external", "binding": "seed"}},
        ],
    }
    # Deliberately declare the producer last: execution must follow typed edges.
    definition["nodes"].append(
        {
            "id": "review",
            "capability": "literature",
            "request": {"kind": "external", "binding": "review_input"},
        }
    )
    raw["execution_profile"] = "native-literature-candidate/v1"
    return _previewed(request, raw, project)


def _add_review(request, raw, node, binding, filename):
    """One managed review input external plus the selected literature LLM routes."""
    project = Path(request.preview.project_root)
    definition = raw["document"]["definition"]
    workspace = Path(definition["task"]["workspace"])
    seed = json.loads((project / "seed.json").read_bytes())
    review = {
        "interpretation_evidence": {"cold_start": True},
        "root_papers": [],
        "dynamic_search": {"enabled": False},
        "storage": {
            "backend": "local",
            "local": {
                "workspace": str(
                    workspace
                    / request.run_name
                    / f"graph_instances/{node}/iteration_001/attempt_001"
                ),
                "run_name": request.run_name,
            },
        },
        "run_name": request.run_name,
        "task_description": seed["task_description"],
        "llm_provider": "openai",
        "llm_model_id": "literature-test",
        "search_llm_provider": "openai",
        "search_llm_model_id": "literature-test",
        "llm_max_retries": 0,
    }
    (project / filename).write_text(json.dumps(review))
    config_path = project / "llm.json"
    config = json.loads(config_path.read_bytes())
    config["lit_review"] = {
        "main": {"provider": "openai", "model_id": "literature-test", "max_retries": 0},
        "search": {"provider": "openai", "model_id": "literature-test", "max_retries": 0},
    }
    config_path.write_text(json.dumps(config))
    definition["externals"].append(
        {"id": binding, "contract": "literature.input", "location": filename}
    )


def _previewed(request, raw, project):
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


def _review_nodes(raw, request, reviews):
    definition = raw["document"]["definition"]
    for node in reviews:
        _add_review(request, raw, node, f"{node}_input", f"{node}.json")
        definition["nodes"].append(
            {
                "id": node,
                "capability": "literature",
                "request": {"kind": "external", "binding": f"{node}_input"},
            }
        )


def literature_collection_request(request, reviews=("survey", "review"), bindings=None):
    """S2: reviews (declared, so executed, in ``reviews`` order) -> collect -> one proposal.

    ``bindings`` is the adaptor's declared review order (default ``reviews``).
    """
    request = fanout_request(request, 1)
    project = Path(request.preview.project_root)
    raw = request.preview.model_dump(mode="json")
    definition = raw["document"]["definition"]
    definition["nodes"][0]["request"] = {
        "kind": "protocol",
        "protocol": "literature-collection-to-proposal",
        "arguments": [
            {"name": "reviews", "source": {"kind": "adaptor", "adaptor": "gather"}},
            {"name": "proposal_input", "source": {"kind": "external", "binding": "seed"}},
        ],
    }
    _review_nodes(raw, request, reviews)
    definition["adaptor_format"] = "siderius.adaptors/v1"
    definition["adaptors"] = [
        {
            "id": "gather",
            "inputs": [{"name": "reviews", "contract": "literature.output", "cardinality": "many"}],
            "bindings": [
                {
                    "port": "reviews",
                    "sources": [{"kind": "result", "node": node} for node in (bindings or reviews)],
                }
            ],
            "combine": {"kind": "collect/v1"},
            "select": {"kind": "all/v1"},
            "distribute": {"kind": "single/v1"},
        }
    ]
    raw["execution_profile"] = "native-literature-collection/v1"
    return _previewed(request, raw, project)


RANKED_TOP = {
    "combine": {"kind": "field-rank/v1", "field": "confidence", "order": "descending"},
    "select": {"kind": "top-k/v1", "k": 3},
}


def literature_split_request(request, count=3, on_short="skip", strategy=RANKED_TOP):
    """S3: one review -> ``strategy`` + split-items(findings, count) -> one family per index."""
    request = families_request(request, count)
    project = Path(request.preview.project_root)
    raw = request.preview.model_dump(mode="json")
    definition = raw["document"]["definition"]
    for node in definition["nodes"]:
        if node["capability"] == "proposal":
            index = int(node["id"].removeprefix("propose"))
            node["request"] = {
                "kind": "protocol",
                "protocol": "literature-to-proposal",
                "arguments": [
                    {
                        "name": "output",
                        "source": {"kind": "adaptor", "adaptor": "split", "index": index},
                    },
                    {
                        "name": "proposal_input",
                        "source": {"kind": "external", "binding": node["request"]["binding"]},
                    },
                ],
            }
    _review_nodes(raw, request, ("review",))
    definition["adaptor_format"] = "siderius.adaptors/v1"
    definition["adaptors"] = [
        {
            "id": "split",
            "inputs": [{"name": "review", "contract": "literature.output", "cardinality": "one"}],
            "bindings": [{"port": "review", "sources": [{"kind": "result", "node": "review"}]}],
            **strategy,
            "distribute": {
                "kind": "split-items/v1",
                "field": "findings",
                "count": count,
                "on_short": on_short,
            },
        }
    ]
    raw["execution_profile"] = "native-literature-split/v1"
    return _previewed(request, raw, project)


def write_literature_provider(project):
    """Only SDK transport is fake; literature runs its real bridge and ledger."""
    import inspect

    from tests.unit.tools.candidate_worker.test_native import Provider

    # Keep the real literature bridge and writer; substitute only its SDK transport.
    # Other native nodes retain the existing offline provider fixture.
    (project / "offline_provider.py").write_text(f"""import builtins, json, runpy, sys
from types import SimpleNamespace
from typing import ClassVar
import agent.llm_bridge as bridge
{inspect.getsource(Provider)}
def complete(**kwargs):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{{"findings": []}}'), finish_reason='stop')], usage=SimpleNamespace(prompt_tokens=11,completion_tokens=7,total_tokens=18), model=kwargs['model'])
bridge.OpenAI = lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
original = builtins.__import__
def offline(name, globals=None, locals=None, fromlist=(), level=0):
    result = original(name, globals, locals, fromlist, level)
    if name in ('nodes.ml_model_proposal_agent.ml_model_proposal_agent', 'nodes.ml_model_implementor.ml_model_implementor', 'nodes.ml_code_validator_agent.ml_code_validator_agent'):
        sys.modules[name].LLMBridge = Provider
    return result
builtins.__import__ = offline
sys.argv = ['tools.candidate_worker.child', sys.argv[1]]
runpy.run_module('tools.candidate_worker.child', run_name='__main__')
""")
