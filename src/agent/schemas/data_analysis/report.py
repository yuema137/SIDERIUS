"""Bounded canonical output contract for the Data Analysis capability."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .action_identity import AnalysisExecutionOrigin
from .assets import AnalysisScopeDescriptor
from .common import CertifiedArtifactRef, FrozenModel, NonEmptyStr, Sha256, canonical_json_bytes
from .generated_skill import GeneratedExperimentSkillRegistryRef
from .skills import AnalysisCoverage, InvocationStatus, QuantitativeResult
from .source_scope import AnalysisSourceScope

MAX_REPORT_RESULT_SUMMARIES = 100
MAX_KEY_RESULTS_PER_SUMMARY = 32
MAX_REPORT_SUMMARY_BYTES = 512 * 1024


class CertifiedResultRef(FrozenModel):
    result_id: NonEmptyStr
    logical_ref: NonEmptyStr
    sha256: Sha256


class EvidencePointer(FrozenModel):
    result_ref: CertifiedResultRef
    quantitative_result_ids: tuple[NonEmptyStr, ...] = ()
    artifact_refs: tuple[CertifiedArtifactRef, ...] = ()


class ConfidenceAssessment(FrozenModel):
    level: Literal["low", "medium", "high"]
    rationale: NonEmptyStr
    limitations: tuple[NonEmptyStr, ...] = ()


class DataFinding(FrozenModel):
    finding_id: NonEmptyStr
    statement: NonEmptyStr
    evidence: tuple[EvidencePointer, ...]
    confidence: ConfidenceAssessment
    scope: AnalysisScopeDescriptor = Field(discriminator="kind")
    method_skill_ids: tuple[NonEmptyStr, ...] = ()
    method_generated_program_ids: tuple[NonEmptyStr, ...] = ()
    coverage: AnalysisCoverage
    modeling_relevance: NonEmptyStr

    @model_validator(mode="after")
    def validate_finding(self) -> DataFinding:
        if not self.evidence:
            raise ValueError("a data finding requires at least one evidence pointer")
        if not self.method_skill_ids and not self.method_generated_program_ids:
            raise ValueError("a data finding requires at least one method identity")
        if len(set(self.method_skill_ids)) != len(self.method_skill_ids):
            raise ValueError("finding method skill IDs must be unique")
        if len(set(self.method_generated_program_ids)) != len(self.method_generated_program_ids):
            raise ValueError("finding generated program IDs must be unique")
        return self


class ReportLimitation(FrozenModel):
    limitation_id: NonEmptyStr
    statement: NonEmptyStr
    affected_question_ids: tuple[NonEmptyStr, ...] = ()


class QuestionOutcome(FrozenModel):
    question_id: NonEmptyStr
    status: Literal["addressed", "partially_addressed", "unresolved", "refused"]
    summary: NonEmptyStr
    finding_ids: tuple[NonEmptyStr, ...] = ()
    limitation_ids: tuple[NonEmptyStr, ...] = ()


class SkillResultSummary(FrozenModel):
    """Legacy-named bounded summary for any certified analysis execution."""

    result_ref: CertifiedResultRef
    execution_origin: AnalysisExecutionOrigin = "configured_external_skill"
    skill_id: NonEmptyStr | None = None
    generated_program_id: NonEmptyStr | None = None
    status: InvocationStatus
    summary: NonEmptyStr
    coverage: AnalysisCoverage | None = None
    key_quantitative_results: tuple[QuantitativeResult, ...] = ()
    warning_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_bound(self) -> SkillResultSummary:
        if self.execution_origin == "generated_program":
            if self.generated_program_id is None or self.skill_id is not None:
                raise ValueError("generated-program summary requires only generated program ID")
        elif self.skill_id is None or self.generated_program_id is not None:
            raise ValueError("skill summary requires only skill ID")
        if len(self.key_quantitative_results) > MAX_KEY_RESULTS_PER_SUMMARY:
            raise ValueError(
                f"skill result summary exceeds {MAX_KEY_RESULTS_PER_SUMMARY} key results"
            )
        return self


class AnalysisResourceSummary(FrozenModel):
    attempted_invocations: int = Field(ge=0)
    completed_invocations: int = Field(ge=0)
    total_wall_time_s: float = Field(ge=0.0)
    total_cpu_time_s: float | None = Field(default=None, ge=0.0)
    maximum_peak_rss_bytes: int | None = Field(default=None, ge=0)
    maximum_peak_vram_bytes: int | None = Field(default=None, ge=0)
    measurement_limitations: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_counts(self) -> AnalysisResourceSummary:
        if self.completed_invocations > self.attempted_invocations:
            raise ValueError("completed invocations cannot exceed attempted invocations")
        return self


class DataAnalysisReportProvenance(FrozenModel):
    input_digest: Sha256
    access_policy_digest: Sha256
    plan_digest: Sha256
    discovery_snapshot_digest: Sha256
    skill_result_set_digest: Sha256
    generated_at: NonEmptyStr
    generated_skill_registry: GeneratedExperimentSkillRegistryRef | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class DataAnalysisReport(FrozenModel):
    """Analysis-shaped canonical output; consumer projections live on protocol edges."""

    schema_version: Literal[1] = 1
    report_id: NonEmptyStr
    analysis_attempt_id: NonEmptyStr
    input_digest: Sha256
    plan_ref: CertifiedArtifactRef
    analysis_scope: tuple[AnalysisScopeDescriptor, ...]
    executive_summary: NonEmptyStr
    question_outcomes: tuple[QuestionOutcome, ...]
    assets_inspected: tuple[NonEmptyStr, ...]
    source_scope: AnalysisSourceScope | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    findings: tuple[DataFinding, ...]
    skill_result_summaries: tuple[SkillResultSummary, ...]
    skill_result_refs: tuple[CertifiedResultRef, ...]
    artifacts: tuple[CertifiedArtifactRef, ...] = ()
    modeling_relevance: tuple[NonEmptyStr, ...] = ()
    limitations: tuple[ReportLimitation, ...] = ()
    unresolved_questions: tuple[NonEmptyStr, ...] = ()
    resource_usage: AnalysisResourceSummary
    provenance: DataAnalysisReportProvenance

    @model_validator(mode="after")
    def validate_report(self) -> DataAnalysisReport:
        if not self.question_outcomes:
            raise ValueError("report requires at least one question outcome")
        if len(self.skill_result_summaries) > MAX_REPORT_RESULT_SUMMARIES:
            raise ValueError(f"report exceeds {MAX_REPORT_RESULT_SUMMARIES} skill result summaries")
        summary_bytes = len(
            canonical_json_bytes(
                [item.model_dump(mode="json") for item in self.skill_result_summaries]
            )
        )
        if summary_bytes > MAX_REPORT_SUMMARY_BYTES:
            raise ValueError(
                f"serialized skill result summaries exceed {MAX_REPORT_SUMMARY_BYTES} bytes"
            )

        self._require_unique(
            "question outcome", [item.question_id for item in self.question_outcomes]
        )
        self._require_unique("asset", list(self.assets_inspected))
        if self.source_scope is not None and not set(self.assets_inspected).issubset(
            set(self.source_scope.raw_input_asset_ids)
            | set(self.source_scope.historical_model_asset_ids)
        ):
            raise ValueError("report inspected an asset outside the source scope")
        self._require_unique("finding", [item.finding_id for item in self.findings])
        self._require_unique("limitation", [item.limitation_id for item in self.limitations])
        self._require_unique(
            "skill result ref", [item.result_id for item in self.skill_result_refs]
        )

        finding_ids = {item.finding_id for item in self.findings}
        limitation_ids = {item.limitation_id for item in self.limitations}
        result_refs = {item.result_id: item for item in self.skill_result_refs}
        summary_result_ids = {item.result_ref.result_id for item in self.skill_result_summaries}
        if summary_result_ids != set(result_refs):
            raise ValueError("every report skill result ref requires exactly one bounded summary")
        for outcome in self.question_outcomes:
            if not set(outcome.finding_ids).issubset(finding_ids):
                raise ValueError("question outcome references an unknown finding")
            if not set(outcome.limitation_ids).issubset(limitation_ids):
                raise ValueError("question outcome references an unknown limitation")
        for summary in self.skill_result_summaries:
            expected = result_refs.get(summary.result_ref.result_id)
            if expected != summary.result_ref:
                raise ValueError("skill result summary does not resolve to a report result ref")
        report_artifacts = {
            (item.logical_ref, item.sha256, item.media_type) for item in self.artifacts
        }
        for finding in self.findings:
            for pointer in finding.evidence:
                expected = result_refs.get(pointer.result_ref.result_id)
                if expected != pointer.result_ref:
                    raise ValueError("finding evidence does not resolve to a report result ref")
                if any(
                    (item.logical_ref, item.sha256, item.media_type) not in report_artifacts
                    for item in pointer.artifact_refs
                ):
                    raise ValueError("finding evidence cites an artifact absent from the report")
        return self

    @staticmethod
    def _require_unique(label: str, values: list[str]) -> None:
        if len(set(values)) != len(values):
            raise ValueError(f"report {label} IDs must be unique")
