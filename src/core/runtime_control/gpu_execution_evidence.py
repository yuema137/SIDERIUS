"""Attempt-local measured phase evidence and terminal execution receipts."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from core.runtime_control.admission import AdmissionDecision
from core.runtime_control.gpu_execution_policy import GpuExecutionPolicy
from core.runtime_control.gpu_measurement_runner import PrephaseMeasurementRun
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.gpu_protection import GpuProtectionReceipt
from core.runtime_control.gpu_requirement_evidence import (
    AdmissionRequirementEvidence,
    GpuRequirementOwnership,
)
from core.runtime_control.inference_measurement_assessment import InferenceMeasurementAssessment
from core.runtime_control.inference_startup import InferenceStartupReceipt
from core.runtime_control.measurement_allowance import (
    MeasurementAllowance,
    MeasurementSegmentReceipt,
)
from core.runtime_control.observed_subprocess import ProcessLifecycle
from core.runtime_control.training_measurement_assessment import TrainingMeasurementAssessment


class PreparedGpuPhase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    attempt_token: str
    spec: GpuMeasurementSpec
    run: PrephaseMeasurementRun
    assessment: TrainingMeasurementAssessment | InferenceMeasurementAssessment

    def requirement(self) -> AdmissionRequirementEvidence:
        if self.assessment.disposition != "admitted":
            raise ValueError(self.assessment.detail)
        if (
            self.run.host_memory.observations_complete is not True
            or self.run.process.final_group_observation is None
            or self.run.process.final_group_observation.status != "absent"
        ):
            raise ValueError("selected measurement lacks complete host/cleanup evidence")
        demand = self.assessment.worker_requirement_mib
        if demand is None:
            raise ValueError("admitted assessment omitted whole-worker demand")
        return AdmissionRequirementEvidence(
            requirement_mib=float(demand),
            provenance="measured",
            ownership=GpuRequirementOwnership(
                domain="new_worker_process_tree",
                device_uuid=self.run.observed_device_uuid,
                process=self.run.process,
                owned_pids=tuple(
                    sorted({pid for phase in self.run.phases for pid in phase.own_pids})
                ),
            ),
        )


class GpuExecutionReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    attempt_token: str
    phase: Literal["training", "inference"]
    outcome: str
    policy: GpuExecutionPolicy
    measurement_segments: tuple[MeasurementSegmentReceipt, ...]
    measurement: PreparedGpuPhase | None
    admission: AdmissionDecision | None = None
    protection: GpuProtectionReceipt | None = None
    lifecycle: ProcessLifecycle | None = None
    startup: InferenceStartupReceipt | None = None
    stdout: str | None = None
    stderr: str | None = None
    watchdog: dict[str, Any] | None = None
    detail: str = ""


@dataclass
class AttemptGpuExecution:
    attempt_token: str
    experiment_id: str
    policy: GpuExecutionPolicy
    allowance: MeasurementAllowance
    phases: dict[str, PreparedGpuPhase] = field(default_factory=dict)
    receipts: list[GpuExecutionReceipt] = field(default_factory=list)
    current_admission: AdmissionDecision | None = None
    current_observer: Any = None
    current_startup: Any = None
    current_lifecycle: ProcessLifecycle | None = None
    current_child_failure: subprocess.CalledProcessError | None = None

    def receipt(
        self, phase: Literal["training", "inference"], outcome: str, **facts
    ) -> GpuExecutionReceipt:
        receipt = GpuExecutionReceipt(
            attempt_token=self.attempt_token,
            phase=phase,
            outcome=outcome,
            policy=self.policy,
            measurement_segments=tuple(self.allowance.receipts),
            measurement=self.phases.get(phase),
            **facts,
        )
        self.receipts.append(receipt)
        return receipt
