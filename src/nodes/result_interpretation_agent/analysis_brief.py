"""Optional, isolated second stage for Interpreter-owned AnalysisBrief output."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field, ValidationError

from agent.schemas.analysis_brief_generation import AnalysisBriefGenerationReceipt
from agent.schemas.data_analysis.common import (
    FrozenModel,
    NonEmptyStr,
    canonical_json_bytes,
    canonical_sha256,
    utc_now,
)
from agent.schemas.data_analysis.context import AnalysisBrief, AnalysisQuestion
from agent.schemas.hyperparam_tuning import serialize_expert_advice
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from core.durable_io import publish_bytes_write_once


class _AnalysisQuestionDraft(FrozenModel):
    question: NonEmptyStr
    priority: int = Field(default=3, ge=1, le=5)
    suspected_failure_modes: tuple[NonEmptyStr, ...] = ()
    observations_to_verify: tuple[NonEmptyStr, ...] = ()
    completion_criterion: str | None = None


class _AnalysisBriefDraft(FrozenModel):
    questions: tuple[_AnalysisQuestionDraft, ...] = Field(min_length=1, max_length=8)
    optional_scope_note: str | None = None


class _AnalysisBriefGenerationRecord(FrozenModel):
    receipt: AnalysisBriefGenerationReceipt
    brief: AnalysisBrief | None = None

    def model_post_init(self, _context) -> None:
        if (self.receipt.status == "generated") != (self.brief is not None):
            raise ValueError("generated receipt and persisted brief must be present together")
        if self.brief is not None:
            if self.receipt.brief_id != self.brief.brief_id:
                raise ValueError("persisted brief ID does not match its receipt")
            if self.receipt.brief_sha256 != canonical_sha256(self.brief):
                raise ValueError("persisted brief digest does not match its receipt")


class AnalysisBriefResumeMismatchError(ValueError):
    """A persisted brief belongs to a different semantic generation request."""


def _prompt(
    inp: InterpretationInput,
    interpretation: InterpretationOutput,
) -> tuple[str, str]:
    system = """You are the optional AnalysisBrief stage of a scientific result Interpreter.
Return strict JSON matching the supplied schema. Identify WHAT scientific questions are worth
investigating; do not choose assets, fields, skills, parameters, sampling, preprocessing, model
architectures, training changes, or downstream decisions. For a cold start, formulate bounded
data-characterization questions from task semantics only and never invent prior experiments,
residuals, failures, regressions, or observations. When an analysis access policy is supplied,
ask questions answerable from its permitted evidence classes. Task semantics may describe
targets without making them accessible: do not request target, prediction, residual, or
metadata evidence that the policy withholds. Do not infer clean-signal properties from raw
inputs alone. Questions and advice never override the policy; unknown availability is not
permission. Keep questions at the scientific level rather than selecting assets or skills.
When an analysis resource envelope is supplied, prioritize a small, useful set of questions
whose breadth is proportionate to it. Planning, code generation, execution, and synthesis
share that wall-time budget; do not request an exhaustive catalogue of diagnostics merely
because the response schema permits more questions."""
    if interpretation.cold_start:
        evidence = {
            "cold_start": True,
            "statement": "No prior experimental evidence exists.",
        }
    else:
        evidence = {
            "cold_start": False,
            "key_findings": interpretation.key_findings,
            "bottlenecks": interpretation.bottlenecks,
            "take_home_message": interpretation.take_home_message,
        }
    if inp.recent_formal_validity:
        evidence["failed_formal_attempts"] = [
            item.model_dump(mode="json") for item in inp.recent_formal_validity
        ]
        if interpretation.cold_start:
            evidence["statement"] = (
                "No valid incumbent exists; failed Formal attempts are evidence."
            )
        system += (
            " Explicit failed Formal attempts are real negative evidence even without a valid "
            "incumbent. Use their recorded facts, not invented outcomes; access policy still "
            "limits what follow-up analysis can inspect."
        )
    user = json.dumps(
        {
            "task_description": inp.task_description,
            "metric_spec": (
                None if inp.metric_spec is None else inp.metric_spec.model_dump(mode="json")
            ),
            "interpretation_evidence": evidence,
            "expert_advice": serialize_expert_advice(inp.expert_advice),
            "human_advice": inp.human_advice,
            "analysis_access_policy": (
                None
                if inp.analysis_access_policy is None
                else inp.analysis_access_policy.model_dump(mode="json")
            ),
            "analysis_resource_envelope": (
                None
                if inp.analysis_resource_envelope is None
                else inp.analysis_resource_envelope.model_dump(mode="json")
            ),
            "response_schema": _AnalysisBriefDraft.model_json_schema(),
        },
        sort_keys=True,
        indent=2,
    )
    return system, user


def _record_path(inp: InterpretationInput) -> Path | None:
    if inp.storage.backend != "local" or inp.storage.local is None:
        return None
    return Path(inp.storage.local.workspace) / (
        f"analysis_brief_generation_{inp.storage.local.run_name}.json"
    )


def _load_record(path: Path) -> _AnalysisBriefGenerationRecord:
    return _AnalysisBriefGenerationRecord.model_validate_json(path.read_bytes())


def generate_or_resume_analysis_brief(
    *,
    bridge,
    inp: InterpretationInput,
    interpretation: InterpretationOutput,
    provider: str,
    model_id: str,
) -> tuple[AnalysisBrief | None, AnalysisBriefGenerationReceipt]:
    """Generate or reuse the optional brief without affecting primary interpretation."""

    if not inp.analysis_brief_requested:
        raise ValueError("brief generation may only run when explicitly requested")
    system, user = _prompt(inp, interpretation)
    prompt_digest = canonical_sha256({"system": system, "user": user})
    schema_digest = canonical_sha256(_AnalysisBriefDraft.model_json_schema())
    advice_digest = canonical_sha256(
        {
            "expert_advice": serialize_expert_advice(inp.expert_advice),
            "human_advice": inp.human_advice,
        }
    )
    path = _record_path(inp)
    if path is not None and path.exists():
        record = _load_record(path)
        receipt = record.receipt
        if (
            receipt.prompt_sha256 != prompt_digest
            or receipt.response_schema_sha256 != schema_digest
            or receipt.advice_sha256 != advice_digest
            or receipt.provider != provider
            or receipt.model_id != model_id
        ):
            raise AnalysisBriefResumeMismatchError(
                "persisted AnalysisBrief receipt is incompatible with this request"
            )
        return record.brief, receipt

    try:
        response = bridge.generate(system, user, label="interpretation.analysis_brief")
        draft = _AnalysisBriefDraft.model_validate(response)
        draft_digest = canonical_sha256(draft)
        brief = AnalysisBrief(
            brief_id=f"analysis-brief-{draft_digest[:16]}",
            questions=tuple(
                AnalysisQuestion(
                    question_id=f"analysis-question-{index:02d}",
                    question=item.question,
                    priority=item.priority,
                    suspected_failure_modes=item.suspected_failure_modes,
                    observations_to_verify=item.observations_to_verify,
                    completion_criterion=item.completion_criterion,
                )
                for index, item in enumerate(draft.questions, start=1)
            ),
            optional_scope_note=draft.optional_scope_note,
            source="interpreter",
            source_ref=(
                f"interpretation:{inp.storage.local.run_name}:iteration:{inp.iteration}"
                if inp.storage.local is not None
                else f"interpretation:iteration:{inp.iteration}"
            ),
        )
        receipt = AnalysisBriefGenerationReceipt(
            status="generated",
            brief_id=brief.brief_id,
            brief_sha256=canonical_sha256(brief),
            prompt_sha256=prompt_digest,
            response_schema_sha256=schema_digest,
            advice_sha256=advice_digest,
            provider=provider,
            model_id=model_id,
            generated_at=utc_now(),
        )
        record = _AnalysisBriefGenerationRecord(receipt=receipt, brief=brief)
    except Exception as exc:
        status = "timed_out" if isinstance(exc, TimeoutError) else "failed"
        failure_code = (
            "invalid_analysis_brief"
            if isinstance(exc, ValidationError)
            else "brief_generation_error"
        )
        receipt = AnalysisBriefGenerationReceipt(
            status=status,
            failure_code=failure_code,
            failure_message=f"{type(exc).__name__}: {exc}",
            prompt_sha256=prompt_digest,
            response_schema_sha256=schema_digest,
            advice_sha256=advice_digest,
            provider=provider,
            model_id=model_id,
            generated_at=utc_now(),
        )
        record = _AnalysisBriefGenerationRecord(receipt=receipt)

    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            publish_bytes_write_once(str(path), canonical_json_bytes(record))
        except FileExistsError:
            persisted = _load_record(path)
            if persisted != record:
                raise ValueError(
                    "concurrent AnalysisBrief generation produced a different record"
                ) from None
            record = persisted
    return record.brief, record.receipt
