# execute_tools/health_checks/standard_views.py
"""The framework-standard Health view payload vocabulary (Step 08c, C1).

08b made the view TRANSPORT opaque: a provider materializes a
:class:`~execute_tools.health_checks._view_provider.HealthView` whose payload
the engine never inspects, under a capability key it never interprets. What
it deliberately did not define is any standard payload CONTENT — every
provider/check pair had to invent its own shape.

This module is that missing vocabulary, for exactly two capabilities the
parent design (§6.3) standardizes:

```text
categorical_predictions   one 1-D integer stream of predicted symbols
continuous_samples        one 1-D floating stream of sample values
```

A pack that emits one of these payloads can be consumed by the generic
collapse checks without either side knowing the other's task. A plugin-local
key (``vendor.whatever``) remains exactly as legitimate as a standard one —
standard vs plugin-local differs ONLY in who ships the payload model and the
consuming checks. Growth of the STANDARD set requires a forcing task; this
module is deliberately not a catalog.

**The frozen ABI** (Step 08c child design §3.1):

* **NumPy-backed, never dense Python objects.** A 5.16 M-sample stream is
  one array, not five million floats.
* **1-D at the standard-view boundary.** The provider owns the projection
  from its artifact's geometry to the stream.
* **Strictly typed, no coercion.** dtype KINDS are checked, not converted:
  categorical accepts signed/unsigned integers only; continuous accepts
  floating dtypes only. bool, strings, objects, Python sequences and — for
  the continuous payload — integer arrays are rejected with the offender
  named.
* **Read-only, no-copy.** The payload stores a read-only VIEW sharing the
  provider's memory (``np.shares_memory``); a check mutating it raises.
  Construction changes neither the provider array's contents nor its own
  writeability state.
* **Runtime-only.** Payloads are never persisted; verdicts and metrics are.
* **Engine-opaque.** No engine module references these keys or types — the
  contract binds provider↔check only.

Payload models validate SHAPE/TYPE only. Whether values are *healthy*
(finite, in-range) is check arithmetic: an empty stream is check-level
ERROR, a non-finite or out-of-range value is check-level FAILED (§3.2a) —
both are accepted here so a provider can hand over exactly what it read.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

CATEGORICAL_PREDICTIONS = "categorical_predictions"
"""Capability key for the standard 1-D integer prediction stream."""

CONTINUOUS_SAMPLES = "continuous_samples"
"""Capability key for the standard 1-D floating sample stream."""


_CATEGORICAL_DTYPE_KINDS = frozenset({"i", "u"})
_CONTINUOUS_DTYPE_KINDS = frozenset({"f"})


def _validated_readonly_stream(
    value: object,
    *,
    field_name: str,
    allowed_kinds: frozenset[str],
    expected: str,
) -> np.ndarray:
    """Validate one standard stream and return a read-only no-copy view.

    Args:
        value: the provider-supplied candidate payload.
        field_name: payload field, named in every rejection.
        allowed_kinds: accepted ``dtype.kind`` values.
        expected: human phrase for the accepted dtype family.

    Returns:
        A new ndarray VIEW over the same memory with ``writeable=False``.
        The supplied array's own flags and contents are untouched.

    Raises:
        ValueError: non-array input, wrong dimensionality, or a dtype whose
            kind is not accepted — each naming the offender. No coercion is
            ever attempted.
    """
    if not isinstance(value, np.ndarray):
        raise ValueError(
            f"{field_name} must be a numpy.ndarray, got {type(value).__name__}; "
            "providers construct arrays explicitly — Python sequences are not coerced"
        )
    if value.ndim != 1:
        raise ValueError(
            f"{field_name} must be 1-D at the standard-view boundary, got shape "
            f"{value.shape}; the provider owns the projection to the stream"
        )
    if value.dtype.kind not in allowed_kinds:
        raise ValueError(
            f"{field_name} must have {expected} dtype, got {value.dtype!r} "
            f"(kind {value.dtype.kind!r}); no coercion is performed"
        )
    view = value.view()
    view.flags.writeable = False
    return view


class CategoricalPredictionsPayload(BaseModel):
    """Payload for :data:`CATEGORICAL_PREDICTIONS`: one symbol per prediction.

    Symbols are integer class indices in whatever range the task's
    ``symbol_cardinality`` declares; range validity is CHECK arithmetic
    (§3.2a), not payload validation — the provider hands over what it read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    symbols: np.ndarray = Field(
        description=(
            "1-D integer array (dtype kind 'i' or 'u') of predicted symbols, "
            "stored as a read-only view of the provider's array."
        ),
    )

    @field_validator("symbols", mode="before")
    @classmethod
    def _validate_symbols(cls, value: object) -> np.ndarray:
        return _validated_readonly_stream(
            value,
            field_name="symbols",
            allowed_kinds=_CATEGORICAL_DTYPE_KINDS,
            expected="a signed or unsigned integer",
        )


class ContinuousSamplesPayload(BaseModel):
    """Payload for :data:`CONTINUOUS_SAMPLES`: one floating value per sample.

    The stream keeps the artifact's NATIVE floating dtype (a float32
    artifact arrives as float32); numerical estimator precision — such as
    float64 accumulation — is owned by the consuming check (§3.5a).
    Non-finite values are accepted here and condemned by the check (§3.2a).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    samples: np.ndarray = Field(
        description=(
            "1-D floating array (dtype kind 'f') of sample values, stored as "
            "a read-only view of the provider's array."
        ),
    )

    @field_validator("samples", mode="before")
    @classmethod
    def _validate_samples(cls, value: object) -> np.ndarray:
        return _validated_readonly_stream(
            value,
            field_name="samples",
            allowed_kinds=_CONTINUOUS_DTYPE_KINDS,
            expected="a floating",
        )
