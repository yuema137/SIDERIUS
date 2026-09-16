"""Reference-workflow policy for the optional Data Analysis capability.

This module owns composition semantics only.  It validates caller-authored
analysis policy and projects existing task-composition authorities into the
caller-independent :class:`DataAnalysisInput` ingredients; it does not add
fields to, or reinterpret, the Data Analysis capability contract.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import StrictBool, model_validator

from agent.data_analysis.discovery import discover_skills
from agent.data_analysis.reference_packs import builtin_pack_refs
from agent.schemas.data_analysis.access import AnalysisAccessPolicy
from agent.schemas.data_analysis.assets import AnalysisAsset, TaskDataAssetLocation
from agent.schemas.data_analysis.common import CertifiedArtifactRef, FrozenModel, NonEmptyStr
from agent.schemas.data_analysis.context import AnalysisTaskContext, SkillPackRef
from agent.schemas.data_analysis.resources import AnalysisResourceEnvelope
from execute_tools.analysis_materialization import (
    TaskAnalysisCapability,
    TaskHistoricalInferenceInputCapability,
)
from execute_tools.evaluation_metric import MetricIdentityKey


class DataAnalysisWorkflowConfig(FrozenModel):
    """Caller-owned policy loaded by an enabled ``data_analysis`` edge."""

    schema_version: Literal[1] = 1
    scientific_goal: NonEmptyStr
    input_description: NonEmptyStr
    target_description: str | None = None
    scientific_constraints: tuple[NonEmptyStr, ...] = ()
    available_assets: tuple[AnalysisAsset, ...]
    access_policy: AnalysisAccessPolicy
    resource_envelope: AnalysisResourceEnvelope
    builtin_skill_packs: tuple[Literal["core-analysis", "time-series"], ...] = ()
    external_skill_packs: tuple[SkillPackRef, ...] = ()
    allow_generated_skill_promotion: StrictBool = False
    historical_inference_base_asset_id: NonEmptyStr | None = None
    report_schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def validate_policy(self) -> DataAnalysisWorkflowConfig:
        if not self.available_assets:
            raise ValueError("an enabled workflow analysis config requires available_assets")
        pack_ids = [
            *self.builtin_skill_packs,
            *(item.pack_id for item in self.external_skill_packs),
        ]
        if not pack_ids:
            raise ValueError("an enabled workflow analysis config requires at least one skill pack")
        if len(set(pack_ids)) != len(pack_ids):
            raise ValueError("workflow analysis skill pack IDs must be unique")
        if len(set(self.scientific_constraints)) != len(self.scientific_constraints):
            raise ValueError("workflow analysis scientific constraints must be unique")
        if self.historical_inference_base_asset_id is not None:
            if not self.access_policy.allow_model_inference:
                raise ValueError("historical inference base asset requires model inference policy")
            matching = [
                asset
                for asset in self.available_assets
                if asset.asset_id == self.historical_inference_base_asset_id
            ]
            if len(matching) != 1 or matching[0].asset_type != "dataset":
                raise ValueError("historical inference base asset must name one dataset asset")
            if not isinstance(matching[0].location, TaskDataAssetLocation):
                raise ValueError("historical inference base asset must be task-owned data")
        return self


@dataclass(frozen=True, slots=True)
class ResolvedWorkflowDataAnalysis:
    """Immutable analysis authorities resolved once at the composition edge."""

    task_context: AnalysisTaskContext
    available_assets: tuple[AnalysisAsset, ...]
    access_policy: AnalysisAccessPolicy
    resource_envelope: AnalysisResourceEnvelope
    allowed_skill_packs: tuple[SkillPackRef, ...]
    task_analysis_capability: TaskAnalysisCapability
    report_schema_version: int
    config_content_sha256: str
    config_path: str
    allow_generated_skill_promotion: bool = False
    historical_inference_base_asset_id: str | None = None
    dataset_profile_path: str | None = None

    def canonical_identity(self) -> dict[str, Any]:
        """Host-independent semantic identity; absolute paths are excluded."""

        identity = {
            "task_context": self.task_context.model_dump(mode="json"),
            "available_assets": [item.model_dump(mode="json") for item in self.available_assets],
            "access_policy": self.access_policy.model_dump(mode="json"),
            "resource_envelope": self.resource_envelope.model_dump(mode="json"),
            "allowed_skill_packs": [
                {
                    "pack_id": item.pack_id,
                    "manifest_ref": item.manifest_ref.model_dump(mode="json"),
                    "environment_lock_ref": (
                        None
                        if item.environment_lock_ref is None
                        else item.environment_lock_ref.model_dump(mode="json")
                    ),
                }
                for item in sorted(self.allowed_skill_packs, key=lambda pack: pack.pack_id)
            ],
            "report_schema_version": self.report_schema_version,
        }
        if self.allow_generated_skill_promotion:
            identity["allow_generated_skill_promotion"] = True
        if self.historical_inference_base_asset_id is not None:
            identity["historical_inference_base_asset_id"] = self.historical_inference_base_asset_id
        return identity


def _resolve_external_pack(pack: SkillPackRef, *, config_dir: Path) -> SkillPackRef:
    root = Path(pack.pack_root)
    if not root.is_absolute():
        root = (config_dir / root).resolve()
    return pack.model_copy(update={"pack_root": str(root)})


def compose_workflow_data_analysis(
    section: object,
    *,
    manifest_path: str,
    task_data_path: object,
    task_data_path_id: str,
    task_description: str,
    forward_contract,
    metric,
    dataset_profile_ref: str,
    dataset_profile_path: str,
) -> ResolvedWorkflowDataAnalysis | None:
    """Resolve the optional manifest section without importing any skill implementation."""

    if section is None:
        return None
    if not isinstance(section, dict):
        raise ValueError("section 'data_analysis' must be a mapping")
    unknown = sorted(set(section) - {"enabled", "config"})
    if unknown:
        raise ValueError(f"section 'data_analysis' declares unknown key(s) {unknown}")
    enabled = section.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("data_analysis.enabled must be a boolean")
    if not enabled:
        if set(section) != {"enabled"}:
            raise ValueError("disabled data_analysis may declare only enabled: false")
        return None
    config_ref = section.get("config")
    if not isinstance(config_ref, str) or not config_ref.strip():
        raise ValueError("enabled data_analysis requires a non-empty config ref")
    manifest_dir = Path(manifest_path).resolve().parent
    config_path = Path(config_ref)
    if not config_path.is_absolute():
        config_path = (manifest_dir / config_path).resolve()
    try:
        payload = config_path.read_bytes()
    except OSError as exc:
        raise ValueError(
            f"data_analysis config at {str(config_path)!r} is unreadable: {exc}"
        ) from exc
    try:
        raw = yaml.safe_load(payload)
        config = DataAnalysisWorkflowConfig.model_validate(raw)
    except Exception as exc:
        raise ValueError(
            f"data_analysis config at {str(config_path)!r} is invalid: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(task_data_path, TaskAnalysisCapability):
        raise ValueError(
            f"task data path {task_data_path_id!r} enables analysis but does not implement "
            "TaskAnalysisCapability"
        )
    if config.historical_inference_base_asset_id is not None and not isinstance(
        task_data_path, TaskHistoricalInferenceInputCapability
    ):
        raise ValueError(
            f"task data path {task_data_path_id!r} enables historical inference but does "
            "not implement TaskHistoricalInferenceInputCapability"
        )

    profile_payload = Path(dataset_profile_path).read_bytes()
    profile_digest = hashlib.sha256(profile_payload).hexdigest()
    for asset in config.available_assets:
        if isinstance(asset.location, TaskDataAssetLocation):
            if asset.location.task_data_path_id != task_data_path_id:
                raise ValueError(
                    f"analysis asset {asset.asset_id!r} names task data path "
                    f"{asset.location.task_data_path_id!r}, expected {task_data_path_id!r}"
                )
            if asset.location.dataset_profile_sha256 != profile_digest:
                raise ValueError(
                    f"analysis asset {asset.asset_id!r} does not pin the composed dataset profile"
                )

    packs = (
        *builtin_pack_refs(*config.builtin_skill_packs),
        *(
            _resolve_external_pack(item, config_dir=config_path.parent)
            for item in config.external_skill_packs
        ),
    )
    # Manifest-only discovery verifies every caller pin without importing a
    # selected implementation.  A broken pack therefore fails at composition,
    # before an Interpreter or planner call can mutate the trajectory.
    discover_skills(tuple(packs))
    metric_identity = MetricIdentityKey(id=metric.spec.id, direction=metric.spec.direction)
    task_context = AnalysisTaskContext(
        task_id=task_data_path_id,
        scientific_goal=config.scientific_goal,
        task_description=task_description,
        target_description=config.target_description,
        input_description=config.input_description,
        metric_identity=metric_identity,
        metric_summary=(
            f"{metric.spec.id}; direction={metric.spec.direction}; "
            f"aggregation={metric.spec.aggregation}"
        ),
        scientific_constraints=config.scientific_constraints,
        dataset_profile_ref=CertifiedArtifactRef(
            logical_ref=dataset_profile_ref,
            sha256=profile_digest,
            media_type="application/json",
            byte_size=len(profile_payload),
        ),
        forward_contract=forward_contract,
    )
    return ResolvedWorkflowDataAnalysis(
        task_context=task_context,
        available_assets=config.available_assets,
        access_policy=config.access_policy,
        resource_envelope=config.resource_envelope,
        allowed_skill_packs=tuple(packs),
        task_analysis_capability=task_data_path,
        report_schema_version=config.report_schema_version,
        config_content_sha256=hashlib.sha256(payload).hexdigest(),
        config_path=str(config_path),
        allow_generated_skill_promotion=config.allow_generated_skill_promotion,
        historical_inference_base_asset_id=config.historical_inference_base_asset_id,
        dataset_profile_path=dataset_profile_path,
    )
