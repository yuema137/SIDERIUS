"""Exact model transport across the unit process boundary (B3-3).

A payload is two JSON lines: the `model_fields_set` tree of every model in the
value, then the value's complete JSON (inf/NaN as JSON constants), bounded by
the 4 MiB control envelope. Decoding validates the JSON and restores
each model's set fields, because protocol mappings, LLM-config defaults and
reconciliation read `model_fields_set` (an `exclude_unset` dump cannot carry
fields that validators fill). Encoding refuses any value that is not a byte
fixpoint of decode/re-encode.
"""

import json
from dataclasses import fields, is_dataclass
from typing import Any

from pydantic import BaseModel
from pydantic_core import to_json

from core.control_json import JSON_LIMIT, ControlOverflow


def _set_tree(value: Any) -> Any:
    """Set fields of every nested model; `None` where no model is reachable."""
    if isinstance(value, BaseModel):
        children = {name: _set_tree(getattr(value, name)) for name in type(value).model_fields}
        return {
            "set": sorted(value.model_fields_set),
            "fields": {name: tree for name, tree in children.items() if tree is not None},
        }
    if is_dataclass(value) and not isinstance(value, type):
        children = {item.name: _set_tree(getattr(value, item.name)) for item in fields(value)}
        kept = {name: tree for name, tree in children.items() if tree is not None}
        return {"fields": kept} if kept else None
    if isinstance(value, (list, tuple)):
        items = [_set_tree(item) for item in value]
        return {"items": items} if any(item is not None for item in items) else None
    if isinstance(value, dict):
        entries = {str(key): _set_tree(item) for key, item in value.items()}
        kept = {key: tree for key, tree in entries.items() if tree is not None}
        return {"entries": kept} if kept else None
    return None


def _restore(value: Any, tree: Any) -> None:
    if tree is None:
        return
    if isinstance(value, BaseModel) and "set" in tree:
        # The attribute Pydantic's own `model_construct(_fields_set=...)` assigns.
        object.__setattr__(value, "__pydantic_fields_set__", set(tree["set"]))
        children = tree["fields"]
    elif is_dataclass(value) and not isinstance(value, BaseModel) and "fields" in tree:
        children = tree["fields"]
    elif isinstance(value, (list, tuple)) and len(tree.get("items", ())) == len(value):
        for item, child in zip(value, tree["items"], strict=True):
            _restore(item, child)
        return
    elif isinstance(value, dict) and "entries" in tree:
        for key, item in value.items():
            _restore(item, tree["entries"].get(str(key)))
        return
    else:
        raise ValueError("unit transport set-field tree disagrees with its value")
    for name, child in children.items():
        _restore(getattr(value, name), child)


def decode_transport[Transported: BaseModel](
    kind: type[Transported], payload: bytes
) -> Transported:
    tree, document = payload.split(b"\n", 1)
    value = kind.model_validate_json(document)
    _restore(value, json.loads(tree))
    return value


def _encoded(value: BaseModel) -> bytes:
    tree = json.dumps(_set_tree(value), separators=(",", ":")).encode()
    # Keep inf/NaN as JSON constants: scoring sentinels and launch knobs use them.
    document = to_json(value.model_dump(), inf_nan_mode="constants")
    payload = tree + b"\n" + document
    if len(payload) > JSON_LIMIT:
        raise ControlOverflow(f"{type(value).__name__} unit transport exceeds 4 MiB")
    return payload


def encode_transport(value: BaseModel) -> bytes:
    """Serialize `value`, refusing any value the decoder would not reproduce.

    The check is a byte fixpoint (decode, re-encode, compare), which is NaN-safe
    and covers both the value and every model's set fields.
    """
    payload = _encoded(value)
    try:
        decoded = decode_transport(type(value), payload)
    except ValueError:
        decoded = None
    if decoded is None or type(decoded) is not type(value) or _encoded(decoded) != payload:
        raise ValueError(f"{type(value).__name__} does not round-trip through unit transport")
    return payload
