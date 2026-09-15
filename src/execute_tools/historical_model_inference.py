"""Caller-injected historical-model inference contract and local bounded engine."""

from __future__ import annotations

import hashlib
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

import numpy as np
from pydantic import Field

from agent.data_analysis.historical_inference_worker_protocol import (
    HistoricalInferenceWorkerRequest,
    HistoricalInferenceWorkerResponse,
)
from agent.schemas.data_analysis.assets import MaterializedAnalysisView
from agent.schemas.data_analysis.common import (
    CertifiedArtifactRef,
    FrozenModel,
    NonEmptyStr,
    canonical_json_bytes,
    canonical_sha256,
)
from agent.schemas.data_analysis.inference import (
    HistoricalInferenceMaterialization,
    HistoricalModelInferenceRequest,
)
from agent.schemas.data_analysis.resources import ResourceUsage
from agent.schemas.data_analysis.trained_model import ModelInferenceReceipt, ModelPluginIdentity
from agent.schemas.data_analysis.view_formats import NUMERIC_ARRAY_V1
from core.campaign_identity import validate_path_component
from core.durable_io import publish_bytes_write_once
from core.runtime_control.process_group import process_group_alive, signal_group, tree_rss_bytes
from core.subprocess_env import subprocess_env


class HistoricalInferenceInputPath(FrozenModel):
    binding_id: NonEmptyStr
    path: NonEmptyStr


class HistoricalInferenceRuntimeInputs(FrozenModel):
    """Ephemeral host transport excluded from canonical scientific identity."""

    paths: tuple[HistoricalInferenceInputPath, ...] = Field(min_length=1)


@runtime_checkable
class HistoricalModelInferenceCapability(Protocol):
    """Execute one approved protocol; never derive authorization or plan inputs."""

    def run_historical_inference(
        self,
        request: HistoricalModelInferenceRequest,
        runtime_inputs: HistoricalInferenceRuntimeInputs,
    ) -> HistoricalInferenceMaterialization: ...

    def export_historical_prediction(
        self,
        content_ref: CertifiedArtifactRef,
        destination: Path,
    ) -> None: ...


@runtime_checkable
class HistoricalModelArtifactExporter(Protocol):
    """Resolve immutable refs supplied by the caller's artifact authority."""

    def export_artifact(self, ref: CertifiedArtifactRef, destination: Path) -> None: ...


@runtime_checkable
class ApprovedModelPluginResolver(Protocol):
    """Resolve only an operator-approved plugin identity, never an artifact path."""

    def resolve_model_plugin(self, identity: ModelPluginIdentity) -> Path: ...


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    signal_group(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + 1.0
    while process_group_alive(process.pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    if process_group_alive(process.pid):
        signal_group(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        signal_group(process.pid, signal.SIGKILL)
        process.wait()


class LocalPytorchHistoricalModelInferenceCapability:
    """Bounded implementation of the approved registered-model v1 protocol.

    Checkpoint/config bytes and plugin source come from injected caller
    authorities. The descriptive model artifact never supplies an executable
    path. v1 deliberately implements only the identity prediction decoder and
    numeric-array output; other approved protocols remain substitutable through
    :class:`HistoricalModelInferenceCapability`.
    """

    def __init__(
        self,
        *,
        workspace: Path,
        artifact_exporter: HistoricalModelArtifactExporter,
        plugin_resolver: ApprovedModelPluginResolver,
    ) -> None:
        self._root = workspace.resolve() / "historical_inference"
        self._artifact_exporter = artifact_exporter
        self._plugin_resolver = plugin_resolver

    @staticmethod
    def _verify_export(path: Path, ref: CertifiedArtifactRef) -> None:
        if path.is_symlink() or not path.is_file():
            raise ValueError("artifact authority did not export a regular file")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != ref.sha256:
            raise ValueError("exported artifact digest differs from its certified ref")
        if ref.byte_size is not None and len(payload) != ref.byte_size:
            raise ValueError("exported artifact size differs from its certified ref")

    def _stage_artifacts(
        self, request: HistoricalModelInferenceRequest, directory: Path
    ) -> tuple[Path, Path, Path]:
        checkpoint = directory / "checkpoint.pt"
        model_config = directory / "model_config.json"
        self._artifact_exporter.export_artifact(request.model_artifact.checkpoint.ref, checkpoint)
        self._artifact_exporter.export_artifact(
            request.model_artifact.model_config_ref, model_config
        )
        self._verify_export(checkpoint, request.model_artifact.checkpoint.ref)
        self._verify_export(model_config, request.model_artifact.model_config_ref)

        approved_source = self._plugin_resolver.resolve_model_plugin(
            request.model_artifact.model_plugin_identity
        )
        if approved_source.is_symlink() or not approved_source.is_file():
            raise ValueError("approved model plugin resolver returned no regular source file")
        source_payload = approved_source.read_bytes()
        if hashlib.sha256(source_payload).hexdigest() != (
            request.model_artifact.model_plugin_identity.content_sha256
        ):
            raise ValueError("approved model plugin content differs from artifact identity")
        plugin_directory = directory / "plugins"
        plugin_directory.mkdir()
        member = validate_path_component(
            request.model_artifact.model_plugin_identity.member,
            kind="approved model plugin member",
        )
        if Path(member).suffix != ".py":
            raise ValueError("approved registered-model plugin must be one Python source file")
        plugin_path = plugin_directory / member
        publish_bytes_write_once(str(plugin_path), source_payload)
        return checkpoint, model_config, plugin_directory

    @staticmethod
    def _failure_receipt(
        request: HistoricalModelInferenceRequest,
        *,
        status: Literal["failed", "refused", "timed_out"],
        code: str,
        message: str,
        usage: ResourceUsage,
    ) -> ModelInferenceReceipt:
        artifact = request.model_artifact
        construction = artifact.model_construction_contract
        return ModelInferenceReceipt(
            inference_id=f"inference-{request.scientific_identity_sha256}",
            request_sha256=request.scientific_identity_sha256,
            model_artifact_ref=request.model_artifact_ref,
            checkpoint_sha256=artifact.checkpoint.ref.sha256,
            model_config_sha256=artifact.model_config_ref.sha256,
            model_plugin_sha256=artifact.model_plugin_identity.content_sha256,
            construction_protocol_id=construction.protocol_id,
            construction_implementation_sha256=construction.implementation_sha256,
            construction_loss_type=construction.loss_type,
            inference_protocol_id=artifact.inference_protocol_id,
            input_materialization_ids=tuple(
                view.materialization_id for view in request.input_views
            ),
            input_materialization_sha256s=tuple(
                view.content_ref.sha256 for view in request.input_views
            ),
            split_id=request.split_id,
            scope_sha256=canonical_sha256(request.requested_scope),
            selection_sha256=request.selection_identity.selection_sha256,
            prediction_count=0,
            prediction_output_format=request.requested_prediction_format,
            prediction_semantic_id=(artifact.model_io_contract.inference.prediction_semantic_id),
            determinism=request.configuration.determinism,
            seed=request.configuration.seed,
            status=status,
            failure_code=code,
            failure_message=message,
            resource_usage=usage,
        )

    @staticmethod
    def _prediction_view(
        request: HistoricalModelInferenceRequest,
        receipt: ModelInferenceReceipt,
    ) -> MaterializedAnalysisView:
        prediction_ref = receipt.prediction_artifact_ref
        if receipt.status != "completed" or prediction_ref is None:
            raise ValueError("only a completed inference receipt can certify a prediction view")
        return MaterializedAnalysisView(
            materialization_id=f"materialization-{request.scientific_identity_sha256}",
            invocation_id=request.invocation_id,
            binding_id=request.output_binding_id,
            slot_id=request.output_slot_id,
            asset_id=request.output_asset_id,
            split_id=request.split_id,
            content_ref=prediction_ref,
            format_id=request.requested_prediction_format,
            population_unit=request.selection_identity.population_unit,
            total_available=request.selection_identity.total_available,
            materialized_count=receipt.prediction_count,
            certified_information=request.requested_information,
            selection_identity=request.selection_identity,
            source_digests=(
                request.model_artifact.executable_model_identity_sha256,
                *(item.content_ref.sha256 for item in request.input_views),
            ),
            authorization_receipt=request.model_authorization_receipt,
            historical_inference_receipt=receipt,
        )

    def _reuse_completed_prediction(
        self,
        request: HistoricalModelInferenceRequest,
        directory: Path,
    ) -> HistoricalInferenceMaterialization | None:
        receipt_path = directory / "receipt.json"
        if not receipt_path.is_file():
            return None
        try:
            receipt = ModelInferenceReceipt.model_validate_json(receipt_path.read_bytes())
            prediction_ref = receipt.prediction_artifact_ref
            if (
                receipt.status != "completed"
                or receipt.request_sha256 != request.scientific_identity_sha256
                or prediction_ref is None
            ):
                return None
            source = (self._root.parent / prediction_ref.logical_ref).resolve()
            if self._root not in source.parents:
                return None
            self._verify_export(source, prediction_ref)
            view = self._prediction_view(request, receipt)
        except (OSError, ValueError):
            return None
        return HistoricalInferenceMaterialization(view=view, receipt=receipt)

    def run_historical_inference(
        self,
        request: HistoricalModelInferenceRequest,
        runtime_inputs: HistoricalInferenceRuntimeInputs,
    ) -> HistoricalInferenceMaterialization:
        request = HistoricalModelInferenceRequest.model_validate(request)
        runtime_inputs = HistoricalInferenceRuntimeInputs.model_validate(runtime_inputs)
        if {item.binding_id for item in runtime_inputs.paths} != {
            view.binding_id for view in request.input_views
        }:
            raise ValueError("runtime input paths differ from explicit inference bindings")
        if request.requested_prediction_format != NUMERIC_ARRAY_V1:
            receipt = self._failure_receipt(
                request,
                status="refused",
                code="unsupported_prediction_format",
                message="local registered-model v1 supports numeric-array.v1 output",
                usage=ResourceUsage(wall_time_s=0.0, device=request.configuration.device),
            )
            return HistoricalInferenceMaterialization(receipt=receipt)
        started = time.monotonic()
        runtime_by_binding = {item.binding_id: Path(item.path) for item in runtime_inputs.paths}
        try:
            for view in request.input_views:
                self._verify_export(runtime_by_binding[view.binding_id], view.content_ref)
        except (KeyError, OSError, ValueError) as exc:
            receipt = self._failure_receipt(
                request,
                status="failed",
                code="inference_input_staging_failed",
                message=str(exc) or type(exc).__name__,
                usage=ResourceUsage(
                    wall_time_s=max(0.0, time.monotonic() - started),
                    device=request.configuration.device,
                ),
            )
            return HistoricalInferenceMaterialization(receipt=receipt)
        execution_key = canonical_sha256(
            {
                "request_id": request.request_id,
                "invocation_id": request.invocation_id,
                "output_binding_id": request.output_binding_id,
                "output_slot_id": request.output_slot_id,
                "output_asset_id": request.output_asset_id,
            }
        )
        directory = self._root / request.scientific_identity_sha256 / execution_key
        if directory.exists():
            reused = self._reuse_completed_prediction(request, directory)
            if reused is not None:
                return reused
            receipt = self._failure_receipt(
                request,
                status="refused",
                code="inference_identity_incomplete",
                message="inference identity already has incomplete or unverifiable storage",
                usage=ResourceUsage(wall_time_s=0.0, device=request.configuration.device),
            )
            return HistoricalInferenceMaterialization(receipt=receipt)
        try:
            directory.mkdir(parents=True, exist_ok=False)
            checkpoint, model_config, plugin_directory = self._stage_artifacts(request, directory)
            output_path = directory / "prediction.npz"
            request_path = directory / "worker_request.json"
            response_path = directory / "worker_response.json"
            worker_request = HistoricalInferenceWorkerRequest(
                request=request,
                input_paths={item.binding_id: item.path for item in runtime_inputs.paths},
                checkpoint_path=str(checkpoint),
                model_config_path=str(model_config),
                plugin_directory=str(plugin_directory),
                output_path=str(output_path),
            )
            publish_bytes_write_once(str(request_path), canonical_json_bytes(worker_request))
        except Exception as exc:
            receipt = self._failure_receipt(
                request,
                status="failed",
                code="inference_staging_failed",
                message=str(exc) or type(exc).__name__,
                usage=ResourceUsage(
                    wall_time_s=max(0.0, time.monotonic() - started),
                    device=request.configuration.device,
                ),
            )
            return HistoricalInferenceMaterialization(receipt=receipt)
        timeout = max(0.0, request.deadline_monotonic_s - started)
        timeout = min(timeout, request.resource_envelope.per_skill_timeout_s)
        stdout_path = directory / "stdout.log"
        stderr_path = directory / "stderr.log"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "agent.data_analysis.historical_inference_worker_main",
                    "--request",
                    str(request_path),
                    "--response",
                    str(response_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=subprocess_env(plugin_dir=str(plugin_directory)),
                start_new_session=True,
                close_fds=True,
            )
            peak_rss = 0
            timed_out = timeout <= 0.0
            memory_exceeded = False
            memory_limit = request.resource_envelope.max_host_memory_gb
            memory_ceiling = None if memory_limit is None else int(memory_limit * 1024**3)
            while not timed_out and not memory_exceeded and process.poll() is None:
                peak_rss = max(peak_rss, tree_rss_bytes(process.pid))
                timed_out = time.monotonic() - started >= timeout
                memory_exceeded = memory_ceiling is not None and peak_rss > memory_ceiling
                if not timed_out and not memory_exceeded:
                    time.sleep(0.02)
            if (timed_out or memory_exceeded) and process.poll() is None:
                _terminate_process_group(process)
            elif process.poll() is None:
                process.wait()
            elif process_group_alive(process.pid):
                _terminate_process_group(process)
            returncode = process.wait()
            peak_rss = max(peak_rss, tree_rss_bytes(process.pid))
        elapsed = max(0.0, time.monotonic() - started)
        response = None
        if response_path.exists():
            try:
                response = HistoricalInferenceWorkerResponse.model_validate_json(
                    response_path.read_bytes()
                )
            except ValueError:
                response = None
        peak_vram = response.peak_vram_bytes if response is not None else None
        usage = ResourceUsage(
            wall_time_s=elapsed,
            peak_rss_bytes=peak_rss,
            peak_vram_bytes=peak_vram,
            device=request.configuration.device,
            measurement_limitations=("CPU time was not measured per process group.",),
        )
        if timed_out:
            receipt = self._failure_receipt(
                request,
                status="timed_out",
                code="inference_timeout",
                message="historical inference process tree exceeded its deadline",
                usage=usage,
            )
            return HistoricalInferenceMaterialization(receipt=receipt)
        if memory_exceeded:
            receipt = self._failure_receipt(
                request,
                status="failed",
                code="inference_host_memory_limit",
                message="historical inference process tree exceeded its RSS limit",
                usage=usage,
            )
            return HistoricalInferenceMaterialization(receipt=receipt)
        vram_limit = request.resource_envelope.max_vram_gb
        if (
            vram_limit is not None
            and peak_vram is not None
            and peak_vram > int(vram_limit * 1024**3)
        ):
            receipt = self._failure_receipt(
                request,
                status="failed",
                code="inference_vram_limit",
                message="historical inference exceeded its observed VRAM envelope",
                usage=usage,
            )
            return HistoricalInferenceMaterialization(receipt=receipt)
        if response is None or response.status != "completed" or returncode != 0:
            code = "invalid_worker_response" if response is None else response.error_type
            message = (
                "worker returned no valid response" if response is None else response.error_message
            )
            receipt = self._failure_receipt(
                request,
                status="failed",
                code=code or "worker_failure",
                message=message or "historical inference worker failed",
                usage=usage,
            )
            return HistoricalInferenceMaterialization(receipt=receipt)

        try:
            if output_path.is_symlink() or not output_path.is_file():
                raise ValueError("prediction artifact is not a regular executor-owned file")
            with np.load(output_path, allow_pickle=False) as archive:
                if set(archive.files) != {"example_ids", "information__prediction"}:
                    raise ValueError("prediction artifact contains undeclared arrays")
                example_ids = np.asarray(archive["example_ids"])
                predictions = np.asarray(archive["information__prediction"])
                prediction_count = len(example_ids)
                if predictions.ndim < 1 or predictions.shape[0] != prediction_count:
                    raise ValueError("prediction artifact arrays are not row-aligned")
                if len({str(item) for item in example_ids.tolist()}) != prediction_count:
                    raise ValueError("prediction artifact example IDs are not unique")
            if prediction_count != request.selection_identity.selected_count:
                raise ValueError("executor-observed prediction count differs from selection")
            payload = output_path.read_bytes()
        except Exception as exc:
            receipt = self._failure_receipt(
                request,
                status="failed",
                code="invalid_prediction_artifact",
                message=str(exc) or type(exc).__name__,
                usage=usage,
            )
            return HistoricalInferenceMaterialization(receipt=receipt)
        prediction_ref = CertifiedArtifactRef(
            logical_ref=str(output_path.relative_to(self._root.parent)),
            sha256=hashlib.sha256(payload).hexdigest(),
            media_type="application/x-npz",
            byte_size=len(payload),
        )
        artifact = request.model_artifact
        construction = artifact.model_construction_contract
        inference = artifact.model_io_contract.inference
        assert inference is not None
        receipt = ModelInferenceReceipt(
            inference_id=f"inference-{request.scientific_identity_sha256}",
            request_sha256=request.scientific_identity_sha256,
            model_artifact_ref=request.model_artifact_ref,
            checkpoint_sha256=artifact.checkpoint.ref.sha256,
            model_config_sha256=artifact.model_config_ref.sha256,
            model_plugin_sha256=artifact.model_plugin_identity.content_sha256,
            construction_protocol_id=construction.protocol_id,
            construction_implementation_sha256=construction.implementation_sha256,
            construction_loss_type=construction.loss_type,
            inference_protocol_id=artifact.inference_protocol_id,
            input_materialization_ids=tuple(
                view.materialization_id for view in request.input_views
            ),
            input_materialization_sha256s=tuple(
                view.content_ref.sha256 for view in request.input_views
            ),
            split_id=request.split_id,
            scope_sha256=canonical_sha256(request.requested_scope),
            selection_sha256=request.selection_identity.selection_sha256,
            prediction_count=prediction_count,
            prediction_artifact_ref=prediction_ref,
            prediction_output_format=request.requested_prediction_format,
            prediction_semantic_id=inference.prediction_semantic_id,
            determinism=request.configuration.determinism,
            seed=request.configuration.seed,
            status="completed",
            resource_usage=usage,
        )
        view = self._prediction_view(request, receipt)
        publish_bytes_write_once(str(directory / "receipt.json"), canonical_json_bytes(receipt))
        return HistoricalInferenceMaterialization(view=view, receipt=receipt)

    def export_historical_prediction(
        self,
        content_ref: CertifiedArtifactRef,
        destination: Path,
    ) -> None:
        source = (self._root.parent / content_ref.logical_ref).resolve()
        if self._root not in source.parents:
            raise ValueError("historical prediction ref escapes capability storage")
        self._verify_export(source, content_ref)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
