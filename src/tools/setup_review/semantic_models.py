"""Typed optional snapshot review; no runtime or provider initialization."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.skill_spec import SkillSpec
from core.execution_deadline import ExecutionBudgetReceipt
from tools.setup_review.route_models import RouteTransport
from workflows.llm_config import NodeLLMConfig

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SnapshotInputError(ValueError):
    """An actionable, value-free refusal safe to display on the CLI."""


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SnapshotOperation(ReviewModel):
    report: Path
    expected_sha256: Digest
    output: Path
    input_max_bytes: int = Field(gt=0, strict=True)


class ReviewSnapshotRequest(SnapshotOperation):
    kind: Literal["review"]
    llm: NodeLLMConfig
    total_review_seconds: float = Field(gt=0)
    request_timeout_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def finite_retries(self):
        if self.llm.max_retries is None or self.llm.max_retries < 0:
            raise ValueError("Review requires finite nonnegative llm.max_retries")
        return self


class SkipSnapshotReviewRequest(SnapshotOperation):
    kind: Literal["skip"]
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def meaningful_reason(self):
        if not self.reason.strip():
            raise ValueError("An explicit skip requires a nonblank reason")
        return self


class SemanticReviewRequest(ReviewModel):
    operation: Annotated[
        ReviewSnapshotRequest | SkipSnapshotReviewRequest, Field(discriminator="kind")
    ]


class SetupFinding(ReviewModel):
    severity: Literal["error", "warning", "information"]
    field: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    suggested_correction: str = Field(min_length=1)
    uncertainty: str


class SetupJudgement(ReviewModel):
    summary: str = Field(min_length=1)
    findings: list[SetupFinding]
    uncovered_checks: list[str]


class SemanticReviewReceipt(ReviewModel):
    schema_version: Literal["siderius.setup-semantic-review/v1"] = (
        "siderius.setup-semantic-review/v1"
    )
    outcome: Literal["reviewed", "skipped", "failed"]
    source_report: str
    source_sha256: Digest
    source_schema: str
    deterministic_outcome: str
    output: str
    input_max_bytes: int
    prompt_version: Literal["setup-review/v1"] = "setup-review/v1"
    packet_sha256: Digest
    system_sha256: Digest | None = None
    user_sha256: Digest | None = None
    reviewer: RouteTransport | None = None
    budget: ExecutionBudgetReceipt | None = None
    judgement: SetupJudgement | None = None
    skip_reason: str | None = None
    failure_category: str | None = None
    failure_action: str | None = None
    token_usage_file: str | None = None
    limitations: list[str]

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.outcome == "skipped":
            if not self.skip_reason or self.judgement is not None or self.reviewer is not None:
                raise ValueError("Skipped review requires a reason and no judgement/reviewer")
        elif self.outcome == "reviewed":
            if self.judgement is None or self.reviewer is None or self.failure_category is not None:
                raise ValueError("Reviewed snapshot requires judgement/reviewer and no failure")
        elif not self.failure_category or self.judgement is not None:
            raise ValueError("Failed review requires a failure category and no judgement")
        return self


SKILL_SPEC = SkillSpec(
    name="review_setup_snapshot",
    description=(
        "Optionally review an existing standard setup snapshot with an LLM, or record an "
        "explicit skip. Writes a new local receipt and HTML; never launches an experiment."
    ),
    input_schema=SemanticReviewRequest,
    output_schema=SemanticReviewReceipt,
)
