"""B6-8b: N proposals -> LLM COMBINE -> one branch per output (``native-proposal-judged/v1``).

Offline pseudo integration: real proposer/implementor/validator bodies with the stub
provider, real readiness, the B6-8a executor and verifier replay. Only the judge
bridge is a stub. Each test names the defect it catches.
"""

import json
from pathlib import Path

import pytest

from tests.helpers.candidate_literature import proposal_judged_request
from tests.unit.workflows.test_debate_judge import DebateBridge
from tools.candidate_worker import phases
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow

from .test_literature_adaptors import run, states
from .test_native import native_runner as native_runner


def debate_rank(**overrides):
    return {
        "kind": "debate-judge/v1",
        "route_slot": "debate",
        "max_calls": 4,
        "guidance": "none",
        "criterion": "Which proposal deserves an implementation?",
        "rounds": 1,
        "critic": False,
        "judge_output": "rank",
        **overrides,
    }


@pytest.fixture
def consumed(monkeypatch):
    """(implementation node, implemented candidate_id, seed owner), in run order.

    The seed owner is read from the seed's per-proposal debug path, so a branch that
    implements the right proposal with another proposal's task facts is visible.
    """
    seen: list[tuple[str, str | None, str]] = []
    original = phases.run_implementation

    def record(context, request, initial, inputs, config, proposal, blocks):
        owner = Path(inputs.proposal.debug_dump_proposing_prompt_path).parent.name
        seen.append((context.node_id, proposal.candidate_id, owner))
        return original(context, request, initial, inputs, config, proposal, blocks)

    monkeypatch.setattr(phases, "run_implementation", record)
    return seen


def candidate_ids(receipt) -> dict[str, str]:
    ids = {}
    for item in receipt.graph_trace.nodes:
        if item.capability == "proposal":
            ids[item.node_id] = json.loads(Path(item.record_path).read_bytes())["candidate_id"]
    return ids


def judged(prepared, **overrides):
    fields = {
        "combine": debate_rank(),
        "select": {"kind": "top-k/v1", "k": 2},
        "distribute": {"kind": "per-item/v1", "count": 2, "on_short": "fail"},
    }
    return proposal_judged_request(prepared, **{**fields, **overrides})


def test_top2_proposals_reach_their_branches_in_the_judges_order(
    prepared, native_runner, consumed, monkeypatch
):
    """Defect: branch i implements a proposal other than the judge's i-th choice (declared
    order, a sibling, or the proposal node with the same index), or readback re-runs."""
    bridge = DebateBridge(order=["proposals:2", "proposals:0", "proposals:1"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    request = judged(prepared)
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    ids = candidate_ids(receipt)
    proposals = sorted(ids)
    implementations = sorted(node for node, _, _ in consumed)
    assert {node: (cid, owner) for node, cid, owner in consumed} == {
        implementations[0]: (ids[proposals[2]], proposals[2]),
        implementations[1]: (ids[proposals[0]], proposals[0]),
    }
    calls = len(bridge.calls)
    verify_graph_trace(request, parent, receipt)
    assert len(bridge.calls) == calls


def test_a_failed_judge_blocks_every_branch(prepared, native_runner, consumed, monkeypatch):
    """Defect: branches run on an undecided ranking (e.g. falling back to proposal order)."""
    bridge = DebateBridge(order=["proposals:0"])
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    request = judged(prepared)
    receipt, parent = run(request)
    assert states(receipt)["rank"] == ("failed", "judge_failure")
    assert consumed == []
    verify_graph_trace(request, parent, receipt)


def _refused(request, change, match):
    raw = request.preview.model_dump(mode="json")
    change(raw)
    with pytest.raises(ValueError, match=match):
        preview_workflow(WorkflowPreviewRequest.model_validate_json(json.dumps(raw)))


def test_profile_admission_refusals(prepared):
    """Defect: a judged branch reads a proposal node directly, two branches read one output,
    or the profile admits a deterministic COMBINE."""
    request = judged(prepared)

    def nodes(raw):
        return raw["document"]["definition"]["nodes"]

    def implementation(raw, position):
        return sorted(
            (node for node in nodes(raw) if node["capability"] == "implementation"),
            key=lambda node: node["id"],
        )[position]

    def output(node):
        return next(arg for arg in node["request"]["arguments"] if arg["name"] == "output")

    def direct(raw):
        output(implementation(raw, 0))["source"] = {"kind": "result", "node": "propose0"}

    def duplicate(raw):
        for node in nodes(raw):  # branch 1 (implementation and validation) reads output 0
            for arg in node["request"]["arguments"] if "arguments" in node["request"] else ():
                if arg["source"].get("adaptor") == "rank":
                    arg["source"]["index"] = 0

    def deterministic(raw):
        adaptor = raw["document"]["definition"]["adaptors"][0]
        adaptor["combine"] = {"kind": "pass/v1"}
        adaptor["select"] = {"kind": "all/v1"}
        adaptor["distribute"] = {"kind": "per-item/v1", "count": 3, "on_short": "skip"}

    for change, match in (
        (direct, "unsupported source|AdaptorSource|adaptor output"),
        (duplicate, "one branch per adaptor output index"),
        (deterministic, "requires an LLM COMBINE kind"),
    ):
        _refused(request, change, match)
