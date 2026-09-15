"""Bounded, auditable LLM-to-Pydantic repair for Data Analysis stages."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field, ValidationError

from agent.data_analysis.persistence import AnalysisRunStore
from agent.prompt_templates.data_analysis import render_structured_output_repair_prompt
from agent.schemas.data_analysis.common import FrozenModel, NonEmptyStr, canonical_sha256


class DataAnalysisStructuredOutputError(RuntimeError):
    """One bounded representation repair could not satisfy a typed LLM boundary."""


class _StructuredOutputValidationIssue(FrozenModel):
    path: str
    error_type: NonEmptyStr
    message: NonEmptyStr


class _StructuredOutputReceipt(FrozenModel):
    stage: NonEmptyStr
    initial_validation_passed: bool
    repair_attempted: bool
    validation_errors: tuple[_StructuredOutputValidationIssue, ...] = ()
    repair_passed: bool | None = None
    repair_validation_errors: tuple[_StructuredOutputValidationIssue, ...] = ()
    llm_call_count: int = Field(ge=1, le=2)
    initial_payload_sha256: NonEmptyStr
    repaired_payload_sha256: NonEmptyStr | None = None


def _validation_issues(exc: ValidationError) -> tuple[_StructuredOutputValidationIssue, ...]:
    return tuple(
        _StructuredOutputValidationIssue(
            path=".".join(str(part) for part in issue["loc"]),
            error_type=issue["type"],
            message=issue["msg"],
        )
        for issue in exc.errors(include_url=False, include_input=False)
    )


def generate_validated[ValidatedModelT: BaseModel](
    bridge,
    *,
    store: AnalysisRunStore,
    model_type: type[ValidatedModelT],
    system: str,
    user: str,
    label: str,
    semantic_projection: Callable[[object], object | None],
) -> ValidatedModelT:
    """Validate once, then permit one schema-only repair with semantic anchors."""

    raw = bridge.generate(system, user, label=label)
    initial_digest = canonical_sha256(raw)
    try:
        value = model_type.model_validate(raw)
    except ValidationError as initial_error:
        issues = _validation_issues(initial_error)
        original_semantics = semantic_projection(raw)
        if original_semantics is None:
            store.append_structured_output_receipt(
                _StructuredOutputReceipt(
                    stage=label,
                    initial_validation_passed=False,
                    repair_attempted=False,
                    validation_errors=issues,
                    llm_call_count=1,
                    initial_payload_sha256=initial_digest,
                )
            )
            raise DataAnalysisStructuredOutputError(
                f"{label} output is invalid and its semantic decision is ambiguous"
            ) from initial_error

        repair_system, repair_user = render_structured_output_repair_prompt(
            output_schema=model_type.model_json_schema(),
            original_output=raw,
            validation_errors=[issue.model_dump(mode="json") for issue in issues],
        )
        repaired = bridge.generate(repair_system, repair_user, label=f"{label}.repair")
        repaired_digest = canonical_sha256(repaired)
        try:
            value = model_type.model_validate(repaired)
        except ValidationError as repair_error:
            repair_issues = _validation_issues(repair_error)
            store.append_structured_output_receipt(
                _StructuredOutputReceipt(
                    stage=label,
                    initial_validation_passed=False,
                    repair_attempted=True,
                    validation_errors=issues,
                    repair_passed=False,
                    repair_validation_errors=repair_issues,
                    llm_call_count=2,
                    initial_payload_sha256=initial_digest,
                    repaired_payload_sha256=repaired_digest,
                )
            )
            raise DataAnalysisStructuredOutputError(
                f"{label} output remained invalid after one bounded repair"
            ) from repair_error

        if semantic_projection(repaired) != original_semantics:
            semantic_issue = _StructuredOutputValidationIssue(
                path="semantic_projection",
                error_type="semantic_decision_changed",
                message="repair changed a recoverable semantic decision",
            )
            store.append_structured_output_receipt(
                _StructuredOutputReceipt(
                    stage=label,
                    initial_validation_passed=False,
                    repair_attempted=True,
                    validation_errors=issues,
                    repair_passed=False,
                    repair_validation_errors=(semantic_issue,),
                    llm_call_count=2,
                    initial_payload_sha256=initial_digest,
                    repaired_payload_sha256=repaired_digest,
                )
            )
            raise DataAnalysisStructuredOutputError(
                f"{label} repair changed the recoverable semantic decision"
            ) from None

        store.append_structured_output_receipt(
            _StructuredOutputReceipt(
                stage=label,
                initial_validation_passed=False,
                repair_attempted=True,
                validation_errors=issues,
                repair_passed=True,
                llm_call_count=2,
                initial_payload_sha256=initial_digest,
                repaired_payload_sha256=repaired_digest,
            )
        )
        return value

    store.append_structured_output_receipt(
        _StructuredOutputReceipt(
            stage=label,
            initial_validation_passed=True,
            repair_attempted=False,
            llm_call_count=1,
            initial_payload_sha256=initial_digest,
        )
    )
    return value
