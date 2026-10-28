"""``judge.stop/v1``: the loop-stop judge prompt (consumed by JudgeStop, B2-4)."""

from __future__ import annotations

import json

from agent.judge.template import JudgeTemplate
from agent.schemas.judge import CallRequest, StopJudgeRequest, StopVerdict

_SYSTEM = (
    "You are the stopping judge of a closed-loop research run. The deterministic "
    "core has already scored every completed body and evaluated every declared "
    "metric stop condition; none of them fired. Decide whether the run should "
    "stop after the judged body or continue to the next body. You never compute, "
    'revise or reinterpret scores. Only bodies whose Health class is "valid" '
    'carry a metric value and a rank; "invalid" and "unknown" bodies are not '
    'usable results. Return only a JSON object with exactly these keys: "kind" '
    '(the string "stop_decision"), "decision" ("stop" or "continue"), '
    '"rationale" (at most 2000 characters) and "confidence" ("low", '
    '"medium" or "high").'
)

_USER_FRAME = (
    "Criterion from the experiment:\n{criterion}\n\n"
    "Primary metric `{metric_id}`: {verb} it; {comparative} values are better and "
    "{antonym} values are worse. Rank 1 is the best Health-valid body.\n"
    "Judged boundary: body {iteration} of at most {final_iteration}.\n\n"
    "Facts (JSON):\n{facts}"
)


def _render_user(request: CallRequest) -> str:
    stop = request.content
    if not isinstance(stop, StopJudgeRequest):
        raise TypeError(f"judge.stop/v1 cannot render content kind {stop.kind!r}")
    words = stop.direction_words
    facts = json.dumps(stop.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False)
    return _USER_FRAME.format(
        criterion=stop.criterion,
        metric_id=stop.metric_id,
        verb=words.verb,
        comparative=words.comparative,
        antonym=words.antonym,
        iteration=stop.iteration,
        final_iteration=stop.final_iteration,
        facts=facts,
    )


STOP_TEMPLATE = JudgeTemplate(
    template_id="judge.stop/v1",
    call_role="stop",
    usage_label="judge.stop",
    system=_SYSTEM,
    response_model=StopVerdict,
    render_user=_render_user,
    user_frame=_USER_FRAME,
)
