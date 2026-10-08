"""Explicit per-call transport policy; absence is distinct from unlimited."""

from pydantic import BaseModel, ConfigDict


class RetryPolicy(BaseModel):
    """A supplied policy owns its limit; None retains unbounded status retries.

    A missing optional policy means inherit the owning bridge's limit. Keep
    existing integer semantics: 0 and 1 both permit one initial request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    max_retries: int | None
