"""JSON observations of resolved launch dataclasses, without resolving defaults."""

from dataclasses import fields, is_dataclass
from typing import cast

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from workflows.formal_delta import FORMAL_DELTA_FIELDS, encode_formal_delta

_JSON = TypeAdapter(JsonValue, config=ConfigDict(allow_inf_nan=False))


def _native(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return json_launch_values(value)
    if isinstance(value, dict):
        return {key: _native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native(item) for item in value]
    return value


def json_launch_values(value) -> dict[str, JsonValue]:
    """Preserve actual values; field owners may explicitly omit an absent addition."""
    result: dict[str, JsonValue] = {}
    for field in fields(value):
        item = getattr(value, field.name)
        if item is None and field.metadata.get("omit_if_none"):
            continue
        if field.name in FORMAL_DELTA_FIELDS:
            item = encode_formal_delta(cast(float, item))
        result[field.name] = _JSON.validate_python(_native(item))
    return result
