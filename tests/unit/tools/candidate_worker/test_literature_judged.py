"""B6-8a: LLM COMBINE kinds over literature reviews (``native-literature-judged/v1``).

Offline pseudo integration: real review nodes (SDK transport stubbed, findings
injected), real proposer/implementor/validator bodies with the stub provider, real
readiness, adaptor execution through ``run_llm_strategy`` and verifier replay through
``replay_llm_strategy``. Only the judge bridge is a stub (``bridge_for_route``), so no
API key is needed. Each test names the defect it catches.
"""

import json
from pathlib import Path

import pytest
import yaml

from agent.schemas.judge_task import rubric_ref
from tests.helpers.candidate_literature import literature_judged_request
from tests.unit.workflows.test_debate_judge import DebateBridge
from tests.unit.workflows.test_judge_merge import MergeBridge
from tests.unit.workflows.test_judge_strategies import RUBRIC as SCORED_RUBRIC
from tests.unit.workflows.test_judge_strategies import StubBridge
from tests.unit.workflows.test_primary_advisors import AdvisorsBridge
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow

from .conftest import QUICKSTART, _prepared
from .test_literature import literature_sdk as literature_sdk
from .test_literature_adaptors import findings as findings
from .test_literature_adaptors import proposal_seed, run, states
from .test_native import native_runner as native_runner

REVIEWS = ("review0", "review1", "review2", "review3")


def debate_rank(**overrides):
    return {
        "kind": "debate-judge/v1",
        "route_slot": "debate",
        "max_calls": 5,
        "guidance": "none",
        "criterion": "Which review should seed a proposal?",
        "rounds": 1,
        "critic": False,
        "judge_output": "rank",
        **overrides,
    }


def judge_bridge(monkeypatch, bridge):
    """Every judge call (run and, if it ever happened, readback) reaches ``bridge``."""
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    return bridge


def seeded(findings):
    for index, node in enumerate(REVIEWS):
        findings[node] = [(f"Finding of {node}.", 0.1 * (index + 1))]


def evidence_contents(receipt, proposal):
    _, seed = proposal_seed(receipt, proposal)
    return [item["content"] for item in seed["literature_review_evidence"]["findings"]]


def test_debate_top3_feeds_the_judges_order_and_replays_without_a_provider(
    prepared, native_runner, findings, monkeypatch
):
    """Defect: top-k(3) over a debate ranking feeds proposals in declared (or another) order
    instead of the judge's order, or readback calls the provider again."""
    seeded(findings)
    order = ["reviews:3", "reviews:1", "reviews:0", "reviews:2"]
    bridge = judge_bridge(monkeypatch, DebateBridge(order=order))
    request = literature_judged_request(
        prepared,
        combine=debate_rank(),
        select={"kind": "top-k/v1", "k": 3},
        distribute={"kind": "per-item/v1", "count": 3, "on_short": "fail"},
        reviews=REVIEWS,
    )
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    assert len(bridge.calls) == 5  # rounds x N advocates + 1 judge = static bound
    for proposal, review in zip(
        ("propose0", "propose1", "propose2"), ("review3", "review1", "review0"), strict=True
    ):
        assert evidence_contents(receipt, proposal) == [f"Finding of {review}."]
    record = json.loads(Path(receipt.graph_trace.adaptors[0].record_path).read_bytes())
    assert record["ranking"]["basis"] == "judge"
    assert record["strategy_evidence"]["path"] == "judge.judge/strategy.json"
    calls_before = len(bridge.calls)
    verify_graph_trace(request, parent, receipt)
    assert len(bridge.calls) == calls_before  # readback never contacts a provider


def test_a_tampered_debate_turn_fails_verification(prepared, native_runner, findings, monkeypatch):
    """Defect: the verifier trusts recorded judge calls instead of replaying them."""
    seeded(findings)
    judge_bridge(monkeypatch, DebateBridge())
    request = literature_judged_request(
        prepared,
        combine=debate_rank(),
        select={"kind": "top-k/v1", "k": 3},
        distribute={"kind": "per-item/v1", "count": 3, "on_short": "fail"},
        reviews=REVIEWS,
    )
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    judge_dir = Path(receipt.graph_trace.adaptors[0].record_path).parent / "judge.judge"
    turn = judge_dir / "calls" / "000_advocate.json"
    turn.write_bytes(turn.read_bytes().replace(b'"argument":"turn 1"', b'"argument":"forged"'))
    with pytest.raises(Exception, match="strategy call 0 is refused"):
        verify_graph_trace(request, parent, receipt)


def test_merge_k1_feeds_one_stamped_merged_review(prepared, native_runner, findings, monkeypatch):
    """Defect: the merged value reaches the proposal without framework provenance, or the
    adaptor emits more than the one declared value."""
    seeded(findings)
    bridge = judge_bridge(monkeypatch, MergeBridge())
    combine = {
        "kind": "judge-merge/v1",
        "route_slot": "aggregate",
        "max_calls": 1,
        "guidance": "none",
        "criterion": "Merge the reviews.",
        "synthesize_count": 1,
        "min_parents": 2,
    }
    request = literature_judged_request(
        prepared,
        combine=combine,
        select={"kind": "all/v1"},
        distribute={"kind": "single/v1"},
        reviews=REVIEWS[:2],
    )
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    assert bridge.calls == ["judge.judge-merge"]
    value_path = Path(receipt.graph_trace.adaptors[0].record_path).parent / "judge.out.result.json"
    merged = json.loads(value_path.read_bytes())
    assert merged["run_name"] == "adaptor:judge/judge-merge/v1"
    record = json.loads(Path(receipt.graph_trace.adaptors[0].record_path).read_bytes())
    assert [item["role"] for item in record["contributions"]] == ["synthesized"]
    assert len(record["contributions"][0]["inputs"]) == 2
    verify_graph_trace(request, parent, receipt)


def test_primary_advisors_revises_the_declared_primary(
    prepared, native_runner, findings, monkeypatch
):
    """Defect: the revision's lineage does not start with the declared primary."""
    seeded(findings)
    judge_bridge(monkeypatch, AdvisorsBridge())
    combine = {
        "kind": "primary-advisors-llm/v1",
        "route_slot": "aggregate",
        "max_calls": 3,
        "guidance": "none",
        "criterion": "Strengthen the primary review.",
        "primary": "declared",
        "primary_item": "reviews:2",
        "advice": "per_advisor",
    }
    request = literature_judged_request(
        prepared,
        combine=combine,
        select={"kind": "all/v1"},
        distribute={"kind": "single/v1"},
        reviews=REVIEWS[:3],
    )
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    record = json.loads(Path(receipt.graph_trace.adaptors[0].record_path).read_bytes())
    inputs = record["contributions"][0]["inputs"]
    assert (inputs[0]["port"], inputs[0]["position"]) == ("reviews", 2)
    verify_graph_trace(request, parent, receipt)


def test_judge_failure_runs_the_declared_fallback_and_replays(
    prepared, native_runner, findings, monkeypatch
):
    """Defect: a failed judge with a declared fallback fails the adaptor (or runs the
    fallback silently), or the verifier cannot re-derive the fallback."""
    seeded(findings)
    judge_bridge(monkeypatch, DebateBridge(order=["reviews:0"]))  # not a permutation
    request = literature_judged_request(
        prepared,
        combine=debate_rank(on_failure={"combine": {"kind": "pass/v1"}}),
        select={"kind": "all/v1"},
        distribute={"kind": "per-item/v1", "count": 2, "on_short": "fail"},
        reviews=REVIEWS[:2],
    )
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    record = json.loads(Path(receipt.graph_trace.adaptors[0].record_path).read_bytes())
    assert record["fallback"] == "pass/v1"
    assert evidence_contents(receipt, "propose0") == ["Finding of review0."]
    verify_graph_trace(request, parent, receipt)


def test_judge_failure_without_fallback_fails_the_adaptor_with_judge_failure(
    prepared, native_runner, findings, monkeypatch
):
    """Defect: an undecided judge is closed as an unrecorded native failure or feeds items."""
    seeded(findings)
    judge_bridge(monkeypatch, DebateBridge(order=["reviews:0"]))
    request = literature_judged_request(
        prepared,
        combine=debate_rank(),
        select={"kind": "top-k/v1", "k": 1},
        distribute={"kind": "single/v1"},
        reviews=REVIEWS[:2],
    )
    receipt, parent = run(request)
    assert states(receipt)["judge"] == ("failed", "judge_failure")
    assert receipt.graph_trace.adaptors[0].record_path is not None
    assert not native_runner.calls
    verify_graph_trace(request, parent, receipt)


def test_run_level_max_judge_calls_refuses_before_any_effect(
    prepared, native_runner, literature_sdk, findings, monkeypatch
):
    """Defect: a run whose static judge call sum (5 here) exceeds max_judge_calls (4)
    starts its reviews and only fails at the judge."""
    seeded(findings)
    bridge = judge_bridge(monkeypatch, DebateBridge())
    request = literature_judged_request(
        prepared,
        combine=debate_rank(),
        select={"kind": "top-k/v1", "k": 3},
        distribute={"kind": "per-item/v1", "count": 3, "on_short": "fail"},
        reviews=REVIEWS,
        max_judge_calls=4,
    )
    receipt, _ = run(request)
    assert receipt.status == "failed"
    assert receipt.error == "StrategyError: the run may make 5 judge calls; max_judge_calls is 4"
    assert receipt.graph_trace is None
    assert not literature_sdk[0] and not native_runner.calls and bridge.calls == []


@pytest.fixture
def prepared_rubric(tmp_path, monkeypatch):
    """The quickstart task plus a task-declared rubric (``rubrics:``), as a test manifest.

    The shipped manifest's refs are kept verbatim (``../../examples/...``): plugin module
    identity derives from the authored ref spelling, so a respelled ref would register
    the same plugin under a second identity in a shared test process. The manifest sits
    two levels below the mounted project root, beside an ``examples`` link to the
    checkout's ``examples/``, so the verbatim refs resolve to the shared files.
    """
    project = tmp_path / "project"
    task = project / "task" / "judged"
    task.mkdir(parents=True)
    (project / "examples").symlink_to(QUICKSTART.parents[2] / "examples")
    (task / "rubric.yaml").write_text(yaml.safe_dump(SCORED_RUBRIC.model_dump(mode="json")))
    raw = yaml.safe_load(QUICKSTART.read_text())
    raw["rubrics"] = [{"config": str(task / "rubric.yaml")}]
    manifest = task / "manifest.yaml"
    manifest.write_text(yaml.safe_dump(raw))
    yield from _prepared(tmp_path, monkeypatch, manifest)


def test_rubric_top2_ranks_by_the_task_rubric_end_to_end(
    prepared_rubric, native_runner, findings, monkeypatch
):
    """Defect: the rubric ranking does not decide which reviews reach which proposal
    (lost order or unit mapping), the task rubric is not the one scored, or readback
    re-runs the scorer instead of replaying it.

    Hand-computed weighted means (B2-6 fixture table): reviews:2 = 13/3, reviews:0 = 3,
    reviews:1 = 3 (tie, input order), so top-2 feeds review2 then review0.
    """
    seeded(findings)
    bridge = judge_bridge(monkeypatch, StubBridge())
    combine = {
        "kind": "rubric-rank/v1",
        "route_slot": "aggregate",
        "max_calls": 3,
        "guidance": "none",
        "criterion": "Which review should seed a proposal?",
        "rubric": rubric_ref(SCORED_RUBRIC).model_dump(mode="json"),
        "scoring": "per_item",
        "repeats": 1,
    }
    request = literature_judged_request(
        prepared_rubric,
        combine=combine,
        select={"kind": "top-k/v1", "k": 2},
        distribute={"kind": "per-item/v1", "count": 2, "on_short": "fail"},
        reviews=REVIEWS[:3],
    )
    receipt, parent = run(request)
    assert receipt.status == "accepted", receipt.error
    assert bridge.calls == ["judge.rubric-rank"] * 3
    assert evidence_contents(receipt, "propose0") == ["Finding of review2."]
    assert evidence_contents(receipt, "propose1") == ["Finding of review0."]
    record = json.loads(Path(receipt.graph_trace.adaptors[0].record_path).read_bytes())
    assert [entry["exact"] for entry in record["ranking"]["entries"]] == ["13/3", "3", "3"]
    calls = len(bridge.calls)
    verify_graph_trace(request, parent, receipt)
    assert len(bridge.calls) == calls


def _refused(request, change, match):
    raw = request.preview.model_dump(mode="json")
    change(raw)
    with pytest.raises(ValueError, match=match):
        preview_workflow(WorkflowPreviewRequest.model_validate_json(json.dumps(raw)))


def test_profile_admission_refusals(prepared, findings):
    """Defect: an LLM COMBINE runs under another profile, an unadmitted LLM declaration or
    fallback reaches execution, or an unbounded port is accepted."""
    request = literature_judged_request(
        prepared,
        combine=debate_rank(),
        select={"kind": "top-k/v1", "k": 3},
        distribute={"kind": "per-item/v1", "count": 3, "on_short": "fail"},
        reviews=REVIEWS,
    )

    def adaptor(raw):
        return raw["document"]["definition"]["adaptors"][0]

    for change, match in (
        (
            lambda raw: raw.update(execution_profile="native-literature-split/v1"),
            "executes only under the native-literature-judged/v1",
        ),
        (lambda raw: adaptor(raw)["combine"].update(max_calls=4), "call_bound_exceeds_max_calls"),
        (lambda raw: adaptor(raw)["inputs"][0].pop("max_items"), "unbounded_port"),
        (
            lambda raw: adaptor(raw)["combine"].update(on_failure={"combine": {"kind": "pass/v1"}}),
            "fallback pass/v1 is not admitted with top-k/v1",
        ),
    ):
        _refused(request, change, match)
