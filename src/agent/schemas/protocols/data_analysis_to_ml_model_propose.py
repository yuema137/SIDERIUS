"""Typed fan-in protocol for Data Analysis -> ML Model Proposer.

The protocol attaches the Proposer-owned projection to an already assembled
``ProposalInput``.  It does not expose a raw report mapping or use persisted
files as an implicit communication channel.
"""

from __future__ import annotations

from agent.schemas.data_analysis.common import CertifiedArtifactRef
from agent.schemas.data_analysis.report import DataAnalysisReport
from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_data_analysis_evidence import (
    build_proposer_data_analysis_evidence,
)


def local_typed_evidence(
    report: DataAnalysisReport,
    *,
    report_ref: CertifiedArtifactRef,
    proposal_input: ProposalInput,
) -> ProposalInput:
    """Attach one canonical report through the bounded typed edge projection."""

    evidence = build_proposer_data_analysis_evidence(report, report_ref=report_ref)
    payload = proposal_input.model_dump(mode="python")
    payload["data_analysis_evidence"] = evidence
    return ProposalInput.model_validate(payload)
