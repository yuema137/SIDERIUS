"""Bounded terminal invocation evidence; scientific values stay in native records."""

from typing import Literal

from pydantic import Field, model_validator

from tools.workflow_preview.models import PreviewModel

from .route_eval import RouteEvaluationOutput

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
    # `insufficient_items` also skips a consumer of a non-emitted output index (B6-4).
    "no_admissible_input",
    "insufficient_items",
    "judge_failure",
    # split-items/v1 found more list entries than declared outputs (B6-4).
    "too_many_items",
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


class GraphRouteEvidence(PreviewModel):
    """One predicate route decision, bound to the digest of the record it read.

    The verifier re-projects the same record and re-runs the evaluator; a human
    decision (``decided_by="human"``) is reserved for the gate (B1-PR8).
    """

    branch_id: str
    source_node: str
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator: Literal["siderius.route/v1"] = "siderius.route/v1"
    decision: RouteEvaluationOutput
    decided_by: Literal["predicate"] = "predicate"

    @model_validator(mode="after")
    def _one_branch(self) -> "GraphRouteEvidence":
        if self.decision.branch_id != self.branch_id:
            raise ValueError("route evidence decision names another branch")
        return self


class GraphTrace(PreviewModel):
    nodes: tuple[GraphNodeEvidence, ...]
    # Declared adaptors in declaration order; omitted when none, so traces of
    # unadapted runs keep their bytes.
    adaptors: tuple[GraphNodeEvidence, ...] = Field(default=(), exclude_if=lambda value: not value)
    # Route decisions in branch declaration order; omitted when none (unrouted bytes).
    routes: tuple[GraphRouteEvidence, ...] = Field(default=(), exclude_if=lambda value: not value)
    # B3-4b trace v2: ``parallel-v1`` bodies may drain (units already running when a
    # failure ended finish). Omitted when serial, so serial traces keep their bytes.
    scheduling: Literal["serial", "parallel-v1"] = Field(
        default="serial", exclude_if=lambda value: value == "serial"
    )

    @model_validator(mode="after")
    def _adaptor_entries(self) -> "GraphTrace":
        if any(item.capability == "adaptor" for item in self.nodes) or any(
            item.capability != "adaptor" for item in self.adaptors
        ):
            raise ValueError("graph trace adaptor entries must be exactly its adaptors")
        return self
