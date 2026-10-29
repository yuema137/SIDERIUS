"""``primary-advisors-llm/v1``: revise one primary item with the others as advisors.

The primary is chosen by the declared rule only, never by declaration order unless
``first_admissible`` is declared: ``declared`` names an item id (an inadmissible
declared primary fails before any call, ``primary_unavailable``);
``first_admissible`` takes the first admissible item. ``metric_best`` needs
metric facts that no projectable contract carries yet, so ``admit_llm_strategy``
refuses it and planning raises. The primary is part of every request, so replay
re-derives it by the same rule and refuses evidence naming another primary.

``single_call``: one reviser call sees the primary and every advisor.
``per_advisor``: one advisor call per advisor (advisor order), then one reviser
call that also carries every advisor's note. The reviser returns one value of the
output contract whose ``parents`` are the primary plus the advisors it adopted.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from agent.judge.template import JudgeTemplate
from agent.schemas.judge import (
    AdviceRequest,
    AdvisoryNote,
    CallRequest,
    JudgedItem,
    RevisionRequest,
    SynthesisVerdict,
)
from workflows.definition.llm_strategies import PrimaryAdvisorsStrategy
from workflows.definition.models import InputPort

from .models import (
    CombinedItems,
    StrategyError,
    StrategyFailureCode,
    StrategyInvocation,
    StrategyRefusal,
)
from .plan import PlannedCall, judged_items
from .synthesis import check_draft, combined_items, output_facts

_USAGE_LABEL = "judge.primary-advisors-llm"

_ADVICE_SYSTEM = (
    "You advise on a primary research item in a closed-loop research run. Read the "
    "primary item and one advisor item, and suggest concrete changes to the primary "
    "that the advisor's content supports, for the experiment's criterion. Suggest "
    "only what the advisor item supports. Return only a JSON object with exactly "
    'these keys: "kind" (the string "advice"), "advisor_item" (the advisor\'s item '
    'id) and "suggestions" (1 to 12 strings, each at most 1000 characters).'
)

_ADVICE_FRAME = (
    "Criterion from the experiment:\n{criterion}\n\n"
    "Primary item: `{primary}`. Advisor item: `{advisor}`.\n\n"
    "Facts (JSON):\n{facts}"
)

_REVISION_SYSTEM = (
    "You revise a primary research item in a closed-loop research run. Write one "
    "revised value of the requested output contract: keep the primary item as its "
    "basis and adopt only the advisor content (and advisor notes, when listed) "
    "that improves it for the experiment's criterion. The value is a complete JSON "
    "object that follows the output JSON schema and leaves every framework-owned "
    "field unset (null, empty or absent, as the schema allows). Its parents are the "
    "primary item id followed by the ids of the advisors you adopted, each at most "
    'once. Return only a JSON object with exactly these keys: "kind" (the string '
    '"synthesis"), "items" (exactly one object with "parents", a list of item ids, '
    'and "value", the value object) and "rationale" (at most 2000 characters).'
)

_REVISION_FRAME = (
    "Criterion from the experiment:\n{criterion}\n\n"
    "Revise primary item `{primary}` into one `{contract}` value; its parents start "
    "with `{primary}`.\n\n"
    "Facts (JSON):\n{facts}"
)


def _facts(content: AdviceRequest | RevisionRequest, facts: dict[str, object]) -> str:
    if content.guidance is not None:
        facts["task_guidance"] = content.guidance.model_dump(mode="json", exclude_none=True)
    return json.dumps(facts, sort_keys=True, indent=2, ensure_ascii=False)


def _advice(request: CallRequest) -> AdviceRequest:
    content = request.content
    if not isinstance(content, AdviceRequest):
        raise TypeError(f"judge.advice/v1 cannot render content kind {content.kind!r}")
    return content


def _revision(request: CallRequest) -> RevisionRequest:
    content = request.content
    if not isinstance(content, RevisionRequest):
        raise TypeError(f"judge.revision/v1 cannot render content kind {content.kind!r}")
    return content


def _render_advice(request: CallRequest) -> str:
    content = _advice(request)
    facts: dict[str, object] = {
        "primary": content.primary.model_dump(mode="json"),
        "advisor": content.advisor.model_dump(mode="json"),
    }
    return _ADVICE_FRAME.format(
        criterion=content.criterion,
        primary=content.primary.item_id,
        advisor=content.advisor.item_id,
        facts=_facts(content, facts),
    )


def _check_advice(request: CallRequest, payload: BaseModel) -> str | None:
    content = _advice(request)
    assert isinstance(payload, AdvisoryNote)
    if payload.advisor_item != content.advisor.item_id:
        return f"advice names {payload.advisor_item!r}, not advisor {content.advisor.item_id!r}"
    return None


def _render_revision(request: CallRequest) -> str:
    content = _revision(request)
    facts: dict[str, object] = {
        "primary": content.primary.model_dump(mode="json"),
        "advisors": [item.model_dump(mode="json") for item in content.advisors],
        "output": output_facts(content.output_contract),
    }
    if content.notes:
        facts["advisor_notes"] = [note.model_dump(mode="json") for note in content.notes]
    return _REVISION_FRAME.format(
        criterion=content.criterion,
        primary=content.primary.item_id,
        contract=content.output_contract,
        facts=_facts(content, facts),
    )


def _check_revision(request: CallRequest, payload: BaseModel) -> str | None:
    """Each draft's parents start with the primary (lineage names it: ``parents[0]``),
    cite only listed items, and its value is a valid output value.

    The count is checked by ``fold`` (``cardinality_mismatch``), as for every
    combining kind.
    """
    content = _revision(request)
    assert isinstance(payload, SynthesisVerdict)
    primary = content.primary.item_id
    listed = [primary, *(item.item_id for item in content.advisors)]
    for index, draft in enumerate(payload.items):
        refusal = check_draft(
            draft,
            contract=content.output_contract,
            listed=listed,
            min_parents=1,
            first_parent=primary,
        )
        if refusal is not None:
            return f"revised value {index}: {refusal}"
    return None


ADVICE_TEMPLATE = JudgeTemplate(
    template_id="judge.advice/v1",
    call_role="advisor",
    usage_label=_USAGE_LABEL,
    system=_ADVICE_SYSTEM,
    response_model=AdvisoryNote,
    render_user=_render_advice,
    user_frame=_ADVICE_FRAME,
    check_payload=_check_advice,
)

REVISION_TEMPLATE = JudgeTemplate(
    template_id="judge.revision/v1",
    call_role="reviser",
    usage_label=_USAGE_LABEL,
    system=_REVISION_SYSTEM,
    response_model=SynthesisVerdict,
    render_user=_render_revision,
    user_frame=_REVISION_FRAME,
    check_payload=_check_revision,
)


def _strategy(invocation: StrategyInvocation) -> PrimaryAdvisorsStrategy:
    strategy = invocation.strategy
    if not isinstance(strategy, PrimaryAdvisorsStrategy):
        raise StrategyError(f"primary-advisors-llm/v1 cannot plan {strategy.kind}")
    return strategy


def call_bound(strategy: PrimaryAdvisorsStrategy, n_items: int) -> int:
    """``single_call``: 1; ``per_advisor``: one call per advisor plus the reviser (= N)."""
    return 1 if strategy.advice == "single_call" else n_items


def min_items(strategy: PrimaryAdvisorsStrategy) -> int:
    del strategy
    return 2  # one primary and at least one advisor


def output_count(strategy: PrimaryAdvisorsStrategy) -> int:
    del strategy
    return 1


def admit_parameters(
    strategy: PrimaryAdvisorsStrategy, inputs: tuple[InputPort, ...]
) -> tuple[StrategyRefusal, ...]:
    """``metric_best`` is not yet available; a declared primary names a declared input."""
    if strategy.primary == "metric_best":
        return (
            StrategyRefusal(
                code="primary_rule_unavailable",
                message="primary 'metric_best' needs item metric facts; no projectable "
                "contract carries them yet (declare 'declared' or 'first_admissible')",
            ),
        )
    if strategy.primary == "declared":
        declared = {
            f"{port.name}:{position}"
            for port in inputs
            for position in range(1 if port.cardinality == "one" else port.max_items or 0)
        }
        if strategy.primary_item not in declared:
            return (
                StrategyRefusal(
                    code="primary_item_undeclared",
                    message=f"primary_item {strategy.primary_item!r} is not an input position "
                    "of this adaptor",
                ),
            )
    return ()


def precheck(invocation: StrategyInvocation) -> StrategyFailureCode | None:
    """A declared primary that is not among the admissible items fails before any call."""
    strategy = _strategy(invocation)
    ids = [item.item_id for item in invocation.items]
    if strategy.primary == "declared" and strategy.primary_item not in ids:
        return "primary_unavailable"
    return None


def split(invocation: StrategyInvocation) -> tuple[JudgedItem, tuple[JudgedItem, ...]]:
    """``(primary, advisors in declared order)`` by the declared primary rule."""
    strategy = _strategy(invocation)
    judged = judged_items(invocation)
    match strategy.primary:
        case "declared":
            primary = next(item for item in judged if item.item_id == strategy.primary_item)
        case "first_admissible":
            primary = judged[0]
        case "metric_best":
            raise StrategyError(
                "primary-advisors-llm/v1 primary 'metric_best' needs item metric facts; "
                "no projectable contract carries them"
            )
    return primary, tuple(item for item in judged if item is not primary)


def plan_call(
    invocation: StrategyInvocation, earlier: tuple[AdvisoryNote | SynthesisVerdict, ...]
) -> PlannedCall | None:
    strategy = _strategy(invocation)
    primary, advisors = split(invocation)
    if len(earlier) >= call_bound(strategy, len(invocation.items)):
        return None
    if strategy.advice == "per_advisor" and len(earlier) < len(advisors):
        content = AdviceRequest(
            criterion=strategy.criterion,
            output_contract=invocation.output_contract,
            primary=primary,
            advisor=advisors[len(earlier)],
            guidance=invocation.task_guidance,
        )
        return PlannedCall(role="advisor", template=ADVICE_TEMPLATE, content=content)
    notes = tuple(note for note in earlier if isinstance(note, AdvisoryNote))
    content = RevisionRequest(
        criterion=strategy.criterion,
        output_contract=invocation.output_contract,
        primary=primary,
        advisors=advisors,
        notes=notes,
        guidance=invocation.task_guidance,
    )
    return PlannedCall(role="reviser", template=REVISION_TEMPLATE, content=content)


def fold(
    invocation: StrategyInvocation, verdicts: tuple[AdvisoryNote | SynthesisVerdict, ...]
) -> CombinedItems:
    """The reviser's one value, stamped; the advisor notes are evidence, not output."""
    _strategy(invocation)
    revision = verdicts[-1] if verdicts else None
    if not isinstance(revision, SynthesisVerdict):
        raise StrategyError("primary-advisors-llm/v1 folds a chain that ends with the reviser")
    return combined_items(invocation, revision.items, declared=1)
