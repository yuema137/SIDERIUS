"""Public route facts, with no credential values or provider client objects."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

RouteApplicability = Literal["conditional", "task_dependent", "disabled", "pseudo"]


class RouteTransport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    provider: str
    model_id: str | None
    base_url: str | None
    reasoning_effort: str | None
    max_retries: int | None
    request_timeout: float
    timeout_retries: int


class LLMRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    applicability: RouteApplicability
    bridge_arguments: dict[str, JsonValue]
    transport: RouteTransport | None
    reuse_client_of: str | None = None
    issue: str | None = None


class CredentialNameCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    routes: list[str]
    status: Literal["not_checked", "present_nonempty", "missing", "not_required"]
