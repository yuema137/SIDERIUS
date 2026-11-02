"""Versioned strict JSON for typed records; legacy documents remain readable.

The reserved metadata member records the encoding version and paths of float
leaves represented as strings. Paths distinguish float NaN from the string
"NaN", including inside Any/union fields. Ordinary fields retain their layout.
"""

import math
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictStr
from pydantic_core import to_json, to_jsonable_python

ENCODING_VERSION = "siderius.nonfinite/v1"
EncodingVersion = Literal["siderius.nonfinite/v1"]
METADATA = "$siderius_encoding"
_TOKENS = {"NaN": float("nan"), "Infinity": float("inf"), "-Infinity": float("-inf")}


FloatPath = Annotated[
    list[StrictStr | Annotated[int, Field(strict=True, ge=0)]], Field(min_length=1)
]


class EncodingMetadata(BaseModel):
    """Untrusted record metadata, validated before dereferencing any path."""

    model_config = ConfigDict(extra="forbid", strict=True)
    version: EncodingVersion
    floats: list[FloatPath]
    wrapped: bool = False


def _restore_float(value: dict[str, Any], path: list[str | int]) -> None:
    try:
        parent: Any = value
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = _TOKENS[parent[path[-1]]]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("invalid non-finite float reference") from exc


def _encode(value: Any, path: list[str | int], paths: list[list[str | int]]) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        paths.append(path)
        return "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {key: _encode(item, [*path, key], paths) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item, [*path, index], paths) for index, item in enumerate(value)]
    return value


def _metadata(paths: list[list[str | int]], *, wrapped: bool = False) -> dict[str, Any]:
    # Metadata must not make canonical bytes depend on dictionary insertion order.
    result: dict[str, Any] = {"version": ENCODING_VERSION, "floats": sorted(paths, key=to_json)}
    if wrapped:
        result["wrapped"] = True
    return result


def encoded_record(value: dict[str, Any], *, always: bool = True) -> dict[str, Any]:
    """Encode JSON-mode data, reserving metadata rather than guessing from strings."""
    if METADATA in value:
        raise ValueError(f"reserved record member: {METADATA}")
    paths: list[list[str | int]] = []
    encoded = _encode(value, [], paths)
    if always or paths:
        encoded[METADATA] = _metadata(paths)
    return encoded


def decode_record(value: Any) -> Any:
    """Decode versioned records without mutating input; leave legacy data alone."""
    if isinstance(value, list):
        return [decode_record(item) for item in value]
    if not isinstance(value, dict) or METADATA not in value:
        return value
    metadata = EncodingMetadata.model_validate(value[METADATA])
    # Copy the JSON tree: validators must not mutate their caller's input.
    import copy

    decoded = copy.deepcopy({key: item for key, item in value.items() if key != METADATA})
    seen: set[tuple[str | int, ...]] = set()
    for path in metadata.floats:
        identity = tuple(path)
        if identity in seen:
            raise ValueError("duplicate non-finite float path")
        seen.add(identity)
        _restore_float(decoded, path)
    if metadata.wrapped:
        if set(decoded) != {"value"}:
            raise ValueError("malformed wrapped canonical value")
        return decoded["value"]
    return decoded


def _restore_nonfinite(json_value: Any, python_value: Any) -> Any:
    """Undo Pydantic's null projection in Any fields before our encoding runs."""
    if isinstance(python_value, float) and not math.isfinite(python_value):
        return python_value
    if isinstance(json_value, dict) and isinstance(python_value, dict):
        return {
            key: _restore_nonfinite(item, python_value.get(key)) for key, item in json_value.items()
        }
    if (
        isinstance(json_value, list)
        and isinstance(python_value, (list, tuple))
        and len(json_value) == len(python_value)
    ):
        return [_restore_nonfinite(a, b) for a, b in zip(json_value, python_value, strict=True)]
    return json_value


def model_record_value(value: BaseModel, **dump: Any) -> dict[str, Any]:
    """Keep JSON aliases/serializers while recovering float leaves lost by Any."""
    return _restore_nonfinite(
        value.model_dump(mode="json", **dump),
        to_jsonable_python(value.model_dump(**dump), inf_nan_mode="constants"),
    )


def record_json(value: BaseModel, *, indent: int | None = None, **dump: Any) -> bytes:
    """Strict, lossless record bytes; the model's JSON serializers still apply."""
    return to_json(encoded_record(model_record_value(value, **dump)), indent=indent)


def canonical_value(value: Any) -> Any:
    """Retain finite canonical bytes; version non-finite data with typed paths."""
    if isinstance(value, dict):
        return encoded_record(value, always=False)
    paths: list[list[str | int]] = []
    encoded = _encode(value, ["value"], paths)
    if not paths:
        return value
    return {
        "value": encoded,
        METADATA: _metadata(paths, wrapped=True),
    }


class RecordModel(BaseModel):
    """Decode before validation, preserving strict JSON tuple/date semantics."""

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any) -> Self:
        import json

        raw = json.loads(json_data)
        if isinstance(raw, dict) and METADATA in raw:
            json_data = to_json(decode_record(raw), inf_nan_mode="constants")
        return super().model_validate_json(json_data, **kwargs)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        return super().model_validate(decode_record(obj), **kwargs)
