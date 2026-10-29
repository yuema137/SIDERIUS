"""Declared JSON encodings for candidate-worker persistence (issue #1046).

Each write names its artifact class; the class picks one existing owner:

* ``"record"``: files people and the dashboard read (captured node records
  such as ``run_output_*.json``, request/receipt control documents). Strict
  JSON through the storage owner
  :func:`execute_tools.scoring_utils.coerce_nonfinite_to_none`, so inf/NaN are
  written as ``null`` exactly as the native tuner writes ``run_output``.
* ``"internal"``: documents a later worker phase rereads and compares (node
  inputs, proposal seed, fan-out payloads, graph tuning input). The
  unit-transport constant encoding (:func:`unit_transport.constants_json`), so
  inf/NaN survive the reread.

Kept free of native imports: the parent worker module imports it before any
child binds the task (see ``test_parent_import_does_not_discover_native_nodes``).
"""

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_core import to_json

from execute_tools.scoring_utils import coerce_nonfinite_to_none

from .unit_transport import constants_json

ArtifactClass = Literal["record", "internal"]


def artifact_json(
    value: BaseModel, *, kind: ArtifactClass, indent: int | None = None, **dump: Any
) -> bytes:
    """Serialize ``value`` with the owner its declared artifact class selects."""
    if kind == "internal":
        return constants_json(value, indent=indent, **dump)
    stored = coerce_nonfinite_to_none(value.model_dump(mode="json", **dump))
    return to_json(stored, indent=indent)


def stored_projection[Model: BaseModel](value: Model) -> Model:
    """``value`` as a ``record`` write and reread would give it back.

    Used to compare an in-memory output with an existing native record without
    treating the storage owner's inf/NaN -> null projection as disagreement.
    """
    return type(value).model_validate_json(artifact_json(value, kind="record"))
