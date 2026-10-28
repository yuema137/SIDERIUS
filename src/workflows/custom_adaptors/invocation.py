"""The parent-to-child request for one supervised custom adaptor invocation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Child exit status meaning the captured package failed its pin verification.
IDENTITY_MISMATCH_EXIT = 78
#: Child exit status for an exception (or exit request) raised by adaptor code.
ADAPTOR_EXCEPTION_EXIT = 1


class PortValues(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    contract: str
    values: list[Any]


class CustomInvocation(BaseModel):
    """Everything the child needs; absolute locators, JSON inputs, no host state."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    adaptor_id: str
    role: Literal["combine", "select", "distribute"]
    transport_manifest: str
    transport_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry_path: str
    entry_function: str
    parameters_path: str | None
    parameters_class: str | None
    ports: tuple[PortValues, ...]
    parameters: dict[str, Any]
    output_path: str
