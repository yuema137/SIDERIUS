"""Typed coordination metadata; never scientific checkpoints or run configuration."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class WriterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Registration(WriterModel):
    version: Literal[1] = 1
    workspace: str
    recipe: Literal["captured-native-foreground/v1"] = "captured-native-foreground/v1"
    capture_sha256: Digest


class Claim(WriterModel):
    claim_id: UUID
    workspace: str
    capture_sha256: Digest


class Participation(WriterModel):
    claim_id: UUID
    participant_id: UUID


class Unresolved(WriterModel):
    claim_id: UUID
    reason: Literal["process_cleanup", "participant_exception", "owner_exit"]


class Transport(WriterModel):
    fd: int = Field(ge=3, strict=True)
    workspace: str
    claim_id: UUID | None = None


class Inspection(WriterModel):
    workspace: str
    status: Literal["active", "registered_idle", "unresolved", "unregistered", "invalid"]
    registered: bool = False
    reason: str | None = None


class WriterRefusal(RuntimeError):
    """Bounded public ownership refusal without captured input values."""
