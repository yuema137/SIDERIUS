"""Inert public launch contract: no native node or task imports."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from core.generated_artifact_name import validate_generated_artifact_name
from core.seeding import RunSeed, RunSeedBinding, SeedCoordinates, SeedSource
from tools.setup_review.route_models import LLMRoute
from tools.workflow_preview.models import FileObservation, PreviewModel, WorkflowPreviewRequest

from .graph_models import GraphTrace
from .loop_models import LoopTrace
from .parallel_models import ParallelDispatch


class ReviewedContext(PreviewModel):
    project_id: str
    prepare_operation_id: UUID
    prepared_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkflowSourceSnapshot(PreviewModel):
    origin_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str
    reviewed_context: ReviewedContext | None = None

    @field_validator("origin_path")
    @classmethod
    def absolute_origin(cls, value: str) -> str:
        if not Path(value).is_absolute() or "\0" in value:
            raise ValueError("source origin must be an absolute path")
        return value


class CandidateRunRequest(PreviewModel):
    preview: WorkflowPreviewRequest
    declaration_digest: str
    files: tuple[FileObservation, ...]
    selected_constructor_routes: tuple[LLMRoute, ...]
    storage_policy: Literal["managed_fresh"]
    run_name: str
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    network: bool
    devices: tuple[str, ...]
    read_only: tuple[str, ...]
    environment_names: tuple[str, ...]
    implementation_advice: str | None = None
    validation_advice: str | None = None
    workflow_source: WorkflowSourceSnapshot | None = None
    #: Issue #983 — the operator's explicit run seed; ``None`` lets the entry
    #: boundary generate one. Omitted when ``None``, so seedless request bytes
    #: and digests are unchanged.
    run_seed: RunSeed | None = Field(default=None, exclude_if=lambda value: value is None)
    #: B3-4 — opt-in parallel graph dispatch; omitted for serial runs, so their
    #: request bytes and digests are unchanged.
    parallel: ParallelDispatch | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def source_binding(self):
        from .source import validate_source

        validate_source(self)
        return self

    @field_validator("run_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        validate_generated_artifact_name(value, field="run_name")
        return value


class TrainingOutputEvidence(PreviewModel):
    """Native output identity and digest committed into the terminal receipt."""

    model_name: str
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateRunReceipt(PreviewModel):
    """Execution index; native records remain the authority for node data."""

    run_id: str
    run_name: str
    workspace: str
    declaration_digest: str
    status: Literal[
        "launched",
        "accepted",
        "rejected",
        "failed",
        "timed_out",
        "interrupted",
        "completed",
        "stopped",
        "paused",
        "cancelled",
    ]
    node_ids: tuple[str, ...]
    selected_constructor_routes: tuple[LLMRoute, ...]
    ledger_path: str
    log_path: str
    candidate_id: str | None = None
    composition_fingerprint: str | None = None
    proposal_storage: str | None = None
    implementation_storage: str | None = None
    native_output_paths: tuple[str, ...] = ()
    validation_passed: bool | None = None
    error: str | None = None
    loop_trace: LoopTrace | None = Field(default=None, exclude_if=lambda value: value is None)
    graph_trace: GraphTrace | None = Field(default=None, exclude_if=lambda value: value is None)
    training_output: TrainingOutputEvidence | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    #: Issue #983 — the run seed bound before launch and where it came from.
    #: ``None`` only on receipts written before the seed contract.
    run_seed: RunSeed | None = Field(default=None, exclude_if=lambda value: value is None)
    run_seed_source: SeedSource | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def seed_pair(self):
        if (self.run_seed is None) != (self.run_seed_source is None):
            raise ValueError("run_seed and run_seed_source are recorded together")
        return self

    def seed_binding(self) -> RunSeedBinding | None:
        """The recorded binding; ``None`` for a receipt that predates the seed contract."""
        if self.run_seed is None or self.run_seed_source is None:
            return None
        return RunSeedBinding(value=self.run_seed, source=self.run_seed_source)


#: Receipt fields fixed at launch: a child or terminal receipt never changes them.
RECEIPT_IDENTITY_FIELDS = (
    "run_id",
    "run_name",
    "workspace",
    "declaration_digest",
    "node_ids",
    "selected_constructor_routes",
    "ledger_path",
    "log_path",
    "run_seed",
    "run_seed_source",
)


def tuning_seed_scope(iteration: int, node_id: str) -> SeedCoordinates:
    """The coordinates a candidate tuner derives its attempt seeds under (issue #983).

    ``iteration`` is the global loop index, which a resumed segment continues;
    ``node_id`` is the authored tuning node. Run labels never enter.
    """
    return SeedCoordinates(iteration=iteration, node_id=node_id)
