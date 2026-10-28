"""Framework-owned judge prompt template: pure, byte-stable rendering per call role."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.judge import CallRequest, CallRole, PromptIdentity


@dataclass(frozen=True)
class JudgeTemplate:
    """One versioned template. ``render_user`` must read only the request."""

    template_id: str
    call_role: CallRole
    usage_label: str
    system: str
    response_model: type[BaseModel]
    render_user: Callable[[CallRequest], str]
    user_frame: str

    @property
    def template_sha256(self) -> str:
        return canonical_sha256(
            {
                "template": self.template_id,
                "call_role": self.call_role,
                "usage_label": self.usage_label,
                "system": self.system,
                "user_frame": self.user_frame,
            }
        )

    @property
    def response_schema_sha256(self) -> str:
        return canonical_sha256(self.response_model.model_json_schema())

    def render(self, request: CallRequest) -> tuple[str, str]:
        if request.call_role != self.call_role:
            raise ValueError(
                f"template {self.template_id!r} renders {self.call_role!r} calls, "
                f"not {request.call_role!r}"
            )
        return self.system, self.render_user(request)

    def identity(self, request: CallRequest) -> PromptIdentity:
        system, user = self.render(request)
        return PromptIdentity(
            template=self.template_id,
            template_sha256=self.template_sha256,
            prompt_sha256=canonical_sha256({"system": system, "user": user}),
            response_schema_sha256=self.response_schema_sha256,
        )
