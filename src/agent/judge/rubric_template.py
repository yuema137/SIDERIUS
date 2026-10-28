"""``judge.rubric/v1``: the ``rubric-rank/v1`` scoring prompt (one scorer call).

The judge returns one integer per declared criterion and item. Criterion weights
are not shown: the weighted total is computed by framework code, never by the LLM.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from agent.judge.template import JudgeTemplate
from agent.schemas.judge import CallRequest, RubricScoringRequest, RubricVerdict

_SYSTEM = (
    "You are a rubric scorer in a closed-loop research run. Score every listed "
    "item on every listed rubric criterion with one integer inside the rubric "
    "scale, where a higher integer is better. Score each item on its own "
    "content; you never compute totals, weights or rankings, and you never "
    "score an item that is not listed. Return only a JSON object with exactly "
    'these keys: "kind" (the string "rubric"), "item_scores" (one entry per '
    'listed item: an object with "item_id" and "scores", where "scores" has one '
    'object per criterion with "criterion" (its name) and "score" (an integer)) '
    'and "rationale" (at most 2000 characters).'
)

_USER_FRAME = (
    "Criterion from the experiment:\n{criterion}\n\n"
    "Rubric `{rubric_id}` version {rubric_version}: integer scale {scale_min} to "
    "{scale_max}, higher is better.\n\n"
    "Facts (JSON):\n{facts}"
)


def scoring_content(request: CallRequest) -> RubricScoringRequest:
    content = request.content
    if not isinstance(content, RubricScoringRequest):
        raise TypeError(f"judge.rubric/v1 cannot render content kind {content.kind!r}")
    return content


def _render_user(request: CallRequest) -> str:
    content = scoring_content(request)
    rubric = content.rubric
    facts: dict[str, object] = {
        "criteria": [
            {"name": criterion.name, "description": criterion.description}
            for criterion in rubric.criteria
        ],
        "items": [item.model_dump(mode="json") for item in content.items],
    }
    if content.guidance is not None:
        facts["task_guidance"] = content.guidance.model_dump(mode="json", exclude_none=True)
    return _USER_FRAME.format(
        criterion=content.criterion,
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        scale_min=rubric.scale_min,
        scale_max=rubric.scale_max,
        facts=json.dumps(facts, sort_keys=True, indent=2, ensure_ascii=False),
    )


def _check_payload(request: CallRequest, payload: BaseModel) -> str | None:
    """A verdict must score exactly the listed items on exactly the declared criteria."""
    content = scoring_content(request)
    assert isinstance(payload, RubricVerdict)
    listed = sorted(item.item_id for item in content.items)
    scored = [entry.item_id for entry in payload.item_scores]
    if sorted(scored) != listed:
        return f"scored items {scored} are not exactly the listed items {listed}"
    rubric = content.rubric
    names = sorted(criterion.name for criterion in rubric.criteria)
    for entry in payload.item_scores:
        criteria = [score.criterion for score in entry.scores]
        if sorted(criteria) != names:
            return f"item {entry.item_id!r} scores criteria {criteria}, not exactly {names}"
        for score in entry.scores:
            if not rubric.scale_min <= score.score <= rubric.scale_max:
                return (
                    f"item {entry.item_id!r} criterion {score.criterion!r} score {score.score} "
                    f"is outside {rubric.scale_min}..{rubric.scale_max}"
                )
    return None


RUBRIC_TEMPLATE = JudgeTemplate(
    template_id="judge.rubric/v1",
    call_role="scorer",
    usage_label="judge.rubric-rank",
    system=_SYSTEM,
    response_model=RubricVerdict,
    render_user=_render_user,
    user_frame=_USER_FRAME,
    check_payload=_check_payload,
)
