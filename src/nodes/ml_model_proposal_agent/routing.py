"""Proposer-owned effective routes, independent of workflow configuration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict


class ProposerRoute(BaseModel):
    """All bridge settings that can differ between proposal stages."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model_id: str | None
    reasoning_effort: str | None
    max_retries: int | None

    def bridge_kwargs(self) -> dict[str, Any]:
        # Preserve the bridge's existing omitted-effort constructor contract.
        values = self.model_dump()
        if self.reasoning_effort is None:
            values.pop("reasoning_effort")
        return values


class ProposerRouting(BaseModel):
    """Resolved once; custom reasoning stages use the reasoning route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    comparison: ProposerRoute
    reasoning: ProposerRoute
    proposing: ProposerRoute

    def for_stage(self, name: str) -> ProposerRoute:
        if name == "comparison":
            return self.comparison
        if name == "proposing":
            return self.proposing
        return self.reasoning


def resolve_proposer_routing(
    legacy: ProposerRoute, stage_options: Mapping[str, Any]
) -> ProposerRouting:
    """Apply supplied flat stage keys, preserving explicit None and zero.

    Missing fields inherit the legacy constructor's selection. Workflow callers
    supply complete stage settings; direct legacy callers may omit them all.
    This resolver neither reads credentials nor constructs provider clients.
    """
    routes = {}
    for stage in ProposerRouting.model_fields:
        values = legacy.model_dump()
        for field in ProposerRoute.model_fields:
            key = f"{stage}_{field}"
            if key in stage_options:
                values[field] = stage_options[key]
        routes[stage] = ProposerRoute.model_validate(values)
    return ProposerRouting.model_validate(routes)
