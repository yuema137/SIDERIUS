"""Persist and resolve immutable experiment-local generated analysis programs."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import platform
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from agent.schemas.data_analysis.action_identity import (
    GeneratedProgramGenerationProvenance,
    GeneratedProgramIdentity,
)
from agent.schemas.data_analysis.common import (
    CertifiedArtifactRef,
    FrozenModel,
    NonEmptyStr,
    canonical_json_bytes,
    canonical_sha256,
)
from agent.schemas.data_analysis.generated_program import (
    GeneratedAnalysisProgram,
    GeneratedArtifactDeclaration,
    GeneratedMeasurementDeclaration,
    GeneratedParameterDeclaration,
    GeneratedProgramResourceRequest,
    validate_generated_input_formats,
)
from agent.schemas.data_analysis.skills import SkillInputSlot
from core.campaign_identity import validate_path_component
from core.durable_io import publish_bytes_write_once

MAX_GENERATED_SOURCE_BYTES = 128 * 1024


class GeneratedProgramDraft(FrozenModel):
    """Validated LLM output before source is persisted and content-addressed."""

    program_id: NonEmptyStr
    question_ids: tuple[NonEmptyStr, ...]
    source_code: NonEmptyStr = Field(max_length=MAX_GENERATED_SOURCE_BYTES)
    input_slots: tuple[SkillInputSlot, ...]
    parameters: tuple[GeneratedParameterDeclaration, ...] = ()
    expected_measurements: tuple[GeneratedMeasurementDeclaration, ...]
    expected_artifacts: tuple[GeneratedArtifactDeclaration, ...] = ()
    resource_request: GeneratedProgramResourceRequest
    determinism: Literal["deterministic", "nondeterministic"]
    seed: int | None = Field(default=None, ge=0)
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_source_shape(self) -> GeneratedProgramDraft:
        validate_path_component(self.program_id, kind="generated analysis program id")
        validate_generated_input_formats(self.input_slots)
        if self.determinism not in {"deterministic", "nondeterministic"}:
            raise ValueError("generated program determinism posture is invalid")
        if self.determinism == "deterministic" and self.seed is None:
            raise ValueError("deterministic generated programs require an explicit seed")
        try:
            tree = ast.parse(self.source_code, filename=f"{self.program_id}.py", mode="exec")
        except SyntaxError as exc:
            raise ValueError(f"generated program source is invalid Python: {exc.msg}") from exc
        analyze_functions = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "analyze"
        ]
        if len(analyze_functions) != 1 or isinstance(analyze_functions[0], ast.AsyncFunctionDef):
            raise ValueError("generated source requires exactly one synchronous analyze function")
        function = analyze_functions[0]
        argument_names = [argument.arg for argument in function.args.args]
        if argument_names != ["inputs", "parameters", "output_directory"]:
            raise ValueError(
                "analyze must have signature analyze(inputs, parameters, output_directory)"
            )
        if function.args.vararg or function.args.kwarg or function.args.kwonlyargs:
            raise ValueError("generated analyze function may not use variadic/keyword-only args")
        return self


def runtime_environment_identity() -> str:
    """Hash dependencies plus the code that defines generated execution semantics."""

    distributions = sorted(
        {
            (distribution.metadata["Name"].casefold(), distribution.version)
            for distribution in importlib.metadata.distributions()
            if distribution.metadata.get("Name")
        }
    )
    module_root = Path(__file__).resolve().parent
    schema_root = module_root.parent / "schemas" / "data_analysis"
    runtime_paths = (
        Path(__file__).resolve(),
        module_root / "analysis_code_sandbox.py",
        module_root / "generated_program_runner.py",
        module_root / "generated_program_executor.py",
        module_root / "executor.py",
        module_root / "persistence.py",
        schema_root / "generated_program.py",
        schema_root / "view_formats.py",
        schema_root / "skills.py",
    )
    runtime_files = {
        path.relative_to(module_root.parent.parent).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in runtime_paths
    }
    return canonical_sha256(
        {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "python_abi": sys.implementation.cache_tag,
            "distributions": distributions,
            "sandbox_runtime_files": runtime_files,
        }
    )


def persist_generated_program(
    *,
    root: Path,
    draft: GeneratedProgramDraft,
    generation_provenance: GeneratedProgramGenerationProvenance,
) -> tuple[GeneratedAnalysisProgram, GeneratedProgramIdentity]:
    """Persist exact source/declaration before any executable plan can reference it."""

    program_id = validate_path_component(draft.program_id, kind="generated analysis program id")
    source_bytes = draft.source_code.encode("utf-8")
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    source_relative = Path("generated_analysis") / "sources" / f"{source_sha256}.py"
    source_path = root / source_relative
    source_ref = CertifiedArtifactRef(
        logical_ref=source_relative.as_posix(),
        sha256=source_sha256,
        media_type="text/x-python",
        byte_size=len(source_bytes),
    )
    program = GeneratedAnalysisProgram(
        program_id=program_id,
        question_ids=draft.question_ids,
        source_ref=source_ref,
        source_sha256=source_sha256,
        input_slots=draft.input_slots,
        parameters=draft.parameters,
        expected_measurements=draft.expected_measurements,
        expected_artifacts=draft.expected_artifacts,
        resource_request=draft.resource_request,
        determinism=draft.determinism,
        seed=draft.seed,
        generation_provenance=generation_provenance,
    )
    identity = program.identity(runtime_environment_sha256=runtime_environment_identity())
    try:
        publish_bytes_write_once(str(source_path), source_bytes)
    except FileExistsError:
        if source_path.read_bytes() != source_bytes:
            raise ValueError("generated source content-address collision") from None
    declaration_relative = (
        Path("generated_analysis") / "programs" / program_id / f"{identity.declaration_sha256}.json"
    )
    declaration_bytes = canonical_json_bytes(program)
    declaration_path = root / declaration_relative
    try:
        publish_bytes_write_once(str(declaration_path), declaration_bytes)
    except FileExistsError:
        existing = GeneratedAnalysisProgram.model_validate_json(declaration_path.read_bytes())
        if existing.executable_declaration_body() != program.executable_declaration_body():
            raise ValueError("generated declaration identity collision") from None
    provenance_relative = (
        Path("generated_analysis")
        / "generation_provenance"
        / program_id
        / f"{canonical_sha256(generation_provenance)}.json"
    )
    provenance_bytes = canonical_json_bytes(generation_provenance)
    try:
        publish_bytes_write_once(str(root / provenance_relative), provenance_bytes)
    except FileExistsError:
        if (root / provenance_relative).read_bytes() != provenance_bytes:
            raise ValueError("generated provenance identity collision") from None
    return program, identity


def load_generated_program(
    *,
    root: Path,
    identity: GeneratedProgramIdentity,
) -> tuple[GeneratedAnalysisProgram, Path]:
    """Resolve exact persisted bytes; source mutation after planning fails closed."""

    program_id = validate_path_component(identity.program_id, kind="generated analysis program id")
    declaration_path = (
        root
        / "generated_analysis"
        / "programs"
        / program_id
        / f"{identity.declaration_sha256}.json"
    )
    current = declaration_path
    while current != root:
        if current.is_symlink():
            raise ValueError("persisted generated declaration may not use symbolic links")
        current = current.parent
    try:
        declaration_bytes = declaration_path.read_bytes()
        program = GeneratedAnalysisProgram.model_validate_json(declaration_bytes)
    except FileNotFoundError as exc:
        raise ValueError("persisted generated program declaration is missing") from exc
    if program.identity(runtime_environment_sha256=runtime_environment_identity()) != identity:
        raise ValueError("persisted generated program identity differs from the plan")
    source_candidate = root / program.source_ref.logical_ref
    current = source_candidate
    while current != root:
        if current.is_symlink():
            raise ValueError("persisted generated source may not use symbolic links")
        current = current.parent
    source_path = source_candidate.resolve()
    resolved_root = root.resolve()
    if resolved_root not in source_path.parents or not source_path.is_file():
        raise ValueError("persisted generated source is missing or escapes the run root")
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != program.source_ref.byte_size:
        raise ValueError("persisted generated source byte size changed")
    if hashlib.sha256(source_bytes).hexdigest() != identity.source_sha256:
        raise ValueError("persisted generated source digest differs from the plan")
    return program, source_path
