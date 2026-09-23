"""Two-stage planning support for immutable one-off generated programs."""

from __future__ import annotations

import ast
import io
import symtable
import tokenize
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
from .structured_output import DataAnalysisStructuredOutputError, generate_validated


def _python_source_repair_anchor(
    source: str,
) -> tuple[tuple[tuple[int, str], ...], tuple[str, ...]]:
    """Permit only Python-literal spelling repair, not new analysis logic."""

    replacements = {"null": "None", "true": "True", "false": "False"}
    tokens = tuple(
        (
            token.type,
            replacements.get(token.string, token.string)
            if token.type == tokenize.NAME
            else token.string,
        )
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
    )
    tree = ast.parse(source, mode="exec")
    loaded_literal_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in replacements
    }
    pending_scopes = [symtable.symtable(source, "<generated-analysis>", "exec")]
    while pending_scopes:
        scope = pending_scopes.pop()
        for name in loaded_literal_names.intersection(scope.get_identifiers()):
            symbol = scope.lookup(name)
            if (
                symbol.is_assigned()
                or symbol.is_imported()
                or symbol.is_parameter()
                or symbol.is_declared_global()
                or symbol.is_nonlocal()
            ):
                raise ValueError(f"JSON literal name {name!r} has a Python binding")
        pending_scopes.extend(scope.get_children())
    match_patterns = tuple(
        ast.dump(node.pattern, include_attributes=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.match_case)
    )
    return tokens, match_patterns


def generated_draft_semantics(value: object) -> object | None:
    """Anchor executable decisions; allow only JSON-to-Python literal spelling repair."""

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
    anchored = {key: item for key, item in value.items() if key != "rationale"}
    source = anchored.get("source_code")
    if not isinstance(source, str):
        return None
    try:
        anchored["source_code"] = _python_source_repair_anchor(source)
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None
    return anchored


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
    # Generation precedes AnalysisPlan recovery and needs its own bounded retry.
    # A fresh draft may change decisions; a representation repair still may not.
    for attempt in range(2):
        try:
            draft = generate_validated(
                bridge,
                store=store,
                model_type=GeneratedProgramDraft,
                system=system,
                user=user,
                label=(
                    "data_analysis.generated_program"
                    if attempt == 0
                    else "data_analysis.generated_program.regeneration"
                ),
                semantic_projection=generated_draft_semantics,
            )
            break
        except DataAnalysisStructuredOutputError as exc:
            if attempt:
                raise
            user += (
                f"\nThe previous generated program was rejected before execution: {exc}.\n"
                f"{exc.planning_feedback}\n"
                "This is one fresh generation attempt, not representation-only repair. "
                "Return a complete valid declaration and Python source for the same questions "
                "under the same access/resource contract. Do not widen access.\n"
            )
    else:  # pragma: no cover - each final attempt returns a draft or raises
        raise AssertionError("bounded generated-program recovery must return or raise")
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
