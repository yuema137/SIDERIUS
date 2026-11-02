"""Worker persistence classes: typed strict records or private unit transport.

`record` delegates to core.record_encoding, whose version/type metadata preserves
non-finite floats without nulls or bare JSON constants. `internal` retains the
existing private transport encoding. Unknown classes fail at runtime.
"""

from typing import Any, Literal

from pydantic import BaseModel

from core.record_encoding import record_json

from .unit_transport import constants_json

ArtifactClass = Literal["record", "internal"]


def artifact_json(
    value: BaseModel, *, kind: ArtifactClass, indent: int | None = None, **dump: Any
) -> bytes:
    """Serialize ``value`` with the owner its declared artifact class selects."""
    if kind == "internal":
        return constants_json(value, indent=indent, **dump)
    if kind == "record":
        return record_json(value, indent=indent, **dump)
    raise ValueError(f"unknown artifact class: {kind!r}")
