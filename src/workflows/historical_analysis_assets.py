"""Workflow-owned projection of certified prior models into analysis assets.

This module does not authorize materialization or choose an inference plan.
It reads only typed prior records and digest-verified workspace artifacts,
then asks the task to derive candidate-compatible input geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    AssetProvenance,
    TrainedModelArtifactLocation,
)
from agent.schemas.data_analysis.trained_model import TrainedModelArtifact
from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.analysis_materialization import (
    HistoricalInferenceInputDerivationRequest,
    TaskHistoricalInferenceInputCapability,
    validate_derived_historical_inference_input_asset,
)
from execute_tools.trained_model_artifact import read_certified_artifact
from workflows.data_analysis_composition import ResolvedWorkflowDataAnalysis


@dataclass(frozen=True, slots=True)
class HistoricalTuningSource:
    """A validated tuning output paired with its actual artifact workspace."""

    output: HyperparamTuningOutput
    artifact_root: Path


@dataclass(frozen=True, slots=True)
class HistoricalAnalysisAssets:
    """Exact dynamic descriptors plus workspace roots for the inference exporter."""

    binding: ResolvedWorkflowDataAnalysis
    artifact_roots_by_sha256: dict[str, Path]


def pair_prior_tuning_sources(
    outputs: list[HyperparamTuningOutput],
    source_paths: list[str] | None,
) -> list[HistoricalTuningSource]:
    """Bind validated outputs to their explicit persisted source locations."""

    if source_paths is None:
        if any(
            record.trained_model_artifact_ref for output in outputs for record in output.all_records
        ):
            raise ValueError(
                "model-aware analysis requires explicit prior run-output paths; "
                "legacy source-directory inference is not artifact authority"
            )
        return []
    if len(outputs) != len(source_paths):
        raise ValueError("validated tuning outputs and explicit source paths differ")
    return [
        HistoricalTuningSource(output=output, artifact_root=Path(path).resolve().parent)
        for output, path in zip(outputs, source_paths, strict=True)
    ]


def capture_completed_tuning_source(
    binding: ResolvedWorkflowDataAnalysis | None,
    sources: list[HistoricalTuningSource],
    output: HyperparamTuningOutput,
    tuning_dir: str,
) -> None:
    """Record the exact in-process tuner workspace for the next iteration."""

    if binding is not None and binding.historical_inference_base_asset_id is not None:
        sources.append(
            HistoricalTuningSource(output=output, artifact_root=Path(tuning_dir).resolve())
        )


def _load_record_artifact(
    source: HistoricalTuningSource, record: ExperimentRecord
) -> TrainedModelArtifact:
    ref = record.trained_model_artifact_ref
    assert ref is not None
    payload = read_certified_artifact(source.artifact_root, ref.artifact_ref)
    artifact = TrainedModelArtifact.model_validate_json(payload)
    if (
        artifact.model_artifact_id != ref.model_artifact_id
        or artifact.executable_model_identity_sha256 != ref.executable_model_identity_sha256
        or artifact.training_run.run_name != source.output.run_name
        or artifact.training_run.experiment_id != record.exp_id
        or artifact.training_run.candidate_id != source.output.candidate_id
    ):
        raise ValueError("historical model document differs from its typed training record")
    return artifact


def derive_historical_analysis_assets(
    binding: ResolvedWorkflowDataAnalysis,
    *,
    sources: tuple[HistoricalTuningSource, ...],
    task_composition_fingerprint: str,
) -> HistoricalAnalysisAssets:
    """Expose only certified prior models in the latest eligible tuning output.

    The latest artifact-bearing output is the workflow's already-ordered
    prior-evidence unit; every artifact-bearing record in it is visible,
    with no score ranking or filename-based recovery. Earlier outputs are
    not silently mixed into that iteration's scientific question.
    """

    base_id = binding.historical_inference_base_asset_id
    if base_id is None or not sources:
        return HistoricalAnalysisAssets(binding=binding, artifact_roots_by_sha256={})
    if binding.dataset_profile_path is None:
        raise ValueError("historical inference needs the resolved dataset profile source")
    capability = binding.task_analysis_capability
    if not isinstance(capability, TaskHistoricalInferenceInputCapability):
        raise ValueError("task does not implement historical inference input derivation")
    base = next((asset for asset in binding.available_assets if asset.asset_id == base_id), None)
    if base is None:
        raise ValueError("declared historical inference base asset is unavailable")
    profile_payload = Path(binding.dataset_profile_path).read_bytes()
    try:
        profile_json = profile_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("dataset profile is not UTF-8 JSON") from exc

    dynamic: list[AnalysisAsset] = []
    roots: dict[str, Path] = {}
    latest = next(
        (
            source
            for source in reversed(sources)
            if any(record.trained_model_artifact_ref for record in source.output.all_records)
        ),
        None,
    )
    if latest is None:
        return HistoricalAnalysisAssets(binding=binding, artifact_roots_by_sha256={})
    for record in latest.output.all_records:
        if record.trained_model_artifact_ref is None:
            continue  # A legacy/failed record never becomes a guessed model.
        artifact = _load_record_artifact(latest, record)
        task_binding = artifact.task_inference_binding
        if task_binding.task_composition_fingerprint != task_composition_fingerprint:
            raise ValueError("historical model belongs to another task composition")
        config_bytes = read_certified_artifact(latest.artifact_root, artifact.model_config_ref)
        try:
            config_json = config_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("certified historical model config is not UTF-8 JSON") from exc
        request = HistoricalInferenceInputDerivationRequest(
            base_asset=base,
            model_artifact=artifact,
            model_config_json=config_json,
            dataset_profile_json=profile_json,
        )
        input_asset = validate_derived_historical_inference_input_asset(
            request,
            capability.derive_historical_inference_input_asset(request),
        )
        # The task owns scope containment. The model asset shares the exact
        # task-certified scope; inference still needs an explicit plan binding.
        model_asset = AnalysisAsset(
            asset_id=f"historical-model-{artifact.model_artifact_id}",
            asset_type="trained_model",
            description=f"Certified historical model {artifact.model_artifact_id}",
            location=TrainedModelArtifactLocation(
                artifact_ref=record.trained_model_artifact_ref.artifact_ref,
                artifact=artifact,
            ),
            provenance=AssetProvenance(
                producer="certified-training-record",
                run_id=artifact.training_run.run_name,
                iteration_id=artifact.training_run.iteration_id,
                source_asset_ids=(input_asset.asset_id,),
            ),
            authorized_scope=input_asset.authorized_scope,
            split_id=input_asset.split_id,
            allowed_operations=("infer",),
        )
        dynamic.extend((input_asset, model_asset))
        for ref in (artifact.checkpoint.ref, artifact.model_config_ref):
            previous = roots.setdefault(ref.sha256, latest.artifact_root)
            if previous != latest.artifact_root:
                raise ValueError("one artifact digest resolves to conflicting workspace roots")

    declared_ids = {asset.asset_id for asset in binding.available_assets}
    derived_ids = [asset.asset_id for asset in dynamic]
    if len(set(derived_ids)) != len(derived_ids) or declared_ids.intersection(derived_ids):
        raise ValueError("historical inference asset identities collide with declared assets")
    if not dynamic:
        return HistoricalAnalysisAssets(binding=binding, artifact_roots_by_sha256={})
    return HistoricalAnalysisAssets(
        binding=replace(binding, available_assets=(*binding.available_assets, *dynamic)),
        artifact_roots_by_sha256=roots,
    )
