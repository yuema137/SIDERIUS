"""Typed Proposer consumer view of a canonical Data Analysis report.

The Data Analysis capability does not import this module.  This projection is
owned by the Data Analysis -> Proposer protocol edge: capability schemas
describe analysis semantics, while this schema describes composition semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import model_validator

from agent.schemas.data_analysis.common import (
    CertifiedArtifactRef,
    FrozenModel,
    NonEmptyStr,
    canonical_sha256,
)
from agent.schemas.data_analysis.report import DataAnalysisReport
from agent.schemas.data_analysis.skills import AnalysisCoverage, QuantitativeResult


class ProposerAnalysisQuestionOutcome(FrozenModel):
    """Bounded question disposition relevant to downstream model reasoning."""

    question_id: NonEmptyStr
    status: Literal["addressed", "partially_addressed", "unresolved", "refused"]
    summary: NonEmptyStr
    finding_ids: tuple[NonEmptyStr, ...] = ()


class ProposerDataFinding(FrozenModel):
    """A report finding projected with only its bounded, cited measurements."""

    finding_id: NonEmptyStr
    statement: NonEmptyStr
    confidence_level: Literal["low", "medium", "high"]
    confidence_rationale: NonEmptyStr
    method_skill_ids: tuple[NonEmptyStr, ...]
    modeling_relevance: NonEmptyStr
    coverage: AnalysisCoverage
    quantitative_evidence: tuple[QuantitativeResult, ...] = ()
    result_refs: tuple[NonEmptyStr, ...]


class ProposerDataAnalysisEvidence(FrozenModel):
    """Strict, bounded Data Analysis evidence accepted by ``ProposalInput``."""

    report_ref: CertifiedArtifactRef
    executive_summary: NonEmptyStr
    question_outcomes: tuple[ProposerAnalysisQuestionOutcome, ...]
    findings: tuple[ProposerDataFinding, ...]
    modeling_relevance: tuple[NonEmptyStr, ...] = ()
    limitations: tuple[NonEmptyStr, ...] = ()
    unresolved_questions: tuple[NonEmptyStr, ...] = ()
    coverage_summary: tuple[AnalysisCoverage, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> ProposerDataAnalysisEvidence:
        finding_ids = {item.finding_id for item in self.findings}
        for outcome in self.question_outcomes:
            if not set(outcome.finding_ids).issubset(finding_ids):
                raise ValueError("analysis question outcome cites an unknown projected finding")
        return self


def build_proposer_data_analysis_evidence(
    report: DataAnalysisReport | Mapping[str, Any],
    *,
    report_ref: CertifiedArtifactRef,
) -> ProposerDataAnalysisEvidence:
    """Project one validated report into the Proposer's bounded consumer view.

    ``report`` may be the in-memory capability output or its canonical JSON
    mapping.  Both paths first validate the complete public report contract;
    malformed persisted reports therefore fail closed instead of being mined
    opportunistically by a downstream prompt renderer.
    """

    validated = (
        report
        if isinstance(report, DataAnalysisReport)
        else DataAnalysisReport.model_validate(report)
    )
    summaries_by_result = {
        item.result_ref.result_id: item for item in validated.skill_result_summaries
    }
    projected_findings: list[ProposerDataFinding] = []
    for finding in validated.findings:
        quantitative: list[QuantitativeResult] = []
        seen_quantitative: set[tuple[str, str]] = set()
        result_refs: list[str] = []
        for pointer in finding.evidence:
            result_id = pointer.result_ref.result_id
            result_refs.append(result_id)
            summary = summaries_by_result.get(result_id)
            if summary is None:
                raise ValueError("analysis finding cites a result without a bounded summary")
            requested = set(pointer.quantitative_result_ids)
            available = {item.result_key: item for item in summary.key_quantitative_results}
            if not requested.issubset(available):
                raise ValueError("analysis finding cites quantitative evidence absent from report")
            for result_key in pointer.quantitative_result_ids:
                identity = (result_id, result_key)
                if identity not in seen_quantitative:
                    quantitative.append(available[result_key])
                    seen_quantitative.add(identity)
        projected_findings.append(
            ProposerDataFinding(
                finding_id=finding.finding_id,
                statement=finding.statement,
                confidence_level=finding.confidence.level,
                confidence_rationale=finding.confidence.rationale,
                method_skill_ids=finding.method_skill_ids,
                modeling_relevance=finding.modeling_relevance,
                coverage=finding.coverage,
                quantitative_evidence=tuple(quantitative),
                result_refs=tuple(result_refs),
            )
        )

    coverage_by_digest: dict[str, AnalysisCoverage] = {}
    for summary in validated.skill_result_summaries:
        if summary.coverage is not None:
            digest = canonical_sha256(summary.coverage)
            coverage_by_digest[digest] = summary.coverage

    return ProposerDataAnalysisEvidence(
        report_ref=report_ref,
        executive_summary=validated.executive_summary,
        question_outcomes=tuple(
            ProposerAnalysisQuestionOutcome(
                question_id=item.question_id,
                status=item.status,
                summary=item.summary,
                finding_ids=item.finding_ids,
            )
            for item in validated.question_outcomes
        ),
        findings=tuple(projected_findings),
        modeling_relevance=validated.modeling_relevance,
        limitations=tuple(item.statement for item in validated.limitations),
        unresolved_questions=validated.unresolved_questions,
        coverage_summary=tuple(coverage_by_digest[key] for key in sorted(coverage_by_digest)),
    )
