"""Native value types for the catalog contracts a custom adaptor may read or emit.

The workflow catalog names contracts with inert strings. This module is the one
place a custom adaptor resolves a contract id to its native Pydantic type, so
the parent (before launch and after the child returns) and the child (before
calling user code) validate against the same models. ``optional.*`` contracts
carry a value when an adaptor reads or emits them; ``None`` is not a value.

Resolution is lazy: importing this package never imports native schema modules
(or, through them, ``torch`` and plugin discovery); only validating a value does.
Digests use the shared ``core.canonical_json`` owner.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from functools import cache
from types import MappingProxyType
from typing import Any, Literal

from pydantic import TypeAdapter

_Shape = Literal["value", "list"]

#: Contract id -> (module, attribute, shape) of its native value type. Authority
#: contracts are readable (an adaptor may choose among scored items); they are
#: never emittable (`workflows.definition.catalog.CUSTOM_EMITTABLE`).
_NATIVE_TYPES: Mapping[str, tuple[str, str, _Shape]] = MappingProxyType(
    {
        "interpretation.output": ("agent.schemas.interpretation", "InterpretationOutput", "value"),
        "literature.output": ("agent.schemas.literature_review", "LiteratureReviewOutput", "value"),
        "proposal.output": ("agent.schemas.proposal", "ProposalOutput", "value"),
        "implementation.output": ("agent.schemas.implementor", "ImplementorOutput", "value"),
        "validation.output": ("agent.schemas.validator", "ValidatorOutput", "value"),
        "tuning.output": ("agent.schemas.hyperparam_tuning", "HyperparamTuningOutput", "value"),
        "optional.text": ("builtins", "str", "value"),
        "optional.expert-advice": ("agent.schemas.hyperparam_tuning", "ExpertAdviceInput", "value"),
        "optional.expert-context": ("agent.schemas.proposal", "ExpertContextItem", "list"),
    }
)

#: Contracts a custom adaptor input port may name.
READABLE_CONTRACTS = frozenset(_NATIVE_TYPES)


@cache
def native_type(contract: str) -> Any:
    """Import and return the native value type of one readable contract."""
    module, attribute, shape = _NATIVE_TYPES[contract]
    value_type = getattr(importlib.import_module(module), attribute)
    return list[value_type] if shape == "list" else value_type


@cache
def values_adapter(contract: str) -> TypeAdapter[tuple[Any, ...]]:
    """Validator for an ordered tuple of values of one readable contract."""
    return TypeAdapter(tuple[native_type(contract), ...])


def validate_values(contract: str, payload: object) -> tuple[Any, ...]:
    """Validate JSON-compatible values into native models; raises ``ValueError``."""
    return values_adapter(contract).validate_python(payload)


def dump_values(contract: str, values: tuple[Any, ...]) -> list[Any]:
    """JSON-compatible form of validated values (native serialization rules)."""
    return values_adapter(contract).dump_python(values, mode="json")
