"""Validate report citations against measured evidence before publication."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import Field

from agent.data_analysis.persistence import AnalysisRunStore
from agent.data_analysis.structured_output import generate_validated
from agent.prompt_templates.data_analysis import render_report_synthesis_prompt
from agent.schemas.data_analysis.common import FrozenModel, NonEmptyStr
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.skills import SkillResult


class _FindingDraft(FrozenModel):
    finding_id: NonEmptyStr
    result_id: NonEmptyStr
    statement: NonEmptyStr
    quantitative_result_ids: tuple[NonEmptyStr, ...] = ()
    confidence_level: Literal["low", "medium", "high"]
    confidence_rationale: NonEmptyStr
    confidence_limitations: tuple[NonEmptyStr, ...] = ()
    modeling_relevance: NonEmptyStr


class _QuestionOutcomeDraft(FrozenModel):
    question_id: NonEmptyStr
    status: Literal["addressed", "partially_addressed", "unresolved", "refused"]
    summary: NonEmptyStr
    finding_ids: tuple[NonEmptyStr, ...] = ()
    limitation_ids: tuple[NonEmptyStr, ...] = ()


class _LimitationDraft(FrozenModel):
    limitation_id: NonEmptyStr
    statement: NonEmptyStr
    affected_question_ids: tuple[NonEmptyStr, ...] = ()


class _ReportSynthesis(FrozenModel):
    executive_summary: NonEmptyStr
    findings: tuple[_FindingDraft, ...] = ()
    question_outcomes: tuple[_QuestionOutcomeDraft, ...]
    limitations: tuple[_LimitationDraft, ...] = ()
    unresolved_questions: tuple[NonEmptyStr, ...] = ()
    modeling_relevance: tuple[NonEmptyStr, ...] = ()


class _GroundingReceipt(FrozenModel):
    stage: Literal["data_analysis.synthesis.grounding"] = "data_analysis.synthesis.grounding"
    attempt: int = Field(ge=1, le=2)
    draft: _ReportSynthesis
    errors: tuple[str, ...]


def _grounding_errors(
    draft: _ReportSynthesis, inp: DataAnalysisInput, results: tuple[SkillResult, ...]
) -> tuple[str, ...]:
    """Check references without inventing, dropping or rewriting any finding."""
    errors = []
    by_id = {r.result_id: r for r in results}
    for finding in draft.findings:
        result = by_id.get(finding.result_id)
        if result is None or result.status != "completed" or result.coverage is None:
            errors.append(
                f"{finding.finding_id}: result {finding.result_id!r} is not completed with coverage"
            )
            continue
        keys = {q.result_key for q in result.quantitative_results}
        unknown = sorted(set(finding.quantitative_result_ids) - keys)
        if unknown:
            errors.append(
                f"{finding.finding_id}: unknown quantitative keys {unknown!r}; allowed keys {sorted(keys)!r}"
            )
    questions = {q.question_id for q in inp.analysis_brief.questions}
    ids = [q.question_id for q in draft.question_outcomes]
    if set(ids) != questions or len(ids) != len(questions):
        errors.append(
            f"Question outcomes must address exactly these question IDs once: {sorted(questions)!r}"
        )
    findings = {f.finding_id for f in draft.findings}
    limitations = {item.limitation_id for item in draft.limitations}
    if len(findings) != len(draft.findings) or len(limitations) != len(draft.limitations):
        errors.append("Finding IDs and limitation IDs must each be unique")
    for outcome in draft.question_outcomes:
        if not set(outcome.finding_ids) <= findings:
            errors.append(f"{outcome.question_id}: unknown finding reference")
        if not set(outcome.limitation_ids) <= limitations:
            errors.append(f"{outcome.question_id}: unknown limitation reference")
    for limitation in draft.limitations:
        if not set(limitation.affected_question_ids) <= questions:
            errors.append(f"{limitation.limitation_id}: unknown affected question reference")
    return tuple(errors)


def generate_grounded_synthesis(
    bridge: Any,
    *,
    inp: DataAnalysisInput,
    results: tuple[SkillResult, ...],
    store: AnalysisRunStore,
    semantic_projection: Callable[[object], object | None],
) -> _ReportSynthesis:
    """Permit one fresh synthesis on identical evidence under the existing deadline.

    This is evidence-grounding retry, not the schema-only representation repair.
    Both rejected and accepted drafts remain auditable. No measurements or
    authorizations change, and persistent invalid citations fail closed.
    """
    system, user = render_report_synthesis_prompt(
        inp, results, output_schema=_ReportSynthesis.model_json_schema()
    )
    for attempt in (1, 2):
        draft = generate_validated(
            bridge,
            store=store,
            model_type=_ReportSynthesis,
            system=system,
            user=user,
            label="data_analysis.synthesis"
            if attempt == 1
            else "data_analysis.synthesis.grounding_retry",
            semantic_projection=semantic_projection,
        )
        errors = _grounding_errors(draft, inp, results)
        store.append_synthesis_grounding_receipt(
            _GroundingReceipt(attempt=attempt, draft=draft, errors=errors)
        )
        if not errors:
            return draft
        if attempt == 1:
            user += (
                "\nThe previous synthesis failed evidence validation. Generate one new complete "
                "report from the SAME certified results above. Correct citations and unsupported "
                "claims; do not invent measurements, change evidence, or claim failed work succeeded. "
                "If evidence cannot support a finding, state that limitation explicitly.\n"
                + "\n".join(errors)
                + "\nRejected draft:\n"
                + draft.model_dump_json()
            )
    raise ValueError(
        "analysis synthesis failed evidence validation after one retry: " + "; ".join(errors)
    )
