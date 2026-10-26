"""One explicit native literature input connected to the existing candidate fixture."""

import json
from pathlib import Path

from tests.helpers.candidate_fanout import fanout_request
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow


def literature_request(request):
    request = fanout_request(request, 1)
    project = Path(request.preview.project_root)
    raw = request.preview.model_dump(mode="json")
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
                    / "graph_instances/review/iteration_001/attempt_001"
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
    (project / "review.json").write_text(json.dumps(review))
    config_path = project / "llm.json"
    config = json.loads(config_path.read_bytes())
    config["lit_review"] = {
        "main": {"provider": "openai", "model_id": "literature-test", "max_retries": 0},
        "search": {"provider": "openai", "model_id": "literature-test", "max_retries": 0},
    }
    config_path.write_text(json.dumps(config))
    definition["externals"].append(
        {"id": "review_input", "contract": "literature.input", "location": "review.json"}
    )
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
