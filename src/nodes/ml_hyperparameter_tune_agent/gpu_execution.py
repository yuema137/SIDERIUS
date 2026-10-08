"""Connect the existing native phase measurements to one protected attempt."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Literal

from core.durable_io import publish_bytes_write_once
from core.runtime_control.checkpoint_identity import CheckpointIdentityRequest
from core.runtime_control.checkpoint_identity_runner import prepare_checkpoint_identity
from core.runtime_control.gpu_accounting import DeviceIdentity
from core.runtime_control.gpu_execution_evidence import AttemptGpuExecution, PreparedGpuPhase
from core.runtime_control.gpu_measurement_identity import (
    build_planned_identity,
    resolve_inference_batch,
)
from core.runtime_control.gpu_measurement_runner import run_prephase_measurement
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.gpu_requirement import CandidateMeasurementRequest
from core.runtime_control.inference_measurement_assessment import assess_inference_measurement
from core.runtime_control.inference_measurement_binding import inference_measurement_binding
from core.runtime_control.measurement_allowance import MeasurementAllowance
from core.runtime_control.observed_subprocess import ProcessLimits
from core.runtime_control.pair_admission import mib_from_gib, resolve_gpu_ceiling
from core.runtime_control.training_measurement_assessment import assess_training_measurement
from core.runtime_control.training_measurement_binding import bind_training_measurement
from core.sandbox_layout import training_checkpoint_path
from core.subprocess_env import subprocess_env
from execute_tools.evaluation_execution import candidate_evaluation_executor
from nodes.ml_hyperparameter_tune_agent.probe_data import build_task_probe_data


def begin_attempt(sandbox, agent_input, exp_id: str) -> None:
    """Selection is explicit; CPU/pseudo never allocate a measurement state."""
    sandbox.gpu_execution = None
    from core.sandbox_executor import StubSandbox

    policy = agent_input.gpu_execution_policy
    if policy is None or isinstance(sandbox, StubSandbox) or sandbox.device_available is False:
        return
    sandbox.gpu_execution = AttemptGpuExecution(
        attempt_token=uuid.uuid4().hex,
        experiment_id=exp_id,
        policy=policy,
        allowance=MeasurementAllowance(policy.phase_measurement_budget_seconds),
    )


def end_attempt(sandbox) -> None:
    state = getattr(sandbox, "gpu_execution", None)
    if isinstance(state, AttemptGpuExecution):
        state.allowance.finish_if_active("attempt terminated during preparation")
    sandbox.gpu_execution = None


def _limits(state: AttemptGpuExecution, remaining: float) -> ProcessLimits:
    control = state.policy.protection.control
    return ProcessLimits(
        deadline_seconds=remaining,
        rss_limit_bytes=state.policy.worker_rss_limit_bytes,
        poll_seconds=control.poll_seconds,
        grace_seconds=control.grace_seconds,
        reap_seconds=control.reap_seconds,
    )


def _spec(
    bindings,
    prepared,
    phase: Literal["training", "inference"],
    state: AttemptGpuExecution,
    deadline: float,
    directory: Path,
    checkpoint=None,
) -> GpuMeasurementSpec:
    sandbox = bindings.sandbox
    active = prepared.active_params
    probe = build_task_probe_data(
        task_composition_ref=bindings.agent_input.task_composition_ref,
        task_scopes=prepared.task_scopes,
        data_dir=bindings.time_data_dir,
        epoch_seed=prepared.trial_config.train_base_seed,
        train_portion=prepared.trial_config.train_portion,
        max_samples=bindings.agent_input.validation_max_train_samples,
    )
    if probe is None or probe.evaluation_scope_payload is None:
        raise ValueError(
            "protected native GPU execution requires composed training and evaluation scopes"
        )
    inference_batch = resolve_inference_batch(
        prepared.model_type, explicit=active.get("inference_batch")
    )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("phase preparation exhausted the shared measurement allowance")
    spec = GpuMeasurementSpec(
        label=f"{prepared.exp_id}:{phase}",
        request=CandidateMeasurementRequest(
            model_type=prepared.model_type,
            planned_identity=build_planned_identity(
                model_type=prepared.model_type,
                model_config=active["model_config"],
                train_config=active["train_config"],
                inference_batch_size=inference_batch,
                segmentation_applicability=probe.segmentation_applicability,
            ),
            request_id=uuid.uuid4().hex,
            device_uuid=sandbox.device_identity.uuid,
            phase=phase,
            deadline_seconds=remaining,
        ),
        strict_lifecycle=True,
        model_config_payload=active["model_config"],
        train_config=active["train_config"],
        loss_config=active["loss_config"],
        expected_custom_loss_snapshot=prepared.expected_custom_loss_snapshot,
        inference_batch_size=inference_batch,
        inference_checkpoint=checkpoint,
        data_dir=bindings.time_data_dir,
        dataset_profile=bindings.run_profile,
        model_io_contract=bindings.run_model_io,
        task_probe_data=probe,
        plugin_dir=sandbox.plugin_dir,
        loss_dir=sandbox.loss_dir,
        result_path=str(directory / "result.json"),
        journal_path=str(directory / "phases.ndjson"),
        sampler_ready_path=str(directory / "ready"),
        setup_complete_path=str(directory / "setup"),
        phase_complete_path=str(directory / "work"),
        reservation_ack_path=str(directory / "reservation"),
        worker_memory_limit_bytes=state.policy.worker_rss_limit_bytes,
    )
    spec = spec.model_copy(
        update={
            "max_phase_seconds": min(spec.max_phase_seconds, remaining),
            "sampler_ready_timeout_seconds": min(spec.sampler_ready_timeout_seconds, remaining),
        }
    )
    env = subprocess_env(sandbox.plugin_dir, sandbox.loss_dir)
    if phase == "training":
        return bind_training_measurement(spec, environ=env)
    return spec.model_copy(
        update={"inference_binding": inference_measurement_binding(spec, environ=env)}
    )


def prepare_phase(bindings, prepared, identity, *, phase: Literal["training", "inference"]):
    """None is unselected; selected calls return the existing prephase disposition."""
    from nodes.ml_hyperparameter_tune_agent.runtime import PrephaseOutcome

    sandbox = bindings.sandbox
    state = getattr(sandbox, "gpu_execution", None)
    if not isinstance(state, AttemptGpuExecution):
        return None
    directory = Path(sandbox.base_dir) / "gpu_execution" / state.attempt_token / phase
    outcome = "unavailable"
    try:
        deadline = state.allowance.begin(phase)
        if not isinstance(sandbox.device_identity, DeviceIdentity):
            raise ValueError("protected GPU execution requires a discovered device identity")
        if candidate_evaluation_executor() is not None:
            raise ValueError(
                "protected native GPU execution does not support an external evaluation executor"
            )
        directory.mkdir(parents=True, exist_ok=False)
        checkpoint = None
        if phase == "inference":
            remaining = deadline - time.monotonic()
            request = CheckpointIdentityRequest(
                checkpoint_path=str(
                    training_checkpoint_path(
                        sandbox.dirs["models"], prepared.model_type, prepared.exp_id
                    ).resolve()
                ),
                model_type=prepared.model_type,
                experiment_id=prepared.exp_id,
                request_nonce=uuid.uuid4().hex,
                cooperative_seconds=remaining,
            )
            result = prepare_checkpoint_identity(
                request,
                limits=_limits(state, remaining),
                request_directory=directory,
                env=subprocess_env(sandbox.plugin_dir, sandbox.loss_dir),
            )
            publish_bytes_write_once(
                str(directory / "checkpoint.json"), result.model_dump_json().encode()
            )
            if result.reference is None:
                raise ValueError(result.detail)
            checkpoint = result.reference
        spec = _spec(bindings, prepared, phase, state, deadline, directory, checkpoint)
        limits = resolve_gpu_ceiling(
            ceiling_gib=bindings.agent_input.gpu_pair_ceiling_gib,
            measured_capacity_gib=bindings.hardware_context.total_memory_gb,
        )
        cap = int(mib_from_gib(limits.effective_gib))
        control = state.policy.protection.control
        run = run_prephase_measurement(
            spec,
            device=sandbox.device_identity,
            deadline_at=deadline,
            poll_seconds=control.poll_seconds,
            grace_seconds=control.grace_seconds,
        )
        assert spec.inference_batch_size is not None
        assessment = (
            assess_training_measurement(spec, run, cap_mib=cap)
            if phase == "training"
            else assess_inference_measurement(
                request=spec.request,
                binding=spec.inference_binding,
                run=run,
                batch_size=spec.inference_batch_size,
                max_batches=spec.inference_batches,
                cap_mib=cap,
                checkpoint=checkpoint,
            )
        )
        entry = PreparedGpuPhase(
            attempt_token=state.attempt_token, spec=spec, run=run, assessment=assessment
        )
        state.phases[phase] = entry
        publish_bytes_write_once(
            str(directory / "measurement.json"), entry.model_dump_json().encode()
        )
        if assessment.disposition == "capacity_refused":
            outcome = "capacity_refused"
            state.allowance.finish(outcome)
            record_capacity_refusal(bindings, prepared, identity, phase, entry)
            return PrephaseOutcome.TERMINAL_RESOURCE_REFUSAL
        entry.requirement()
        if time.monotonic() >= deadline:
            raise TimeoutError("measurement finalization exhausted the shared allowance")
        outcome = "measured"
    except Exception as error:
        state.allowance.finish_if_active("unavailable")
        fail_attempt(sandbox, phase, str(error))
    finally:
        state.allowance.finish_if_active(outcome)
    return PrephaseOutcome.PROCEED


def fail_attempt(sandbox, phase: Literal["training", "inference"], detail: str) -> None:
    """Persist typed infrastructure evidence before the tuner terminates."""
    from nodes.ml_hyperparameter_tune_agent.runtime import RuntimeEvidenceChannelError

    state = sandbox.gpu_execution
    receipt = state.receipt(phase, "aborted_infrastructure", detail=detail)
    try:
        persist_receipt(sandbox, receipt)
    except Exception as error:
        raise RuntimeEvidenceChannelError(
            f"{detail}; terminal evidence persistence failed: {error}"
        ) from error
    raise RuntimeEvidenceChannelError(detail)


def persist_receipt(sandbox, receipt) -> None:
    directory = Path(sandbox.base_dir) / "gpu_execution" / receipt.attempt_token
    directory.mkdir(parents=True, exist_ok=True)
    publish_bytes_write_once(
        str(directory / f"{receipt.phase}-terminal.json"), receipt.model_dump_json().encode()
    )


def record_capacity_refusal(bindings, prepared, identity, phase, entry) -> None:
    from importlib import import_module

    from core.record_role import observed_attempt_role

    records = import_module("nodes.ml_hyperparameter_tune_agent.records")
    from nodes.ml_hyperparameter_tune_agent.runtime import _build_resource_admission_record

    sandbox = bindings.sandbox
    state = sandbox.gpu_execution
    receipt = state.receipt(phase, "capacity_refused", detail=entry.assessment.detail)
    persist_receipt(sandbox, receipt)
    record = _build_resource_admission_record(
        resource_type="gpu_memory",
        reason_code="insufficient_headroom",
        detail=entry.assessment.detail,
        exp_id=prepared.exp_id,
        model_type=prepared.model_type,
        file_index=bindings.file_index,
        record_params=prepared.record_params,
        expert_advice_str=bindings.expert_advice_str,
        hypothesis=prepared.hypothesis,
        round_index=identity.round_index,
        attempt_in_round=identity.attempt_in_round,
        admission_evidence={"measurement_request": entry.spec.request.model_dump(mode="json")},
    )
    records._emit_record(
        sandbox,
        record,
        candidate_id=bindings.agent_input.candidate_id,
        experiment_arm=bindings.agent_input.experiment_arm,
        ordering=prepared.ordering,
        attempt_role=observed_attempt_role(prepared.plan.is_trial),
    )
