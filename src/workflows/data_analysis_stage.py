"""Optional typed workflow traversal for Interpreter -> Analysis -> Proposer."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from agent.schemas.data_analysis.common import CallerIdentity, CertifiedArtifactRef
from agent.schemas.data_analysis.report import DataAnalysisReport
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.protocols.data_analysis_to_ml_model_propose import local_typed_evidence
from agent.schemas.protocols.interpreter_to_data_analysis import (
    MissingAnalysisBriefError,
    local_analysis_input,
)
from agent.schemas.storage import StorageConfig
from execute_tools.historical_model_inference import HistoricalModelInferenceCapability
from nodes.data_analysis_agent import DataAnalysisAgent
from workflows.data_analysis_composition import ResolvedWorkflowDataAnalysis


@dataclass(frozen=True, slots=True)
class WorkflowAnalysisOutput:
    """The capability output plus the edge-certified persisted report identity."""

    report: DataAnalysisReport
    report_ref: CertifiedArtifactRef


def run_optional_data_analysis(
    interpretation: InterpretationOutput,
    *,
    binding: ResolvedWorkflowDataAnalysis | None,
    iteration: int,
    run_name: str,
    storage: StorageConfig,
    human_advice: str | None,
    llm_kwargs: dict,
    bridge_factory,
    historical_model_inference_capability: HistoricalModelInferenceCapability | None = None,
    literature_output: LiteratureReviewOutput | None = None,
) -> WorkflowAnalysisOutput | None:
    """Run the independent capability only when the composition enables its edge.

    A missing brief is an explicit no-analysis disposition already recorded by
    the Interpreter's brief receipt.  This edge never invents replacement
    questions from prose.
    """

    if binding is None:
        return None
    request_id = f"iteration-{iteration:03d}"
    try:
        analysis_input = local_analysis_input(
            interpretation,
            request_id=request_id,
            task_context=binding.task_context,
            available_assets=binding.available_assets,
            access_policy=binding.access_policy,
            resource_envelope=binding.resource_envelope,
            allowed_skill_packs=binding.allowed_skill_packs,
            storage=storage,
            caller=CallerIdentity(
                caller_id=run_name,
                caller_type="workflow",
                request_source=f"iteration:{iteration}",
            ),
            human_advice=human_advice,
            allow_generated_skill_promotion=binding.allow_generated_skill_promotion,
        )
    except MissingAnalysisBriefError:
        return None
    if literature_output is not None:
        from agent.schemas.protocols.ml_literature_review_to_data_analysis import (
            attach_typed_evidence,
        )

        analysis_input = attach_typed_evidence(analysis_input, literature_output)

    report = DataAnalysisAgent(
        task_analysis_capability=binding.task_analysis_capability,
        historical_model_inference_capability=historical_model_inference_capability,
        bridge_factory=bridge_factory,
        **llm_kwargs,
    ).run(analysis_input)
    assert storage.local is not None
    relative = Path("data_analysis") / storage.local.run_name / request_id / "report.json"
    path = Path(storage.local.workspace) / relative
    payload = path.read_bytes()
    report_ref = CertifiedArtifactRef(
        logical_ref=str(relative),
        sha256=hashlib.sha256(payload).hexdigest(),
        media_type="application/json",
        byte_size=len(payload),
    )
    return WorkflowAnalysisOutput(report=report, report_ref=report_ref)


def attach_analysis_to_proposer(
    proposal_input: ProposalInput,
    analysis: WorkflowAnalysisOutput | None,
) -> ProposalInput:
    """Apply the Data Analysis -> Proposer edge without exposing report internals."""

    if analysis is None:
        return proposal_input
    return local_typed_evidence(
        analysis.report,
        report_ref=analysis.report_ref,
        proposal_input=proposal_input,
    )
