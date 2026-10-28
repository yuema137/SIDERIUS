"""Literature adaptor profiles: S2 collection and S3 split (B6-4).

Offline pseudo integration: the real review node (SDK transport stubbed, findings
injected per review), real proposer/implementor/validator bodies with the stub
provider, real readiness, adaptor execution and verifier recomputation.
"""

import json
from pathlib import Path

import pytest

from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import ExpertContextItem
from tests.helpers.candidate_literature import (
    RANKED_TOP,
    literature_collection_request,
    literature_split_request,
)
from tools.candidate_worker import launch_candidate, literature_phase
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow
from workflows.definition.candidate import ADAPTORS_NOT_ADMITTED

from .test_graph import initial
from .test_literature import literature_sdk as literature_sdk
from .test_native import native_runner as native_runner


@pytest.fixture
def findings(literature_sdk, monkeypatch):
    """Findings each review node returns, keyed by node id, as (content, confidence)."""
    returned: dict[str, list[tuple[str, float]]] = {}
    original = literature_phase.MLLiteratureReviewAgent.run

    def run(self, inputs):
        output = LiteratureReviewOutput.model_validate(original(self, inputs))
        node = Path(inputs.storage.local.workspace).parts[-3]  # graph_instances/<node>/...
        items = [
            ExpertContextItem(
                source="ml_literature_review",
                kind="literature",
                content=content,
                source_ref=f"{node}{index}",
                confidence=confidence,
            )
            for index, (content, confidence) in enumerate(returned.get(node, []))
        ]
        output = output.model_copy(update={"findings": items})
        # The stubbed review persists what it returns, as the native node does.
        record = (
            Path(inputs.storage.local.workspace) / f"ml_literature_review_{inputs.run_name}.json"
        )
        record.write_text(output.model_dump_json(indent=2))
        return output

    monkeypatch.setattr(literature_phase.MLLiteratureReviewAgent, "run", run)
    return returned


@pytest.fixture
def prompts(native_runner, monkeypatch):
    seen = []
    original = native_runner.generate_text

    def text(self, system, user, **kwargs):
        seen.append(user)
        return original(self, system, user, **kwargs)

    monkeypatch.setattr(native_runner, "generate_text", text)
    return seen


def run(request):
    receipt = launch_candidate(request)
    return receipt, initial(request).model_copy(update={"run_id": receipt.run_id})


def states(receipt) -> dict[str, tuple[str, str | None]]:
    trace = receipt.graph_trace
    return {item.node_id: (item.state, item.reason) for item in (*trace.nodes, *trace.adaptors)}


def proposal_seed(receipt, node: str) -> tuple[Path, dict]:
    path = Path(receipt.workspace) / f"candidate_run/proposal_inputs/{node}.json"
    return path, json.loads(path.read_bytes())


def test_collection_keeps_declared_binding_order_and_attribution(
    prepared, native_runner, findings, prompts
):
    """``survey`` executes first; the binding order puts ``review`` first.

    Fails if the collection follows completion order or loses per-review attribution.
    """
    findings.update(review=[("Claim from review.", 0.4)], survey=[("Claim from survey.", 0.7)])
    request = literature_collection_request(prepared, bindings=("review", "survey"))
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    assert [item.node_id for item in receipt.graph_trace.nodes][-2:] == ["survey", "review"]
    _, seed = proposal_seed(receipt, "propose")
    reviews = seed["literature_review_evidence"]["reviews"]
    assert [item["contribution_id"] for item in reviews] == ["review", "survey"]
    assert [item["evidence"]["findings"][0]["content"] for item in reviews] == [
        "Claim from review.",
        "Claim from survey.",
    ]
    prompt = next(item for item in prompts if "### Review: review" in item)
    assert (
        prompt.index("### Review: review")
        < prompt.index("Claim from review.")
        < prompt.index("### Review: survey")
        < prompt.index("Claim from survey.")
    )
    verify_graph_trace(request, parent, receipt)
    # The verifier re-derives the collection from the review records, in binding order.
    path, seed = proposal_seed(receipt, "propose")
    original = path.read_bytes()
    seed["literature_review_evidence"]["reviews"].reverse()
    path.write_text(json.dumps(seed))
    with pytest.raises(ValueError, match="declared literature edge"):
        verify_graph_trace(request, parent, receipt)
    path.write_bytes(original)


def test_split_skip_feeds_ranked_findings_and_skips_short_indices(
    prepared, native_runner, findings
):
    """M=3 with two findings under on_short=skip: two families run, the third is skipped.

    Fails if output index i does not reach proposal i in rank order, if a skipped
    index still dispatches its proposal, or if the verifier accepts a relabelled skip.
    """
    findings["review"] = [("Weak lead.", 0.2), ("Strong lead.", 0.9)]
    request = literature_split_request(prepared, count=3, on_short="skip")
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    observed = states(receipt)
    assert observed["split"] == ("succeeded", None)
    for node in ("propose2", "build2", "check2"):
        assert observed[node] == ("skipped", "insufficient_items")
    for index, content in enumerate(("Strong lead.", "Weak lead.")):
        _, seed = proposal_seed(receipt, f"propose{index}")
        evidence = seed["literature_review_evidence"]
        assert [item["content"] for item in evidence["findings"]] == [content]
        assert observed[f"check{index}"] == ("succeeded", None)
    record = json.loads(Path(receipt.graph_trace.adaptors[0].record_path).read_bytes())
    assert [item["status"] for item in record["outputs"]] == ["emitted", "emitted", "skipped"]
    verify_graph_trace(request, parent, receipt)
    # A skip relabelled as a route skip contradicts the recomputed adaptor outcome.
    nodes = tuple(
        item.model_copy(update={"reason": "route_not_selected"})
        if item.node_id == "propose2"
        else item
        for item in receipt.graph_trace.nodes
    )
    forged = receipt.model_copy(
        update={"graph_trace": receipt.graph_trace.model_copy(update={"nodes": nodes})}
    )
    with pytest.raises(ValueError, match="serial readiness"):
        verify_graph_trace(request, parent, forged)
    # Proposal 1 must have read output index 1, not a sibling's finding.
    path, seed = proposal_seed(receipt, "propose1")
    _, sibling = proposal_seed(receipt, "propose0")
    seed["literature_review_evidence"] = sibling["literature_review_evidence"]
    path.write_text(json.dumps(seed))
    with pytest.raises(ValueError, match="declared literature edge"):
        verify_graph_trace(request, parent, receipt)


THREE = [("One.", 0.1), ("Two.", 0.5), ("Three.", 0.3)]
PASS_ALL = {"combine": {"kind": "pass/v1"}, "select": {"kind": "all/v1"}}


@pytest.mark.parametrize(
    ("returned", "count", "strategy", "reason"),
    [
        # on_short=fail: two ranked findings cannot fill three outputs.
        (THREE[:2], 3, RANKED_TOP, "insufficient_items"),
        # Three findings are never truncated into two outputs.
        (THREE, 2, PASS_ALL, "too_many_items"),
    ],
)
def test_split_failure_records_its_reason_and_blocks_every_family(
    prepared, native_runner, findings, returned, count, strategy, reason
):
    """Fails if a split failure closes as an unrecorded native failure or runs a family."""
    findings["review"] = returned
    request = literature_split_request(prepared, count=count, on_short="fail", strategy=strategy)
    receipt, parent = run(request)
    observed = states(receipt)
    assert observed["split"] == ("failed", reason)
    assert receipt.graph_trace.adaptors[0].record_path is not None
    assert all(
        observed[node] == ("blocked", "dependency_not_successful")
        for node in observed
        if node.startswith(("propose", "build", "check"))
    )
    assert not native_runner.calls
    assert receipt.status == "failed"
    verify_graph_trace(request, parent, receipt)


def _refused(request, change, match):
    raw = request.preview.model_dump(mode="json")
    change(raw)
    with pytest.raises(ValueError, match=match):
        preview_workflow(WorkflowPreviewRequest.model_validate_json(json.dumps(raw)))


def _definition(raw):
    return raw["document"]["definition"]


def test_collection_profile_admission_refusals(prepared, findings):
    request = literature_collection_request(prepared)
    for change, match in (
        (
            lambda raw: _definition(raw)["adaptors"][0]["bindings"][0]["sources"].pop(),
            "bind every review result exactly once",
        ),
        (
            lambda raw: raw.update(execution_profile="native-literature-split/v1"),
            "split-items/v1",
        ),
        (
            lambda raw: raw.update(execution_profile="native-literature-candidate/v1"),
            ADAPTORS_NOT_ADMITTED,
        ),
    ):
        _refused(request, change, match)


def test_split_profile_requires_one_proposal_per_index(prepared, findings):
    request = literature_split_request(prepared, count=3)

    def rebind(raw):
        proposal = next(node for node in _definition(raw)["nodes"] if node["id"] == "propose2")
        proposal["request"]["arguments"][0]["source"]["index"] = 1

    _refused(request, rebind, "one proposal per adaptor output index")
