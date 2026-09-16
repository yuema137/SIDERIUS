"""Typed Literature Review -> Data Analysis projection."""

from agent.schemas.data_analysis.context import (
    DataAnalysisInput,
    DataAnalysisLiteratureEvidence,
    DataAnalysisLiteratureFinding,
)
from agent.schemas.literature_review import LiteratureReviewOutput


def local_typed_evidence(output: LiteratureReviewOutput) -> DataAnalysisLiteratureEvidence:
    return DataAnalysisLiteratureEvidence(
        review_run_name=output.run_name,
        findings=tuple(
            DataAnalysisLiteratureFinding(
                source_ref=item.source_ref,
                content=item.content,
                confidence=item.confidence,
            )
            for item in output.findings
        ),
        retrieved_paper_ids=tuple(item.paper_id for item in output.retrieved_papers),
    )


def attach_typed_evidence(
    analysis_input: DataAnalysisInput,
    output: LiteratureReviewOutput,
) -> DataAnalysisInput:
    payload = analysis_input.model_dump(mode="python")
    payload["literature_evidence"] = local_typed_evidence(output)
    return DataAnalysisInput.model_validate(payload)
