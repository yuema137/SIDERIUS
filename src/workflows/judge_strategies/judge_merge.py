"""``judge-merge/v1``: one merger call synthesizes ``synthesize_count`` values from N parents.

The ``judge.merge/v1`` template lives here, not in ``agent/judge``, because its
payload check resolves the output contract's native type and framework-owned
fields (``synthesis.py``). Pure apart from rendering the contract's JSON schema.
A merged proposal is a new candidate: downstream training still requires its own
implementation and validation (B6 profile admission).
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from agent.judge.template import JudgeTemplate
from agent.schemas.judge import CallRequest, MergeRequest, SynthesisVerdict
from workflows.definition.llm_strategies import JudgeMergeStrategy

from .models import CombinedItems, StrategyError, StrategyInvocation
from .plan import PlannedCall, judged_items
from .synthesis import check_draft, combined_items, output_facts

_SYSTEM = (
    "You merge research items in a closed-loop research run. From the listed "
    "items, write the requested number of new values that combine their "
    "strongest content for the experiment's criterion. Each new value is a "
    "complete JSON object that follows the output JSON schema and leaves every "
    "framework-owned field unset (null, empty or absent, as the schema allows). "
    "Cite as parents only listed item ids, each at most once. Return only a JSON "
    'object with exactly these keys: "kind" (the string "synthesis"), "items" '
    '(one object per new value with "parents", a list of item ids, and "value", '
    'the value object) and "rationale" (at most 2000 characters).'
)

_USER_FRAME = (
    "Criterion from the experiment:\n{criterion}\n\n"
    "Write exactly {count} new `{contract}` value(s). Each cites at least "
    "{min_parents} distinct listed item ids as parents.\n\n"
    "Facts (JSON):\n{facts}"
)


def _content(request: CallRequest) -> MergeRequest:
    content = request.content
    if not isinstance(content, MergeRequest):
        raise TypeError(f"judge.merge/v1 cannot render content kind {content.kind!r}")
    return content


def _render_user(request: CallRequest) -> str:
    content = _content(request)
    facts: dict[str, object] = {
        "items": [item.model_dump(mode="json") for item in content.items],
        "output": output_facts(content.output_contract),
    }
    if content.guidance is not None:
        facts["task_guidance"] = content.guidance.model_dump(mode="json", exclude_none=True)
    return _USER_FRAME.format(
        criterion=content.criterion,
        count=content.synthesize_count,
        contract=content.output_contract,
        min_parents=content.min_parents,
        facts=json.dumps(facts, sort_keys=True, indent=2, ensure_ascii=False),
    )


def _check_payload(request: CallRequest, payload: BaseModel) -> str | None:
    """Every draft cites ≥ ``min_parents`` listed items and is a valid output value.

    The count is not checked here: a count other than ``synthesize_count`` is the
    strategy failure ``cardinality_mismatch`` (``fold``).
    """
    content = _content(request)
    assert isinstance(payload, SynthesisVerdict)
    listed = [item.item_id for item in content.items]
    for index, draft in enumerate(payload.items):
        refusal = check_draft(
            draft,
            contract=content.output_contract,
            listed=listed,
            min_parents=content.min_parents,
        )
        if refusal is not None:
            return f"merged value {index}: {refusal}"
    return None


MERGE_TEMPLATE = JudgeTemplate(
    template_id="judge.merge/v1",
    call_role="merger",
    usage_label="judge.judge-merge",
    system=_SYSTEM,
    response_model=SynthesisVerdict,
    render_user=_render_user,
    user_frame=_USER_FRAME,
    check_payload=_check_payload,
)


def _strategy(invocation: StrategyInvocation) -> JudgeMergeStrategy:
    strategy = invocation.strategy
    if not isinstance(strategy, JudgeMergeStrategy):
        raise StrategyError(f"judge-merge/v1 cannot plan {strategy.kind}")
    return strategy


def call_bound(strategy: JudgeMergeStrategy, n_items: int) -> int:
    del strategy, n_items
    return 1


def min_items(strategy: JudgeMergeStrategy) -> int:
    """Every merged value cites ``min_parents`` distinct items, so fewer items cannot run."""
    return strategy.min_parents


def output_count(strategy: JudgeMergeStrategy) -> int:
    return strategy.synthesize_count


def plan_call(invocation: StrategyInvocation, call_index: int) -> PlannedCall | None:
    strategy = _strategy(invocation)
    if call_index >= 1:
        return None
    content = MergeRequest(
        criterion=strategy.criterion,
        output_contract=invocation.output_contract,
        synthesize_count=strategy.synthesize_count,
        min_parents=strategy.min_parents,
        items=judged_items(invocation),
        guidance=invocation.task_guidance,
    )
    return PlannedCall(role="merger", template=MERGE_TEMPLATE, content=content)


def fold(invocation: StrategyInvocation, verdicts: tuple[SynthesisVerdict, ...]) -> CombinedItems:
    strategy = _strategy(invocation)
    if len(verdicts) != 1:
        raise StrategyError("judge-merge/v1 folds exactly one merger verdict")
    return combined_items(invocation, verdicts[0].items, declared=strategy.synthesize_count)
