"""
core/runtime_control/session.py

In-subprocess runtime-verification session (RT2-B).

Design: docs/design/runtime_estimation_and_watchdog.md §2.1 (in-
subprocess verification), §2.2 (setup measurement), §6.2 (progressive
observation lifecycle). The session is the EVENT LOG of one production
execution attempt: it creates the `RuntimeObservation` when setup
begins and atomically rewrites the observation sidecar at every stage
transition, so a crash at any point leaves the last completed stage's
evidence on disk — never a partially written record presented as
complete.

Stage progression (``RuntimeObservation.final_status``):

    setup_started → setup_complete → admitted | rejected
                  → completed | failed_<stage>

RT2-B admission semantics: the only measured component is setup, so the
session rejects exactly when the MEASURED setup alone already exceeds
the operator budget — a conservative lower bound on the total (§3:
the full total prediction can only be larger). Everything else is
admitted with an explicit "training verification pending" reason; the
live training/inference verifiers (RT2-C/D) tighten this decision
without changing the session contract.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.phases import RuntimePhase
from core.runtime_control.provenance import (
    capture_environment_provenance,
    classify_cache_state,
    read_process_read_bytes,
    read_process_rss_bytes,
)
from core.runtime_control.records import (
    AdmissionRecord,
    PhaseComponentRecord,
    PhaseMeasurement,
    RuntimeObservation,
    RuntimePrediction,
)
from core.runtime_control.workload import ResolvedPhaseWorkload

ADMISSION_STAGE_POST_SETUP = "post_setup_runtime_verification"


class RuntimeControlPolicy(BaseModel):
    """Operator runtime policy in force for one execution attempt.

    Validated at the executor boundary before being written to the
    subprocess policy JSON (LLM/operator input never reaches execution
    unvalidated). RT2-B carries only the budget; RT2-C adds
    stabilization caps and safety factors as they become live.
    """

    model_config = ConfigDict(frozen=True)

    operator_budget_seconds: float | None = Field(
        default=None,
        gt=0.0,
        description="Wall-clock budget for the attempt. None → record-only (no enforcement).",
    )


class RuntimeVerificationSession:
    """Progressive builder + sidecar writer for one attempt's observation.

    Args:
        observation_path: Sidecar JSON path (atomically rewritten at
            each stage). Parent process reads this back after exit.
        policy:           Validated runtime policy; ``None`` → record-only.
        chain_id:         Optional chain identifier for the observation.
        attempt_id:       Optional attempt identifier (e.g. ``exp_id``).

    The session never raises out of its sidecar writes: losing the
    ability to persist provenance must not kill a healthy training
    run. Write failures are printed and the in-memory observation
    remains authoritative for the process lifetime.
    """

    def __init__(
        self,
        observation_path: str,
        policy: RuntimeControlPolicy | None = None,
        chain_id: str | None = None,
        attempt_id: str | None = None,
    ):
        self.observation_path = observation_path
        self.policy = policy or RuntimeControlPolicy()
        self._chain_id = chain_id
        self._attempt_id = attempt_id
        self._environment = capture_environment_provenance()
        self._components: dict[RuntimePhase, PhaseComponentRecord] = {}
        self._admission: AdmissionRecord | None = None
        self._final_status: str = "setup_started"
        self._storage: dict[str, Any] = {}

        self._setup_start = time.perf_counter()
        self._io_bytes_at_start = read_process_read_bytes()
        self._rss_at_start = read_process_rss_bytes()
        self._setup_seconds: float | None = None
        self._write_sidecar()

    # ── Stage transitions ────────────────────────────────────────────────

    def complete_setup(
        self,
        *,
        storage_provenance: dict[str, Any],
        training_workload: ResolvedPhaseWorkload | None = None,
        detail: dict[str, Any] | None = None,
    ) -> float:
        """Close the setup window and record the setup component.

        Called when the phase preparation is fully materialized (dataset
        constructed, DataLoader ready, model/optimizer on device) — the
        boundary where steady-state production work begins. The setup
        component's prediction IS its measurement (the in-subprocess
        preamble makes this the actual formal setup — §2.2), so
        prediction error is zero by construction; the value of the
        record is the measured magnitude plus provenance.

        Args:
            storage_provenance: ``capture_storage_provenance`` output for
                the files this setup read.
            training_workload:  Exact training workload materialized by
                this setup (ground truth from the constructed dataset).
            detail:             Extra setup evidence (sample counts, …).

        Returns:
            Measured setup seconds.
        """
        setup_seconds = time.perf_counter() - self._setup_start
        self._setup_seconds = setup_seconds
        io_after = read_process_read_bytes()
        bytes_read = (
            io_after - self._io_bytes_at_start
            if (io_after is not None and self._io_bytes_at_start is not None)
            else None
        )
        cache_state = classify_cache_state(bytes_read, storage_provenance.get("expected_raw_bytes"))
        self._storage = {
            **storage_provenance,
            "bytes_read_from_storage": bytes_read,
            "cache_state": cache_state,
            "rss_bytes_before_setup": self._rss_at_start,
            "rss_bytes_after_setup": read_process_rss_bytes(),
        }

        setup_ms = max(setup_seconds * 1000.0, 1e-6)
        measurement = PhaseMeasurement(
            unit="setup_pass",
            n_measured_units=1,
            n_stabilization_units=0,
            unit_time_ms_median=setup_ms,
            steady_state_reached=True,
            total_measurement_seconds=setup_seconds,
            raw_timings_ms=[setup_ms],
            detail=dict(detail or {}),
        )
        prediction = RuntimePrediction(
            predicted_seconds=max(setup_seconds, 1e-9),
            source="real_dataset_setup",
            formal_execution_eligible=True,
            steady_state=True,
            verification="passed",
            confidence="high",
            ms_per_unit=setup_ms,
            n_steady_units=1,
            unit_count=1,
            safety_factor=1.0,
        )
        setup_record = PhaseComponentRecord(
            prediction=prediction, measurement=measurement
        ).with_actual(max(setup_seconds, 1e-9))
        self._components["setup"] = setup_record

        if training_workload is not None:
            self._components["training"] = PhaseComponentRecord(workload=training_workload)

        self._final_status = "setup_complete"
        self._write_sidecar()
        return setup_seconds

    def decide_admission(self) -> AdmissionRecord:
        """RT2-B admission decision at the post-setup boundary.

        Reject exactly when the measured setup ALONE exceeds the
        operator budget (the total can only be larger — conservative
        §3 lower bound). ``complete_setup`` must have been called.

        Returns:
            The recorded :class:`AdmissionRecord`.

        Raises:
            RuntimeError: called before ``complete_setup``.
        """
        if self._setup_seconds is None:
            raise RuntimeError("decide_admission requires complete_setup to have run first.")
        budget = self.policy.operator_budget_seconds
        if budget is not None and self._setup_seconds > budget:
            self._admission = AdmissionRecord(
                decision="rejected",
                stage=ADMISSION_STAGE_POST_SETUP,
                setup_cost_seconds=self._setup_seconds,
                verification_cost_seconds=0.0,
                reason=(
                    f"measured setup {self._setup_seconds:.1f}s alone exceeds the "
                    f"operator budget {budget:.1f}s — total prediction can only be larger."
                ),
            )
            self._final_status = "rejected"
        else:
            self._admission = AdmissionRecord(
                decision="admitted",
                stage=ADMISSION_STAGE_POST_SETUP,
                setup_cost_seconds=self._setup_seconds,
                verification_cost_seconds=0.0,
                reason=(
                    "setup within budget; live training verification pending (RT2-C)"
                    if budget is not None
                    else "record-only: no operator budget in force"
                ),
            )
            self._final_status = "admitted"
        self._write_sidecar()
        return self._admission

    def record_phase_actual(self, phase: RuntimePhase, actual_seconds: float) -> None:
        """Attach a phase's ACTUAL production runtime to the observation.

        Creates the phase component if it does not exist yet; derives
        the prediction error when a prediction is present (§2.3).
        """
        existing = self._components.get(phase, PhaseComponentRecord())
        self._components[phase] = existing.with_actual(max(actual_seconds, 1e-9))
        self._write_sidecar()

    def finalize(self, final_status: str) -> RuntimeObservation:
        """Record the terminal status and write the final sidecar."""
        self._final_status = final_status
        self._write_sidecar()
        return self.observation

    # ── Observation assembly ─────────────────────────────────────────────

    @property
    def observation(self) -> RuntimeObservation:
        """The current observation state (validated on every assembly)."""
        return RuntimeObservation(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            chain_id=self._chain_id,
            attempt_id=self._attempt_id,
            hardware={
                k: self._environment.get(k) for k in ("hostname", "gpu_name", "cuda_version")
            },
            software={
                k: self._environment.get(k) for k in ("platform", "python_version", "torch_version")
            },
            runtime_policy=self.policy.model_dump(),
            storage=dict(self._storage),
            components=dict(self._components),
            admission=self._admission,
            final_status=self._final_status,
        )

    def _write_sidecar(self) -> None:
        """Atomically rewrite the sidecar with the current observation.

        Write-to-temp + ``os.replace`` so the parent never reads a torn
        JSON; failures are reported but never propagate (see class
        docstring).
        """
        try:
            payload = self.observation.model_dump(mode="json")
            tmp_path = f"{self.observation_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self.observation_path)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[runtime_control] sidecar write failed ({self.observation_path}): {exc}")
