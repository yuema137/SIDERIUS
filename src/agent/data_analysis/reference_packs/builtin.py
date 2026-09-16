"""Resolve shipped packs through the same manifest contract as out-of-tree packs."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agent.schemas.data_analysis.common import CertifiedArtifactRef
from agent.schemas.data_analysis.context import SkillPackRef

_PACK_DIRECTORIES = {
    "core-analysis": "core_analysis",
    "time-series": "time_series",
}


def builtin_pack_ref(pack_id: str) -> SkillPackRef:
    try:
        directory = _PACK_DIRECTORIES[pack_id]
    except KeyError as exc:
        raise KeyError(f"unknown built-in analysis pack {pack_id!r}") from exc
    root = Path(__file__).resolve().parent / directory
    manifest = root / "manifest.json"
    payload = manifest.read_bytes()
    return SkillPackRef(
        pack_id=pack_id,
        pack_root=str(root),
        manifest_ref=CertifiedArtifactRef(
            logical_ref="manifest.json",
            sha256=hashlib.sha256(payload).hexdigest(),
            media_type="application/json",
            byte_size=len(payload),
        ),
    )


def builtin_pack_refs(*pack_ids: str) -> tuple[SkillPackRef, ...]:
    return tuple(builtin_pack_ref(pack_id) for pack_id in pack_ids)
