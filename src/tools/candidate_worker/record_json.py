"""Lossless JSON bytes for candidate-worker persistence.

Kept free of native imports: the parent worker module imports it before any
child binds the task (see test_parent_import_does_not_discover_native_nodes).
"""

from typing import Any

from pydantic import BaseModel
from pydantic_core import to_json


def record_json(value: BaseModel, *, indent: int | None = None, **dump: Any) -> bytes:
    """``model_dump_json`` bytes that keep inf/NaN for the worker's rereads.

    Pydantic's default writes inf/NaN as ``null``, which a later
    ``model_validate_json`` refuses or reads back as ``None`` (#1012, #1046).
    They are written as the strings ``"Infinity"``, ``"-Infinity"`` and
    ``"NaN"``, which those readers parse back exactly; finite documents are
    byte-identical. Every candidate-worker JSON persistence write uses this.
    """
    return to_json(value.model_dump(mode="json", **dump), indent=indent, inf_nan_mode="strings")
