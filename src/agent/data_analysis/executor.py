"""Bounded subprocess execution for selected, operator-approved skills."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from agent.schemas.data_analysis.assets import MaterializedAnalysisView
from agent.schemas.data_analysis.common import canonical_json_bytes, utc_now
from agent.schemas.data_analysis.resources import ResourceUsage
from agent.schemas.data_analysis.skills import (
    AnalysisCoverage,
    ResolvedSkillInterface,
    SkillAnalysisUsage,
    SkillExecutionProvenance,
    SkillFailure,
    SkillInput,
    SkillResult,
)
from core.durable_io import publish_bytes_write_once
from core.runtime_control.process_group import process_group_alive, signal_group, tree_rss_bytes
from core.subprocess_env import subprocess_env

from .discovery import DiscoveredSkill
from .execution_origin import trusted_skill_execution_origin
from .persistence import AnalysisPersistenceError, AnalysisRunStore
from .worker_protocol import SkillWorkerRequest, SkillWorkerResponse, ValidatedParameters


@dataclass(frozen=True)
class WorkerObservation:
    response: SkillWorkerResponse | None
    disposition: str
    wall_time_s: float
    peak_rss_bytes: int
    worker_pid: int
    started_at: str
    finished_at: str


class SkillExecutorError(RuntimeError):
    """Pre-materialization validation failed or its worker could not be certified."""


def certify_analysis_coverage(
    views: tuple[MaterializedAnalysisView, ...],
    usage: SkillAnalysisUsage | None,
) -> AnalysisCoverage:
    """Certify untrusted usage against the exact authorized materializations."""

    if not views:
        raise ValueError("coverage certification requires materialized views")
    selection = views[0].selection_identity
    if any(view.selection_identity != selection for view in views):
        raise ValueError("materialized views do not share an identical certified selection")
    if any(view.split_id != views[0].split_id for view in views):
        raise ValueError("materialized views do not share one certified split")
    if any(view.population_unit != selection.population_unit for view in views):
        raise ValueError("materialized view population units differ from selection identity")
    if usage is None:
        effective_count = selection.selected_count
        filters: tuple[str, ...] = ()
    else:
        if usage.effective_count + usage.dropped_count != selection.selected_count:
            raise ValueError(
                "skill-reported effective and dropped counts must account for the selection"
            )
        effective_count = usage.effective_count
        filters = tuple(item.reason for item in usage.drop_reasons)
    inference_receipts = tuple(
        view.historical_inference_receipt
        for view in views
        if view.historical_inference_receipt is not None
    )
    if len(inference_receipts) > 1:
        raise ValueError("v1 coverage supports at most one historical inference binding")
    inference_receipt = inference_receipts[0] if inference_receipts else None
    return AnalysisCoverage(
        population_unit=selection.population_unit,
        total_available=selection.total_available,
        analyzed_count=effective_count,
        binding_ids=tuple(view.binding_id for view in views),
        selection_sha256=selection.selection_sha256,
        split_id=views[0].split_id,
        sampling_strategy=f"{selection.sampling_mode}:{selection.sampling_strategy}",
        sampling_seed=selection.sampling_seed,
        filters=filters,
        model_artifact_ref=(
            inference_receipt.model_artifact_ref.artifact_ref
            if inference_receipt is not None
            else None
        ),
        inference_count=(
            inference_receipt.prediction_count if inference_receipt is not None else None
        ),
    )


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    pgid = process.pid
    signal_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + 1.0
    while process_group_alive(pgid) and time.monotonic() < deadline:
        time.sleep(0.02)
    if process_group_alive(pgid):
        signal_group(pgid, signal.SIGKILL)
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        signal_group(pgid, signal.SIGKILL)
        process.wait()


def _run_worker(
    request: SkillWorkerRequest,
    *,
    control_directory: Path,
    timeout_s: float,
    max_host_memory_gb: float | None,
) -> WorkerObservation:
    control_directory.mkdir(parents=True, exist_ok=False)
    request_path = control_directory / "request.json"
    response_path = control_directory / "response.json"
    stdout_path = control_directory / "stdout.log"
    stderr_path = control_directory / "stderr.log"
    publish_bytes_write_once(str(request_path), canonical_json_bytes(request))
    started_at = utc_now()
    started = time.monotonic()
    memory_ceiling = None if max_host_memory_gb is None else int(max_host_memory_gb * 1024**3)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "agent.data_analysis.worker_main",
                "--request",
                str(request_path),
                "--response",
                str(response_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=subprocess_env(),
            start_new_session=True,
            close_fds=True,
        )
        peak_rss = 0
        disposition = "exited"
        while process.poll() is None:
            peak_rss = max(peak_rss, tree_rss_bytes(process.pid))
            if memory_ceiling is not None and peak_rss > memory_ceiling:
                disposition = "memory_limit_exceeded"
                _terminate_process_group(process)
                break
            if time.monotonic() - started >= timeout_s:
                disposition = "timed_out"
                _terminate_process_group(process)
                break
            time.sleep(0.02)
        peak_rss = max(peak_rss, tree_rss_bytes(process.pid))
        if process.poll() is None:
            _terminate_process_group(process)
        elif process_group_alive(process.pid):
            disposition = "orphaned_process_tree"
            _terminate_process_group(process)
        returncode = process.wait()

    response: SkillWorkerResponse | None = None
    if response_path.exists():
        try:
            response = SkillWorkerResponse.model_validate_json(response_path.read_bytes())
        except ValueError:
            disposition = "invalid_worker_response"
    elif disposition == "exited":
        disposition = f"worker_exit_{returncode}_without_response"
    return WorkerObservation(
        response=response,
        disposition=disposition,
        wall_time_s=max(0.0, time.monotonic() - started),
        peak_rss_bytes=peak_rss,
        worker_pid=process.pid,
        started_at=started_at,
        finished_at=utc_now(),
    )


def validate_skill_parameters(
    skill: DiscoveredSkill,
    interface: ResolvedSkillInterface,
    parameters: dict[str, object],
    *,
    control_directory: Path,
    timeout_s: float,
    max_host_memory_gb: float | None = None,
) -> ValidatedParameters:
    """Load and validate a selected skill in a bounded process before materialization."""

    request = SkillWorkerRequest(
        mode="validate_parameters",
        discovered_skill=skill,
        parameters=parameters,
        expected_parameter_schema_sha256=interface.parameter_schema_sha256,
    )
    observed = _run_worker(
        request,
        control_directory=control_directory,
        timeout_s=timeout_s,
        max_host_memory_gb=max_host_memory_gb,
    )
    response = observed.response
    if (
        observed.disposition != "exited"
        or response is None
        or response.status != "validated"
        or response.validated_parameters is None
    ):
        detail = observed.disposition
        if response is not None and response.error_message:
            detail = f"{response.error_type}: {response.error_message}"
        raise SkillExecutorError(f"selected skill parameter validation failed: {detail}")
    return response.validated_parameters


def resolve_skill_interface(
    skill: DiscoveredSkill,
    *,
    control_directory: Path,
    timeout_s: float,
    max_host_memory_gb: float | None = None,
) -> ResolvedSkillInterface:
    """Resolve one selected schema/instruction surface before plan arguments exist."""

    observed = _run_worker(
        SkillWorkerRequest(mode="resolve_interface", discovered_skill=skill),
        control_directory=control_directory,
        timeout_s=timeout_s,
        max_host_memory_gb=max_host_memory_gb,
    )
    response = observed.response
    if (
        observed.disposition != "exited"
        or response is None
        or response.status != "interface_resolved"
        or response.resolved_interface is None
    ):
        detail = observed.disposition
        if response is not None and response.error_message:
            detail = f"{response.error_type}: {response.error_message}"
        raise SkillExecutorError(f"selected skill interface resolution failed: {detail}")
    return response.resolved_interface


def execute_skill(
    *,
    result_id: str,
    skill: DiscoveredSkill,
    validated_parameters: ValidatedParameters,
    skill_input: SkillInput,
    materialization_paths: dict[str, str],
    store: AnalysisRunStore,
    staging_directory: Path,
    control_directory: Path,
    plan_sha256: str,
    timeout_s: float,
    max_host_memory_gb: float | None = None,
    pre_execution_resource_usage: tuple[ResourceUsage, ...] = (),
) -> SkillResult:
    """Execute one already-planned and already-authorized invocation."""

    execution_origin = trusted_skill_execution_origin(skill)
    request = SkillWorkerRequest(
        mode="execute",
        discovered_skill=skill,
        parameters=validated_parameters.parameters,
        skill_input=skill_input,
        materialization_paths=materialization_paths,
        artifact_directory=str(staging_directory),
        expected_parameter_schema_sha256=validated_parameters.parameter_schema_sha256,
        expected_validated_parameters_sha256=validated_parameters.validated_parameters_sha256,
    )
    effective_timeout = min(
        timeout_s, max(0.0, skill_input.deadline_monotonic_s - time.monotonic())
    )
    if effective_timeout <= 0.0:
        observed = WorkerObservation(
            response=None,
            disposition="timed_out",
            wall_time_s=0.0,
            peak_rss_bytes=0,
            worker_pid=os.getpid(),
            started_at=utc_now(),
            finished_at=utc_now(),
        )
    else:
        observed = _run_worker(
            request,
            control_directory=control_directory,
            timeout_s=effective_timeout,
            max_host_memory_gb=max_host_memory_gb,
        )

    inference_wall_time = sum(item.wall_time_s for item in pre_execution_resource_usage)
    inference_peak_rss = max(
        (item.peak_rss_bytes or 0 for item in pre_execution_resource_usage), default=0
    )
    inference_peak_vram = max(
        (item.peak_vram_bytes or 0 for item in pre_execution_resource_usage), default=0
    )
    resource_usage = ResourceUsage(
        wall_time_s=inference_wall_time + observed.wall_time_s,
        peak_rss_bytes=max(inference_peak_rss, observed.peak_rss_bytes),
        peak_vram_bytes=inference_peak_vram or None,
        device=("+".join(sorted({item.device for item in pre_execution_resource_usage} | {"cpu"}))),
        measurement_limitations=(
            "CPU time was not measured per process group.",
            "VRAM was not observed by the generic worker supervisor.",
            *(
                note
                for item in pre_execution_resource_usage
                for note in item.measurement_limitations
            ),
        ),
    )
    response = observed.response
    provenance = SkillExecutionProvenance(
        plan_sha256=plan_sha256,
        parameter_schema_sha256=validated_parameters.parameter_schema_sha256,
        validated_parameters_sha256=validated_parameters.validated_parameters_sha256,
        authorization_receipts=tuple(
            view.authorization_receipt for view in skill_input.materializations
        ),
        inference_receipts=tuple(
            view.historical_inference_receipt
            for view in skill_input.materializations
            if view.historical_inference_receipt is not None
        ),
        environment_lock_verified=bool(
            skill.identity.environment_lock_sha256 is not None
            and response is not None
            and response.environment_lock_verified
        ),
        started_at=observed.started_at,
        finished_at=observed.finished_at,
        worker_pid=observed.worker_pid,
        host_details={"supervisor_disposition": observed.disposition},
    )
    if observed.disposition == "timed_out":
        return SkillResult(
            result_id=result_id,
            invocation_id=skill_input.invocation_id,
            skill_identity=skill.identity,
            execution_origin=execution_origin,
            status="timed_out",
            summary="Skill execution exceeded its hard deadline.",
            resource_usage=resource_usage,
            failure=SkillFailure(
                failure_type="timeout",
                message="worker process tree was terminated at the invocation deadline",
                materialization_occurred=True,
            ),
            provenance=provenance,
        )
    if observed.disposition == "memory_limit_exceeded":
        return SkillResult(
            result_id=result_id,
            invocation_id=skill_input.invocation_id,
            skill_identity=skill.identity,
            execution_origin=execution_origin,
            status="failed",
            summary="Skill execution exceeded its host-memory limit.",
            resource_usage=resource_usage,
            failure=SkillFailure(
                failure_type="host_memory_limit",
                message="worker process tree was terminated after exceeding peak RSS limit",
                materialization_occurred=True,
            ),
            provenance=provenance,
        )
    if response is None or response.status != "completed" or response.payload is None:
        message = observed.disposition
        failure_type = "worker_failure"
        if response is not None and response.error_message:
            message = response.error_message
            failure_type = response.error_type or failure_type
        return SkillResult(
            result_id=result_id,
            invocation_id=skill_input.invocation_id,
            skill_identity=skill.identity,
            execution_origin=execution_origin,
            status="failed",
            summary="Skill worker failed before producing a valid result.",
            resource_usage=resource_usage,
            failure=SkillFailure(
                failure_type=failure_type,
                message=message,
                materialization_occurred=True,
            ),
            provenance=provenance,
        )

    payload = response.payload
    try:
        coverage = certify_analysis_coverage(skill_input.materializations, payload.analysis_usage)
    except ValueError as exc:
        return SkillResult(
            result_id=result_id,
            invocation_id=skill_input.invocation_id,
            skill_identity=skill.identity,
            execution_origin=execution_origin,
            status="failed",
            summary="Skill reported analysis usage inconsistent with certified materialization.",
            quantitative_results=payload.quantitative_results,
            resource_usage=resource_usage,
            warnings=payload.warnings,
            failure=SkillFailure(
                failure_type="invalid_analysis_usage",
                message=str(exc),
                materialization_occurred=True,
            ),
            provenance=provenance,
        )
    undeclared_artifact_types = {item.artifact_type for item in payload.produced_artifacts} - set(
        skill.card.produced_artifact_types
    )
    if undeclared_artifact_types:
        return SkillResult(
            result_id=result_id,
            invocation_id=skill_input.invocation_id,
            skill_identity=skill.identity,
            execution_origin=execution_origin,
            status="failed",
            summary="Skill declared artifacts outside its discovery card.",
            quantitative_results=payload.quantitative_results,
            coverage=coverage,
            resource_usage=resource_usage,
            warnings=payload.warnings,
            failure=SkillFailure(
                failure_type="artifact_certification",
                message=f"undeclared artifact types: {sorted(undeclared_artifact_types)}",
                materialization_occurred=True,
            ),
            provenance=provenance,
        )
    try:
        artifact_refs = store.certify_artifacts(
            staging_directory=staging_directory,
            declarations=payload.produced_artifacts,
            contract=skill_input.artifact_output_contract,
        )
    except AnalysisPersistenceError as exc:
        return SkillResult(
            result_id=result_id,
            invocation_id=skill_input.invocation_id,
            skill_identity=skill.identity,
            execution_origin=execution_origin,
            status="failed",
            summary="Skill artifacts failed executor certification.",
            quantitative_results=payload.quantitative_results,
            coverage=coverage,
            resource_usage=resource_usage,
            warnings=payload.warnings,
            failure=SkillFailure(
                failure_type="artifact_certification",
                message=str(exc),
                materialization_occurred=True,
            ),
            provenance=provenance,
        )
    return SkillResult(
        result_id=result_id,
        invocation_id=skill_input.invocation_id,
        skill_identity=skill.identity,
        execution_origin=execution_origin,
        status="completed",
        summary=payload.summary,
        quantitative_results=payload.quantitative_results,
        artifact_refs=artifact_refs,
        coverage=coverage,
        resource_usage=resource_usage,
        warnings=payload.warnings,
        provenance=provenance,
    )
