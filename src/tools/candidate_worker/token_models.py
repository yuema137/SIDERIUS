"""Bounded reported-token projection; these models are not billing records."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

COVERAGE_NOTE = "Observed provider reports; missing or unrecorded usage may exist."


class TokenReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CandidateTokenReadRequest(TokenReadModel):
    allowed_workspace_root: str
    workspace: str
    expected_run_id: str


class CandidateTokenGroup(TokenReadModel):
    provider: str
    requested_model: str
    served_model: str | None
    response_rows: int = 0
    reported_input_tokens: int | None = None
    reported_output_tokens: int | None = None
    reported_total_tokens: int | None = None
    missing_input_rows: int = 0
    missing_output_rows: int = 0
    missing_total_rows: int = 0


class CandidateTokenQuality(TokenReadModel):
    partial: bool = False
    invalid_rows: int = 0
    marker_rows: int = 0
    oversized_rows: int = 0
    excluded_identity_rows: int = 0
    excluded_group_rows: int = 0
    invalid_timestamp_rows: int = 0
    trailing_fragment: bool = False
    truncated_bytes: bool = False
    truncated_rows: bool = False
    short_read: bool = False


class CandidateTokenSnapshot(TokenReadModel):
    run_id: str | None = None
    run_name: str | None = None
    observed_at: str
    last_valid_usage_at: str | None = None
    availability: Literal["available", "unavailable", "not_applicable"]
    reason: Literal[
        "reported_responses",
        "no_reported_responses",
        "native_evidence_unavailable",
        "usage_unavailable",
        "preparation_not_applicable",
    ]
    groups: tuple[CandidateTokenGroup, ...] = ()
    quality: CandidateTokenQuality = CandidateTokenQuality()
    coverage_note: str = COVERAGE_NOTE
    scope: Literal["chain_cumulative"] | None = Field(default=None, exclude_if=lambda v: v is None)
    identity_basis: Literal["observed_sidecar", "retained_sidecar"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
