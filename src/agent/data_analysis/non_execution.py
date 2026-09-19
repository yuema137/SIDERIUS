"""Persist an explicit no-work plan and report without fabricating analysis evidence."""

from __future__ import annotations

from agent.data_analysis.persistence import AnalysisRunStore
from agent.schemas.data_analysis.common import canonical_sha256, utc_now
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.plan import AnalysisPlan, StopPolicy
from agent.schemas.data_analysis.report import (
    AnalysisResourceSummary,
    DataAnalysisReport,
    DataAnalysisReportProvenance,
    QuestionOutcome,
    ReportLimitation,
)


def build_non_execution_report(
    *, inp: DataAnalysisInput, store: AnalysisRunStore, discovery_digest: str, reason: str
) -> DataAnalysisReport:
    """A planner's stated limitation is not a measured finding or access decision."""
    question_ids = tuple(question.question_id for question in inp.analysis_brief.questions)
    input_digest = canonical_sha256(inp)
    policy_digest = canonical_sha256(inp.access_policy)
    plan = AnalysisPlan(
        plan_id=f"{inp.request_id}.no-execution",
        input_digest=input_digest,
        access_policy_digest=policy_digest,
        discovery_snapshot_digest=discovery_digest,
        questions=question_ids,
        invocations=(),
        stop_policy=StopPolicy(max_invocations=1),
        rationale=reason,
        non_execution_reason=reason,
    )
    plan_ref = store.write_plan(plan)
    limitation_id = "no-applicable-analysis"
    summary = "No analysis was executed; no empirical findings were produced."
    return DataAnalysisReport(
        report_id=f"{inp.request_id}.report",
        analysis_attempt_id=inp.request_id,
        input_digest=input_digest,
        plan_ref=plan_ref,
        analysis_scope=(),
        executive_summary=summary,
        question_outcomes=tuple(
            QuestionOutcome(
                question_id=q,
                status="unresolved",
                summary=summary,
                limitation_ids=(limitation_id,),
            )
            for q in question_ids
        ),
        assets_inspected=(),
        source_scope=inp.effective_source_scope(),
        findings=(),
        skill_result_summaries=(),
        skill_result_refs=(),
        limitations=(
            ReportLimitation(
                limitation_id=limitation_id,
                statement=f"Planner reported no applicable authorized analysis: {reason}",
                affected_question_ids=question_ids,
            ),
        ),
        unresolved_questions=tuple(q.question for q in inp.analysis_brief.questions),
        resource_usage=AnalysisResourceSummary(
            attempted_invocations=0,
            completed_invocations=0,
            total_wall_time_s=0.0,
            measurement_limitations=(
                "No skill executed; whole-node LLM/planning time is in budget_receipt.json.",
            ),
        ),
        provenance=DataAnalysisReportProvenance(
            input_digest=input_digest,
            access_policy_digest=policy_digest,
            plan_digest=canonical_sha256(plan),
            discovery_snapshot_digest=discovery_digest,
            skill_result_set_digest=canonical_sha256([]),
            generated_at=utc_now(),
        ),
    )
