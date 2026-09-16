"""Trusted certification around untrusted generated-analysis execution."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from agent.schemas.data_analysis.action_identity import GeneratedProgramIdentity
from agent.schemas.data_analysis.assets import MaterializedAnalysisView
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.generated_program import (
    GeneratedAnalysisProgram,
    GeneratedMeasurementDeclaration,
)
from agent.schemas.data_analysis.skills import (
    ArtifactOutputContract,
    ProducedArtifact,
    QuantitativeResult,
    SkillExecutionProvenance,
    SkillFailure,
    SkillResult,
)

from .analysis_code_sandbox import AnalysisCodeSandbox
from .executor import certify_analysis_coverage
from .persistence import AnalysisPersistenceError, AnalysisRunStore


def _value_matches(value: object, declaration: GeneratedMeasurementDeclaration) -> bool:
    value_type = declaration.value_type
    if value_type == "nullable_number" and value is None:
        return True
    if value_type in {"number", "nullable_number"}:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    return isinstance(value, str)


def _validate_measurements(
    program: GeneratedAnalysisProgram,
    results: tuple[QuantitativeResult, ...],
) -> None:
    expected = {item.result_key: item for item in program.expected_measurements}
    observed = {item.result_key: item for item in results}
    if len(observed) != len(results):
        raise ValueError("generated program emitted duplicate quantitative result keys")
    if set(observed) != set(expected):
        raise ValueError("generated program measurements differ from its declaration")
    for key, result in observed.items():
        declaration = expected[key]
        if not _value_matches(result.value, declaration):
            raise ValueError(f"generated measurement {key!r} has the wrong value type")
        if result.unit != declaration.unit:
            raise ValueError(f"generated measurement {key!r} has an undeclared unit")
        if result.description != declaration.description:
            raise ValueError(f"generated measurement {key!r} changed its declared semantics")


def _validate_artifact_declarations(
    program: GeneratedAnalysisProgram,
    artifacts: tuple[ProducedArtifact, ...],
) -> None:
    expected = {item.artifact_type: item for item in program.expected_artifacts}
    observed_types: set[str] = set()
    for artifact in artifacts:
        declaration = expected.get(artifact.artifact_type)
        if declaration is None:
            raise ValueError(
                f"generated program emitted undeclared artifact type {artifact.artifact_type!r}"
            )
        if artifact.media_type != declaration.media_type:
            raise ValueError(
                f"generated artifact {artifact.logical_name!r} has an undeclared media type"
            )
        observed_types.add(artifact.artifact_type)
    missing = {
        item.artifact_type
        for item in program.expected_artifacts
        if item.required and item.artifact_type not in observed_types
    }
    if missing:
        raise ValueError(f"generated program omitted required artifact types: {sorted(missing)}")


def _failed_result(
    *,
    result_id: str,
    invocation_id: str,
    identity: GeneratedProgramIdentity,
    plan_sha256: str,
    validated_parameters_sha256: str,
    materializations: tuple[MaterializedAnalysisView, ...],
    receipt,
    failure_type: str,
    message: str,
    status: Literal["failed", "timed_out"] = "failed",
) -> SkillResult:
    return SkillResult(
        result_id=result_id,
        invocation_id=invocation_id,
        execution_origin="generated_program",
        generated_program_identity=identity,
        status=status,
        summary="Generated analysis did not produce certified scientific evidence.",
        quantitative_results=(),
        resource_usage=receipt.resource_usage,
        warnings=(),
        failure=SkillFailure(
            failure_type=failure_type,
            message=message,
            materialization_occurred=True,
        ),
        provenance=SkillExecutionProvenance(
            plan_sha256=plan_sha256,
            parameter_schema_sha256=identity.parameter_schema_sha256,
            validated_parameters_sha256=validated_parameters_sha256,
            authorization_receipts=tuple(view.authorization_receipt for view in materializations),
            inference_receipts=(),
            environment_lock_verified=True,
            started_at=receipt.started_at,
            finished_at=receipt.finished_at,
            worker_pid=receipt.worker_pid,
            host_details={
                "sandbox_protocol_id": identity.sandbox_protocol_id,
                "sandbox_disposition": receipt.status,
                "stdout_sha256": receipt.stdout_sha256,
                "stderr_sha256": receipt.stderr_sha256,
            },
        ),
    )


def execute_generated_program(
    *,
    result_id: str,
    invocation_id: str,
    program: GeneratedAnalysisProgram,
    identity: GeneratedProgramIdentity,
    source_path: Path,
    parameters: dict[str, Any],
    materializations: tuple[MaterializedAnalysisView, ...],
    materialization_paths: dict[str, str],
    store: AnalysisRunStore,
    staging_directory: Path,
    control_directory: Path,
    artifact_contract: ArtifactOutputContract,
    plan_sha256: str,
    timeout_s: float,
    max_host_memory_gb: float,
    sandbox: AnalysisCodeSandbox | None = None,
) -> SkillResult:
    """Execute fixed source, then certify its untrusted payload in the parent."""

    validated_parameters_sha256 = canonical_sha256(parameters)
    descriptors = {
        view.binding_id: {
            "binding_id": view.binding_id,
            "slot_id": view.slot_id,
            "asset_id": view.asset_id,
            "split_id": view.split_id,
            "format_id": view.format_id,
            "population_unit": view.population_unit,
            "total_available": view.total_available,
            "materialized_count": view.materialized_count,
            "certified_information": [
                item.model_dump(mode="json") for item in view.certified_information
            ],
            "selection_identity": view.selection_identity.model_dump(mode="json"),
        }
        for view in materializations
    }
    runner = sandbox or AnalysisCodeSandbox()
    receipt = runner.execute(
        program=program,
        source_path=source_path,
        materialization_paths=materialization_paths,
        materialization_descriptors=descriptors,
        parameters=parameters,
        output_directory=staging_directory,
        control_directory=control_directory,
        timeout_s=min(timeout_s, program.resource_request.wall_time_s),
        max_host_memory_gb=min(
            max_host_memory_gb,
            program.resource_request.max_host_memory_gb,
        ),
    )

    if receipt.status != "completed" or receipt.payload is None:
        return _failed_result(
            result_id=result_id,
            invocation_id=invocation_id,
            identity=identity,
            plan_sha256=plan_sha256,
            validated_parameters_sha256=validated_parameters_sha256,
            materializations=materializations,
            receipt=receipt,
            failure_type=receipt.failure_type or "generated_program_failure",
            message=receipt.failure_message or receipt.status,
            status="timed_out" if receipt.status == "timed_out" else "failed",
        )

    payload = receipt.payload
    try:
        _validate_measurements(program, payload.quantitative_results)
        _validate_artifact_declarations(program, payload.produced_artifacts)
        coverage = certify_analysis_coverage(materializations, payload.analysis_usage)
        artifact_refs = store.certify_artifacts(
            staging_directory=staging_directory,
            declarations=payload.produced_artifacts,
            contract=artifact_contract,
        )
    except (ValueError, AnalysisPersistenceError) as exc:
        return _failed_result(
            result_id=result_id,
            invocation_id=invocation_id,
            identity=identity,
            plan_sha256=plan_sha256,
            validated_parameters_sha256=validated_parameters_sha256,
            materializations=materializations,
            receipt=receipt,
            failure_type="generated_payload_certification",
            message=str(exc),
        )

    return SkillResult(
        result_id=result_id,
        invocation_id=invocation_id,
        execution_origin="generated_program",
        generated_program_identity=identity,
        status="completed",
        summary=payload.summary,
        quantitative_results=payload.quantitative_results,
        artifact_refs=artifact_refs,
        coverage=coverage,
        resource_usage=receipt.resource_usage,
        warnings=payload.warnings,
        provenance=SkillExecutionProvenance(
            plan_sha256=plan_sha256,
            parameter_schema_sha256=identity.parameter_schema_sha256,
            validated_parameters_sha256=validated_parameters_sha256,
            authorization_receipts=tuple(view.authorization_receipt for view in materializations),
            inference_receipts=(),
            environment_lock_verified=True,
            started_at=receipt.started_at,
            finished_at=receipt.finished_at,
            worker_pid=receipt.worker_pid,
            host_details={
                "sandbox_protocol_id": identity.sandbox_protocol_id,
                "sandbox_disposition": receipt.status,
                "stdout_sha256": receipt.stdout_sha256,
                "stderr_sha256": receipt.stderr_sha256,
            },
        ),
    )
