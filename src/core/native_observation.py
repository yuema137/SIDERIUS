"""Dependency-light version and explicit aggregate-read contract for native evidence."""

from typing import Annotated, Literal

from pydantic import Field

ObservationPolicy = Annotated[int, Field(strict=True, ge=1, le=3)]
EvidenceReadBytes = Annotated[int, Field(strict=True, gt=0)]


def observation_policy(read_bytes: int | None) -> Literal[2, 3]:
    """Legacy requests retain their combined budget; explicit reads select policy 3."""
    return 2 if read_bytes is None else 3
