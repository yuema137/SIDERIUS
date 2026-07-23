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
                  → verifying_<phase> → verified_<phase> | verification_failed_<phase>
                  → admitted | rejected → completed

Admission semantics (RT2-B/C): the KNOWN-COST lower bound — the sum of
every component prediction present (setup's prediction equals its
measured actual; verified phases contribute measurement-backed
predictions) — can only grow as more phases verify, so exceeding the
operator budget at any stage is a final rejection (§3). With a budget
in force a failed verification rejects (fail closed, §2.11); without
one the session is record-only and always admits. Later stages'
decisions supersede earlier ones (``AdmissionRecord.stage`` records
where the final decision was made).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.adaptive import (
    AdaptiveUnitVerification,
    AdaptiveVerificationConfig,
)
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
    PredictionSource,
    RuntimeObservation,
    RuntimePrediction,
    TotalRecord,
)
from core.runtime_control.total_assembly import (
    DEFAULT_HISTORICAL_SHARE_LIMIT,
    TotalAssessment,
    assemble_total,
)
from core.runtime_control.workload import ResolvedPhaseWorkload

ADMISSION_STAGE_POST_SETUP = "post_setup_runtime_verification"
ADMISSION_STAGE_POST_PHASE = "post_{phase}_verification"


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
    safety_factor: float = Field(
        default=1.0,
        ge=1.0,
        description=(
            "Multiplier applied to the known-cost sum at admission time "
            "(§2.10 — revised from the error ledger once RT2-F lands)."
        ),
    )
    verification: AdaptiveVerificationConfig = Field(
        default_factory=AdaptiveVerificationConfig,
        description="Adaptive stopping policy for phase verification (§2.5/§2.12/§5).",
    )
    historical_phase_share_limit: float = Field(
        default=DEFAULT_HISTORICAL_SHARE_LIMIT,
        ge=0.0,
        le=1.0,
        description=(
            "Maximum admissible Σ(historically estimated phases) ÷ total "
            "predicted runtime (RT2-E contribution-based policy). "
            "Exceeding it escalates those phases to live verification."
        ),
    )
    observation_store_root: str | None = Field(
        default=None,
        description=(
            "Root of the run's append-only observation store (RT2-F). "
            "When set, verifiers consume historical priors from it "
            "(§2.5 prior comparison) — never as a verification "
            "substitute, only for early-exit/drift classification."
        ),
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
        self._verification_seconds: float = 0.0
        self._verification_failures: dict[str, str] = {}
        self._calibration_context: dict[str, Any] = {}
        self._total: TotalRecord | None = None

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

    @classmethod
    def resume_or_start(
        cls,
        observation_path: str,
        policy: RuntimeControlPolicy | None = None,
        chain_id: str | None = None,
        attempt_id: str | None = None,
        resumed_status: str = "resumed",
    ) -> RuntimeVerificationSession:
        """Continue an attempt's observation from a later subprocess (RT2-D).

        The component-first observation is per ATTEMPT (§6.1): the
        training subprocess records setup + training, and the inference
        subprocess CONTINUES the same sidecar rather than opening a
        parallel one. An absent or unreadable sidecar starts fresh —
        the later phases still record their evidence (absence of the
        earlier components stays explicit).

        The setup window is NOT restarted on resume: setup belongs to
        the subprocess that materialized the dataset. This process's
        own preparation cost is the resuming phase's business (§2.6
        inference setup lives inside the inference component).
        """
        # Read BEFORE constructing: __init__ writes the initial sidecar,
        # which would clobber the previous subprocess's evidence.
        previous: RuntimeObservation | None = None
        try:
            with open(observation_path, encoding="utf-8") as f:
                previous = RuntimeObservation.model_validate(json.load(f))
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[runtime_control] resume failed ({observation_path}): {exc} — starting fresh")
        session = cls(observation_path, policy=policy, chain_id=chain_id, attempt_id=attempt_id)
        if previous is None:
            # Fresh start still carries the caller's stage label — a
            # resuming subprocess owns no setup window, so leaving
            # "setup_started" on the observation would be misleading.
            session._final_status = resumed_status
            session._write_sidecar()
            return session
        session._components = dict(previous.components)
        session._storage = dict(previous.storage)
        session._admission = previous.admission
        session._calibration_context = dict(previous.calibration_context)
        session._total = previous.total
        session._chain_id = chain_id or previous.chain_id
        session._attempt_id = attempt_id or previous.attempt_id
        setup = previous.components.get("setup")
        session._setup_seconds = setup.actual_seconds if setup is not None else None
        session._final_status = resumed_status
        session._write_sidecar()
        return session

    def set_calibration_context(self, context: dict[str, Any]) -> None:
        """Record the §6a calibration-key inputs for this attempt.

        The engine that KNOWS the facts records them (precision,
        optimizer, model family, parameter count, seg/batch size,
        runtime flags). Without a context the observation remains
        evidence but never feeds calibration (RT2-F).
        """
        self._calibration_context = dict(context)
        self._write_sidecar()

    def record_phase_workload(self, phase: RuntimePhase, workload: ResolvedPhaseWorkload) -> None:
        """Record a phase's resolved production workload (§1.2).

        Overwrites any earlier workload for the phase (the later, more
        materialized resolution wins); other component fields survive.
        """
        existing = self._components.get(phase, PhaseComponentRecord())
        self._components[phase] = existing.model_copy(update={"workload": workload})
        self._write_sidecar()

    def lookup_phase_prior(self, phase: RuntimePhase) -> float | None:
        """Historical unit-time prior for ``phase`` from the store (RT2-G).

        Uses the observation's own calibration context + current
        environment; only a ``valid`` lookup yields a prior (stale/
        drift-evicted/mismatched → ``None`` → ``new_configuration``,
        §6b). Best-effort: store problems never affect execution.
        """
        root = self.policy.observation_store_root
        if not root or not self._calibration_context:
            return None
        try:
            from core.runtime_control.observation_store import (
                ObservationStore,
                observation_calibration_key,
            )

            key = observation_calibration_key(self.observation, phase)
            if key is None:
                return None
            lookup = ObservationStore(root).lookup_prior(
                key,
                phase,
                current_gpu_name=self._environment.get("gpu_name"),
                current_torch_version=self._environment.get("torch_version"),
            )
            if lookup.status == "valid":
                return lookup.prior_unit_ms
            return None
        except Exception as exc:
            print(f"[runtime_control] prior lookup failed (non-fatal): {exc}")
            return None

    def start_phase_verification(
        self,
        phase: RuntimePhase,
        unit: str,
        prior_expected_unit_ms: float | None = None,
    ) -> AdaptiveUnitVerification:
        """Begin adaptive verification of one phase (RT2-C, §2.5).

        Returns the incremental driver the production loop feeds unit
        timings into. The stopping policy comes from
        ``policy.verification``; the historical prior arrives with the
        RT2-F store (``None`` → ``new_configuration``).
        """
        self._final_status = f"verifying_{phase}"
        self._write_sidecar()
        return AdaptiveUnitVerification(
            unit=unit,
            config=self.policy.verification,
            prior_expected_unit_ms=prior_expected_unit_ms,
        )

    def complete_phase_verification(
        self,
        phase: RuntimePhase,
        verifier: AdaptiveUnitVerification,
        *,
        source: PredictionSource,
        extra_predicted_seconds: float = 0.0,
        extra_detail: dict[str, Any] | None = None,
    ) -> RuntimePrediction | None:
        """Record a phase verification's evidence and prediction.

        The measurement is recorded REGARDLESS of outcome (§6.2 event
        log); the prediction exists only when the verification VERIFIED
        (§2.11 fail closed — a failed verification never yields a
        formal-eligible prediction). Verification cost accrues into the
        §2.1 admission cost model.

        Raises:
            RuntimeError: the phase has no recorded workload (the
                trainer must record it at ``complete_setup``) while the
                verifier verified — a prediction cannot be assembled.
        """
        if not verifier.is_terminal:
            verifier.finalize()
        self._verification_seconds += verifier.verification_seconds

        existing = self._components.get(phase, PhaseComponentRecord())
        prediction: RuntimePrediction | None = None
        if verifier.state == "verified":
            if existing.workload is None:
                raise RuntimeError(
                    f"phase {phase!r} verified but has no recorded workload — "
                    "record it at complete_setup before verification."
                )
            prediction = verifier.prediction(
                existing.workload,
                source,
                safety_factor=self.policy.safety_factor,
                extra_predicted_seconds=extra_predicted_seconds,
                extra_detail=extra_detail,
            )
        else:
            self._verification_failures[str(phase)] = (
                verifier.failure_reason or f"verification ended in state {verifier.state}"
            )

        self._components[phase] = PhaseComponentRecord(
            workload=existing.workload,
            prediction=prediction,
            measurement=verifier.measurement(),
            actual_seconds=existing.actual_seconds,
            prediction_error=None,
        )
        self._final_status = (
            f"verified_{phase}" if prediction is not None else f"verification_failed_{phase}"
        )
        self._write_sidecar()
        return prediction

    def decide_admission(self, stage: str = ADMISSION_STAGE_POST_SETUP) -> AdmissionRecord:
        """Admission decision from the evidence available at ``stage``.

        Conservative §3 lower-bound rule: the KNOWN-COST sum (every
        component prediction present — setup's prediction equals its
        measured actual) can only grow as more phases verify, so
        exceeding the budget at any stage is final. With a budget in
        force, a failed verification rejects (fail closed §2.11);
        without one the session is record-only and always admits. The
        LATEST decision is the authoritative one (stage records where
        it was made).

        Raises:
            RuntimeError: called before ``complete_setup``.
        """
        if self._setup_seconds is None:
            raise RuntimeError("decide_admission requires complete_setup to have run first.")
        budget = self.policy.operator_budget_seconds
        safety = self.policy.safety_factor
        known_cost = sum(
            c.prediction.predicted_seconds
            for c in self._components.values()
            if c.prediction is not None
        )
        adjusted = known_cost * safety
        cost_fields = {
            "setup_cost_seconds": self._setup_seconds,
            "verification_cost_seconds": self._verification_seconds,
        }

        if budget is None:
            self._admission = AdmissionRecord(
                decision="admitted",
                stage=stage,
                reason=(
                    "record-only: no operator budget in force"
                    + (
                        f" (verification failures recorded: {sorted(self._verification_failures)})"
                        if self._verification_failures
                        else ""
                    )
                ),
                **cost_fields,
            )
            self._final_status = "admitted"
        elif self._verification_failures:
            failures = "; ".join(
                f"{phase}: {reason}"
                for phase, reason in sorted(self._verification_failures.items())
            )
            self._admission = AdmissionRecord(
                decision="rejected",
                stage=stage,
                avoided_predicted_runtime_seconds=adjusted,
                reason=f"verification failed — fail closed for formal (§2.11): {failures}",
                **cost_fields,
            )
            self._final_status = "rejected"
        elif adjusted > budget:
            self._admission = AdmissionRecord(
                decision="rejected",
                stage=stage,
                avoided_predicted_runtime_seconds=adjusted,
                reason=(
                    f"known-cost lower bound {known_cost:.1f}s (safety x{safety:g} -> "
                    f"{adjusted:.1f}s) exceeds the operator budget {budget:.1f}s — "
                    "the full total can only be larger."
                ),
                **cost_fields,
            )
            self._final_status = "rejected"
        else:
            self._admission = AdmissionRecord(
                decision="admitted",
                stage=stage,
                reason=(
                    f"known-cost lower bound {known_cost:.1f}s (safety x{safety:g} -> "
                    f"{adjusted:.1f}s) within budget {budget:.1f}s; unverified phases "
                    "remain pending"
                ),
                **cost_fields,
            )
            self._final_status = "admitted"
        self._write_sidecar()
        return self._admission

    def assess_total(self, required_phases: tuple[RuntimePhase, ...]) -> TotalAssessment:
        """Assemble the derived total under the contribution policy (RT2-E).

        The assessment's ``TotalRecord`` is stored on the observation.
        Every prediction-bearing component must be in
        ``required_phases`` — the derived total must account for every
        prediction the observation carries (§6.1 exact-sum invariant).

        Raises:
            ValueError: a prediction-bearing phase is missing from
                ``required_phases``.
        """
        predicted_phases = {p for p, c in self._components.items() if c.prediction is not None}
        unaccounted = predicted_phases - set(required_phases)
        if unaccounted:
            raise ValueError(
                f"phases with predictions not in required_phases: {sorted(unaccounted)} — "
                "the derived total must account for every recorded prediction (§6.1)."
            )
        assessment = assemble_total(
            self._components,
            required_phases=required_phases,
            historical_phase_share_limit=self.policy.historical_phase_share_limit,
            safety_factor=self.policy.safety_factor,
            operator_budget_seconds=self.policy.operator_budget_seconds,
        )
        self._total = assessment.total
        self._write_sidecar()
        return assessment

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
            calibration_context=dict(self._calibration_context),
            components=dict(self._components),
            total=self._total,
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
