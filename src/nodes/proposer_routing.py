"""Proposer-owned effective routes, independent of workflow configuration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from agent.llm_transport.contracts import PydanticTransportConfig


class ProposerRoute(BaseModel):
    """All bridge settings that can differ between proposal stages."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model_id: str | None
    reasoning_effort: str | None
    max_output_tokens: int | None = Field(
        default=None, gt=0, exclude_if=lambda value: value is None
    )
    max_retries: int | None
    transport: PydanticTransportConfig | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    def bridge_kwargs(self) -> dict[str, Any]:
        # Preserve the bridge's existing omitted-effort constructor contract.
        values = self.model_dump(exclude={"transport"})
        if self.reasoning_effort is None:
            values.pop("reasoning_effort")
        if self.transport is not None:
            # The bridge receives the typed carrier, not its serialized form.
            values["transport"] = self.transport
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


#: The flat per-stage route options ``{stage}_{field}`` (for example
#: ``proposing_provider``), one optional field per stage and route field. Extra
#: keys are refused, so a misspelled option cannot leave a stage on the legacy
#: route unnoticed (#1536). Values are checked again as complete routes.
_STAGE_OPTION_FIELDS: dict[str, Any] = {
    f"{stage}_{field}": (info.annotation, None)
    for stage in ProposerRouting.model_fields
    for field, info in ProposerRoute.model_fields.items()
}
ProposerStageOptions = create_model(
    "ProposerStageOptions",
    __config__=ConfigDict(frozen=True, extra="forbid"),
    **_STAGE_OPTION_FIELDS,
)


class UnknownProposerStageOption(TypeError):
    """Keyword options outside ``ProposerStageOptions``, named with the accepted ones."""

    def __init__(self, unknown: Sequence[str]) -> None:
        self.unknown = tuple(unknown)
        accepted = ", ".join(ProposerStageOptions.model_fields)
        super().__init__(
            f"unknown proposer stage option(s): {', '.join(self.unknown)}; "
            f"accepted options are {accepted}"
        )


def resolve_proposer_routing(
    legacy: ProposerRoute, stage_options: Mapping[str, Any]
) -> ProposerRouting:
    """Apply supplied flat stage keys, preserving explicit None and zero.

    Missing fields inherit the legacy constructor's selection. Workflow callers
    supply complete stage settings; direct legacy callers may omit them all.
    A key that is not a ``ProposerStageOptions`` field raises
    ``UnknownProposerStageOption``; an invalid value raises ``ValidationError``.
    This resolver neither reads credentials nor constructs provider clients.
    """
    try:
        options = ProposerStageOptions.model_validate(dict(stage_options))
    except ValidationError as error:
        unknown = [
            str(item["loc"][0]) for item in error.errors() if item["type"] == "extra_forbidden"
        ]
        if unknown:
            raise UnknownProposerStageOption(unknown) from None
        raise
    routes = {}
    for stage in ProposerRouting.model_fields:
        values = legacy.model_dump()
        for field in ProposerRoute.model_fields:
            key = f"{stage}_{field}"
            if key in options.model_fields_set:
                values[field] = getattr(options, key)
        routes[stage] = ProposerRoute.model_validate(values)
    return ProposerRouting.model_validate(routes)
