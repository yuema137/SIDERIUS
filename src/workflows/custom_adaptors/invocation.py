"""The parent-to-child request and the child's typed failure report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Files the child writes in its control directory.
READY_FILE = "ready"
FAILURE_FILE = "failure.json"
OUTPUT_FILE = "output.json"
LOG_FILE = "child.log"
#: Bytes of child stdout+stderr kept in ``LOG_FILE``; the rest is discarded.
MAX_LOG_BYTES = 64 * 1024


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
    control_dir: str
    max_output_bytes: int = Field(gt=0)

    def file(self, name: str) -> Path:
        return Path(self.control_dir) / name


class ChildFailure(BaseModel):
    """Written by the child before exiting non-zero.

    ``identity``, ``input`` and ``parameters`` are only meaningful before the
    ready marker exists: once adaptor code has run, it could forge this file, so
    the parent then classifies every failure as ``custom_exception``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: Literal["identity", "input", "parameters", "adaptor", "output"]
    detail: str = Field(max_length=4000)
