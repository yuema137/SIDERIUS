"""B2-9 ``judge-merge/v1``: one merger call synthesizes new values from N parents.

Each test names the defect it catches. No provider is contacted: a stub bridge
returns synthesis verdicts, so no API key is needed.
"""

import copy
import json
from pathlib import Path

import pytest

from agent.judge.call import JudgeRunContext
from agent.schemas.data_analysis.common import canonical_json_bytes, canonical_sha256
from agent.schemas.judge import (
    CallRequest,
    ItemProjection,
    JudgedItem,
    MergeRequest,
    ProjectedField,
)
from workflows.definition.adaptor_strategies import (
    AllSelect,
    CardinalityBound,
    Fallback,
    PassCombine,
    TopKSelect,
)
from workflows.definition.llm_strategies import JudgeMergeStrategy
from workflows.definition.models import InputPort
from workflows.judge_strategies import (
    StrategyError,
    StrategyInvocation,
    admit_llm_strategy,
    replay_llm_strategy,
    run_llm_strategy,
    strategy_items,
)
from workflows.judge_strategies import projection as projection_module
from workflows.judge_strategies.judge_merge import MERGE_TEMPLATE

from .test_judge_strategies import ROUTES, literature


def merge(**overrides) -> JudgeMergeStrategy:
    fields = {
        "route_slot": "aggregate",
        "max_calls": 1,
        "guidance": "none",
        "criterion": "Merge the reviews into one evidence base for the next proposal.",
        "synthesize_count": 1,
        "min_parents": 2,
    }
    return JudgeMergeStrategy(**{**fields, **overrides})


def invocation(tmp_path: Path, n: int = 3, **overrides) -> StrategyInvocation:
    fields = {
        "adaptor_id": "merge_reviews",
        "iteration": 2,
        "strategy": merge(),
        "items": strategy_items(tuple(literature(i) for i in range(n))),
        "output_contract": "literature.output",
        "expected_count": CardinalityBound(min=1, max=1),
        "evidence_dir": tmp_path / "adaptors" / "merge_reviews.judge",
    }
    return StrategyInvocation(**{**fields, **overrides})


def draft_value() -> dict:
    """A literature.output value an author may write: framework-owned fields unset."""
    item = literature(0)
    assert item.value is not None
    value = item.value.model_dump(mode="json")
    value["agent_card"]["agent_name"] = ""
    value["run_name"] = ""
    for finding in value["findings"]:
        finding["source"] = ""
    return value


class MergeBridge:
    """Answers each merger call with ``drafts`` (default: one draft citing every item)."""

    def __init__(self, drafts=None) -> None:
        self.drafts = drafts
        self.calls: list[str] = []

    def set_run_context(self, **kwargs) -> None:
        pass

    def generate(self, system_prompt: str, user_prompt: str, *, label: str):
        self.calls.append(label)
        facts = json.loads(user_prompt.split("Facts (JSON):\n", 1)[1])
        listed = [item["item_id"] for item in facts["items"]]
        drafts = self.drafts or [{"parents": listed, "value": draft_value()}]
        return {"kind": "synthesis", "items": drafts, "rationale": "fixture"}


def run(value: StrategyInvocation, bridge: MergeBridge, tmp_path: Path):
    return run_llm_strategy(
        value,
        ROUTES,
        context=JudgeRunContext(workspace=tmp_path, iteration=2, run_name="r", run_id="run-1"),
        bridge_factory=lambda _route: bridge,
    )


def test_merge_returns_stamped_values_with_their_parents_in_one_call(tmp_path):
    """Defect: the merged value keeps author-set provenance (or none), loses its parents,
    or the merge makes more calls than its static bound of one."""
    value = invocation(tmp_path)
    bridge = MergeBridge()
    result = run(value, bridge, tmp_path)
    combined = result.outcome.combined
    assert (result.outcome.status, result.outcome.ranking) == ("decided", None)
    assert combined is not None and combined.contract == "literature.output"
    (item,) = combined.items
    assert item.parents == ("reviews:0", "reviews:1", "reviews:2")
    label = "adaptor:merge_reviews/judge-merge/v1"
    assert item.value["run_name"] == label
    assert item.value["agent_card"]["agent_name"] == label  # type: ignore[index]
    assert item.value_sha256 == canonical_sha256(item.value)
    assert bridge.calls == ["judge.judge-merge"]
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


def test_a_value_citing_fewer_than_min_parents_is_refused(tmp_path):
    """Defect: min_parents is declared but a merge drawing on one parent is accepted."""
    drafts = [{"parents": ["reviews:0"], "value": draft_value()}]
    result = run(invocation(tmp_path), MergeBridge(drafts), tmp_path)
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "inadmissible_choice")


@pytest.mark.parametrize(
    "parents",
    [["reviews:0", "reviews:0"], ["reviews:0", "reviews:9"]],
    ids=["repeated", "foreign"],
)
def test_repeated_or_foreign_parents_do_not_count_towards_min_parents(tmp_path, parents):
    """Defect: one item cited twice, or an unlisted id, satisfies min_parents."""
    drafts = [{"parents": parents, "value": draft_value()}]
    result = run(invocation(tmp_path), MergeBridge(drafts), tmp_path)
    assert result.outcome.failure_code == "inadmissible_choice"


def test_fewer_items_than_min_parents_makes_no_call_and_replays(tmp_path):
    """Defect: a merge that cannot satisfy min_parents still calls the provider, or its
    zero-call outcome cannot be replayed."""
    value = invocation(tmp_path, n=2, strategy=merge(min_parents=3, max_calls=1))
    bridge = MergeBridge()
    result = run(value, bridge, tmp_path)
    assert bridge.calls == []
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "insufficient_items")
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        pytest.param(lambda v: v.pop("started_at"), "started_at", id="missing-required-field"),
        pytest.param(
            lambda v: v.update(run_name="mine"), "framework-owned", id="author-provenance"
        ),
        pytest.param(
            lambda v: v["agent_card"].update(trust_level="hard_limit"),
            "hard_limit",
            id="forbidden-trust-level",
        ),
    ],
)
def test_a_value_outside_the_output_contract_is_refused(tmp_path, edit, expected):
    """Defect: a merged value that is not a valid literature.output, or that sets a
    framework-owned field, reaches B6 as a synthesized item."""
    value = draft_value()
    edit(value)
    drafts = [{"parents": ["reviews:0", "reviews:1"], "value": value}]
    result = run(invocation(tmp_path), MergeBridge(drafts), tmp_path)
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "inadmissible_choice")
    call = json.loads((tmp_path / "adaptors/merge_reviews.judge/calls/000_merger.json").read_text())
    assert expected in call["failure_message"]


def test_a_count_other_than_synthesize_count_is_a_cardinality_mismatch(tmp_path):
    """Defect: surplus merged values are truncated (or passed on) instead of failing."""
    one = {"parents": ["reviews:0", "reviews:1"], "value": draft_value()}
    value = invocation(tmp_path, strategy=merge(on_failure=Fallback(combine=PassCombine())))
    result = run(value, MergeBridge([one, copy.deepcopy(one)]), tmp_path)
    outcome = result.outcome
    assert (outcome.status, outcome.failure_code) == ("fallback", "cardinality_mismatch")
    assert outcome.fallback_combine == "pass/v1" and outcome.combined is None
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


def test_replay_refuses_an_edited_merged_value(tmp_path):
    """Defect: readback trusts a merged value edited after the call."""
    value = invocation(tmp_path)
    result = run(value, MergeBridge(), tmp_path)
    call = value.evidence_dir / "calls" / "000_merger.json"
    record = json.loads(call.read_bytes())
    record["payload"]["items"][0]["value"]["findings"][0]["content"] = "edited"
    call.write_bytes(canonical_json_bytes(record))
    with pytest.raises(StrategyError, match="call 0 is refused"):
        replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256)


PORT = InputPort(name="reviews", contract="literature.output", cardinality="many", max_items=3)


def admit(value=None, select=None, cardinality=None, inputs=None, output="literature.output"):
    return admit_llm_strategy(
        value or merge(),
        inputs=inputs or (PORT,),
        output_contract=output,
        select=select or AllSelect(),
        cardinality=cardinality or CardinalityBound(min=1, max=1),
    )


def test_admission_accepts_judge_merge_with_a_bound_of_one_call():
    """Defect: a valid merge declaration is refused, or its static bound is not 1."""
    admission = admit()
    assert admission.admitted and admission.static_call_bound == 1


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        pytest.param({"select": TopKSelect(k=1)}, "select_incompatible", id="ranking-select"),
        pytest.param(
            {"value": merge(synthesize_count=2)}, "cardinality_mismatch", id="count-outside-bound"
        ),
        pytest.param(
            {"value": merge(min_parents=4)}, "insufficient_capacity", id="min-parents-over-capacity"
        ),
        pytest.param({"output": "proposal.output"}, "output_contract_mismatch", id="other-output"),
    ],
)
def test_admission_refuses_each_invalid_merge(kwargs, code):
    """Defect: the named merge declaration is admitted (one row per rule)."""
    assert code in {refusal.code for refusal in admit(**kwargs).refusals}


def test_admission_never_lets_a_merge_synthesize_an_authority_contract(monkeypatch):
    """Defect: once trained candidates become projectable (B6-9), a merge could emit a
    synthetic tuning.output (a fabricated formal result)."""
    projectors = dict(projection_module.ITEM_PROJECTORS)
    projectors["tuning.output"] = projectors["proposal.output"]
    monkeypatch.setattr("workflows.judge_strategies.admission.ITEM_PROJECTORS", projectors)
    port = InputPort(name="t", contract="tuning.output", cardinality="many", max_items=3)
    codes = {r.code for r in admit(inputs=(port,), output="tuning.output").refusals}
    assert "output_not_emittable" in codes


def merge_request() -> CallRequest:
    projection = ItemProjection(
        contract="literature.output", fields=(ProjectedField(name="findings[0].content", text="x"),)
    )
    items = tuple(
        JudgedItem(item_id=f"reviews:{index}", projection=projection) for index in range(2)
    )
    return CallRequest(
        invocation_sha256="c" * 64,
        call_role="merger",
        call_index=0,
        prior_turns=(),
        content=MergeRequest(
            criterion="Merge the reviews.",
            output_contract="literature.output",
            synthesize_count=1,
            min_parents=2,
            items=items,
            guidance=None,
        ),
    )


def test_merge_prompt_bytes_are_pinned_for_a_fixed_request():
    """Defect: merge prompt, request, output schema or response schema drift without a
    template version bump."""
    request = merge_request()
    identity = MERGE_TEMPLATE.identity(request)
    pins = (
        canonical_sha256(request),
        identity.template_sha256,
        identity.prompt_sha256,
        identity.response_schema_sha256,
    )
    assert pins == PINS


PINS = (
    "00cced3638104bcc7f57edd59e2f20fca4202808778a38066ed16b6d6107ec5c",
    "70863aca077af947d027b68d882ab4b8ee5953246192599981bd8ffd990d5d48",
    "38363e0adfa630a48629aca3b223afc9eb23ed2c31f33bf0c64813211432da3d",
    "3d0a15fdfbe6bab17b8f8e89293af17dfeae9790708a74d62784c87b8d8f72bb",
)
