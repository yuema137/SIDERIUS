"""Selected-only lazy loading and parameter validation for analysis skills."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import BaseModel

from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.context import SkillPackRef
from agent.schemas.data_analysis.skills import (
    ResolvedSkillInterface,
    implementation_identity_sha256,
    parameter_schema_sha256,
)

from .discovery import DiscoveredSkill, load_verified_manifest
from .environment import verify_environment_lock


class SkillLoadError(ValueError):
    """A selected implementation or its declared interface failed certification."""


class LoadedSkill:
    """Process-local loaded implementation; deliberately not a public schema."""

    def __init__(
        self,
        *,
        discovered: DiscoveredSkill,
        module_path: Path,
        parameter_schema: type[BaseModel],
        run: Any,
        instructions: str,
        environment_lock_verified: bool,
    ) -> None:
        self.discovered = discovered
        self.module_path = module_path
        self.parameter_schema = parameter_schema
        self.run = run
        self.instructions = instructions
        self.environment_lock_verified = environment_lock_verified

    def validate_parameters(self, parameters: dict[str, Any]) -> BaseModel:
        return self.parameter_schema.model_validate(parameters)

    @property
    def parameter_schema_sha256(self) -> str:
        return parameter_schema_sha256(self.parameter_schema)

    def validated_parameters_sha256(self, parameters: BaseModel) -> str:
        return canonical_sha256(parameters.model_dump(mode="json"))

    def resolved_interface(self) -> ResolvedSkillInterface:
        schema = self.parameter_schema.model_json_schema()
        return ResolvedSkillInterface(
            skill_identity=self.discovered.identity,
            parameter_json_schema=schema,
            parameter_schema_sha256=parameter_schema_sha256(self.parameter_schema),
            selected_skill_instructions=self.instructions,
        )


def resolve_skill_module_path(skill: DiscoveredSkill) -> Path:
    root = Path(skill.pack_root).resolve()
    path = (root / skill.entrypoint.module_path).resolve()
    if path != root and root not in path.parents:
        raise SkillLoadError("selected skill module escapes its configured pack root")
    return path


def load_selected_skill(skill: DiscoveredSkill) -> LoadedSkill:
    """Import one selected implementation after verifying its declared content digest."""

    root = Path(skill.pack_root).resolve()
    # Re-verify the complete pack at selected-load time to close discovery/load TOCTOU.
    load_verified_manifest(
        SkillPackRef(
            pack_id=skill.identity.pack_id,
            pack_root=skill.pack_root,
            manifest_ref=skill.manifest_ref,
            environment_lock_ref=skill.environment_lock_ref,
        )
    )
    for content_file in skill.implementation_files:
        content_path = (root / content_file.relative_path).resolve()
        if content_path == root or root not in content_path.parents:
            raise SkillLoadError("selected implementation file escapes its pack root")
        unresolved_content_path = root / content_file.relative_path
        if unresolved_content_path.is_symlink() or not unresolved_content_path.is_file():
            raise SkillLoadError("selected implementation content must be a regular file")
        try:
            observed_file = hashlib.sha256(content_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise SkillLoadError(f"cannot read selected implementation file: {exc}") from exc
        if observed_file != content_file.sha256:
            raise SkillLoadError(
                f"implementation file digest mismatch: {content_file.relative_path!r}"
            )
    if (
        implementation_identity_sha256(skill.implementation_files)
        != skill.identity.implementation_sha256
    ):
        raise SkillLoadError("selected implementation closure identity mismatch")
    environment_lock_verified = verify_environment_lock(root, skill.environment_lock_ref)

    path = resolve_skill_module_path(skill)
    package_name = (
        f"_siderius_analysis_pack_{skill.identity.pack_id.replace('-', '_')}_"
        f"{skill.identity.pack_content_sha256[:16]}"
    )
    relative_module = skill.entrypoint.module_path.removesuffix(".py").replace("/", ".")
    module_name = f"{package_name}.{relative_module}"
    package_parts = module_name.split(".")[:-1]
    for index in range(1, len(package_parts) + 1):
        current_name = ".".join(package_parts[:index])
        if current_name in sys.modules:
            continue
        package = ModuleType(current_name)
        relative_parts = package_parts[1:index]
        package.__path__ = [str(root.joinpath(*relative_parts))]  # type: ignore[attr-defined]
        package.__package__ = current_name
        sys.modules[current_name] = package
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SkillLoadError(f"cannot construct import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise SkillLoadError(f"selected skill import failed: {exc}") from exc

    parameter_schema = getattr(module, skill.entrypoint.parameter_schema_symbol, None)
    run = getattr(module, skill.entrypoint.callable_symbol, None)
    instructions = getattr(module, skill.entrypoint.instructions_symbol, None)
    if not inspect.isclass(parameter_schema) or not issubclass(parameter_schema, BaseModel):
        raise SkillLoadError("selected skill parameter schema is not a Pydantic BaseModel class")
    if not callable(run):
        raise SkillLoadError("selected skill entrypoint is not callable")
    if not isinstance(instructions, str) or not instructions.strip():
        raise SkillLoadError("selected skill instructions must be a non-empty string")
    signature = inspect.signature(run)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if len(positional) != 3 or any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    ):
        raise SkillLoadError(
            "selected skill entrypoint must accept exactly (skill_input, parameters, runtime)"
        )
    return LoadedSkill(
        discovered=skill,
        module_path=path,
        parameter_schema=parameter_schema,
        run=run,
        instructions=instructions,
        environment_lock_verified=environment_lock_verified,
    )
