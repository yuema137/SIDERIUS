"""Deterministic human-readable rendering of the canonical report."""

from __future__ import annotations

from agent.schemas.data_analysis.report import DataAnalysisReport


def render_report_markdown(report: DataAnalysisReport) -> str:
    lines = [f"# Data Analysis Report: {report.report_id}", "", report.executive_summary, ""]
    if report.source_scope is not None:
        lines.extend(["## Source scope", ""])
        lines.append(f"- Mode: {report.source_scope.mode}")
        lines.extend(
            f"- Raw input: {asset_id}" for asset_id in report.source_scope.raw_input_asset_ids
        )
        lines.extend(
            f"- Historical model: {asset_id}"
            for asset_id in report.source_scope.historical_model_asset_ids
        )
        lines.extend(["", "## Sources actually inspected", ""])
        lines.extend(f"- {asset_id}" for asset_id in report.assets_inspected)
        if not report.assets_inspected:
            lines.append("- None")
        lines.append("")
    lines.extend(["## Questions", ""])
    for outcome in report.question_outcomes:
        lines.append(f"- **{outcome.question_id}** ({outcome.status}): {outcome.summary}")
    lines.extend(["", "## Findings", ""])
    if report.findings:
        for finding in report.findings:
            lines.append(f"### {finding.finding_id}")
            lines.extend(
                [
                    "",
                    finding.statement,
                    "",
                    f"Confidence: {finding.confidence.level} — {finding.confidence.rationale}",
                    "",
                    f"Coverage: {finding.coverage.analyzed_count} "
                    f"{finding.coverage.population_unit} on {finding.coverage.split_id}",
                    "",
                    f"Modeling relevance: {finding.modeling_relevance}",
                    "",
                ]
            )
    else:
        lines.extend(["No supported findings were produced.", ""])
    lines.extend(["## Limitations", ""])
    if report.limitations:
        lines.extend(f"- {item.statement}" for item in report.limitations)
    else:
        lines.append("- None reported.")
    lines.extend(["", "## Resource usage", ""])
    lines.append(
        f"Attempted {report.resource_usage.attempted_invocations} analysis invocation(s); "
        f"completed {report.resource_usage.completed_invocations}; "
        f"total observed wall time {report.resource_usage.total_wall_time_s:.3f} s."
    )
    return "\n".join(lines).rstrip() + "\n"
