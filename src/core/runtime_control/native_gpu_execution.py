"""Selected native executor admission, startup and terminal evidence wiring."""

from __future__ import annotations

import functools
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from core.durable_io import publish_bytes_write_once
from core.runtime_control.admission import RESOURCE_REJECTIONS, evaluate_gpu_admission
from core.runtime_control.gpu_accounting import sample
from core.runtime_control.gpu_execution_evidence import AttemptGpuExecution
from core.runtime_control.gpu_observer import GpuPhaseObserver
from core.runtime_control.gpu_protection import GpuProtectionBinding, TimedGpuObservation
from core.runtime_control.inference_measurement_binding import inference_measurement_binding
from core.runtime_control.inference_startup import (
    InferenceStartup,
    InferenceStartupRequest,
    publish_message,
)
from core.runtime_control.observed_subprocess import ProcessControlError, supervise_subprocess
from core.runtime_control.training_measurement_binding import training_measurement_binding
from core.subprocess_env import subprocess_env


def active_attempt(sandbox) -> AttemptGpuExecution | None:
    state = getattr(sandbox, "gpu_execution", None)
    return state if isinstance(state, AttemptGpuExecution) else None


def validate_native_inputs(
    sandbox,
    phase: str,
    *,
    exp_id: str,
    model_type: str,
    model_config: dict,
    loss_config: dict,
    task_scopes,
    train_config: dict | None = None,
    inference_batch: int | None = None,
    train_portion: float | None = None,
    train_base_seed: int | None = None,
    custom_loss_snapshot=None,
) -> None:
    state = active_attempt(sandbox)
    if state is None:
        return
    entry = state.phases.get(phase)
    if entry is None or entry.attempt_token != state.attempt_token or exp_id != state.experiment_id:
        raise ValueError("protected native launch has no evidence for this attempt/phase")
    spec = entry.spec
    if (
        spec.request.model_type != model_type
        or spec.request.device_uuid != sandbox.device_identity.uuid
    ):
        raise ValueError("protected native launch model/device differs from its measurement")
    expected_model, expected_loss = sandbox._validate_model_and_loss(
        model_type, spec.model_config_payload, spec.loss_config
    )
    if model_config != expected_model or loss_config != expected_loss:
        raise ValueError("protected native launch configs differ from their measurement")
    probe = spec.task_probe_data
    from execute_tools.task_data_path import (
        require_bound_task_data_path,
        resolve_task_scope_capability,
    )
    from workflows.task_composition import active_composition_fingerprint
    from workflows.task_config import run_bound_model_io_contract

    if probe is None or task_scopes is None:
        raise ValueError("protected native launch requires the measured task scope")
    capability = resolve_task_scope_capability(require_bound_task_data_path())
    selected_scope = task_scopes.training if phase == "training" else task_scopes.evaluation
    expected_scope = (
        probe.training_scope_payload if phase == "training" else probe.evaluation_scope_payload
    )
    if (
        capability.serialize_scope(selected_scope) != expected_scope
        or active_composition_fingerprint() != probe.semantic_fingerprint
        or run_bound_model_io_contract() != spec.model_io_contract
        or sandbox.dirs["data"] != spec.data_dir
    ):
        raise ValueError("protected native launch task/data contract differs from its measurement")
    if phase == "training":
        from core.capability_registry import CapabilityContractSnapshot
        from ml_models.models_format_sandbox import TrainConfig

        actual_loss_snapshot = (
            CapabilityContractSnapshot.model_validate(custom_loss_snapshot)
            if custom_loss_snapshot is not None
            else None
        )
        if actual_loss_snapshot != spec.expected_custom_loss_snapshot:
            raise ValueError("protected native loss contract differs from its measurement")
        if train_config != TrainConfig(**spec.train_config).model_dump():
            raise ValueError("protected native training config differs from its measurement")
        if (
            train_portion != probe.sampling.train_portion
            or train_base_seed != probe.sampling.epoch_seed
        ):
            raise ValueError("protected native training sampling differs from its measurement")
    elif inference_batch != spec.inference_batch_size:
        raise ValueError("protected native inference batch differs from its measurement")
    env = subprocess_env(sandbox.plugin_dir, sandbox.loss_dir)
    current = (
        training_measurement_binding(spec, environ=env)
        if phase == "training"
        else inference_measurement_binding(spec, environ=env)
    )
    expected = spec.training_binding if phase == "training" else spec.inference_binding
    if current != expected:
        raise ValueError("protected native execution sources changed after measurement")
    entry.requirement()


def admit_phase(sandbox, phase: str) -> dict | None:
    state = active_attempt(sandbox)
    assert state is not None
    entry = state.phases[phase]
    requirement = entry.requirement()
    started = time.monotonic()
    snapshot = sample(os.getpid(), sandbox.device_identity)
    observed = TimedGpuObservation(
        sequence=0, query_started_at=started, query_completed_at=time.monotonic(), snapshot=snapshot
    )
    policy = sandbox.admission_policy
    decision = evaluate_gpu_admission(
        snapshot=snapshot,
        requirement_mib=requirement.requirement_mib,
        requirement_provenance=requirement.provenance,
        requirement_ownership=requirement.ownership,
        requirement_error=requirement.validation_error,
        mode=policy.mode,
        ceiling_gib=policy.ceiling_gib,
        run_name=state.experiment_id,
    )
    state.current_admission = decision
    if not decision.admitted:
        return {
            "status": (
                "skipped_resource_admission"
                if decision.reason_code in RESOURCE_REJECTIONS
                else "aborted_infrastructure"
            ),
            "message": decision.reason,
            "admission": decision.model_dump(mode="json"),
        }
    if snapshot.device_total_mib is None:
        return {
            "status": "aborted_infrastructure",
            "message": "admission omitted current physical device capacity",
            "admission": decision.model_dump(mode="json"),
        }
    binding = GpuProtectionBinding(
        attempt_token=state.attempt_token,
        phase=phase,
        device=snapshot.device,
        device_total_mib=snapshot.device_total_mib,
        effective_ceiling_gib=decision.evidence["effective_ceiling_gib"],
        ceiling_origin=str(decision.evidence["ceiling_resolution"]["operator_source"]),
    )
    state.current_observer = GpuPhaseObserver(
        snapshot.device,
        protection_policy=state.policy.protection,
        protection_binding=binding,
        initial_observation=observed,
    )
    return None


def prepare_startup(sandbox, cmd: list[str]) -> InferenceStartup:
    state = active_attempt(sandbox)
    assert state is not None
    deadline = state.allowance.deadline
    directory = Path(sandbox.base_dir) / "gpu_execution" / state.attempt_token / "startup"
    directory.mkdir(parents=True, exist_ok=False)
    policy = state.policy
    request = InferenceStartupRequest(
        nonce=state.attempt_token,
        spec=state.phases["inference"].spec,
        deadline_at=deadline,
        ack_timeout_seconds=policy.startup_ack_timeout_seconds,
        poll_seconds=policy.protection.control.poll_seconds,
        receipt_limit_bytes=policy.startup_receipt_limit_bytes,
    )
    path = directory / "request.json"
    publish_message(path, request, policy.startup_receipt_limit_bytes)
    startup = InferenceStartup(
        path,
        request,
        rss_limit_bytes=policy.worker_rss_limit_bytes,
        on_publication=lambda at: state.allowance.finish("authorized", ended_at=at),
        environment=subprocess_env(sandbox.plugin_dir, sandbox.loss_dir),
        control=state.current_observer,
    )
    state.current_startup = startup
    cmd.extend(["--inference_startup_json", str(path)])
    return startup


def control_kwargs(sandbox) -> dict:
    state = active_attempt(sandbox)
    if state is None:
        return {}
    values = {"control": state.current_observer}
    if state.current_startup is not None:
        values["startup"] = state.current_startup
    return values


def run_native_subprocess(sandbox, ordinary_runner, cmd, **kwargs):
    """Retain typed selected lifecycle while the legacy caller keeps its tuple."""
    state = active_attempt(sandbox)
    if state is None:
        return ordinary_runner(cmd, **kwargs)
    if state.current_startup is None:
        kwargs["launch_measurement"] = state.allowance
    try:
        result = supervise_subprocess(cmd, **kwargs)
    except subprocess.CalledProcessError as error:
        state.current_child_failure = error
        state.current_lifecycle = getattr(error, "process_lifecycle", None)
        raise
    state.current_lifecycle = result.lifecycle
    return result.completed, result.timeout


def _cleanup_attempt(sandbox, phase: str, exp_id: str, model_type: str, run_name: str) -> None:
    from core.sandbox_layout import training_checkpoint_path

    if phase == "training":
        paths = (
            training_checkpoint_path(sandbox.dirs["models"], model_type, exp_id),
            Path(sandbox.dirs["models"]) / f"_OK_{exp_id}",
            Path(sandbox.dirs["records"])
            / run_name
            / f"experiment_results_{model_type}_{exp_id}.json",
        )
    elif sandbox.deliverable_naming is not None:
        paths = Path(sandbox.base_dir).glob(
            sandbox.deliverable_naming.attempt_glob(
                model_type=model_type, run_name=run_name, exp_id=exp_id
            )
        )
    else:
        paths = ()
    for path in paths:
        Path(path).unlink(missing_ok=True)


def record_protected_phase(phase: Literal["training", "inference"]):
    """Wrap only the two native phase result boundaries; absent selection is a direct call."""

    def decorate(function):
        @functools.wraps(function)
        def run(sandbox, *args, **kwargs):
            state = active_attempt(sandbox)
            if state is None:
                return function(sandbox, *args, **kwargs)
            state.current_admission = state.current_observer = state.current_startup = None
            state.current_lifecycle = None
            state.current_child_failure = None
            lifecycle = None
            result: dict[str, Any]
            try:
                state.allowance.begin(f"{phase}_launch")
                result = function(sandbox, *args, **kwargs)
            except Exception as error:
                from core.local_code.failure import raise_if_code_package_failure

                raise_if_code_package_failure(error)
                lifecycle = getattr(error, "lifecycle", getattr(error, "process_lifecycle", None))
                result = {"status": "aborted_infrastructure", "message": str(error)}
                if isinstance(error, ProcessControlError):
                    result.update(stdout=error.stdout, stderr=error.stderr, watchdog=error.timeout)
                elif isinstance(error, subprocess.CalledProcessError):
                    result.update(
                        stdout=error.stdout, stderr=error.stderr, returncode=error.returncode
                    )
            finally:
                state.allowance.finish_if_active("startup failed before authorization")
            child_failure = state.current_child_failure
            if child_failure is not None:
                result.update(
                    stdout=child_failure.stdout,
                    stderr=child_failure.stderr,
                    returncode=child_failure.returncode,
                )
            observer = state.current_observer
            protection = observer.protection_receipt() if observer is not None else None
            startup = state.current_startup
            if protection is not None and protection.decision.status == "stop":
                result["status"] = "aborted_infrastructure"
                result["message"] = protection.decision.reason
            if startup is not None and (
                startup.receipt.error is not None or startup.receipt.consumed is None
            ):
                result["status"] = "aborted_infrastructure"
                result["message"] = (
                    startup.receipt.error or "inference child did not acknowledge authorization"
                )
            if result.get("status") not in {"success", "skipped_resource_admission"}:
                try:
                    _cleanup_attempt(
                        sandbox,
                        phase,
                        kwargs.get("exp_id", args[0] if args else state.experiment_id),
                        kwargs.get("model_type") or (args[2] if len(args) > 2 else ""),
                        kwargs.get("run_name") or (args[1] if len(args) > 1 else ""),
                    )
                except Exception as error:
                    result["status"] = "aborted_infrastructure"
                    result["message"] = (
                        f"{result.get('message', '')}; attempt cleanup failed: {error}"
                    )
            receipt = state.receipt(
                phase,
                result.get("status", "unavailable"),
                admission=state.current_admission,
                protection=protection,
                lifecycle=lifecycle or state.current_lifecycle,
                stdout=result.get("stdout"),
                stderr=result.get("stderr"),
                watchdog=result.get("watchdog"),
                detail=result.get("message", ""),
                startup=startup.receipt if startup is not None else None,
            )
            directory = Path(sandbox.base_dir) / "gpu_execution" / state.attempt_token
            try:
                directory.mkdir(parents=True, exist_ok=True)
                publish_bytes_write_once(
                    str(directory / f"{phase}-terminal.json"), receipt.model_dump_json().encode()
                )
            except Exception as error:
                result["status"] = "aborted_infrastructure"
                result["message"] = (
                    f"Execution outcome was {receipt.outcome}; GPU terminal evidence could not be persisted: {error}"
                )
                receipt = receipt.model_copy(
                    update={"outcome": "aborted_infrastructure", "detail": result["message"]}
                )
                state.receipts[-1] = receipt
            result["gpu_execution"] = receipt.model_dump(mode="json")
            return result

        return run

    return decorate
