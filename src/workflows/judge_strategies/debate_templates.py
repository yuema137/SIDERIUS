"""``debate-judge/v1`` prompt templates: advocate, critic and the final judge (rank or synthesize).

Every debate call sees the projected items and the verbatim transcript of all
earlier turns. The synthesizing judge's payload check resolves the output
contract's native type, so these templates live beside the strategy, not in
``agent/judge``. Usage label of every debate call: ``judge.debate-judge``.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from agent.judge.template import JudgeTemplate
from agent.schemas.judge import (
    AdvocacyRequest,
    CallRequest,
    CritiqueRequest,
    DebateTurn,
    DebateVerdictRequest,
    RankVerdict,
    SynthesisVerdict,
)

from .synthesis import check_draft, output_facts

USAGE_LABEL = "judge.debate-judge"

_TURN_KEYS = (
    'Return only a JSON object with exactly these keys: "kind" (the string '
    '"debate_turn"), "round" (the round number given), "role" ({role}), "item_id" '
    '({item_id}), "argument" (at most 3000 characters) and "cites" (a list of the '
    "listed item ids your argument relies on)."
)

_ADVOCATE_SYSTEM = (
    "You are an advocate in a structured debate inside a closed-loop research run. "
    "Argue, for the experiment's criterion, why your assigned item is the strongest "
    "of the listed items, answering earlier arguments in the transcript. Use only "
    "the listed items and the transcript. "
    + _TURN_KEYS.format(role='the string "advocate"', item_id="your assigned item id")
)

_CRITIC_SYSTEM = (
    "You are the critic in a structured debate inside a closed-loop research run. "
    "Weigh the arguments of the transcript for the experiment's criterion: name "
    "unsupported claims and the strongest points on each side. You argue for no "
    "item. " + _TURN_KEYS.format(role='the string "critic"', item_id="null")
)

_RANK_SYSTEM = (
    "You are the judge of a structured debate inside a closed-loop research run. "
    "Using the listed items and the full transcript, rank every listed item for the "
    "experiment's criterion, best first. Return only a JSON object with exactly "
    'these keys: "kind" (the string "rank"), "order" (every listed item id exactly '
    'once, best first) and "rationale" (at most 2000 characters).'
)

_SYNTHESIZE_SYSTEM = (
    "You are the judge of a structured debate inside a closed-loop research run. "
    "Using the listed items and the full transcript, write the requested number of "
    "new values that keep the strongest content for the experiment's criterion. "
    "Each value is a complete JSON object that follows the output JSON schema and "
    "leaves every framework-owned field unset (null, empty or absent, as the schema "
    "allows); its parents are the listed item ids it draws on, each at most once. "
    'Return only a JSON object with exactly these keys: "kind" (the string '
    '"synthesis"), "items" (one object per value with "parents", a list of item '
    'ids, and "value", the value object) and "rationale" (at most 2000 characters).'
)

_TURN_FRAME = (
    "Criterion from the experiment:\n{criterion}\n\nRound {round}. {task}\n\nFacts (JSON):\n{facts}"
)

_VERDICT_FRAME = "Criterion from the experiment:\n{criterion}\n\n{task}\n\nFacts (JSON):\n{facts}"

Content = AdvocacyRequest | CritiqueRequest | DebateVerdictRequest


def _content[T](request: CallRequest, kind: type[T], template: str) -> T:
    content = request.content
    if not isinstance(content, kind):
        raise TypeError(f"{template} cannot render content kind {content.kind!r}")
    return content


def _facts(content: Content, extra: dict[str, object] | None = None) -> str:
    facts: dict[str, object] = {
        "items": [item.model_dump(mode="json") for item in content.items],
        "transcript": [turn.model_dump(mode="json") for turn in content.transcript],
        **(extra or {}),
    }
    if content.guidance is not None:
        facts["task_guidance"] = content.guidance.model_dump(mode="json", exclude_none=True)
    return json.dumps(facts, sort_keys=True, indent=2, ensure_ascii=False)


def _listed(content: Content) -> list[str]:
    return [item.item_id for item in content.items]


def _check_turn(content: AdvocacyRequest | CritiqueRequest, turn: DebateTurn) -> str | None:
    role = "advocate" if isinstance(content, AdvocacyRequest) else "critic"
    item_id = content.item_id if isinstance(content, AdvocacyRequest) else None
    if (turn.round, turn.role, turn.item_id) != (content.round, role, item_id):
        return (
            f"turn is ({turn.round}, {turn.role}, {turn.item_id}); "
            f"expected ({content.round}, {role}, {item_id})"
        )
    foreign = sorted(set(turn.cites) - set(_listed(content)))
    return f"cites unlisted items {foreign}" if foreign else None


def _render_advocate(request: CallRequest) -> str:
    content = _content(request, AdvocacyRequest, "judge.debate.advocate/v1")
    task = f"You advocate for item `{content.item_id}`."
    return _TURN_FRAME.format(
        criterion=content.criterion, round=content.round, task=task, facts=_facts(content)
    )


def _check_advocate(request: CallRequest, payload: BaseModel) -> str | None:
    assert isinstance(payload, DebateTurn)
    return _check_turn(_content(request, AdvocacyRequest, "judge.debate.advocate/v1"), payload)


def _render_critic(request: CallRequest) -> str:
    content = _content(request, CritiqueRequest, "judge.debate.critic/v1")
    task = "You are the critic for this round."
    return _TURN_FRAME.format(
        criterion=content.criterion, round=content.round, task=task, facts=_facts(content)
    )


def _check_critic(request: CallRequest, payload: BaseModel) -> str | None:
    assert isinstance(payload, DebateTurn)
    return _check_turn(_content(request, CritiqueRequest, "judge.debate.critic/v1"), payload)


def _render_rank(request: CallRequest) -> str:
    content = _content(request, DebateVerdictRequest, "judge.debate.rank/v1")
    task = "Rank every listed item, best first."
    return _VERDICT_FRAME.format(criterion=content.criterion, task=task, facts=_facts(content))


def _check_rank(request: CallRequest, payload: BaseModel) -> str | None:
    """The order must be a permutation of the listed items: no subset, no extra, no repeat."""
    content = _content(request, DebateVerdictRequest, "judge.debate.rank/v1")
    assert isinstance(payload, RankVerdict)
    listed = _listed(content)
    if sorted(payload.order) != sorted(listed):
        return f"order {list(payload.order)} is not a permutation of {listed}"
    return None


def _render_synthesize(request: CallRequest) -> str:
    content = _content(request, DebateVerdictRequest, "judge.debate.synthesize/v1")
    assert content.output_contract is not None
    task = f"Write exactly {content.synthesize_count} new `{content.output_contract}` value(s)."
    facts = _facts(content, {"output": output_facts(content.output_contract)})
    return _VERDICT_FRAME.format(criterion=content.criterion, task=task, facts=facts)


def _check_synthesize(request: CallRequest, payload: BaseModel) -> str | None:
    """Each value cites listed parents and is a valid output value; the count is the fold's."""
    content = _content(request, DebateVerdictRequest, "judge.debate.synthesize/v1")
    assert isinstance(payload, SynthesisVerdict) and content.output_contract is not None
    for index, draft in enumerate(payload.items):
        refusal = check_draft(
            draft, contract=content.output_contract, listed=_listed(content), min_parents=1
        )
        if refusal is not None:
            return f"synthesized value {index}: {refusal}"
    return None


ADVOCATE_TEMPLATE = JudgeTemplate(
    template_id="judge.debate.advocate/v1",
    call_role="advocate",
    usage_label=USAGE_LABEL,
    system=_ADVOCATE_SYSTEM,
    response_model=DebateTurn,
    render_user=_render_advocate,
    user_frame=_TURN_FRAME,
    check_payload=_check_advocate,
)

CRITIC_TEMPLATE = JudgeTemplate(
    template_id="judge.debate.critic/v1",
    call_role="critic",
    usage_label=USAGE_LABEL,
    system=_CRITIC_SYSTEM,
    response_model=DebateTurn,
    render_user=_render_critic,
    user_frame=_TURN_FRAME,
    check_payload=_check_critic,
)

RANK_TEMPLATE = JudgeTemplate(
    template_id="judge.debate.rank/v1",
    call_role="judge",
    usage_label=USAGE_LABEL,
    system=_RANK_SYSTEM,
    response_model=RankVerdict,
    render_user=_render_rank,
    user_frame=_VERDICT_FRAME,
    check_payload=_check_rank,
)

SYNTHESIZE_TEMPLATE = JudgeTemplate(
    template_id="judge.debate.synthesize/v1",
    call_role="judge",
    usage_label=USAGE_LABEL,
    system=_SYNTHESIZE_SYSTEM,
    response_model=SynthesisVerdict,
    render_user=_render_synthesize,
    user_frame=_VERDICT_FRAME,
    check_payload=_check_synthesize,
)
