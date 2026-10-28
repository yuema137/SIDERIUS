"""B2-8 ``primary-advisors-llm/v1``: revise one primary item with the others as advisors.

Each test names the defect it catches. No provider is contacted: a stub bridge
answers advisor and reviser calls, so no API key is needed.
"""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.judge.call import JudgeRunContext
from agent.judge.evidence import JudgeEvidenceError, verify_call_chain
from agent.schemas.data_analysis.common import canonical_json_bytes, canonical_sha256
from agent.schemas.judge import (
    AdviceRequest,
    AdvisoryNote,
    CallRequest,
    ItemProjection,
    JudgeCallEvidence,
    JudgedItem,
    ProjectedField,
    RevisionRequest,
)
from workflows.definition.adaptor_strategies import AllSelect, CardinalityBound, TopKSelect
from workflows.definition.llm_strategies import PrimaryAdvisorsStrategy
from workflows.definition.models import InputPort
from workflows.judge_strategies import (
    StrategyError,
    StrategyInvocation,
    admit_llm_strategy,
    replay_llm_strategy,
    run_llm_strategy,
    strategy_items,
)
from workflows.judge_strategies.primary_advisors import ADVICE_TEMPLATE, REVISION_TEMPLATE

from .test_judge_merge import draft_value
from .test_judge_strategies import ROUTES, literature


def primary_advisors(**overrides) -> PrimaryAdvisorsStrategy:
    fields = {
        "route_slot": "aggregate",
        "max_calls": 3,
        "guidance": "none",
        "criterion": "Strengthen the primary review with what the others found.",
        "primary": "first_admissible",
        "advice": "single_call",
    }
    return PrimaryAdvisorsStrategy(**{**fields, **overrides})


def invocation(tmp_path: Path, positions=(0, 1, 2), **overrides) -> StrategyInvocation:
    fields = {
        "adaptor_id": "revise_review",
        "iteration": 2,
        "strategy": primary_advisors(),
        "items": strategy_items(tuple(literature(i) for i in positions)),
        "output_contract": "literature.output",
        "expected_count": CardinalityBound(min=1, max=1),
        "evidence_dir": tmp_path / "adaptors" / "revise_review.judge",
    }
    return StrategyInvocation(**{**fields, **overrides})


class AdvisorsBridge:
    """Advisor calls: one suggestion naming the advisor. Reviser: one value whose parents
    are the primary and every advisor (or ``parents`` when given)."""

    def __init__(self, *, parents=None, advisor_item=None) -> None:
        self.parents = parents
        self.advisor_item = advisor_item
        self.calls: list[str] = []
        self.prompts: list[dict] = []

    def set_run_context(self, **kwargs) -> None:
        pass

    def generate(self, system_prompt: str, user_prompt: str, *, label: str):
        self.calls.append(label)
        facts = json.loads(user_prompt.split("Facts (JSON):\n", 1)[1])
        self.prompts.append(facts)
        if "advisor" in facts:
            advisor = self.advisor_item or facts["advisor"]["item_id"]
            return {"kind": "advice", "advisor_item": advisor, "suggestions": [f"use {advisor}"]}
        parents = self.parents or [
            facts["primary"]["item_id"],
            *(item["item_id"] for item in facts["advisors"]),
        ]
        value = {"parents": parents, "value": draft_value()}
        return {"kind": "synthesis", "items": [value], "rationale": "fixture"}


def run(value: StrategyInvocation, bridge: AdvisorsBridge, tmp_path: Path):
    return run_llm_strategy(
        value,
        ROUTES,
        context=JudgeRunContext(workspace=tmp_path, iteration=2, run_name="r", run_id="run-1"),
        bridge_factory=lambda _route: bridge,
    )


def call_content(value: StrategyInvocation, name: str):
    record = json.loads((value.evidence_dir / "calls" / name).read_text())
    return record["request"]["content"]


def test_single_call_revises_the_first_admissible_item_in_one_call(tmp_path):
    """Defect: single_call makes more than its one call, or the revised value loses
    its primary/adopted-advisor lineage or framework stamping."""
    value = invocation(tmp_path)
    bridge = AdvisorsBridge()
    result = run(value, bridge, tmp_path)
    combined = result.outcome.combined
    assert result.outcome.status == "decided" and combined is not None
    (item,) = combined.items
    assert item.parents == ("reviews:0", "reviews:1", "reviews:2")
    assert item.value["run_name"] == "adaptor:revise_review/primary-advisors-llm/v1"
    assert bridge.calls == ["judge.primary-advisors-llm"]
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


def test_a_declared_primary_is_used_not_the_first_item(tmp_path):
    """Defect: the primary falls back to declaration order although another item is declared."""
    value = invocation(
        tmp_path, strategy=primary_advisors(primary="declared", primary_item="reviews:2")
    )
    result = run(value, AdvisorsBridge(), tmp_path)
    content = call_content(value, "000_reviser.json")
    assert content["primary"]["item_id"] == "reviews:2"
    assert [item["item_id"] for item in content["advisors"]] == ["reviews:0", "reviews:1"]
    assert result.outcome.combined is not None
    assert result.outcome.combined.items[0].parents[0] == "reviews:2"


def test_replay_refuses_evidence_whose_primary_the_declared_rule_did_not_choose(tmp_path):
    """Defect: a complete, self-consistent forgery that revised another primary (request,
    request digest, prompt identity, payload lineage and recorded outcome all rewritten,
    then re-anchored) replays, because readback trusts the recorded request instead of
    re-deriving the primary from the declared rule."""
    value = invocation(
        tmp_path, strategy=primary_advisors(primary="declared", primary_item="reviews:2")
    )
    result = run(value, AdvisorsBridge(), tmp_path)
    call_path = value.evidence_dir / "calls" / "000_reviser.json"
    record = json.loads(call_path.read_bytes())
    content = record["request"]["content"]
    first, *rest = content["advisors"]
    content["primary"], content["advisors"] = first, [content["primary"], *rest]
    request = CallRequest.model_validate_json(json.dumps(record["request"]))
    record["request_sha256"] = canonical_sha256(request)
    record["prompt"] = REVISION_TEMPLATE.identity(request).model_dump(mode="json")
    parents = ["reviews:0", "reviews:2", "reviews:1"]
    record["payload"]["items"][0]["parents"] = parents
    forged = canonical_json_bytes(record)
    call_path.write_bytes(forged)
    strategy_path = value.evidence_dir / "strategy.json"
    anchor = json.loads(strategy_path.read_bytes())
    anchor["calls"] = [hashlib.sha256(forged).hexdigest()]
    anchor["outcome"]["combined"]["items"][0]["parents"] = parents
    strategy_path.write_bytes(canonical_json_bytes(anchor))
    with pytest.raises(StrategyError, match="request differs from the re-projected request"):
        replay_llm_strategy(value, ROUTES, expected_sha256=canonical_sha256(anchor))
    assert result.outcome.status == "decided"


def test_lineage_names_the_primary_first(tmp_path):
    """Defect: a revision of primary reviews:2 answering parents [reviews:0, reviews:2]
    reaches B6 with lineage that reads as if reviews:0 were the primary."""
    strategy = primary_advisors(primary="declared", primary_item="reviews:2")
    bridge = AdvisorsBridge(parents=["reviews:0", "reviews:2"])
    result = run(invocation(tmp_path, strategy=strategy), bridge, tmp_path)
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "inadmissible_choice")


def test_primary_advisors_over_more_items_than_one_call_may_hold_is_refused(tmp_path):
    """Defect: the reviser prompt grows with the declared item count (every item is listed)."""
    wide = InputPort(
        name="reviews", contract="literature.output", cardinality="many", max_items=200
    )
    assert "batch_too_large" in {r.code for r in admit(inputs=(wide,)).refusals}
    bridge = AdvisorsBridge()
    with pytest.raises(StrategyError, match="17 items exceed 16 items per call"):
        run(invocation(tmp_path, positions=tuple(range(17))), bridge, tmp_path)
    assert bridge.calls == []


def test_per_advisor_consults_each_advisor_then_revises_with_every_note(tmp_path):
    """Defect: per_advisor skips or reorders advisors, exceeds its bound of N calls, or the
    reviser never sees the advisors' notes."""
    value = invocation(tmp_path, strategy=primary_advisors(advice="per_advisor"))
    bridge = AdvisorsBridge()
    result = run(value, bridge, tmp_path)
    assert len(bridge.calls) == 3
    assert [p["advisor"]["item_id"] for p in bridge.prompts[:2]] == ["reviews:1", "reviews:2"]
    notes = bridge.prompts[2]["advisor_notes"]
    assert [note["advisor_item"] for note in notes] == ["reviews:1", "reviews:2"]
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


def test_advice_naming_another_advisor_ends_the_chain(tmp_path):
    """Defect: a note attributed to the wrong advisor is carried into the revision."""
    value = invocation(tmp_path, strategy=primary_advisors(advice="per_advisor"))
    bridge = AdvisorsBridge(advisor_item="reviews:0")
    result = run(value, bridge, tmp_path)
    assert len(bridge.calls) == 1
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "inadmissible_choice")


def test_a_revision_that_drops_the_primary_is_refused(tmp_path):
    """Defect: the revised value's lineage omits the primary it was built on."""
    result = run(invocation(tmp_path), AdvisorsBridge(parents=["reviews:1"]), tmp_path)
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "inadmissible_choice")


def test_an_inadmissible_declared_primary_fails_before_any_call(tmp_path):
    """Defect: a rejected declared primary is silently replaced by another item."""
    strategy = primary_advisors(primary="declared", primary_item="reviews:0")
    value = invocation(tmp_path, positions=(1, 2), strategy=strategy)
    bridge = AdvisorsBridge()
    result = run(value, bridge, tmp_path)
    assert bridge.calls == []
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "primary_unavailable")
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


def test_metric_best_never_runs_by_declaration_order(tmp_path):
    """Defect: metric_best, without metric facts, quietly takes the first item as primary."""
    bridge = AdvisorsBridge()
    with pytest.raises(StrategyError, match="metric_best"):
        run(
            invocation(tmp_path, strategy=primary_advisors(primary="metric_best")), bridge, tmp_path
        )
    assert bridge.calls == []


PORT = InputPort(name="reviews", contract="literature.output", cardinality="many", max_items=3)


def admit(value=None, select=None, cardinality=None, inputs=None):
    return admit_llm_strategy(
        value or primary_advisors(),
        inputs=inputs or (PORT,),
        output_contract="literature.output",
        select=select or AllSelect(),
        cardinality=cardinality or CardinalityBound(min=1, max=1),
    )


def test_admission_bounds_single_call_at_one_and_per_advisor_at_n():
    """Defect: the static call bound ignores the advice mode."""
    assert admit().admitted and admit().static_call_bound == 1
    per_advisor = admit(primary_advisors(advice="per_advisor"))
    assert per_advisor.admitted and per_advisor.static_call_bound == 3


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        pytest.param(
            {"value": primary_advisors(primary="metric_best")},
            "primary_rule_unavailable",
            id="metric-best",
        ),
        pytest.param(
            {"value": primary_advisors(primary="declared", primary_item="reviews:3")},
            "primary_item_undeclared",
            id="declared-outside-ports",
        ),
        pytest.param({"select": TopKSelect(k=1)}, "select_incompatible", id="ranking-select"),
        pytest.param(
            {"inputs": (InputPort(name="r", contract="literature.output", cardinality="one"),)},
            "insufficient_capacity",
            id="no-advisor",
        ),
        pytest.param(
            {"cardinality": CardinalityBound(min=2, max=2)}, "cardinality_mismatch", id="two-out"
        ),
        pytest.param(
            {"value": primary_advisors(advice="per_advisor", max_calls=2)},
            "call_bound_exceeds_max_calls",
            id="cap",
        ),
    ],
)
def test_admission_refuses_each_invalid_primary_advisors(kwargs, code):
    """Defect: the named declaration is admitted (one row per rule)."""
    assert code in {refusal.code for refusal in admit(**kwargs).refusals}


def _projection(text: str) -> ItemProjection:
    return ItemProjection(
        contract="literature.output",
        fields=(ProjectedField(name="findings[0].content", text=text),),
    )


def _request(role: str, content) -> CallRequest:
    return CallRequest(
        invocation_sha256="d" * 64,
        call_role=role,
        call_index=0 if role == "advisor" else 1,
        prior_turns=() if role == "advisor" else ("e" * 64,),
        content=content,
    )


def test_advice_and_revision_prompt_bytes_are_pinned_for_fixed_requests():
    """Defect: advisor or reviser prompt, request, output schema or response schema drift
    without a template version bump."""
    primary = JudgedItem(item_id="reviews:0", projection=_projection("p"))
    advisor = JudgedItem(item_id="reviews:1", projection=_projection("a"))
    advice = AdviceRequest(
        criterion="c",
        output_contract="literature.output",
        primary=primary,
        advisor=advisor,
        guidance=None,
    )
    note = AdvisoryNote(kind="advice", advisor_item="reviews:1", suggestions=("s",))
    revision = RevisionRequest(
        criterion="c",
        output_contract="literature.output",
        primary=primary,
        advisors=(advisor,),
        notes=(note,),
        guidance=None,
    )
    pins = []
    for template, request in (
        (ADVICE_TEMPLATE, _request("advisor", advice)),
        (REVISION_TEMPLATE, _request("reviser", revision)),
    ):
        identity = template.identity(request)
        pins.append(
            (
                canonical_sha256(request),
                identity.template_sha256,
                identity.prompt_sha256,
                identity.response_schema_sha256,
            )
        )
    assert pins == PINS


PINS = [
    (
        "e8edb3e5642d89fb79aa70f9bf034034e13ff4c2ad5be3c345b26395650eef65",
        "9a6ef3fbbea9efc134afbd23c1882c9c29b91493dfd85f0a5c17273310f1359d",
        "d0c85d1732a3242c3eddaacb24a544fa7d24e9d720a43d44f5c3563a551a6c42",
        "e4a800330224c5b1182bd81a48dee61f968b3bb5c07f3a54e7665901dc4567b8",
    ),
    (
        "faf737c8b3a9031865702eab4a466ab5f0bf62070d7a9ad9aa1fd19af340179c",
        "baf19fe9576e5d97f940172f5d2edff498f5b5c3a5dfec0344750ac9f3b7fcb8",
        "b39ba5a1f0a21fcf0291997ab124e434688f466849a72cbffff756a6e6f43a8d",
        "3d0a15fdfbe6bab17b8f8e89293af17dfeae9790708a74d62784c87b8d8f72bb",
    ),
]


def test_an_advice_then_revision_chain_verifies_against_its_declared_kinds(tmp_path):
    """Defect: chain verification requires one content kind, refusing every valid
    per_advisor chain (advice, advice, revision), or accepts a revision recorded where
    the planner declared advice."""
    value = invocation(tmp_path, strategy=primary_advisors(advice="per_advisor"))
    run(value, AdvisorsBridge(), tmp_path)
    calls = [
        JudgeCallEvidence.model_validate_json(path.read_bytes())
        for path in sorted((value.evidence_dir / "calls").iterdir())
    ]
    verify_call_chain(calls, content_kinds=("advice", "advice", "revision"))
    with pytest.raises(JudgeEvidenceError, match="not the declared 'advice'"):
        verify_call_chain(calls, content_kinds=("advice", "advice", "advice"))
