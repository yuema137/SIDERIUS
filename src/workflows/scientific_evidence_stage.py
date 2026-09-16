"""Workflow-owned composition of independent scientific evidence capabilities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

EvidenceStageOrder = Literal["analysis_then_literature", "literature_then_analysis"]


@dataclass(frozen=True, slots=True)
class ScientificEvidenceStageOutput[AnalysisOutputT, LiteratureOutputT]:
    analysis_output: AnalysisOutputT | None
    literature_output: LiteratureOutputT | None


def run_scientific_evidence_stage[AnalysisOutputT, LiteratureOutputT](
    *,
    order: EvidenceStageOrder,
    run_analysis: Callable[[LiteratureOutputT | None], AnalysisOutputT | None] | None,
    run_literature: Callable[[AnalysisOutputT | None], LiteratureOutputT | None] | None,
) -> ScientificEvidenceStageOutput[AnalysisOutputT, LiteratureOutputT]:
    """Traverse two optional nodes in workflow-selected order."""

    analysis_output: AnalysisOutputT | None = None
    literature_output: LiteratureOutputT | None = None
    if order == "analysis_then_literature":
        if run_analysis is not None:
            analysis_output = run_analysis(None)
        if run_literature is not None:
            literature_output = run_literature(analysis_output)
    elif order == "literature_then_analysis":
        if run_literature is not None:
            literature_output = run_literature(None)
        if run_analysis is not None:
            analysis_output = run_analysis(literature_output)
    else:  # pragma: no cover - closed vocabulary is validated by the caller
        raise ValueError(f"unknown scientific evidence stage order: {order!r}")
    return ScientificEvidenceStageOutput(
        analysis_output=analysis_output,
        literature_output=literature_output,
    )
