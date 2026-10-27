"""Bounded terminal invocation evidence; scientific values stay in native records."""

from typing import Literal

from pydantic import Field

from tools.workflow_preview.models import PreviewModel

GraphCapability = Literal[
    "proposal", "implementation", "validation", "literature", "interpretation"
]
GraphState = Literal["pending", "running", "succeeded", "rejected", "failed", "blocked"]
GraphReason = Literal["dependency_not_successful", "native_failure", "validation_rejected"]


class GraphNodeEvidence(PreviewModel):
    node_id: str
    capability: GraphCapability
    predecessors: tuple[str, ...]
    storage: str
    state: GraphState
    record_path: str | None = None
    record_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason: GraphReason | None = None


class GraphTrace(PreviewModel):
    nodes: tuple[GraphNodeEvidence, ...]
