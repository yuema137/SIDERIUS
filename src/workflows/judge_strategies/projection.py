"""Contract-owned item projectors and the builder of admissible ``StrategyItem``s.

A projector turns one verified value of its contract into a bounded, deterministic
``ItemProjection`` (texts truncated by a fixed rule, list entries capped with the
omitted count recorded). System identities such as ``candidate_id`` and
self-reported confidences are not projected. A contract without a projector cannot
be judged; ``admit_llm_strategy`` refuses it.
"""

from collections.abc import Callable
from types import MappingProxyType

from pydantic import BaseModel

from agent.schemas.judge import MAX_PROJECTED_CHARS, ItemProjection, ProjectedField
from workflows.adaptors.items import AdaptorItem, AdaptorStrategyError, admit_items

from .models import StrategyItem

#: List entries projected per value; the rest are counted, never silently dropped.
MAX_PROJECTED_ENTRIES = 24


def _field(name: str, text: str | None) -> ProjectedField:
    return ProjectedField(name=name, text=(text or "")[:MAX_PROJECTED_CHARS])


def _proposal(value: BaseModel) -> tuple[ProjectedField, ...]:
    from agent.schemas.proposal import ProposalOutput

    if not isinstance(value, ProposalOutput):
        raise AdaptorStrategyError("proposal.output projector received another value type")
    return (
        _field("model_name", value.model_name),
        _field("model_description", value.model_description),
        _field("mathematical_definition", value.mathematical_definition),
        _field("motivation", value.motivation),
    )


def _literature(value: BaseModel) -> tuple[ProjectedField, ...]:
    from agent.schemas.literature_review import LiteratureReviewOutput

    if not isinstance(value, LiteratureReviewOutput):
        raise AdaptorStrategyError("literature.output projector received another value type")
    shown = value.findings[:MAX_PROJECTED_ENTRIES]
    fields: list[ProjectedField] = []
    for index, finding in enumerate(shown):
        fields.append(_field(f"findings[{index}].content", finding.content))
        fields.append(_field(f"findings[{index}].source_ref", finding.source_ref))
    fields.append(_field("findings.omitted", str(len(value.findings) - len(shown))))
    return tuple(fields)


ITEM_PROJECTORS: MappingProxyType[str, Callable[[BaseModel], tuple[ProjectedField, ...]]] = (
    MappingProxyType({"proposal.output": _proposal, "literature.output": _literature})
)


def project_item(contract: str, value: BaseModel) -> ItemProjection:
    projector = ITEM_PROJECTORS.get(contract)
    if projector is None:
        raise AdaptorStrategyError(f"no LLM item projector is registered for {contract!r}")
    return ItemProjection(contract=contract, fields=projector(value))


def strategy_items(items: tuple[AdaptorItem, ...]) -> tuple[StrategyItem, ...]:
    """Project B6's admissible items, re-checking the B6 admissibility rule and order.

    Refuses (``AdaptorStrategyError``) any item ``workflows.adaptors.admit`` does not
    admit and any tuple not in declared order: B2 never judges an inadmissible input.
    """
    for item, admission in zip(items, admit_items(items), strict=True):
        if admission.admission != "admissible":
            raise AdaptorStrategyError(
                f"adaptor input {item.ref.port}:{item.ref.position} is {admission.admission}; "
                "an LLM strategy judges admissible items only"
            )
    projected: list[StrategyItem] = []
    for item in items:
        assert item.value is not None  # admissible implies succeeded
        projected.append(
            StrategyItem(
                ref=item.ref,
                contract=item.contract,
                projection=project_item(item.contract, item.value),
            )
        )
    return tuple(projected)
