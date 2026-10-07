"""Explicit task-bound policy for verifying an inference-only static refusal."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InferencePreflightPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["bounded_measurement", "static_only"] = "bounded_measurement"
    max_batches: int = Field(default=3, gt=0)


_ACTIVE: ContextVar[InferencePreflightPolicy | None] = ContextVar(
    "inference_preflight_policy", default=None
)


def active_inference_preflight_policy() -> InferencePreflightPolicy:
    return _ACTIVE.get() or InferencePreflightPolicy()


@contextmanager
def bind_inference_preflight_policy(policy: InferencePreflightPolicy) -> Iterator[None]:
    resolved = InferencePreflightPolicy.model_validate(policy)
    token = _ACTIVE.set(resolved)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
