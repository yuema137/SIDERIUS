"""Typed Data Analysis -> Literature Review projection."""

from agent.schemas.data_analysis.report import DataAnalysisReport
from agent.schemas.literature_review import (
    LiteratureReviewDataEvidence,
    LiteratureReviewDataFinding,
    LiteratureReviewDataMeasurement,
)


def local_typed_evidence(report: DataAnalysisReport) -> LiteratureReviewDataEvidence:
    summaries = {item.result_ref.result_id: item for item in report.skill_result_summaries}
    projected: list[LiteratureReviewDataFinding] = []
    for finding in report.findings:
        measurements: list[LiteratureReviewDataMeasurement] = []
        seen: set[tuple[str, str]] = set()
        for pointer in finding.evidence:
            summary = summaries[pointer.result_ref.result_id]
            by_key = {item.result_key: item for item in summary.key_quantitative_results}
            for result_key in pointer.quantitative_result_ids:
                identity = (pointer.result_ref.result_id, result_key)
                if identity in seen:
                    continue
                value = by_key[result_key]
                measurements.append(
                    LiteratureReviewDataMeasurement(
                        result_key=value.result_key,
                        value=value.value,
                        unit=value.unit,
                        description=value.description,
                    )
                )
                seen.add(identity)
        projected.append(
            LiteratureReviewDataFinding(
                finding_id=finding.finding_id,
                statement=finding.statement,
                confidence_level=finding.confidence.level,
                modeling_relevance=finding.modeling_relevance,
                measurements=tuple(measurements),
            )
        )
    return LiteratureReviewDataEvidence(
        report_id=report.report_id,
        executive_summary=report.executive_summary,
        findings=tuple(projected),
        limitations=tuple(item.statement for item in report.limitations),
        unresolved_questions=report.unresolved_questions,
    )
