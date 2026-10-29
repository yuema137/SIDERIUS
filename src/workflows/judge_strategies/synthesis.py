"""Synthesized values of the combining kinds: admissibility, stamping, combined items.

A draft value must be a native value of the invocation's output contract
(``workflows.custom_adaptors.contracts``) that leaves every catalogued
framework-owned field unset; the fold then stamps the provenance label into the
``stamp-source`` fields (``workflows.custom_adaptors.protected``), exactly as for a
custom COMBINE (operator decision B6-D3). Only contracts in
``catalog.CUSTOM_EMITTABLE`` can be synthesized; ``admit_llm_strategy`` refuses
any other output contract.
"""

from collections.abc import Iterable

from pydantic import JsonValue

from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.judge import SynthesizedDraft
from workflows.custom_adaptors.contracts import dump_values, native_type, validate_values
from workflows.custom_adaptors.protected import stamp_protected
from workflows.definition.catalog import PROTECTED_FIELDS

from .models import CombinedItem, CombinedItems, StrategyInvocation
from .plan import StrategyFoldFailure

#: Label used only while checking a draft; the fold stamps the invocation's own label.
_CHECK_LABEL = "adaptor:check"


def output_facts(contract: str) -> dict[str, JsonValue]:
    """What the LLM must produce: the contract's JSON schema and its framework-owned fields."""
    owned: list[JsonValue] = [
        {"path": rule.path, "rule": rule.rule, "value": rule.value}
        for rule in PROTECTED_FIELDS[contract]
    ]
    return {
        "contract": contract,
        "json_schema": native_type(contract).model_json_schema(),
        "framework_owned_fields": owned,
    }


def _stamped(contract: str, value: dict[str, JsonValue], label: str) -> dict[str, JsonValue]:
    """Validate, stamp and re-validate one value; ``ValueError`` names the first defect."""
    authored = dump_values(contract, validate_values(contract, [value]))
    (stamped,) = dump_values(
        contract, validate_values(contract, stamp_protected(contract, authored, label))
    )
    return stamped


def check_draft(
    draft: SynthesizedDraft,
    *,
    contract: str,
    listed: Iterable[str],
    min_parents: int,
    first_parent: str | None = None,
) -> str | None:
    """Why ``draft`` is inadmissible for its request, or ``None``.

    Parents must be distinct listed ids, at least ``min_parents`` of them, and
    start with ``first_parent`` when one is given (a revision names its primary
    first); the value must be a valid value of ``contract`` whose framework-owned
    fields are unset.
    """
    parents = draft.parents
    if len(set(parents)) != len(parents):
        return f"parents {list(parents)} repeat an item"
    foreign = sorted(set(parents) - set(listed))
    if foreign:
        return f"parents {foreign} are not listed items"
    if len(parents) < min_parents:
        return f"{len(parents)} parents cited; at least {min_parents} are required"
    if first_parent is not None and parents[0] != first_parent:
        return f"parents must start with {first_parent!r}, not {parents[0]!r}"
    try:
        _stamped(contract, draft.value, _CHECK_LABEL)
    except ValueError as error:
        return f"value is not an admissible {contract} value: {error}"
    return None


def provenance_label(invocation: StrategyInvocation) -> str:
    """Stamped into ``stamp-source`` fields of every value this invocation synthesizes."""
    return f"adaptor:{invocation.adaptor_id}/{invocation.strategy.kind}"


def combined_items(
    invocation: StrategyInvocation, drafts: tuple[SynthesizedDraft, ...], *, declared: int
) -> CombinedItems:
    """Stamped ``CombinedItems`` from checked drafts.

    Raises ``StrategyFoldFailure("cardinality_mismatch")`` when the count differs
    from the declared ``declared`` or leaves B6's ``expected_count``.
    """
    bound = invocation.expected_count
    if len(drafts) != declared or not bound.min <= len(drafts) <= bound.max:
        raise StrategyFoldFailure(
            "cardinality_mismatch",
            f"{len(drafts)} values synthesized; declared {declared}, "
            f"expected {bound.min}..{bound.max}",
        )
    contract = invocation.output_contract
    label = provenance_label(invocation)
    items = []
    for index, draft in enumerate(drafts):
        value = _stamped(contract, draft.value, label)
        items.append(
            CombinedItem(
                output_index=index,
                parents=draft.parents,
                value=value,
                value_sha256=canonical_sha256(value),
            )
        )
    return CombinedItems(contract=contract, items=tuple(items))
