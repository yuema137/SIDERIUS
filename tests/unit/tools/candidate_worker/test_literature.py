"""Native review edge, input authority and independently checked result transport."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers.candidate_literature import literature_request
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.graph_evidence import record_digest, verify_graph_trace

from .conftest import refresh
from .test_graph import initial
from .test_native import native_runner


@pytest.fixture
def literature_sdk(monkeypatch):
    """Real LLMBridge usage writer; only SDK transport is replaced."""
    calls = []
    findings = []

    def complete(**kwargs):
        calls.append(kwargs)
        body = (
            {"action": "done", "reasoning": "Fixture search is complete"}
            if kwargs["model"] == "search-test"
            else {"findings": findings}
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(body)), finish_reason="stop"
                )
            ],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
            model=kwargs["model"],
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    monkeypatch.setattr("agent.llm_bridge.OpenAI", lambda **kwargs: client)
    return calls, findings


def test_nonempty_native_review_reaches_real_proposer_and_ledger(
    prepared, native_runner, literature_sdk, monkeypatch
):
    """Deleting the typed projection loses the finding; late binding loses real usage rows."""
    from agent.skills.paper_resolver_skill import wrapper

    request = literature_request(prepared).model_copy(update={"network": True})
    project = Path(request.preview.project_root)
    path = project / "review.json"
    raw = json.loads(path.read_bytes())
    raw.update(
        root_papers=[{"source_type": "arxiv", "identifier": "1706.03762", "verbosity": 0}],
        dynamic_search={"enabled": True, "max_rounds": 1},
        search_llm_provider="openai",
        search_llm_model_id="search-test",
    )
    path.write_text(json.dumps(raw))
    config = json.loads((project / "llm.json").read_bytes())
    config["lit_review"]["search"]["model_id"] = "search-test"
    (project / "llm.json").write_text(json.dumps(config))
    prompts = []
    original_text = native_runner.generate_text

    def text(self, system, user, **kwargs):
        prompts.append(user)
        return original_text(self, system, user, **kwargs)

    monkeypatch.setattr(native_runner, "generate_text", text)
    calls, findings = literature_sdk
    findings.append(
        {
            "source_ref": "arxiv:1706.03762",
            "content_paper_id": "arxiv:1706.03762",
            "content": "Attention-based sequence modeling is a research lead; transfer to this synthetic classifier is unqualified.",
            "confidence": 0.3,
        }
    )
    urls = []

    # Identity/title/year checked against https://arxiv.org/abs/1706.03762.
    # Metadata-only fixture; this does not claim full-text or live retrieval.
    def get(url, **kwargs):
        urls.append(url)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "title": "Attention Is All You Need",
                "year": 2017,
                "externalIds": {"ArXiv": "1706.03762"},
            },
        )

    monkeypatch.setenv("S2_API_KEY", "")
    monkeypatch.setattr(wrapper, "_S2_CACHE", {})
    monkeypatch.setattr(wrapper.requests, "get", get)
    request = refresh(request)
    receipt = launch_candidate(request)
    assert receipt.status == "accepted", receipt.error
    assert len(urls) == 1 and "1706.03762" in urls[0]
    assert [item["model"] for item in calls] == ["search-test", "literature-test"]
    control = Path(receipt.workspace) / "candidate_run"
    seed = json.loads((control / "proposal_inputs/propose.json").read_bytes())
    assert seed["literature_review_evidence"]["findings"][0]["source_ref"] == "arxiv:1706.03762"
    assert seed["literature_review_evidence"]["retrieved_paper_ids"] == ["arxiv:1706.03762"]
    rows = [json.loads(line) for line in Path(receipt.ledger_path).read_text().splitlines()]
    assert [row["label"] for row in rows] == ["lit_review.search_decision", "lit_review.synthesis"]
    assert all(row["run_id"] == receipt.run_id and row["tokens"]["total"] == 18 for row in rows)
    assert any("Attention-based sequence modeling" in prompt for prompt in prompts)
    assert receipt.graph_trace.nodes[0].predecessors == ("review",)
    verify_graph_trace(request, initial(request), receipt)
    # Parent checks input/task and projection independently of output hashes.
    for diagnostic, field, value in (
        (control / "literature_inputs/review.json", "task_description", "forged task"),
        (control / "proposal_inputs/propose.json", "literature_review_evidence", None),
    ):
        original_bytes = diagnostic.read_bytes()
        modified = json.loads(original_bytes)
        modified[field] = value
        diagnostic.write_text(json.dumps(modified))
        with pytest.raises(ValueError, match=r"binding mismatch|declared literature edge"):
            verify_graph_trace(request, initial(request), receipt)
        diagnostic.write_bytes(original_bytes)
    # Native typed output is re-signed by the child but its run identity is wrong.
    review = next(node for node in receipt.graph_trace.nodes if node.node_id == "review")
    output_path = Path(review.record_path)
    output = json.loads(output_path.read_bytes())
    output["run_name"] = "forged"
    output_path.write_text(json.dumps(output))
    nodes = tuple(
        node.model_copy(update={"record_sha256": record_digest(str(output_path))})
        if node.node_id == "review"
        else node
        for node in receipt.graph_trace.nodes
    )
    forged = receipt.model_copy(
        update={"graph_trace": receipt.graph_trace.model_copy(update={"nodes": nodes})}
    )
    with pytest.raises(ValueError, match="run binding"):
        verify_graph_trace(request, initial(request), forged)


@pytest.mark.parametrize("defect", ["task", "route", "storage", "local", "network", "constraints"])
def test_review_admission_refuses_before_provider(prepared, native_runner, literature_sdk, defect):
    request = literature_request(prepared)
    path = Path(request.preview.project_root) / "review.json"
    raw = json.loads(path.read_bytes())
    if defect == "task":
        raw["task_description"] = "another task"
    elif defect == "route":
        raw["llm_model_id"] = "unreviewed"
    elif defect == "storage":
        raw["storage"]["local"]["workspace"] = str(path.parent)
    elif defect == "constraints":
        raw["constraint_context"] = {"known_sections": []}
    elif defect == "local":
        raw["root_papers"] = [{"source_type": "local", "identifier": "paper.txt"}]
    else:
        raw["dynamic_search"] = {"enabled": True}
    path.write_text(json.dumps(raw))
    receipt = launch_candidate(refresh(request))
    assert receipt.status == "failed"
    assert not literature_sdk[0] and not native_runner.calls
    assert not (Path(receipt.workspace) / "candidate_run/literature_inputs").exists()


def test_empty_review_is_valid_but_escaping_exception_blocks_proposal(
    prepared, native_runner, literature_sdk, monkeypatch
):
    """Native exceptions must not turn into a successful empty graph result."""
    from tools.candidate_worker import literature_phase

    request = literature_request(prepared)

    def fail(self, inputs):
        raise RuntimeError("uncertain native review failure")

    monkeypatch.setattr(literature_phase.MLLiteratureReviewAgent, "run", fail)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
    assert not native_runner.calls
    assert {item.node_id: item.state for item in receipt.graph_trace.nodes} == {
        "review": "failed",
        "propose": "blocked",
        "build0": "blocked",
        "check0": "blocked",
    }
    assert not receipt.native_output_paths
    verify_graph_trace(request, initial(request), receipt)


@pytest.mark.parametrize("collision", ["input", "cache", "record"])
def test_managed_literature_collision_refuses_before_any_call(
    prepared, native_runner, literature_sdk, monkeypatch, collision
):
    from tools.candidate_worker import graph
    from tools.candidate_worker.layout import (
        graph_instance_dir,
        literature_cache_dir,
        literature_input_path,
    )

    request = literature_request(prepared)
    original = graph.materialize_fanout

    def materialize(request, workspace, *args):
        path = {
            "input": literature_input_path(workspace, "review"),
            "cache": literature_cache_dir(workspace, request.run_name, "review"),
            "record": graph_instance_dir(workspace, request.run_name, "review")
            / f"ml_literature_review_{request.run_name}.json",
        }[collision]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale")
        return original(request, workspace, *args)

    monkeypatch.setattr(graph, "materialize_fanout", materialize)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
    assert not native_runner.calls and not literature_sdk[0]


@pytest.mark.parametrize(
    "defect", ["old_profile", "extra_branch", "external_result", "missing_file"]
)
def test_explicit_shape_and_captured_review_are_required(prepared, defect):
    from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow

    request = literature_request(prepared)
    raw = request.preview.model_dump(mode="json")
    if defect == "old_profile":
        raw["execution_profile"] = "native-proposal-fanout/v1"
    elif defect == "extra_branch":
        raw["document"]["definition"]["nodes"].append(
            {
                "id": "second",
                "capability": "proposal",
                "request": {"kind": "external", "binding": "seed"},
            }
        )
    elif defect == "external_result":
        raw["document"]["definition"]["externals"].append(
            {"id": "output", "contract": "literature.output", "location": "review.json"}
        )
        raw["document"]["definition"]["nodes"][0]["request"]["arguments"][0]["source"] = {
            "kind": "external",
            "binding": "output",
        }
    else:
        Path(request.preview.project_root, "review.json").unlink()
    with pytest.raises((ValueError, OSError)):
        preview_workflow(WorkflowPreviewRequest.model_validate_json(json.dumps(raw)))
    assert not Path(raw["document"]["definition"]["task"]["workspace"]).exists()


def test_native_review_iterations_keep_lazy_usage_and_cache_separate(
    prepared, literature_sdk, monkeypatch
):
    """The lazy native bridge and root cache must follow the selected iteration."""
    from agent.schemas.literature_review import LiteratureReviewInput
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from tools.candidate_worker import literature_phase
    from tools.candidate_worker.invocation import invocation_from_storage

    request = literature_request(prepared)
    receipt = initial(request)
    workspace = Path(receipt.workspace)
    raw = json.loads((Path(request.preview.project_root) / "review.json").read_bytes())
    caches = []
    original = literature_phase.MLLiteratureReviewAgent.__init__

    def construct(self, **kwargs):
        caches.append(kwargs["root_cache_dir"])
        original(self, **kwargs)

    monkeypatch.setattr(literature_phase.MLLiteratureReviewAgent, "__init__", construct)
    preserved = {}
    for iteration in (1, 2):
        directory = (
            workspace
            / request.run_name
            / "graph_instances/review"
            / f"iteration_{iteration:03d}/attempt_001"
        )
        storage = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(directory), run_name=request.run_name),
        )
        value = LiteratureReviewInput.model_validate({**raw, "storage": storage})
        context = invocation_from_storage(
            receipt, node_id="review", phase="literature", storage=storage, iteration=iteration
        )
        output, record = literature_phase.run_literature(context, request, receipt, value)
        assert not output.findings
        diagnostic = workspace / "candidate_run"
        if iteration == 2:
            diagnostic /= "iteration_002"
        diagnostic /= "literature_inputs/review.json"
        assert json.loads(diagnostic.read_bytes())["storage"] == storage.model_dump(mode="json")
        assert caches[-1] == str(directory / "cache/root_papers")
        assert record == directory / "ml_literature_review_candidate.json"
        assert all(path.read_bytes() == content for path, content in preserved.items())
        preserved.update({record: record.read_bytes(), diagnostic: diagnostic.read_bytes()})
    rows = [json.loads(line) for line in Path(receipt.ledger_path).read_text().splitlines()]
    assert [row["iter"] for row in rows] == [1, 2]
    assert all(row["run_id"] == receipt.run_id and row["tokens"]["total"] == 18 for row in rows)
    assert len(literature_sdk[0]) == 2
