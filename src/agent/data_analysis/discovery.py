"""Manifest-only discovery for configured, operator-approved analysis packs."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from pydantic import model_validator

from agent.schemas.data_analysis.action_identity import GeneratedProgramIdentity
from agent.schemas.data_analysis.common import (
    CertifiedArtifactRef,
    FrozenModel,
    NonEmptyStr,
    Sha256,
    canonical_json_bytes,
    canonical_sha256,
)
from agent.schemas.data_analysis.context import SkillPackRef
from agent.schemas.data_analysis.generated_skill import GeneratedExperimentSkillRegistryRef
from agent.schemas.data_analysis.skills import (
    ResolvedSkillInterface,
    SkillCard,
    SkillContentFile,
    SkillEntrypoint,
    SkillIdentity,
    SkillPackManifest,
)

_IGNORED_GENERATED_DIRECTORIES = frozenset(
    {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)
_IGNORED_GENERATED_SUFFIXES = frozenset({".pyc", ".pyo"})


class SkillDiscoveryError(ValueError):
    """A configured pack could not be certified without importing code."""


class DiscoveredSkill(FrozenModel):
    identity: SkillIdentity
    card: SkillCard
    entrypoint: SkillEntrypoint
    implementation_files: tuple[SkillContentFile, ...]
    pack_root: NonEmptyStr
    manifest_ref: CertifiedArtifactRef
    environment_lock_ref: CertifiedArtifactRef | None = None

    def identity_dump(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"pack_root"})


class DiscoveredGeneratedExperimentSkill(FrozenModel):
    """A SkillCard whose exact implementation remains an untrusted program."""

    identity: SkillIdentity
    card: SkillCard
    program_identity: GeneratedProgramIdentity
    resolved_interface: ResolvedSkillInterface
    registry_root: NonEmptyStr
    program_declaration_ref: CertifiedArtifactRef

    def identity_dump(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"registry_root"})


DiscoveredAnalysisSkill = DiscoveredSkill | DiscoveredGeneratedExperimentSkill


class DiscoverySnapshot(FrozenModel):
    enabled_pack_ids: tuple[NonEmptyStr, ...]
    manifest_digests: tuple[Sha256, ...]
    skills: tuple[DiscoveredAnalysisSkill, ...]
    snapshot_digest: Sha256

    @model_validator(mode="after")
    def validate_snapshot(self) -> DiscoverySnapshot:
        expected = canonical_sha256(self.identity_body())
        if expected != self.snapshot_digest:
            raise ValueError("discovery snapshot digest does not match its canonical body")
        return self

    def identity_body(self) -> dict[str, object]:
        return {
            "enabled_pack_ids": list(self.enabled_pack_ids),
            "manifest_digests": list(self.manifest_digests),
            "skills": [item.identity_dump() for item in self.skills],
        }


def _resolve_within(root: Path, relative_ref: str) -> Path:
    root = root.expanduser().resolve()
    candidate = (root / relative_ref).resolve()
    if candidate != root and root not in candidate.parents:
        raise SkillDiscoveryError(f"pack path escapes configured root: {relative_ref!r}")
    return candidate


def _pack_file_records(root: Path, *, manifest_path: Path) -> list[dict[str, object]]:
    """Hash every non-generated regular pack file, with stable POSIX paths.

    v0.1 deliberately invalidates conservatively: documentation, configuration,
    locks, declared and accidentally undeclared helpers are all included. Only
    the manifest file itself, known generated cache directories, and Python
    bytecode are excluded. Runtime output must not be written inside a pack.
    """

    root = root.resolve()
    records: list[dict[str, object]] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names[:] = sorted(
            name for name in directory_names if name not in _IGNORED_GENERATED_DIRECTORIES
        )
        current = Path(directory)
        for directory_name in directory_names:
            if (current / directory_name).is_symlink():
                raise SkillDiscoveryError("symbolic-link directories are forbidden in skill packs")
        for name in sorted(file_names):
            path = current / name
            if path == manifest_path:
                continue
            if path.suffix in _IGNORED_GENERATED_SUFFIXES:
                continue
            if path.is_symlink() or not path.is_file():
                raise SkillDiscoveryError("skill pack content must be regular files, not links")
            payload = path.read_bytes()
            records.append(
                {
                    "relative_path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_size": len(payload),
                }
            )
    return sorted(records, key=lambda item: str(item["relative_path"]))


def compute_pack_content_sha256(
    root: Path,
    manifest: SkillPackManifest,
    *,
    manifest_path: Path,
) -> str:
    """Hash canonical manifest semantics plus ordered content records.

    ``manifest.canonical_body`` omits only ``pack_content_sha256``, avoiding a
    self-reference. File records use normalized root-relative POSIX paths and
    canonical lexical ordering.
    """

    domain = {
        "manifest": json.loads(manifest.canonical_body()),
        "files": _pack_file_records(root, manifest_path=manifest_path),
    }
    return hashlib.sha256(canonical_json_bytes(domain)).hexdigest()


def _verify_content_ref(root: Path, ref: CertifiedArtifactRef, *, label: str) -> Path:
    unresolved = root.expanduser().resolve() / ref.logical_ref
    if unresolved.is_symlink():
        raise SkillDiscoveryError(f"{label} must be a regular file, not a symbolic link")
    path = _resolve_within(root, ref.logical_ref)
    if not path.is_file():
        raise SkillDiscoveryError(f"{label} must be a regular file, not a symbolic link")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SkillDiscoveryError(f"cannot read {label}: {exc}") from exc
    if ref.byte_size is not None and len(payload) != ref.byte_size:
        raise SkillDiscoveryError(f"{label} byte size mismatch")
    if hashlib.sha256(payload).hexdigest() != ref.sha256:
        raise SkillDiscoveryError(f"{label} digest mismatch")
    return path


def load_verified_manifest(pack_ref: SkillPackRef) -> SkillPackManifest:
    root = Path(pack_ref.pack_root).expanduser().resolve()
    path = _verify_content_ref(
        root,
        pack_ref.manifest_ref,
        label=f"manifest {pack_ref.pack_id!r}",
    )
    payload = path.read_bytes()
    try:
        manifest = SkillPackManifest.model_validate_json(payload)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SkillDiscoveryError(f"invalid manifest for pack {pack_ref.pack_id!r}: {exc}") from exc
    if manifest.pack_id != pack_ref.pack_id:
        raise SkillDiscoveryError(
            f"configured pack ID {pack_ref.pack_id!r} does not match manifest {manifest.pack_id!r}"
        )
    observed_pack_digest = compute_pack_content_sha256(root, manifest, manifest_path=path)
    if observed_pack_digest != manifest.pack_content_sha256:
        raise SkillDiscoveryError(f"pack content digest mismatch for pack {pack_ref.pack_id!r}")
    if pack_ref.environment_lock_ref is not None:
        _verify_content_ref(
            root,
            pack_ref.environment_lock_ref,
            label=f"environment lock for pack {pack_ref.pack_id!r}",
        )
    return manifest


def discover_skills(
    pack_refs: tuple[SkillPackRef, ...],
    *,
    generated_skill_registry: GeneratedExperimentSkillRegistryRef | None = None,
) -> DiscoverySnapshot:
    """Read and certify manifest data only; no implementation module is imported."""

    discovered: list[DiscoveredAnalysisSkill] = []
    manifest_digests: list[str] = []
    seen_skill_ids: set[str] = set()
    for pack_ref in sorted(pack_refs, key=lambda item: item.pack_id):
        manifest = load_verified_manifest(pack_ref)
        manifest_digests.append(pack_ref.manifest_ref.sha256)
        for declaration in manifest.skills:
            skill_id = declaration.card.skill_id
            if skill_id in seen_skill_ids:
                raise SkillDiscoveryError(
                    f"duplicate skill ID {skill_id!r} across enabled packs; shadowing is forbidden"
                )
            seen_skill_ids.add(skill_id)
            discovered.append(
                DiscoveredSkill(
                    identity=SkillIdentity(
                        pack_id=manifest.pack_id,
                        pack_version=manifest.pack_version,
                        pack_content_sha256=manifest.pack_content_sha256,
                        skill_id=skill_id,
                        skill_version=declaration.card.skill_version,
                        implementation_sha256=declaration.implementation_sha256,
                        environment_lock_sha256=(
                            None
                            if pack_ref.environment_lock_ref is None
                            else pack_ref.environment_lock_ref.sha256
                        ),
                        determinism=declaration.card.determinism,
                    ),
                    card=declaration.card,
                    entrypoint=declaration.entrypoint,
                    implementation_files=declaration.implementation_files,
                    pack_root=str(Path(pack_ref.pack_root).expanduser().resolve()),
                    manifest_ref=pack_ref.manifest_ref,
                    environment_lock_ref=pack_ref.environment_lock_ref,
                )
            )
    enabled_pack_ids = sorted(pack.pack_id for pack in pack_refs)
    if generated_skill_registry is not None:
        from .generated_skill_registry import load_generated_skill_registry

        registry = load_generated_skill_registry(generated_skill_registry)
        manifest_digests.append(generated_skill_registry.manifest_ref.sha256)
        for promoted in registry.skills:
            skill_id = promoted.skill_identity.skill_id
            pack_id = promoted.skill_identity.pack_id
            if pack_id in enabled_pack_ids:
                raise SkillDiscoveryError(
                    f"generated experiment pack ID {pack_id!r} collides with an enabled pack"
                )
            enabled_pack_ids.append(pack_id)
            if skill_id in seen_skill_ids:
                raise SkillDiscoveryError(
                    f"duplicate skill ID {skill_id!r} across enabled packs; shadowing is forbidden"
                )
            seen_skill_ids.add(skill_id)
            discovered.append(
                DiscoveredGeneratedExperimentSkill(
                    identity=promoted.skill_identity,
                    card=promoted.declaration.card,
                    program_identity=promoted.program_identity,
                    resolved_interface=promoted.resolved_interface,
                    registry_root=generated_skill_registry.registry_root,
                    program_declaration_ref=promoted.program_declaration_ref,
                )
            )
    identity_body = {
        "enabled_pack_ids": sorted(enabled_pack_ids),
        "manifest_digests": manifest_digests,
        "skills": [item.identity_dump() for item in discovered],
    }
    return DiscoverySnapshot(
        enabled_pack_ids=tuple(sorted(enabled_pack_ids)),
        manifest_digests=tuple(manifest_digests),
        skills=tuple(discovered),
        snapshot_digest=canonical_sha256(identity_body),
    )


def search_skill_cards(
    snapshot: DiscoverySnapshot,
    query: str,
    *,
    limit: int = 8,
) -> tuple[DiscoveredAnalysisSkill, ...]:
    """Deterministic v0.1 keyword/tag/alias matching over lightweight cards."""

    if limit < 1:
        raise ValueError("skill search limit must be positive")
    tokens = {token for token in re.findall(r"[a-z0-9_+-]+", query.casefold()) if token}

    def rank(item: DiscoveredAnalysisSkill) -> tuple[int, str, str]:
        card = item.card
        exact = {card.skill_id.casefold(), *(alias.casefold() for alias in card.aliases)}
        indexed = {
            *(keyword.casefold() for keyword in card.keywords),
            *(tag.casefold() for tag in card.tags),
        }
        text = f"{card.title} {card.one_line_description} {card.applicable_when}".casefold()
        score = 5 * len(tokens & exact) + 3 * len(tokens & indexed)
        score += sum(1 for token in tokens if token in text)
        return (-score, item.identity.pack_id, card.skill_id)

    ranked = sorted(snapshot.skills, key=rank)
    if tokens:
        ranked = [item for item in ranked if rank(item)[0] < 0]
    return tuple(ranked[:limit])
