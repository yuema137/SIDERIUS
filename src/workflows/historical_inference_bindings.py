"""Run-bound artifact and plugin authorities for historical analysis inference."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_sha256
from agent.schemas.data_analysis.trained_model import ModelPluginIdentity
from core.campaign_identity import validate_path_component
from execute_tools.trained_model_artifact import copy_certified_artifact
from ml_models.plugin_binding import RunModelPluginBinding


@dataclass(frozen=True, slots=True)
class RunBoundHistoricalArtifactExporter:
    """Export only exact refs from the typed source-output workspace mapping."""

    roots_by_sha256: Mapping[str, Path]

    def export_artifact(self, ref: CertifiedArtifactRef, destination: Path) -> None:
        root = self.roots_by_sha256.get(ref.sha256)
        if root is None:
            raise ValueError("historical inference artifact was not declared by a prior record")
        copy_certified_artifact(root, ref, destination)


@dataclass(frozen=True, slots=True)
class RunBoundHistoricalModelPluginResolver:
    """Resolve a model implementation from run declarations or its exact local stage."""

    declared_plugins: RunModelPluginBinding | None
    generated_plugin_dir: Path

    def resolve_model_plugin(self, identity: ModelPluginIdentity) -> Path:
        member = validate_path_component(identity.member, kind="historical model plugin")
        matched = None
        if self.declared_plugins is not None:
            matched = next(
                (
                    item
                    for item in self.declared_plugins.plugins
                    if item.configured_ref == identity.configured_ref
                    and item.member == member
                    and item.model_type == identity.model_type
                    and item.content_sha256 == identity.content_sha256
                ),
                None,
            )
        if matched is not None:
            if identity.local_code_identity_sha256 is not None and (
                matched.local_code is None
                or canonical_sha256(matched.local_code) != identity.local_code_identity_sha256
            ):
                raise ValueError("historical model local-code identity differs from run binding")
            candidate = Path(matched.absolute_path)
        elif identity.configured_ref == "run-scoped-model-plugin":
            if identity.local_code_identity_sha256 is not None:
                raise ValueError(
                    "run-scoped generated model cannot claim package local-code identity"
                )
            candidate = self.generated_plugin_dir / member
        else:
            raise ValueError("historical model plugin is not in the run-approved plugin set")
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("approved historical model plugin is not a regular file")
        payload = candidate.read_bytes()
        if hashlib.sha256(payload).hexdigest() != identity.content_sha256:
            raise ValueError("approved historical model plugin content identity changed")
        return candidate
