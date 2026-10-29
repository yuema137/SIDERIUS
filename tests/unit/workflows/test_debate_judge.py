"""B2-7 ``debate-judge/v1``: advocates and an optional critic debate, one judge decides.

Each test names the defect it catches. No provider is contacted: a stub bridge
answers every debate role, so no API key is needed.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.judge.call import JudgeRunContext
from agent.schemas.data_analysis.common import canonical_json_bytes, canonical_sha256
from agent.schemas.judge import (
    AdvocacyRequest,
    CallRequest,
    CritiqueRequest,
    DebateTurn,
    DebateVerdictRequest,
    ItemProjection,
    JudgedItem,
    JudgeRoutes,
    ProjectedField,
)
from workflows.definition.adaptor_strategies import (
    AllSelect,
    CardinalityBound,
    Fallback,
    FirstAdmissibleSelect,
    PassCombine,
    ThresholdSelect,
    TopKSelect,
)
from workflows.definition.llm_strategies import DebateJudgeStrategy
from workflows.definition.models import InputPort
from workflows.judge_strategies import (
    StrategyError,
    StrategyInvocation,
    admit_llm_strategy,
    replay_llm_strategy,
    run_llm_strategy,
    strategy_items,
)
from workflows.judge_strategies.debate_templates import (
    ADVOCATE_TEMPLATE,
    CRITIC_TEMPLATE,
    RANK_TEMPLATE,
    SYNTHESIZE_TEMPLATE,
)

from .test_judge_merge import draft_value
from .test_judge_strategies import ROUTE, literature

ROUTES = JudgeRoutes(debate=ROUTE, max_judge_calls=20)


def debate(**overrides) -> DebateJudgeStrategy:
    fields = {
        "route_slot": "debate",
        "max_calls": 9,
        "guidance": "none",
        "criterion": "Which review should inform the next proposal?",
        "rounds": 2,
        "critic": True,
        "judge_output": "rank",
    }
    return DebateJudgeStrategy(**{**fields, **overrides})


def invocation(tmp_path: Path, n: int = 3, **overrides) -> StrategyInvocation:
    fields = {
        "adaptor_id": "debate_reviews",
        "iteration": 2,
        "strategy": debate(),
        "items": strategy_items(tuple(literature(i) for i in range(n))),
        "output_contract": "literature.output",
        "expected_count": CardinalityBound(min=1, max=1),
        "evidence_dir": tmp_path / "adaptors" / "debate_reviews.judge",
    }
    return StrategyInvocation(**{**fields, **overrides})


class DebateBridge:
    """Answers each debate role. ``order`` is the judge ranking (default: reverse input)."""

    def __init__(self, *, order=None, drafts=None, turn_item=None, cites=None) -> None:
        self.cites = cites
        self.order = order
        self.drafts = drafts
        self.turn_item = turn_item
        self.calls: list[str] = []
        self.facts: list[dict] = []
        self.markers: list[str] = []

    def set_run_context(self, **kwargs) -> None:
        pass

    def emit_marker(self, *, label: str, extra=None) -> None:
        self.markers.append(label)

    def generate(self, system_prompt: str, user_prompt: str, *, label: str):
        self.calls.append(label)
        facts = json.loads(user_prompt.split("Facts (JSON):\n", 1)[1])
        self.facts.append(facts)
        listed = [item["item_id"] for item in facts["items"]]
        if match := re.search(r"Round (\d+)\.", user_prompt):
            advocate = re.search(r"You advocate for item `([^`]+)`", user_prompt)
            item_id = self.turn_item or (advocate.group(1) if advocate else None)
            return {
                "kind": "debate_turn",
                "round": int(match.group(1)),
                "role": "advocate" if advocate else "critic",
                "item_id": item_id,
                "argument": f"turn {len(self.calls)}",
                "cites": self.cites if self.cites is not None else listed[:1],
            }
        if "Rank every listed item" in user_prompt:
            order = self.order or list(reversed(listed))
            return {"kind": "rank", "order": order, "rationale": "fixture"}
        drafts = self.drafts or [{"parents": listed, "value": draft_value()}]
        return {"kind": "synthesis", "items": drafts, "rationale": "fixture"}


def run(value: StrategyInvocation, bridge: DebateBridge, tmp_path: Path):
    return run_llm_strategy(
        value,
        ROUTES,
        context=JudgeRunContext(workspace=tmp_path, iteration=2, run_name="r", run_id="run-1"),
        bridge_factory=lambda _route: bridge,
    )


def test_rank_debate_makes_exactly_its_static_bound_and_returns_the_judge_order(tmp_path):
    """Defect: the debate makes more or fewer calls than rounds × (N + critic) + 1, or
    the ranking is not the judge's order (e.g. input order, or a value-ranked order)."""
    value = invocation(tmp_path)
    bridge = DebateBridge()
    result = run(value, bridge, tmp_path)
    assert len(bridge.calls) == 2 * (3 + 1) + 1 == 9
    ranking = result.outcome.ranking
    assert result.outcome.status == "decided" and ranking is not None
    assert ranking.order == ("reviews:2", "reviews:1", "reviews:0")
    assert ranking.scores is None
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


def test_every_call_sees_every_earlier_turn_in_round_major_order(tmp_path):
    """Defect: later speakers or the judge do not see earlier turns, or turns are ordered
    other than round-major, advocates in item order, then the critic."""
    bridge = DebateBridge()
    run(invocation(tmp_path), bridge, tmp_path)
    expected = [
        turn
        for r in (1, 2)
        for turn in (*((r, "advocate", f"reviews:{i}") for i in range(3)), (r, "critic", None))
    ]
    for index, facts in enumerate(bridge.facts):
        seen = [(t["round"], t["role"], t["item_id"]) for t in facts["transcript"]]
        assert seen == expected[:index]


def _forge(value: StrategyInvocation, edit) -> str:
    """Apply ``edit`` to the anchored call digests, re-anchor and return the new anchor."""
    path = value.evidence_dir / "strategy.json"
    record = json.loads(path.read_bytes())
    record["calls"] = edit(record["calls"])
    path.write_bytes(canonical_json_bytes(record))
    return canonical_sha256(record)


def test_replay_refuses_an_edited_dropped_or_reordered_turn(tmp_path):
    """Defect: a debate turn edited after the call, a dropped turn or swapped turns
    replay as the recorded debate (chain tamper)."""
    value = invocation(tmp_path, strategy=debate(rounds=1, critic=False))
    result = run(value, DebateBridge(), tmp_path)
    calls_dir = value.evidence_dir / "calls"
    turn = calls_dir / "001_advocate.json"
    original = turn.read_bytes()
    record = json.loads(original)
    record["payload"]["argument"] = "edited"
    turn.write_bytes(canonical_json_bytes(record))
    with pytest.raises(StrategyError, match="call 1 is refused"):
        replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256)
    turn.write_bytes(original)

    strategy_path = value.evidence_dir / "strategy.json"
    anchored = strategy_path.read_bytes()
    anchor = _forge(value, lambda calls: [calls[0], calls[2], calls[1], calls[3]])
    with pytest.raises(StrategyError, match="call 1 is refused"):
        replay_llm_strategy(value, ROUTES, expected_sha256=anchor)
    strategy_path.write_bytes(anchored)
    anchor = _forge(value, lambda calls: calls[:2])
    with pytest.raises(StrategyError, match="before the planned call chain is complete"):
        replay_llm_strategy(value, ROUTES, expected_sha256=anchor)


def test_replay_refuses_a_turn_re_recorded_with_a_forged_chain_digest(tmp_path):
    """Defect: a turn rewritten with a recomputed request digest (but the same chain
    position) replays, because later calls' prior_turns are not re-derived."""
    value = invocation(tmp_path, strategy=debate(rounds=1, critic=False))
    result = run(value, DebateBridge(), tmp_path)
    turn = value.evidence_dir / "calls" / "000_advocate.json"
    record = json.loads(turn.read_bytes())
    record["payload"]["argument"] = "forged"
    forged = canonical_json_bytes(record)
    turn.write_bytes(forged)
    anchor = _forge(value, lambda calls: [hashlib.sha256(forged).hexdigest(), *calls[1:]])
    with pytest.raises(StrategyError, match="call 1 is refused"):
        replay_llm_strategy(value, ROUTES, expected_sha256=anchor)
    assert result.outcome.status == "decided"


@pytest.mark.parametrize(
    "order",
    [
        ["reviews:0", "reviews:1"],
        ["reviews:0", "reviews:1", "reviews:2", "reviews:9"],
        ["reviews:0", "reviews:0", "reviews:1", "reviews:2"],
    ],
    ids=["subset", "extra", "repeat"],
)
def test_a_judge_order_that_is_not_a_permutation_is_refused(tmp_path, order):
    """Defect: a judge ranking that omits, invents or repeats items reaches B6 SELECT."""
    value = invocation(tmp_path, strategy=debate(on_failure=Fallback(combine=PassCombine())))
    result = run(value, DebateBridge(order=order), tmp_path)
    assert (result.outcome.status, result.outcome.failure_code) == (
        "fallback",
        "inadmissible_choice",
    )


def test_an_advocate_arguing_for_another_item_ends_the_chain(tmp_path):
    """Defect: a turn attributed to the wrong item enters the transcript."""
    bridge = DebateBridge(turn_item="reviews:2")
    result = run(invocation(tmp_path), bridge, tmp_path)
    assert len(bridge.calls) == 1
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "inadmissible_choice")


def test_a_single_item_rank_is_skipped_without_a_call_and_replays(tmp_path):
    """Defect: one item is debated (wasted calls) or its trivial ranking is not recorded."""
    value = invocation(tmp_path, n=1)
    bridge = DebateBridge()
    result = run(value, bridge, tmp_path)
    assert bridge.calls == [] and bridge.markers == ["judge.debate-judge.skipped"]
    assert result.outcome.status == "skipped"
    assert result.outcome.ranking is not None
    assert result.outcome.ranking.order == ("reviews:0",)
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


def synthesize(**overrides) -> DebateJudgeStrategy:
    return debate(judge_output="synthesize", synthesize_count=1, **overrides)


def test_synthesize_returns_stamped_values_after_the_debate(tmp_path):
    """Defect: synthesize mode returns a ranking, loses lineage, or skips stamping."""
    value = invocation(tmp_path, n=2, strategy=synthesize(rounds=1, critic=False))
    bridge = DebateBridge()
    result = run(value, bridge, tmp_path)
    combined = result.outcome.combined
    assert result.outcome.ranking is None and combined is not None
    assert len(bridge.calls) == 3
    (item,) = combined.items
    assert item.parents == ("reviews:0", "reviews:1")
    assert item.value["run_name"] == "adaptor:debate_reviews/debate-judge/v1"
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


def test_synthesize_count_and_item_floor_are_enforced(tmp_path):
    """Defect: surplus synthesized values pass, or a one-item synthesis is debated."""
    one = {"parents": ["reviews:0"], "value": draft_value()}
    value = invocation(tmp_path, n=2, strategy=synthesize(rounds=1, critic=False))
    result = run(value, DebateBridge(drafts=[one, one]), tmp_path)
    assert result.outcome.failure_code == "cardinality_mismatch"
    single = invocation(tmp_path / "single", n=1, strategy=synthesize())
    bridge = DebateBridge()
    assert run(single, bridge, tmp_path).outcome.failure_code == "insufficient_items"
    assert bridge.calls == []


@pytest.mark.parametrize(
    ("cites", "code"),
    [
        (["reviews:9"], "inadmissible_choice"),
        (["reviews:0", "reviews:0"], "invalid_payload"),
    ],
    ids=["unlisted", "duplicate"],
)
def test_a_turn_citing_unlisted_or_repeated_items_ends_the_chain(tmp_path, cites, code):
    """Defect: a turn cites items outside the debate, or repeats cites (which inflate every
    later prompt that copies the transcript)."""
    bridge = DebateBridge(cites=cites)
    result = run(invocation(tmp_path), bridge, tmp_path)
    assert len(bridge.calls) == 1
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", code)


def test_a_debate_over_more_items_than_one_call_may_hold_is_refused(tmp_path):
    """Defect: debate prompts grow with the declared item count (a 200-item port is
    admitted with a 403-call bound and every call lists every item)."""
    wide = InputPort(
        name="reviews", contract="literature.output", cardinality="many", max_items=200
    )
    refusals = admit_llm_strategy(
        debate(max_calls=403),
        inputs=(wide,),
        output_contract="literature.output",
        select=TopKSelect(k=1),
        cardinality=CardinalityBound(min=1, max=1),
    ).refusals
    assert "batch_too_large" in {r.code for r in refusals}
    bridge = DebateBridge()
    with pytest.raises(StrategyError, match="17 items exceed 16 items per call"):
        run(invocation(tmp_path, n=17, strategy=debate(max_calls=403)), bridge, tmp_path)
    assert bridge.calls == []


PORT = InputPort(name="reviews", contract="literature.output", cardinality="many", max_items=3)


def admit(value=None, select=None, cardinality=None):
    return admit_llm_strategy(
        value or debate(),
        inputs=(PORT,),
        output_contract="literature.output",
        select=select or TopKSelect(k=1),
        cardinality=cardinality or CardinalityBound(min=1, max=1),
    )


def test_admission_accepts_rank_with_top_k_or_all_and_reports_the_bound():
    """Defect: a valid debate is refused, or its static bound is wrong."""
    assert admit().admitted and admit().static_call_bound == 9
    assert admit(select=AllSelect()).admitted
    assert admit(synthesize(), select=AllSelect()).admitted


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        pytest.param(
            {"select": ThresholdSelect(basis="rubric", at_least=1.0)},
            "select_incompatible",
            id="rank-threshold-has-no-scale",
        ),
        pytest.param({"select": FirstAdmissibleSelect()}, "select_incompatible", id="rank-first"),
        pytest.param({"value": synthesize()}, "select_incompatible", id="synthesize-top-k"),
        pytest.param(
            {
                "value": debate(judge_output="synthesize", synthesize_count=2),
                "select": AllSelect(),
            },
            "cardinality_mismatch",
            id="synthesize-count-outside-bound",
        ),
        pytest.param({"value": debate(max_calls=8)}, "call_bound_exceeds_max_calls", id="cap"),
    ],
)
def test_admission_refuses_each_invalid_debate(kwargs, code):
    """Defect: the named debate declaration is admitted (one row per rule)."""
    assert code in {refusal.code for refusal in admit(**kwargs).refusals}


def _projection(text: str) -> ItemProjection:
    return ItemProjection(
        contract="literature.output",
        fields=(ProjectedField(name="findings[0].content", text=text),),
    )


def test_debate_prompt_bytes_are_pinned_for_fixed_requests():
    """Defect: an advocate, critic or judge prompt, request or response schema drifts
    without a template version bump."""
    items = tuple(
        JudgedItem(item_id=f"reviews:{i}", projection=_projection(str(i))) for i in (0, 1)
    )
    turn = DebateTurn(
        kind="debate_turn", round=1, role="advocate", item_id="reviews:0", argument="a", cites=()
    )
    common = {"criterion": "c", "items": items, "transcript": (turn,), "guidance": None}
    cases = (
        (ADVOCATE_TEMPLATE, "advocate", AdvocacyRequest(**common, round=1, item_id="reviews:1")),
        (CRITIC_TEMPLATE, "critic", CritiqueRequest(**common, round=1)),
        (
            RANK_TEMPLATE,
            "judge",
            DebateVerdictRequest(
                **common, judge_output="rank", synthesize_count=None, output_contract=None
            ),
        ),
        (
            SYNTHESIZE_TEMPLATE,
            "judge",
            DebateVerdictRequest(
                **common,
                judge_output="synthesize",
                synthesize_count=1,
                output_contract="literature.output",
            ),
        ),
    )
    pins = []
    for template, role, content in cases:
        request = CallRequest(
            invocation_sha256="f" * 64,
            call_role=role,
            call_index=1,
            prior_turns=("a" * 64,),
            content=content,
        )
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
        "1a9959dfdab75b157c6d38bb3e10366b0e19f814c260b963ac49f85031b8fcaf",
        "bf1c2be16b1be034135fe283c109ec4bfaefbc5eb2f5b96faa05006f6fda594e",
        "b9c3244ef18ef0ef7a88e1fbceee1b37134bb195a8a1f855ca4e0054f6528810",
        "219d3ff7a739d47bdc4184bcf7fcb1b9ab06702505a6227c241d425a2750be57",
    ),
    (
        "7a7265d80a610cff11442246fa371fd998a5cd865da07ba39d7129c3b64d6507",
        "f969e25b6d2f5ff3dde61febf6f1fdfc6c5b790b01c7cc967ab2558682214072",
        "45099f8826eb6d09dae7c5bfb76361b2e0dd49e3455616e29cd9d310589ec968",
        "219d3ff7a739d47bdc4184bcf7fcb1b9ab06702505a6227c241d425a2750be57",
    ),
    (
        "ad7e9da189b0354f3b03c02c25e251ccb84b5887a1b2872c070be2bc7d1a43a6",
        "e91acdd4bca9f4506a1327cd5eaa7c8eff5b295c8e13bfc0cc4c253582860596",
        "860aa16dbc4d6adaef2e999eebe30b81a45cf6d9ce23f88a215f7d8f7bc81ec2",
        "14ab6a5b6709bd8baea3fdffb0fa551b5a0cc46b13855101478da45952d68b9f",
    ),
    (
        "256e78de532af9b6fd6239b6be5cb449596dc0573801b80cd1c1507e4c932a40",
        "7ba507c157a22c0f331989349ef7666162ef8f1eb99551cba6e8705287c0507f",
        "817d2c52be03aa52e034b2fc355b55de76233b0da430e3dbeb65370735a4cb3d",
        "3d0a15fdfbe6bab17b8f8e89293af17dfeae9790708a74d62784c87b8d8f72bb",
    ),
]


def test_a_growing_transcript_that_would_exceed_the_prompt_budget_ends_the_debate(
    tmp_path, monkeypatch
):
    """Defect: a later debate call whose transcript pushes its prompt past the budget is
    sent anyway; it must end the chain as recorded prompt_too_large and replay equal."""
    sizes: list[int] = []

    class Measuring(DebateBridge):
        def generate(self, system_prompt, user_prompt, *, label):
            sizes.append(len(system_prompt) + len(user_prompt))
            return super().generate(system_prompt, user_prompt, label=label)

    strategy = debate(rounds=1, critic=False)
    run(invocation(tmp_path / "probe", strategy=strategy), Measuring(), tmp_path)
    assert sizes[0] < sizes[1]  # the transcript grows the prompt
    for module in ("run", "plan"):
        monkeypatch.setattr(f"workflows.judge_strategies.{module}.MAX_JUDGE_PROMPT_CHARS", sizes[0])
    value = invocation(tmp_path, strategy=strategy)
    bridge = DebateBridge()
    result = run(value, bridge, tmp_path)
    assert len(bridge.calls) == 1
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "prompt_too_large")
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


@pytest.fixture
def over_budget_debate(tmp_path, monkeypatch):
    prompts: list[tuple[str, str]] = []

    class Measuring(DebateBridge):
        def generate(self, system_prompt, user_prompt, *, label):
            prompts.append((system_prompt, user_prompt))
            return super().generate(system_prompt, user_prompt, label=label)

    strategy = debate(rounds=1, critic=False)
    run(invocation(tmp_path / "probe", strategy=strategy), Measuring(), tmp_path)
    for module in ("run", "plan"):
        monkeypatch.setattr(
            f"workflows.judge_strategies.{module}.MAX_JUDGE_PROMPT_CHARS",
            sum(map(len, prompts[0])),
        )
    value = invocation(tmp_path, strategy=strategy)
    bridge = DebateBridge()
    result = run(value, bridge, tmp_path)
    assert len(bridge.calls) == 1
    return value, result, prompts[1]


def test_unsent_prompt_measurement_is_recorded(over_budget_debate):
    """Defect: refusal evidence loses the unsent prompt; compare to the probe's real call."""
    value, result, (system, user) = over_budget_debate
    record = json.loads((value.evidence_dir / "strategy.json").read_bytes())
    assert record["unsent_prompt_chars"] == len(system) + len(user)
    assert record["unsent_prompt_sha256"] == canonical_sha256({"system": system, "user": user})
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


@pytest.mark.parametrize("field", ["unsent_prompt_chars", "unsent_prompt_sha256"])
def test_replay_refuses_changed_unsent_prompt_measurement(over_budget_debate, field):
    """Defect: replay accepts stale refusal measurements even with a valid outer anchor."""
    value, _, _ = over_budget_debate
    path = value.evidence_dir / "strategy.json"
    record = json.loads(path.read_bytes())
    record[field] = record[field] + 1 if field == "unsent_prompt_chars" else "0" * 64
    path.write_bytes(canonical_json_bytes(record))
    with pytest.raises(StrategyError, match="unsent prompt size or digest differs"):
        replay_llm_strategy(value, ROUTES, expected_sha256=canonical_sha256(record))


def test_replay_capacity_refusal_is_strategy_error(tmp_path):
    """Defect: removing replay's capacity check leaks request-schema ValidationError."""
    from workflows.judge_strategies.models import invocation_sha256

    value = invocation(tmp_path)
    run(value, DebateBridge(), tmp_path)
    wide = invocation(tmp_path, n=17, strategy=debate(max_calls=403))
    path = value.evidence_dir / "strategy.json"
    record = json.loads(path.read_bytes())
    record["invocation_sha256"] = invocation_sha256(wide)
    record["static_call_bound"] = 2 * (17 + 1) + 1
    path.write_bytes(canonical_json_bytes(record))
    with pytest.raises(StrategyError, match="17 items exceed 16 items per call"):
        replay_llm_strategy(wide, ROUTES, expected_sha256=canonical_sha256(record))
