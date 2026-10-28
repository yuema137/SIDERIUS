"""Enforce the catalog `PROTECTED_FIELDS` on values a custom COMBINE emitted.

Works on the JSON-compatible dump of already validated values. Authors leave
protected fields unset; the framework then writes the provenance label into
``stamp-source`` locations. Any author-set protected value is refused rather
than silently replaced, so the rule stays visible to the author.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

from workflows.definition.catalog import PROTECTED_FIELDS, ProtectedField

_UNSET: tuple[Any, ...] = (None, "", [], {})


def _tokens(path: str) -> list[str]:
    """``"findings[].source"`` -> ``["findings", "[]", "source"]``."""
    tokens: list[str] = []
    for segment in path.split("."):
        if segment.endswith("[]"):
            tokens.extend(token for token in (segment[:-2], "[]") if token)
        else:
            tokens.append(segment)
    return tokens


def _locations(value: Any, tokens: list[str]) -> Iterator[tuple[dict[str, Any], str]]:
    """Yield every (containing object, key) the tokens address; absent parents yield none."""
    head, rest = tokens[0], tokens[1:]
    if head == "[]":
        if isinstance(value, list):
            for item in value:
                yield from _locations(item, rest)
    elif isinstance(value, dict):
        if rest:
            yield from _locations(value.get(head), rest)
        else:
            yield value, head


def _apply(rule: ProtectedField, value: Any, label: str) -> None:
    for container, key in _locations(value, _tokens(rule.path)):
        current = container.get(key)
        if rule.rule == "forbid-value":
            if current == rule.value:
                raise ValueError(f"protected field {rule.path!r} may not be {rule.value!r}")
        elif current not in _UNSET:
            raise ValueError(
                f"protected field {rule.path!r} is framework-owned; leave it unset "
                f"(found {current!r})"
            )
        elif rule.rule == "stamp-source":
            container[key] = label


def stamp_protected(contract: str, values: list[Any], label: str) -> list[Any]:
    """Return a stamped copy of ``values``; raise ``ValueError`` on an author-set field."""
    stamped = copy.deepcopy(values)
    for value in stamped:
        for rule in PROTECTED_FIELDS[contract]:
            _apply(rule, value, label)
    return stamped
