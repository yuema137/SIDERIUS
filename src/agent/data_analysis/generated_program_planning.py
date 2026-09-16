"""Two-stage planning support for immutable one-off generated programs."""

from __future__ import annotations

from typing import Any

from agent.prompt_templates.data_analysis import render_generated_program_prompt
from agent.schemas.data_analysis.action_identity import (
    GeneratedProgramGenerationProvenance,
    GeneratedProgramIdentity,
)
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.generated_program import GeneratedAnalysisProgram

from .generated_programs import GeneratedProgramDraft, persist_generated_program
from .persistence import AnalysisRunStore
from .structured_output import generate_validated


def generated_draft_semantics(value: object) -> object | None:
    """Anchor every executable decision; only rationale may change in repair."""

    if not isinstance(value, dict):
        return None
    required = {
        "program_id",
        "question_ids",
        "source_code",
        "input_slots",
        "expected_measurements",
        "resource_request",
        "determinism",
    }
    if not required.issubset(value):
        return None
    return {key: item for key, item in value.items() if key != "rationale"}


def prepare_generated_program(
    *,
    bridge: Any,
    store: AnalysisRunStore,
    analysis_input: DataAnalysisInput,
    question_ids: tuple[str, ...],
    provider: str,
    requested_model_id: str | None,
    llm_config: dict[str, object],
) -> tuple[GeneratedAnalysisProgram, GeneratedProgramIdentity]:
    """Generate, validate and persist source before final AnalysisPlan creation."""

    available_questions = {item.question_id for item in analysis_input.analysis_brief.questions}
    if not question_ids or not set(question_ids).issubset(available_questions):
        raise ValueError("generated-program questions must come from the AnalysisBrief")
    system, user = render_generated_program_prompt(
        analysis_input,
        question_ids=question_ids,
        output_schema=GeneratedProgramDraft.model_json_schema(),
    )
    draft = generate_validated(
        bridge,
        store=store,
        model_type=GeneratedProgramDraft,
        system=system,
        user=user,
        label="data_analysis.generated_program",
        semantic_projection=generated_draft_semantics,
    )
    if set(draft.question_ids) != set(question_ids):
        raise ValueError("generated program changed the selected capability-gap questions")
    resolved_model_id = requested_model_id or str(getattr(bridge, "model_name", "provider-default"))
    provenance = GeneratedProgramGenerationProvenance(
        provider=provider,
        model_id=resolved_model_id,
        llm_config_sha256=canonical_sha256(llm_config),
        generation_prompt_sha256=canonical_sha256({"system": system, "user": user}),
        originating_request_id=analysis_input.request_id,
        question_ids=question_ids,
    )
    return persist_generated_program(
        root=store.root,
        draft=draft,
        generation_provenance=provenance,
    )
