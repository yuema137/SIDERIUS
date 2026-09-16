"""Classify trusted skill origin from immutable manifest/content provenance."""

from __future__ import annotations

from functools import lru_cache

from agent.schemas.data_analysis.action_identity import AnalysisExecutionOrigin

from .discovery import DiscoveredSkill, load_verified_manifest
from .reference_packs.builtin import builtin_pack_refs


@lru_cache(maxsize=1)
def _reference_skill_identities() -> frozenset[tuple[str, str, str, str, str, str]]:
    identities: set[tuple[str, str, str, str, str, str]] = set()
    for pack_ref in builtin_pack_refs("core-analysis", "time-series"):
        manifest = load_verified_manifest(pack_ref)
        for declaration in manifest.skills:
            identities.add(
                (
                    manifest.pack_id,
                    manifest.pack_version,
                    manifest.pack_content_sha256,
                    declaration.card.skill_id,
                    declaration.card.skill_version,
                    declaration.implementation_sha256,
                )
            )
    return frozenset(identities)


def trusted_skill_execution_origin(skill: DiscoveredSkill) -> AnalysisExecutionOrigin:
    """Use content identity, never an absolute pack path, to choose provenance."""

    identity = skill.identity
    key = (
        identity.pack_id,
        identity.pack_version,
        identity.pack_content_sha256,
        identity.skill_id,
        identity.skill_version,
        identity.implementation_sha256,
    )
    return (
        "reference_skill" if key in _reference_skill_identities() else "configured_external_skill"
    )
