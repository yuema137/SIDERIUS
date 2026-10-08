"""Lossless JSON transport of the two owner-permitted formal-policy deltas."""

import math
from typing import Annotated, Literal

from pydantic import Field

FormalDelta = (
    Annotated[float, Field(strict=True, allow_inf_nan=False)] | Literal["nan", "+inf", "-inf"]
)
FORMAL_DELTA_FIELDS = frozenset({"skip_formal_min_delta", "bypass_formal_time_budget_min_delta"})


def encode_formal_delta(value: float) -> FormalDelta:
    """Preserve even unused nonfinite values without nonstandard JSON numbers."""
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "+inf" if value > 0 else "-inf"
    return value


def decode_formal_delta(value: FormalDelta) -> float:
    return float(value)
