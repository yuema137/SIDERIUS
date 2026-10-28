"""Bounded terminal invocation evidence; scientific values stay in native records."""

from typing import Literal

from pydantic import Field, model_validator

from tools.workflow_preview.models import PreviewModel

# "adaptor" marks a `GraphTrace.adaptors` entry; it is never a declared node capability.
GraphCapability = Literal[
    "proposal", "implementation", "validation", "literature", "interpretation", "tuning", "adaptor"
]
GraphState = Literal["pending", "running", "succeeded", "rejected", "failed", "blocked", "skipped"]
GraphReason = Literal[
    "dependency_not_successful",
    "native_failure",
    "validation_rejected",
    "route_not_selected",
    # Adaptor outcomes (B6-3); `judge_failure` is reserved for LLM strategies (B6-8).
    "no_admissible_input",
    "insufficient_items",
    "judge_failure",
]


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
    # Declared adaptors in declaration order; omitted when none, so traces of
    # unadapted runs keep their bytes.
    adaptors: tuple[GraphNodeEvidence, ...] = Field(default=(), exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def _adaptor_entries(self) -> "GraphTrace":
        if any(item.capability == "adaptor" for item in self.nodes) or any(
            item.capability != "adaptor" for item in self.adaptors
        ):
            raise ValueError("graph trace adaptor entries must be exactly its adaptors")
        return self
