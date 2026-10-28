"""Native value types for the catalog contracts a custom adaptor may read or emit.

The workflow catalog names contracts with inert strings. This module is the one
place a custom adaptor resolves a contract id to its native Pydantic type, so
the parent (before launch and after the child returns) and the child (before
calling user code) validate against the same models. ``optional.*`` contracts
carry a value when an adaptor reads or emits them; ``None`` is not a value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import cache
from types import MappingProxyType
from typing import Any

from pydantic import TypeAdapter

from agent.schemas.hyperparam_tuning import ExpertAdviceInput, HyperparamTuningOutput
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import ExpertContextItem, ProposalOutput
from agent.schemas.validator import ValidatorOutput

#: Contracts a custom adaptor input port may name. Authority contracts are
#: readable (an adaptor may choose among scored items); they are never emittable
#: (`workflows.definition.catalog.CUSTOM_EMITTABLE`).
READABLE_CONTRACT_TYPES: Mapping[str, Any] = MappingProxyType(
    {
        "interpretation.output": InterpretationOutput,
        "literature.output": LiteratureReviewOutput,
        "proposal.output": ProposalOutput,
        "implementation.output": ImplementorOutput,
        "validation.output": ValidatorOutput,
        "tuning.output": HyperparamTuningOutput,
        "optional.text": str,
        "optional.expert-advice": ExpertAdviceInput,
        "optional.expert-context": list[ExpertContextItem],
    }
)


@cache
def values_adapter(contract: str) -> TypeAdapter[tuple[Any, ...]]:
    """Validator for an ordered tuple of values of one readable contract."""
    return TypeAdapter(tuple[READABLE_CONTRACT_TYPES[contract], ...])


def validate_values(contract: str, payload: object) -> tuple[Any, ...]:
    """Validate JSON-compatible values into native models; raises ``ValueError``."""
    return values_adapter(contract).validate_python(payload)


def dump_values(contract: str, values: tuple[Any, ...]) -> list[Any]:
    """JSON-compatible form of validated values (native serialization rules)."""
    return values_adapter(contract).dump_python(values, mode="json")


def canonical_json(value: object) -> bytes:
    """Byte form used for every digest and determinism comparison."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
