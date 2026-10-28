"""Shared declaration primitives, imported by the document and strategy models."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$", max_length=100)]
Location = Annotated[str, StringConstraints(min_length=1, pattern=r"^[^\x00]+$")]


class DeclarationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
