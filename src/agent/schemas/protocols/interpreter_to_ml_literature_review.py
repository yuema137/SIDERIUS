"""Typed Interpretation -> Literature Review projection."""

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewInterpretationEvidence


def local_typed_evidence(output: InterpretationOutput) -> LiteratureReviewInterpretationEvidence:
    return LiteratureReviewInterpretationEvidence(
        model_types=tuple(output.model_types),
        key_findings=tuple(output.key_findings),
        bottlenecks=tuple(output.bottlenecks),
        take_home_message=output.take_home_message,
        cold_start=output.cold_start,
    )
