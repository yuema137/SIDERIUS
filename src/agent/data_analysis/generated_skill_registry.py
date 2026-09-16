"""Content-addressed persistence for run-scoped generated experiment skills."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent.schemas.data_analysis.common import (
    CertifiedArtifactRef,
    canonical_json_bytes,
    canonical_sha256,
    utc_now,
)
from agent.schemas.data_analysis.generated_program import (
    GeneratedAnalysisProgram,
    GeneratedParameterDeclaration,
)
from agent.schemas.data_analysis.generated_skill import (
    GeneratedExperimentSkill,
    GeneratedExperimentSkillRegistry,
    GeneratedExperimentSkillRegistryRef,
    GeneratedSkillPromotionDraft,
    GeneratedSkillPromotionProvenance,
)
from agent.schemas.data_analysis.skills import (
    ResolvedSkillInterface,
    SkillCard,
    SkillContentFile,
    SkillDeclaration,
    SkillEntrypoint,
    SkillIdentity,
    implementation_identity_sha256,
)
from core.campaign_identity import validate_path_component
from core.durable_io import publish_bytes_write_once

from .generated_programs import load_generated_program


class GeneratedSkillRegistryError(ValueError):
    """A local registry failed identity, path, or content verification."""


def _verify_ref(root: Path, ref: CertifiedArtifactRef) -> Path:
    root = root.expanduser().resolve()
    unresolved = root / ref.logical_ref
    current = unresolved
    while current != root:
        if current.is_symlink():
            raise GeneratedSkillRegistryError("generated registry paths may not use symlinks")
        current = current.parent
    path = unresolved.resolve()
    if path == root or root not in path.parents or not path.is_file():
        raise GeneratedSkillRegistryError("generated registry artifact is missing or escapes root")
    payload = path.read_bytes()
    if ref.byte_size is not None and len(payload) != ref.byte_size:
        raise GeneratedSkillRegistryError("generated registry artifact byte size changed")
    if hashlib.sha256(payload).hexdigest() != ref.sha256:
        raise GeneratedSkillRegistryError("generated registry artifact digest changed")
    return path


def load_generated_skill_registry(
    ref: GeneratedExperimentSkillRegistryRef,
) -> GeneratedExperimentSkillRegistry:
    root = Path(ref.registry_root)
    path = _verify_ref(root, ref.manifest_ref)
    try:
        registry = GeneratedExperimentSkillRegistry.model_validate_json(path.read_bytes())
    except (ValueError, json.JSONDecodeError) as exc:
        raise GeneratedSkillRegistryError("generated skill registry manifest is invalid") from exc
    if registry.registry_id != ref.registry_id or registry.registry_sha256 != ref.registry_sha256:
        raise GeneratedSkillRegistryError("generated skill registry identity differs from its ref")
    for skill in registry.skills:
        program, _source = load_generated_program(
            root=root,
            identity=skill.program_identity,
        )
        if program.input_slots != skill.declaration.card.input_slots:
            raise GeneratedSkillRegistryError("promoted SkillCard input slots differ from program")
        declaration_path = _verify_ref(root, skill.program_declaration_ref)
        if GeneratedAnalysisProgram.model_validate_json(declaration_path.read_bytes()) != program:
            raise GeneratedSkillRegistryError(
                "promoted program ref differs from its executable declaration"
            )
        expected_schema = generated_parameter_json_schema(program.parameters)
        if skill.resolved_interface.parameter_json_schema != expected_schema:
            raise GeneratedSkillRegistryError(
                "promoted skill parameter interface differs from its program"
            )
        if skill.declaration.implementation_files != (
            SkillContentFile(
                relative_path=program.source_ref.logical_ref,
                sha256=program.source_sha256,
            ),
        ):
            raise GeneratedSkillRegistryError(
                "promoted skill implementation differs from its program source"
            )
    return registry


def generated_parameter_json_schema(
    declarations: tuple[GeneratedParameterDeclaration, ...],
) -> dict[str, Any]:
    """Build the exact small JSON-schema surface exposed to the planner."""

    type_names = {
        "string": "string",
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
    }
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    for item in declarations:
        json_type: str | list[str] = type_names[item.value_type]
        if not item.required and item.default is None:
            json_type = [json_type, "null"]
        value: dict[str, Any] = {
            "type": json_type,
            "description": item.description,
        }
        if item.choices:
            value["enum"] = list(item.choices)
        if item.minimum is not None:
            value["minimum"] = item.minimum
        if item.maximum is not None:
            value["maximum"] = item.maximum
        if not item.required:
            value["default"] = item.default
        else:
            required.append(item.name)
        properties[item.name] = value
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _copy_program_into_registry(
    *,
    source_root: Path,
    registry_root: Path,
    program: GeneratedAnalysisProgram,
    identity,
) -> CertifiedArtifactRef:
    loaded, source_path = load_generated_program(root=source_root, identity=identity)
    if loaded != program:
        raise GeneratedSkillRegistryError("promotion source program differs from persisted bytes")
    source_destination = registry_root / program.source_ref.logical_ref
    source_bytes = source_path.read_bytes()
    try:
        publish_bytes_write_once(str(source_destination), source_bytes)
    except FileExistsError:
        if source_destination.read_bytes() != source_bytes:
            raise GeneratedSkillRegistryError("generated source collision in registry") from None
    declaration_relative = (
        Path("generated_analysis")
        / "programs"
        / validate_path_component(program.program_id, kind="generated program id")
        / f"{identity.declaration_sha256}.json"
    )
    declaration_bytes = canonical_json_bytes(program)
    declaration_path = registry_root / declaration_relative
    try:
        publish_bytes_write_once(str(declaration_path), declaration_bytes)
    except FileExistsError:
        if declaration_path.read_bytes() != declaration_bytes:
            raise GeneratedSkillRegistryError(
                "generated declaration collision in registry"
            ) from None
    return CertifiedArtifactRef(
        logical_ref=declaration_relative.as_posix(),
        sha256=hashlib.sha256(declaration_bytes).hexdigest(),
        media_type="application/json",
        byte_size=len(declaration_bytes),
    )


def promote_generated_program(
    *,
    source_root: Path,
    registry_root: Path,
    registry_id: str,
    existing: GeneratedExperimentSkillRegistry | None,
    program: GeneratedAnalysisProgram,
    program_identity,
    draft: GeneratedSkillPromotionDraft,
    originating_request_id: str,
    originating_result_id: str,
) -> tuple[GeneratedExperimentSkillRegistry, GeneratedExperimentSkillRegistryRef]:
    """Persist one explicit promotion and return a new immutable registry snapshot."""

    registry_id = validate_path_component(registry_id, kind="generated skill registry id")
    skill_id = validate_path_component(draft.skill_id, kind="generated experiment skill id")
    if draft.program_id != program.program_id:
        raise GeneratedSkillRegistryError("promotion draft references a different program")
    if existing is not None and existing.registry_id != registry_id:
        raise GeneratedSkillRegistryError("cannot merge different generated skill registries")
    registry_root.mkdir(parents=True, exist_ok=True)
    program_ref = _copy_program_into_registry(
        source_root=source_root,
        registry_root=registry_root,
        program=program,
        identity=program_identity,
    )
    card = SkillCard(
        skill_id=skill_id,
        title=draft.title,
        one_line_description=draft.one_line_description,
        keywords=draft.keywords,
        aliases=draft.aliases,
        tags=draft.tags,
        input_slots=program.input_slots,
        produced_artifact_types=tuple(item.artifact_type for item in program.expected_artifacts),
        applicable_when=draft.applicable_when,
        time_cost=draft.time_cost,
        memory_cost=draft.memory_cost,
        preferred_device="cpu",
        supports_sampling=True,
        skill_version="1",
        determinism=program.determinism,
        determinism_notes=(
            None
            if program.determinism == "deterministic"
            else "Generated program declared nondeterministic execution."
        ),
    )
    content_file = SkillContentFile(
        relative_path=program.source_ref.logical_ref,
        sha256=program.source_sha256,
    )
    implementation_sha256 = implementation_identity_sha256((content_file,))
    declaration = SkillDeclaration(
        card=card,
        entrypoint=SkillEntrypoint(
            module_path=program.source_ref.logical_ref,
            callable_symbol="analyze",
            parameter_schema_symbol="GENERATED_PARAMETER_SCHEMA",
            instructions_symbol="GENERATED_SKILL_INSTRUCTIONS",
        ),
        implementation_files=(content_file,),
        implementation_sha256=implementation_sha256,
    )
    parameter_schema = generated_parameter_json_schema(program.parameters)
    parameter_schema_sha256 = canonical_sha256(parameter_schema)
    pack_content_sha256 = canonical_sha256(
        {
            "registry_id": registry_id,
            "declaration": declaration.model_dump(mode="json"),
            "program_identity": program_identity.model_dump(mode="json"),
            "parameter_json_schema": parameter_schema,
        }
    )
    skill_identity = SkillIdentity(
        # Each promoted capability is one immutable virtual single-skill pack.
        # A registry may gain later skills without changing an existing skill's
        # executable identity or assigning different pack digests to one pack ID.
        pack_id=f"generated-experiment.{registry_id}.{skill_id}",
        pack_version="1",
        pack_content_sha256=pack_content_sha256,
        skill_id=skill_id,
        skill_version="1",
        implementation_sha256=implementation_sha256,
        environment_lock_sha256=program_identity.runtime_environment_sha256,
        determinism=program.determinism,
    )
    interface = ResolvedSkillInterface(
        skill_identity=skill_identity,
        parameter_json_schema=parameter_schema,
        parameter_schema_sha256=parameter_schema_sha256,
        selected_skill_instructions=(
            "Execute the exact promoted generated analysis program through the untrusted "
            "AnalysisCodeSandbox. Use only declared inputs and parameters."
        ),
    )
    promoted = GeneratedExperimentSkill(
        declaration=declaration,
        skill_identity=skill_identity,
        program_identity=program_identity,
        program_declaration_ref=program_ref,
        resolved_interface=interface,
        promotion_provenance=GeneratedSkillPromotionProvenance(
            originating_request_id=originating_request_id,
            originating_result_id=originating_result_id,
            rationale=draft.rationale,
            promoted_at=utc_now(),
        ),
    )
    skills = list(existing.skills if existing is not None else ())
    same_id = [item for item in skills if item.skill_identity.skill_id == skill_id]
    if same_id:
        if same_id[0].executable_identity_body() != promoted.executable_identity_body():
            raise GeneratedSkillRegistryError("generated skill ID already names different content")
    else:
        skills.append(promoted)
    skills.sort(key=lambda item: item.skill_identity.skill_id)
    body = {
        "schema_version": 1,
        "registry_id": registry_id,
        "skills": [item.model_dump(mode="json") for item in skills],
    }
    registry = GeneratedExperimentSkillRegistry(
        **body,
        registry_sha256=canonical_sha256(body),
    )
    payload = canonical_json_bytes(registry)
    relative = Path("registries") / f"{registry.registry_sha256}.json"
    path = registry_root / relative
    try:
        publish_bytes_write_once(str(path), payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise GeneratedSkillRegistryError("generated registry manifest collision") from None
    manifest_ref = CertifiedArtifactRef(
        logical_ref=relative.as_posix(),
        sha256=hashlib.sha256(payload).hexdigest(),
        media_type="application/json",
        byte_size=len(payload),
    )
    return registry, GeneratedExperimentSkillRegistryRef(
        registry_id=registry_id,
        registry_root=str(registry_root.resolve()),
        manifest_ref=manifest_ref,
        registry_sha256=registry.registry_sha256,
    )
