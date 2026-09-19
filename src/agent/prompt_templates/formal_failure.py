"""Task-independent facts from failed Formal attempts, without candidate authority."""

from collections.abc import Sequence

from agent.schemas.health_feedback import FormalValidityFeedback


def render_formal_failure_feedback(entries: Sequence[FormalValidityFeedback]) -> str:
    if not entries:
        return ""
    lines = ["## [RECENT FORMAL VALIDITY] Failed evidence, not valid candidates or scores."]
    for entry in entries:
        lines.append(
            f"Model {entry.model_type}: {entry.formal_records_considered} Formal records; "
            f"{entry.invalid_count} gate-invalid, {entry.unknown_validity_count} unknown, "
            f"{entry.execution_failure_count} execution failures."
        )
        for outcome in entry.outcomes:
            lines.append(
                f"- {outcome.exp_id}: status={outcome.status}; "
                f"validity={outcome.health_validity.value}; gates={outcome.failed_gate_names}; "
                f"reasons={outcome.failure_reasons}; metrics={outcome.key_metrics}"
            )
        lines.extend(f"Evidence absent: {item}" for item in entry.evidence_absent)
    return "\n".join(lines) + "\n"
