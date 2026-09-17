"""Execute one resolved analysis action without enlarging node orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent.schemas.data_analysis.assets import AnalysisAuthorizationReceipt
from agent.schemas.data_analysis.common import canonical_sha256, utc_now
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.plan import AnalysisPlan
from agent.schemas.data_analysis.resources import ResourceUsage
from agent.schemas.data_analysis.skills import (
    ArtifactOutputContract,
    SkillExecutionProvenance,
    SkillFailure,
    SkillInput,
    SkillResult,
)
from agent.schemas.data_analysis.trained_model import ModelInferenceReceipt
from execute_tools.analysis_materialization import (
    AnalysisAuthorizationError,
    TaskAnalysisCapability,
)
from execute_tools.historical_model_inference import (
    HistoricalModelInferenceCapability,
    HistoricalPredictionRetentionCapability,
    HistoricalPredictionRetentionReceipt,
)

from .analysis_code_sandbox import (
    AnalysisCodeSandbox,
    AnalysisCodeSandboxError,
    AnalysisCodeSandboxUnavailable,
)
from .execution_origin import trusted_skill_execution_origin
from .executor import execute_skill
from .generated_program_executor import execute_generated_program
from .historical_inference import HistoricalInferenceError
from .invocation_materialization import prepare_invocation_materializations
from .materialization import AnalysisMaterializationError
from .persistence import AnalysisRunStore
from .plan_validation import (
    ResolvedAnalysisInvocation,
    ResolvedGeneratedExperimentSkillInvocation,
    ResolvedGeneratedProgramInvocation,
    ResolvedPlannedInvocation,
)


@dataclass(frozen=True)
class AnalysisActionExecutionOutcome:
    result: SkillResult
    inference_receipts: tuple[ModelInferenceReceipt, ...]
    inspected_asset_ids: tuple[str, ...]


def _apply_prediction_retention(
    *,
    capability: HistoricalModelInferenceCapability | None,
    inference_receipts: tuple[ModelInferenceReceipt, ...],
    retain_model_outputs: bool,
    store: AnalysisRunStore,
) -> tuple[HistoricalPredictionRetentionReceipt, ...]:
    """Retire completed predictions after their consuming action returns."""

    recorded: list[HistoricalPredictionRetentionReceipt] = []
    for inference in inference_receipts:
        ref = inference.prediction_artifact_ref
        if inference.status != "completed" or ref is None:
            continue
        try:
            if not isinstance(capability, HistoricalPredictionRetentionCapability):
                raise ValueError("historical inference has no retention capability")
            receipt = capability.apply_prediction_retention(
                inference, retain_model_outputs=retain_model_outputs
            )
            if (
                receipt.inference_id != inference.inference_id
                or receipt.prediction_artifact_ref != ref
                or receipt.retain_model_outputs != retain_model_outputs
            ):
                raise ValueError("prediction retention receipt disagrees with exact inference")
            if receipt.status not in {
                "failed",
                "retained" if retain_model_outputs else "retired",
            }:
                raise ValueError("prediction retention disposition contradicts the run policy")
        except Exception as exc:
            receipt = HistoricalPredictionRetentionReceipt(
                inference_id=inference.inference_id,
                prediction_artifact_ref=ref,
                retain_model_outputs=retain_model_outputs,
                status="failed",
                failure_code="prediction_retention_failed",
                failure_message=str(exc) or type(exc).__name__,
            )
        store.append_prediction_retention_receipt(receipt)
        recorded.append(receipt)
    return tuple(recorded)


def _with_retention_failure(result: SkillResult) -> SkillResult:
    """Do not expose a completed scientific finding after output cleanup failed."""

    if result.status != "completed":
        return result
    payload = result.model_dump(mode="python")
    payload.update(
        status="failed",
        summary="Analysis executed, but prediction retention could not be certified.",
        quantitative_results=(),
        artifact_refs=(),
        failure=SkillFailure(
            failure_type="prediction_retention_failed",
            message="The temporary prediction output could not be safely retired or certified.",
            materialization_occurred=True,
        ),
    )
    return SkillResult.model_validate(payload)


def _pre_execution_result(
    *,
    inp: DataAnalysisInput,
    item: ResolvedAnalysisInvocation,
    plan: AnalysisPlan,
    status: Literal["failed", "refused"],
    failure_type: str,
    message: str,
    materialization_occurred: bool,
    started_at: str,
    started_monotonic: float,
    authorization_receipts: tuple[AnalysisAuthorizationReceipt, ...] = (),
    inference_receipts: tuple[ModelInferenceReceipt, ...] = (),
) -> SkillResult:
    if isinstance(item, ResolvedGeneratedProgramInvocation):
        execution_origin = "generated_program"
        skill_identity = None
        generated_program_identity = item.invocation.program_identity
    elif isinstance(item, ResolvedGeneratedExperimentSkillInvocation):
        execution_origin = "generated_experiment_skill"
        skill_identity = item.skill.identity
        generated_program_identity = None
    else:
        execution_origin = trusted_skill_execution_origin(item.skill)
        skill_identity = item.skill.identity
        generated_program_identity = None
    return SkillResult(
        result_id=f"{inp.request_id}.{item.invocation.invocation_id}.result",
        invocation_id=item.invocation.invocation_id,
        execution_origin=execution_origin,
        skill_identity=skill_identity,
        generated_program_identity=generated_program_identity,
        status=status,
        summary="Analysis invocation could not reach bounded execution.",
        resource_usage=ResourceUsage(
            wall_time_s=max(0.0, time.monotonic() - started_monotonic),
            peak_rss_bytes=0,
            device="cpu",
            measurement_limitations=(
                "No analysis worker was launched; resource usage covers orchestration only.",
            ),
        ),
        failure=SkillFailure(
            failure_type=failure_type,
            message=message,
            materialization_occurred=materialization_occurred,
            refusal_code=failure_type if status == "refused" else None,
        ),
        provenance=SkillExecutionProvenance(
            plan_sha256=canonical_sha256(plan),
            parameter_schema_sha256=item.validated_parameters.parameter_schema_sha256,
            validated_parameters_sha256=(item.validated_parameters.validated_parameters_sha256),
            authorization_receipts=authorization_receipts,
            inference_receipts=inference_receipts,
            environment_lock_verified=False,
            started_at=started_at,
            finished_at=utc_now(),
            host_details={"supervisor_disposition": "worker_not_started"},
        ),
    )


def execute_resolved_action(
    *,
    item: ResolvedAnalysisInvocation,
    inp: DataAnalysisInput,
    plan: AnalysisPlan,
    store: AnalysisRunStore,
    task_capability: TaskAnalysisCapability,
    inference_capability: HistoricalModelInferenceCapability | None,
    control_root: Path,
    deadline_monotonic_s: float,
) -> AnalysisActionExecutionOutcome:
    """Materialize, execute through the origin-owned path, and clean private copies."""

    started_at = utc_now()
    started_monotonic = time.monotonic()
    sandbox: AnalysisCodeSandbox | None = None
    if isinstance(
        item,
        (ResolvedGeneratedProgramInvocation, ResolvedGeneratedExperimentSkillInvocation),
    ):
        sandbox = AnalysisCodeSandbox()
        capability = sandbox.probe()
        if not capability.available:
            return AnalysisActionExecutionOutcome(
                result=_pre_execution_result(
                    inp=inp,
                    item=item,
                    plan=plan,
                    status="refused",
                    failure_type="generated_code_sandbox_unavailable",
                    message=capability.reason or "generated-code sandbox is unavailable",
                    materialization_occurred=False,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
                inference_receipts=(),
                inspected_asset_ids=(),
            )

    materialization_directory = store.root / "materializations" / item.invocation.invocation_id
    try:
        bundle = prepare_invocation_materializations(
            invocation=item,
            task_capability=task_capability,
            inference_capability=inference_capability,
            available_assets={asset.asset_id: asset for asset in inp.available_assets},
            access_policy=inp.access_policy,
            source_scope=inp.effective_source_scope(),
            resource_envelope=inp.resource_envelope,
            deadline_monotonic_s=deadline_monotonic_s,
            destination_root=materialization_directory,
        )
    except AnalysisAuthorizationError as exc:
        return AnalysisActionExecutionOutcome(
            result=_pre_execution_result(
                inp=inp,
                item=item,
                plan=plan,
                status="refused",
                failure_type=exc.refusal.code,
                message=exc.refusal.message,
                materialization_occurred=False,
                started_at=started_at,
                started_monotonic=started_monotonic,
            ),
            inference_receipts=(),
            inspected_asset_ids=(),
        )
    except AnalysisMaterializationError as exc:
        store.cleanup_materializations(materialization_directory)
        return AnalysisActionExecutionOutcome(
            result=_pre_execution_result(
                inp=inp,
                item=item,
                plan=plan,
                status="failed",
                failure_type="materialization_contract",
                message=str(exc),
                materialization_occurred=True,
                started_at=started_at,
                started_monotonic=started_monotonic,
            ),
            inference_receipts=(),
            inspected_asset_ids=(),
        )
    except HistoricalInferenceError as exc:
        try:
            _apply_prediction_retention(
                capability=inference_capability,
                inference_receipts=exc.completed_receipts,
                retain_model_outputs=inp.retain_model_outputs,
                store=store,
            )
        finally:
            store.cleanup_materializations(materialization_directory)
        receipts = exc.completed_receipts
        if exc.receipt is not None and exc.receipt not in receipts:
            receipts = (*receipts, exc.receipt)
        return AnalysisActionExecutionOutcome(
            result=_pre_execution_result(
                inp=inp,
                item=item,
                plan=plan,
                status="refused" if exc.refused else "failed",
                failure_type=(
                    "historical_inference_capability_unavailable"
                    if exc.refused
                    else "historical_inference_failed"
                ),
                message=str(exc),
                materialization_occurred=not exc.refused,
                inference_receipts=receipts,
                started_at=started_at,
                started_monotonic=started_monotonic,
            ),
            inference_receipts=receipts,
            inspected_asset_ids=(),
        )

    if isinstance(
        item,
        (ResolvedGeneratedProgramInvocation, ResolvedGeneratedExperimentSkillInvocation),
    ):
        allowed_media_types = tuple(
            sorted({artifact.media_type for artifact in item.program.expected_artifacts})
        )
        artifact_contract = store.artifact_output_contract(
            item.invocation.invocation_id,
            allowed_media_types=allowed_media_types,
            max_artifact_count=item.program.resource_request.max_artifact_count,
            max_total_bytes=item.program.resource_request.max_artifact_bytes,
        )
    else:
        artifact_contract = ArtifactOutputContract(
            output_directory_ref=f"staging/{item.invocation.invocation_id}",
            allowed_media_types=("application/json", "image/png", "text/csv"),
        )

    staging = store.staging_directory(item.invocation.invocation_id)
    retention_receipts: tuple[HistoricalPredictionRetentionReceipt, ...] = ()
    try:
        if isinstance(item, ResolvedPlannedInvocation):
            skill_input = SkillInput(
                invocation_id=item.invocation.invocation_id,
                skill_identity=item.skill.identity,
                materializations=bundle.views,
                question_ids=item.invocation.question_ids,
                deadline_monotonic_s=deadline_monotonic_s,
                artifact_output_contract=artifact_contract,
            )
            result = execute_skill(
                result_id=f"{inp.request_id}.{item.invocation.invocation_id}.result",
                skill=item.skill,
                validated_parameters=item.validated_parameters,
                skill_input=skill_input,
                materialization_paths=bundle.paths,
                store=store,
                staging_directory=staging,
                control_directory=control_root / f"execute-{item.invocation.invocation_id}",
                plan_sha256=canonical_sha256(plan),
                timeout_s=min(
                    inp.resource_envelope.per_skill_timeout_s,
                    max(0.0, deadline_monotonic_s - time.monotonic()),
                ),
                max_host_memory_gb=inp.resource_envelope.max_host_memory_gb,
                pre_execution_resource_usage=tuple(
                    receipt.resource_usage for receipt in bundle.inference_receipts
                ),
            )
        else:
            assert sandbox is not None
            max_memory = (
                inp.resource_envelope.max_host_memory_gb
                or item.program.resource_request.max_host_memory_gb
            )
            try:
                result = execute_generated_program(
                    result_id=f"{inp.request_id}.{item.invocation.invocation_id}.result",
                    invocation_id=item.invocation.invocation_id,
                    program=item.program,
                    identity=(
                        item.invocation.program_identity
                        if isinstance(item, ResolvedGeneratedProgramInvocation)
                        else item.skill.program_identity
                    ),
                    execution_origin=(
                        "generated_program"
                        if isinstance(item, ResolvedGeneratedProgramInvocation)
                        else "generated_experiment_skill"
                    ),
                    skill_identity=(
                        None
                        if isinstance(item, ResolvedGeneratedProgramInvocation)
                        else item.skill.identity
                    ),
                    parameter_schema_sha256=(item.validated_parameters.parameter_schema_sha256),
                    source_path=item.source_path,
                    parameters=item.validated_parameters.parameters,
                    materializations=bundle.views,
                    materialization_paths=bundle.paths,
                    store=store,
                    staging_directory=staging,
                    control_directory=(
                        control_root / f"execute-generated-{item.invocation.invocation_id}"
                    ),
                    artifact_contract=artifact_contract,
                    plan_sha256=canonical_sha256(plan),
                    timeout_s=min(
                        inp.resource_envelope.per_skill_timeout_s,
                        max(0.0, deadline_monotonic_s - time.monotonic()),
                    ),
                    max_host_memory_gb=max_memory,
                    sandbox=sandbox,
                )
            except (AnalysisCodeSandboxUnavailable, AnalysisCodeSandboxError) as exc:
                result = _pre_execution_result(
                    inp=inp,
                    item=item,
                    plan=plan,
                    status="failed",
                    failure_type="generated_code_sandbox_failure",
                    message=str(exc),
                    materialization_occurred=True,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                    authorization_receipts=tuple(
                        view.authorization_receipt for view in bundle.views
                    ),
                )
    finally:
        try:
            retention_receipts = _apply_prediction_retention(
                capability=inference_capability,
                inference_receipts=bundle.inference_receipts,
                retain_model_outputs=inp.retain_model_outputs,
                store=store,
            )
        finally:
            store.cleanup_staging(staging)
            store.cleanup_materializations(materialization_directory)

    if any(receipt.status == "failed" for receipt in retention_receipts):
        result = _with_retention_failure(result)

    return AnalysisActionExecutionOutcome(
        result=result,
        inference_receipts=bundle.inference_receipts,
        inspected_asset_ids=bundle.inspected_asset_ids,
    )
