"""Tuner RUNTIME integration — coordination of the runtime-control surfaces.

Step 07 PR 07b, C7 (operator scope amendment): moved VERBATIM out of
``ml_hyperparameter_tune_agent.py``. Zero behaviour change.

What belongs here: the tuner's side of VRAM and wall-time preflight, probe
requests, pre-phase GPU measurement, admission and runtime policy construction,
step guardrails, epoch bounds, watchdog and evidence-channel failures, and the
runtime observations / calibration a run emits.

This module COORDINATES ``core.runtime_control`` and the preflight skills; it
owns none of their science. Estimator formulas, admission arithmetic and
calibration rules stay where they are — duplicating them here would create a
second authority for numbers that already have one.
"""

import importlib
import os
import time
from enum import StrEnum
from importlib import import_module as _import_module
from pathlib import Path
from typing import Any

from agent.skills.evaluate_vram_skill.probe_budgets import InconclusivePreflight
from core.sandbox_executor import TidmadSandbox
from nodes.ml_hyperparameter_tune_agent.policy import _latest_trial_inference_marginal
from nodes.ml_hyperparameter_tune_agent.records import (
    RESOURCE_ADMISSION_STATUS,
    _build_resource_admission_record,
)

# --- node-local, one-way (Step 07 PR 07b, C7) --------------------------------
# runtime -> records and runtime -> policy ONLY. Neither imports back: a runtime
# handler may BUILD and EMIT a refusal record, but a record builder never reaches
# into runtime. That direction is what keeps the graph acyclic — the first cut
# put the emit seam on the records side and produced a genuine cycle.
# `_emit_record` is the node's ONE record-emission point, called from four
# modules. Same reasoning as `_runtime._run_skill`: resolve it through its
# owner so the node has a single binding, and a stub installed on that owner
# intercepts every emission rather than whichever module it was aimed at.
_records = _import_module("nodes.ml_hyperparameter_tune_agent.records")


class PrephaseOutcome(StrEnum):
    """What `run()` must do after the formal pre-phase measurement.

    A `bool` carried two incompatible meanings — "the candidate does not
    fit" and "we could not measure at all" — and the caller treated both
    as an ordinary attempt failure. V20 attempt 2 therefore retried a
    DETERMINISTIC infrastructure condition 15 times, consuming
    `attempts_per_round` and the failure counters while the GPU was idle.

    Splitting them is the point: a resource refusal is a fact about this
    attempt and the next attempt may differ; an infrastructure failure is
    a fact about the environment and retrying it changes nothing.
    """

    PROCEED = "proceed"
    #: Measured, and the environment genuinely cannot hold this candidate.
    #: Consumes the attempt — a smaller candidate may still fit.
    TERMINAL_RESOURCE_REFUSAL = "terminal_resource_refusal"
    #: The measurement itself could not be established. Must NOT consume a
    #: scientific attempt, and must NOT be retried in place — that is how
    #: "don't count it" becomes an infinite loop.
    TERMINAL_INFRASTRUCTURE_FAILURE = "terminal_infrastructure_failure"


def _vram_skip_memory_extra(resource_check: dict, chosen_vram_budget: float | None) -> dict:
    """Optional memory fields on a `skipped_oom_risk` record (B-C4a0 E2).

    Phase K — surface the same two VRAM fields the success record
    carries, so the planner sees the same shape regardless of pass/fail.
    Omitted when the gate is disabled (`chosen_vram_budget is None`),
    mirroring §J.3 for time. Mode is inferred from `time_mode` on records
    where the time gate also ran — there is no separate `vram_mode`.
    See docs/resource_estimator_implement.md §10.4 / §10.8.

    K.2.5-8 — the soft-fallback flag is independent of the budget being
    set: the gate runs unconditionally, and the flag says whether the
    inference estimate was against a registered batch. Recorded on every
    `skipped_oom_risk` so post-hoc analysis can discount rejections that
    came from an uncalibrated estimate.
    """
    extra: dict[str, Any] = {}
    if chosen_vram_budget is not None:
        extra["vram_estimate_gb"] = resource_check.get("estimated_gb")
        extra["vram_budget_gb"] = resource_check.get("limit_gb")
    if resource_check.get("inference_batch_uncalibrated"):
        extra["inference_batch_uncalibrated"] = True
    return extra


def _time_skip_memory_extra(time_check: dict, plan) -> dict:
    """Optional memory fields on a `skipped_time_risk` record (B-C4a0 E2).

    Phase J — the same three fields the success record carries, so the
    planner sees the same shape regardless of pass/fail (§J.3).

    refine_inference_time_estimator.md Commit D — `inference_ms_source`
    is surfaced on skipped records too, so a verdict produced under the
    measured path is distinguishable from one produced under the legacy
    x2.7 ratio.

    K.2.5-8 — both gates call the same inference estimator and carry the
    same soft-fallback flag; the time wrapper's is the natural source.
    """
    extra: dict[str, Any] = {
        "time_estimate_minutes": time_check.get("estimated_minutes"),
        "time_budget_minutes": time_check.get("limit_minutes"),
        "time_mode": "trial" if plan.is_trial else "formal",
        "inference_ms_source": (time_check.get("breakdown") or {}).get("inference_ms_source"),
    }
    if time_check.get("inference_batch_uncalibrated"):
        extra["inference_batch_uncalibrated"] = True
    return extra


def _handle_admission_refusal(
    status: dict,
    *,
    phase: str,
    sandbox,
    exp_id: str,
    model_type: str,
    file_index: Any,
    record_params: dict,
    expert_advice_str: str,
    hypothesis: str,
    round_index: int,
    attempt_in_round: int,
    candidate_id: str | None = None,
    experiment_arm: str | None = None,
) -> bool:
    """Record a phase the environment refused to start (B-C4c).

    Returns True when the caller must skip the rest of this attempt.

    The refusal is an infrastructure condition. It consumes the attempt
    slot — planning, pre-flight and admission really ran — but it is not
    a candidate failure, produces no negative planner evidence, updates
    no incumbent, and triggers no retry. Those five properties are
    separable, and collapsing any of them is how an environment problem
    becomes a scientific conclusion about a model.

    Every admission refusal goes through `_build_resource_admission_record`
    so the wording and the accounting exist in one place; a
    hand-assembled equivalent elsewhere would drift.
    """
    if status.get("status") != RESOURCE_ADMISSION_STATUS:
        return False
    admission = status.get("admission") or {}
    record = _build_resource_admission_record(
        resource_type="gpu_memory",
        reason_code=admission.get("reason_code") or "policy_unavailable",
        detail=str(status.get("message") or "the environment refused the phase"),
        exp_id=exp_id,
        model_type=model_type,
        file_index=file_index,
        record_params=record_params,
        expert_advice_str=expert_advice_str,
        hypothesis=hypothesis,
        round_index=round_index,
        attempt_in_round=attempt_in_round,
        admission_evidence=admission,
    )
    _records._emit_record(sandbox, record, candidate_id=candidate_id, experiment_arm=experiment_arm)
    print(
        f"  Saved admission refusal ({phase}): {record['status']} "
        f"[{record['memory']['reason_code']}]"
    )
    return True


#: Wall-clock bound for one pre-phase GPU measurement (V20 PR C2 / C2-7).
#: Setup plus four training steps on a bounded batch; PR A's isolated
#: pre-flight allows 900 s for a heavier structural trace, so this sits well
#: inside a comparable envelope. The ONE place to change it.
PREPHASE_MEASUREMENT_DEADLINE_SECONDS = 600.0
#: The worker stops itself here so it can report partial evidence; the
#: parent's kill is the hard bound (D-C2-3).
PREPHASE_MEASUREMENT_SOFT_BUDGET_SECONDS = 480.0
#: Disposition -> the refusal lane the record is filed under. PR B's three
#: lanes are unchanged; the disposition itself is preserved in the evidence,
#: so nothing is lost by the narrowing.
_PREPHASE_REASON_CODE = {
    "STOP_OVER_CAP": "insufficient_headroom",
    "STOP_MEASURED_OOM": "insufficient_headroom",
    "STOP_MEASUREMENT_UNAVAILABLE": "measurement_unavailable",
    "STOP_TIMEOUT": "measurement_unavailable",
    "STOP_PROBE_HOST_MEMORY_EXCEEDED": "measurement_unavailable",
    "STOP_INFRASTRUCTURE_FAILURE": "measurement_unavailable",
}


def _handle_prephase_gpu_measurement(
    *,
    agent_input,
    sandbox,
    is_trial: bool,
    active_params: dict,
    exp_id: str,
    model_type: str,
    file_index: Any,
    record_params: dict,
    expert_advice_str: str,
    hypothesis: str,
    round_index: int,
    attempt_in_round: int,
    run_profile: Any = None,
    run_model_io: Any = None,
) -> PrephaseOutcome:
    """Measure this candidate on this card before a formal GPU launch.

    Returns the disposition `run()` must act on (O-7).

    **This function delegates; it does not decide.** Identity comparison,
    classification, authority validation and PR B admission all live in
    `core.runtime_control.prephase_admission`, which returns ONE
    disposition. `run()` is the giant orchestrator the decomposition rule
    governs, and reimplementing any of that here would put O-7's accounting
    in the one scope where it is hardest to see.

    **Three applicability rules, none of them a feature flag.**

    *Trial rounds are not measured.* O-7 governs formal execution, and a
    trial round's admission posture already proceeds while recording what it
    could not prove. Measuring every trial round would double the GPU cost
    of the cheap screen.

    *No device identity means nothing to measure.* This is the same rule
    `_admission_refusal` already applies -- a CPU or pseudo run has no card
    to take a driver-visible reading from, and admission has nothing to
    decide. Unchanged behaviour there, not a refusal.

    *A task declaring no TIDMAD topology has no batch this probe can build.*
    Step 12 / PR-12d, **B12 / F-12d-25**, operator-ruled 2026-08-24
    (option B). The worker's batch builder
    (`probe_batch.build_bounded_probe_batch`) has a TIDMAD-SPECIFIC INPUT
    CONTRACT -- `abra_training_????.h5`, `tidmad_topology(...).channels`,
    h5py group layout -- and deliberately refuses synthetic data (F-1a).
    Pets and DAVIS have no semantically valid input to that legacy probe, so
    applicability must REFUSE TO RUN IT rather than fabricate a TIDMAD input;
    reporting `STOP_INFRASTRUCTURE_FAILURE` (what happened before this rule)
    claimed the ENVIRONMENT was broken when it was healthy. This is the same
    correction Step 08a made when it introduced `CheckVerdict.inapplicable`
    instead of "passed=True with prose", and applicability is decided HERE,
    before the worker is spawned, so an inapplicable measurement opens no
    artifact.

    **This rule is a MEMBERSHIP TEST, never a caught exception, and the
    distinction is load-bearing.** `declares_tidmad_topology` asks whether
    the sections are PRESENT. `tidmad_topology()` raises for TWO different
    reasons -- absent sections, and sections present but MALFORMED -- so
    inferring "this task declares none" from catching its `ValueError` would
    silently reclassify a malformed TIDMAD profile as inapplicable and skip a
    measurement that must instead FAIL. A malformed TIDMAD topology therefore
    still returns `True` here, still spawns the worker, and still fails
    closed. (12bc's row-2-vs-row-4 rule, one subsystem over; the predicate's
    own docstring states it.)

    **What this rule does NOT do**: it does not suppress a failing APPLICABLE
    probe (a TIDMAD run whose data is present but whose probe crashes still
    reaches `TERMINAL_INFRASTRUCTURE_FAILURE`), and it does not touch any
    resource enforcement that is independent of this measurement -- the
    `evaluate_vram_skill` capacity gate still runs for every task and still
    governs admission. Downstream, a measurement that never happened is an
    ALREADY-SUPPORTED state, not a new one: `sandbox_executor.py:552-565`
    returns `(None, None)` when no requirement table was attached.

    **Option A -- making bounded probe-batch construction fully
    task-composable so arbitrary topologies can be measured -- is recorded as
    explicit post-Step-12 debt and is deliberately NOT absorbed here.**
    """
    if is_trial:
        return PrephaseOutcome.PROCEED

    # TYPE-checked, not merely present. `getattr(sandbox, "device_identity",
    # None)` on a `MagicMock` returns a truthy mock, so a presence test
    # silently activates this gate in every mocked test — and, worse, would
    # accept any object at all as a device in production. A measurement
    # needs a real `DeviceIdentity`; anything else is "no device to decide
    # about", which is the same conclusion `_admission_refusal` reaches.
    from core.runtime_control.gpu_accounting import DeviceIdentity

    device_identity = getattr(sandbox, "device_identity", None)
    if not isinstance(device_identity, DeviceIdentity):
        return PrephaseOutcome.PROCEED

    # B12 / F-12d-25. `run_profile is None` is Regime A — an un-composed run,
    # which IS TIDMAD — so it stays applicable and TIDMAD's behaviour is
    # bit-for-bit what it was. Only a COMPOSED profile that declares no
    # TIDMAD topology reaches the inapplicable path.
    from execute_tools.dataset_config import DatasetProfile, declares_tidmad_topology

    if isinstance(run_profile, DatasetProfile) and not declares_tidmad_topology(run_profile):
        print(
            "  Pre-phase GPU measurement NOT APPLICABLE: this task declares no "
            "TIDMAD topology, and the bounded probe batch is TIDMAD-physical "
            "(h5 training family / declared input channel). No measured "
            "requirement is attached for this run; the VRAM capacity gate is "
            "unaffected. This is an applicability decision, not a probe failure."
        )
        return PrephaseOutcome.PROCEED

    import uuid as _uuid

    from core.runtime_control.gpu_measurement_identity import (
        build_planned_identity,
        resolve_inference_batch,
    )
    from core.runtime_control.gpu_measurement_runner import run_prephase_measurement
    from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
    from core.runtime_control.gpu_requirement import CandidateMeasurementRequest
    from core.runtime_control.prephase_admission import (
        attach_measured_requirements,
        decide_prephase_admission,
    )

    model_config = dict(active_params.get("model_config") or {})
    train_config = dict(active_params.get("train_config") or {})
    ceiling_gib = getattr(agent_input, "gpu_pair_ceiling_gib", None)
    workspace = Path(sandbox.base_dir) / "prephase_measurement"
    request_id = _uuid.uuid4().hex
    # V21 PR G G3 — resolved exactly as `execute_inference` resolves it:
    # the current attempt's probe-derived batch when the preflight produced
    # one (already captured into active_params at :4696, before this site
    # runs — 0.R.5 ordering), else the registry table. The recorded
    # planned-identity payload now states the batch production would
    # really run instead of a table value runtime would override.
    _inference_batch = resolve_inference_batch(
        model_type, explicit=active_params.get("inference_batch")
    )

    spec = GpuMeasurementSpec(
        label=f"{exp_id}:training",
        request=CandidateMeasurementRequest(
            model_type=model_type,
            planned_identity=build_planned_identity(
                model_type=model_type,
                model_config=model_config,
                train_config=train_config,
                inference_batch_size=_inference_batch,
            ),
            request_id=request_id,
            device_uuid=str(getattr(device_identity, "uuid", "")),
            phase="training",
            deadline_seconds=PREPHASE_MEASUREMENT_DEADLINE_SECONDS,
        ),
        model_config_payload=model_config,
        train_config=train_config,
        loss_config=dict(active_params.get("loss_config") or {}),
        inference_batch_size=_inference_batch,
        data_dir=getattr(agent_input, "data_dir", None),
        # 07c C2. The worker is a clean subprocess, so the run-bound profile
        # has to be transported or the batch's data facts silently revert to
        # the shipped TIDMAD declaration. The tuner already holds the object
        # (`RunBindings.run_profile`); nothing is resolved here.
        dataset_profile=run_profile,
        # 07c C3. Same reason, for the dtype authority's input. A task that
        # declares no `model_io` passes `None`, which is Regime-A parity.
        model_io_contract=run_model_io,
        # The worker is a clean process and must rebuild the plugin
        # registry from these. Read from the SAME sandbox the training and
        # inference subprocesses use, so the candidate the worker measures
        # is loaded from the candidate the trainer will run.
        plugin_dir=getattr(sandbox, "plugin_dir", None),
        loss_dir=getattr(sandbox, "loss_dir", None),
        result_path=str(workspace / f"{exp_id}_training.json"),
        journal_path=str(workspace / f"{exp_id}_training.phases.ndjson"),
        sampler_ready_path=str(workspace / f"{exp_id}_training.sampler_ready"),
        phase_complete_path=str(workspace / f"{exp_id}_training.phase_complete"),
        worker_memory_limit_bytes=_prephase_worker_memory_limit_bytes(),
        soft_deadline_seconds=PREPHASE_MEASUREMENT_SOFT_BUDGET_SECONDS,
    )

    run = run_prephase_measurement(spec, device=device_identity)
    snapshot, sampling_error = _prephase_device_snapshot(device_identity)
    outcome = decide_prephase_admission(
        run,
        snapshot=snapshot,
        mode="formal",
        vram_cap_mib=int(ceiling_gib * 1024) if ceiling_gib else None,
        ceiling_gib=ceiling_gib,
        run_name=str(active_params.get("run_name") or exp_id),
        sampling_error=sampling_error,
    )

    if outcome.proceeds:
        attach_measured_requirements(sandbox, outcome)
        print(
            f"  Pre-phase GPU measurement: "
            f"{outcome.requirement.driver_tree_peak_mib} MiB (training), admitted"
        )
        return PrephaseOutcome.PROCEED

    record = _build_resource_admission_record(
        resource_type="gpu_memory",
        reason_code=_PREPHASE_REASON_CODE.get(outcome.disposition, "measurement_unavailable"),
        detail=f"pre-phase GPU measurement: {outcome.disposition} — {outcome.detail}",
        exp_id=exp_id,
        model_type=model_type,
        file_index=file_index,
        record_params=record_params,
        expert_advice_str=expert_advice_str,
        hypothesis=hypothesis,
        round_index=round_index,
        attempt_in_round=attempt_in_round,
        admission_evidence={
            "prephase_disposition": outcome.disposition,
            "measurement_outcome": outcome.requirement.outcome,
            "authority_refusal": outcome.requirement.authority_refusal,
            "identity_mismatch": outcome.requirement.identity_mismatch,
            "request_id": request_id,
        },
    )
    _records._emit_record(
        sandbox,
        record,
        candidate_id=agent_input.candidate_id,
        experiment_arm=agent_input.experiment_arm,
    )
    _reason = _PREPHASE_REASON_CODE.get(outcome.disposition, "measurement_unavailable")
    if _reason == "insufficient_headroom":
        print(f"  Pre-phase GPU measurement stopped the attempt: {outcome.disposition}")
        return PrephaseOutcome.TERMINAL_RESOURCE_REFUSAL
    print(
        f"  Pre-phase GPU MEASUREMENT FAILED ({outcome.disposition}) — the "
        f"environment could not measure this candidate, so no admission "
        f"decision was possible. This is infrastructure, not capacity; the "
        f"round is ended rather than retried."
    )
    return PrephaseOutcome.TERMINAL_INFRASTRUCTURE_FAILURE


def _prephase_worker_memory_limit_bytes() -> int:
    """Reuse PR A's host-memory ceiling rather than choosing a second one.

    The two workers construct the same candidates, so a pathological host
    footprint is pathological for both, and two independent ceilings would
    disagree about what "pathological" means.
    """
    from agent.skills.evaluate_vram_skill.isolated_probe import (
        default_worker_memory_limit_bytes,
    )

    return default_worker_memory_limit_bytes()


def _prephase_device_snapshot(device_identity) -> tuple[Any, str | None]:
    """The pre-spawn occupancy PR B admits against, or a named gap.

    Never raises: a sampler that failed must reach the admission policy as
    "no reading was obtained" rather than as an exception the caller
    swallows into a proceed, which is the fail-open posture PR B removed.
    """
    try:
        from core.runtime_control.gpu_accounting import sample

        return sample(os.getpid(), device_identity), None
    except Exception as exc:  # pragma: no cover - driver-shape guard
        return None, f"{type(exc).__name__}: {exc}"


#: What the tuner DOES about each status the pre-flight adapter can emit.
#:
#: There is deliberately no default. Before this table, the only capacity
#: guard was ``resource_check.get("feasible", True)`` -- and the adapter
#: omits ``feasible`` entirely for any outcome whose legacy pair carries
#: ``None`` (``preflight_adapter.py:176``). So ``timeout``,
#: ``host_memory_allocation_failure`` and ``measured_host_memory_exceeded``
#: all fell through that ``True`` default and the tuner LAUNCHED TRAINING
#: after a pre-flight that had just been RSS-killed. Every layer was
#: individually correct and individually tested; the conclusion reached no
#: consumer.
#:
#: "No conclusion" must never resolve to "safe to run".
PREFLIGHT_CONSUMER_ACTIONS: dict[str, str] = {
    # The probe measured a footprint; `feasible` then decides.
    "success": "capacity_verdict",
    # Our machinery broke. Not a statement about the candidate.
    "error": "infrastructure_error",
    # The plugin's own config class rejected the config.
    "schema_violation": "schema_violation",
    # Measured nothing usable. Blocks the attempt, blames nobody.
    "inconclusive": "blocked_unmeasured",
    "timeout": "blocked_unmeasured",
    "host_memory": "blocked_unmeasured",
}
#: Which `InconclusivePreflight.kind` each blocking status carries. They
#: block identically but are different facts (see the exception docstring).
_BLOCKED_KIND_FOR_STATUS: dict[str, str] = {
    "inconclusive": "inconclusive",
    "timeout": "timeout",
    "host_memory": "host_memory",
}


def _raise_if_preflight_blocks(resource_check: dict) -> str:
    """Resolve the pre-flight status to a consumer action, or raise.

    Returns the action for the statuses `run()` handles inline
    (``capacity_verdict`` / ``infrastructure_error`` / ``schema_violation``)
    and raises for every status that must stop the attempt here.

    An UNKNOWN status raises rather than proceeding. A new
    ``PreflightOutcome`` whose legacy status nobody wired up is a wiring
    bug, and the failure mode this function exists to remove is exactly
    the one where such a status silently means "go ahead".
    """
    status = str(resource_check.get("status", ""))
    action = PREFLIGHT_CONSUMER_ACTIONS.get(status)
    if action is None:
        raise RuntimeError(
            f"pre-flight returned status {status!r}, which no consumer branch "
            f"handles. Known: {sorted(PREFLIGHT_CONSUMER_ACTIONS)}. Refusing to "
            "proceed -- an unhandled pre-flight status must never be read as "
            "permission to start training."
        )
    if action != "blocked_unmeasured":
        return action

    kind = _BLOCKED_KIND_FOR_STATUS[status]
    print(
        f"    [VRAM] pre-flight produced no usable footprint ({kind}) — "
        "recorded as an inspection gap, NOT as evidence about this model."
    )
    raise InconclusivePreflight(
        str(resource_check.get("message", "")),
        record=resource_check.get("timeout_record") or {},
        kind=kind,
    )


def _raise_if_inconclusive(resource_check: dict) -> None:
    """Turn an INCONCLUSIVE pre-flight into its own typed failure.

    An inconclusive pre-flight measured nothing. Treating it as a resource
    rejection is what invalidated the V19 campaign stopped on 2026-07-31:
    a batch-search timeout became "model too large", and the agent
    downsized until it was proposing toy models. The attempt still cannot
    proceed without a footprint, but it is recorded as an inspection gap
    and MUST NOT enter capacity feedback.

    Module-level rather than inline: `run()` already sits at pyright's
    complexity-analysis ceiling, and adding this branch inline pushed it
    over.
    """
    if resource_check.get("status") != "inconclusive":
        return
    print(
        "    [VRAM] INCONCLUSIVE pre-flight — recorded as an inspection gap, "
        "NOT as evidence about this model."
    )
    raise InconclusivePreflight(
        str(resource_check.get("message", "")),
        record=resource_check.get("timeout_record") or {},
    )


def _classify_attempt_failure(exc: BaseException, failure_stage: str | None) -> str:
    """Name what went wrong, keeping "we could not measure" separate from
    "the model misbehaved".

    `inconclusive_preflight` exists because the alternative — classifying a
    pre-flight timeout as `model_forward_error` — is what invalidated the
    V19 campaign stopped on 2026-07-31. Downstream feedback keys off this
    name, so conflating the two teaches the agent that its model is at
    fault when the measurement simply never finished.

    Module-level rather than inline: the caller's `try` already sits at
    pyright's complexity-analysis ceiling.
    """
    if isinstance(exc, InconclusivePreflight):
        # Kind-specific so a host-memory kill is never read back as a
        # measurement timeout, or either as "the probe told us nothing".
        return f"{getattr(exc, 'kind', 'inconclusive')}_preflight"
    if isinstance(exc, WallClockTimeoutError):
        return "wall_clock_timeout"  # §4 status-audit decision (RT4)
    if failure_stage == "vram_structural_probe" and isinstance(exc, RuntimeError):
        return "model_forward_error"
    return type(exc).__name__


def _runtime_phase_for(is_trial: bool) -> str:
    """C8c: the phase the shared runtime policy decides under.

    A module-level helper rather than an inline conditional because
    ``run()`` sits at pyright's strict-mode complexity ceiling — one more
    branch inside it makes the whole method unanalyzable.

    No bounded live probe feeds the tuner pre-flight: the authoritative
    formal measurement is the RT2 in-subprocess verification, so a formal
    prior-tier projection resolves to REQUEST_PROBE (proceed into that
    measurement) rather than being priced from a prior.
    """
    return "trial" if is_trial else "formal"


def _run_time_preflight(
    *,
    sandbox,
    active_params: dict,
    time_budget_minutes: float,
    data_dir: str | None,
    memory_history: list,
    is_trial: bool,
    dataset_profile,
) -> dict:
    """Invoke the wall-time pre-flight gate for one attempt.

    Extracted from ``run()`` (C8g): that method sits at pyright's
    strict-mode complexity ceiling, and this block carried three inline
    conditionals plus an eight-argument call. Behavior is unchanged —
    the same skill, the same arguments, the same log line.

    ``inference_per_psd_seg_ms_hint`` is the most recent successful trial
    round's measured per-PSD-segment inference cost; the wrapper prefers
    it over the legacy x2.7 ratio when present and > 0.
    ``allow_store_reuse`` is trial-only (RT3 §3): a formal round's
    authority is the in-subprocess verification, never a stored prior.
    """
    inference_hint = _latest_trial_inference_marginal(memory_history)
    hint_text = f"{inference_hint:.2f} ms/psd_seg" if inference_hint else "none"
    mode = _runtime_phase_for(is_trial)
    print(
        f"\n[Pre-flight 2/2] Time check (mode={mode}, "
        f"budget={time_budget_minutes} min, inf_hint={hint_text})..."
    )
    return _run_skill(
        "evaluate_time_skill",
        sandbox,
        **active_params,
        time_budget_minutes=time_budget_minutes,
        data_dir=data_dir,
        inference_per_psd_seg_ms_hint=inference_hint,
        allow_store_reuse=is_trial,
        observation_store_root=os.path.join(sandbox.base_dir, "runtime_observations"),
        runtime_phase=mode,
        # Step 05b — the run's ONE topology. Every decomposition-derived
        # term in the time gate resolves from this value; the skill no
        # longer resolves one of its own.
        dataset_profile=dataset_profile,
    )


def _resolve_time_check_probe_request(
    time_check: dict,
    *,
    model_type: str,
    active_params: dict,
    time_budget_minutes: float,
    is_trial: bool,
    data_dir: str | None,
    run_name: str,
    exp_id: str,
    device_identity: Any | None = None,
    result_authority: str | None = None,
    vram_threshold_gb: float | None = None,
    measurement_capability: Any | None = None,
) -> str:
    """C9d: turn a REQUEST_PROBE pre-flight into a terminal decision.

    V21 PR B3 Stage B — ``vram_threshold_gb`` arms the frozen S3 admission
    rule for memory. It must be the EFFECTIVE threshold
    (``resource_check["limit_gb"]`` = ``min(physical usable, operator
    budget)``), never the raw operator budget, which differs exactly in
    the ``PHYSICAL VETO`` regime. ``None`` leaves the pre-B3 behaviour
    untouched. Stage A established this is the only production
    ``RuntimeBudget`` site whose estimate carries a measured
    ``peak_vram_gb``; the others would be inert.

    This is the production edge the C8 closure audit found missing. When
    the shared policy asks for a measurement, we take one:

        REQUEST_PROBE -> bounded probe -> persisted observation
                      -> rebuilt estimate -> re-run policy
                      -> ALLOW / REJECT / ABORT

    Mutates ``time_check`` in place (mirroring the bypass gate) and
    returns the action for the caller: ``"proceed"``, ``"skip"`` (the
    existing attempt-local skipped_time_risk path) or ``"abort"`` (chain
    halt). Any other pre-flight decision returns ``"proceed"`` untouched.

    When the environment cannot build a real probe runner — CPU box, no
    dataset, pseudo run — the request is recorded as a VISIBLY TYPED
    advisory rather than resolved.

    **M6 (2026-08-06): that advisory must not become a proceed for a
    production scientific formal decision.** The pre-launch audit found
    this path failing OPEN: `REQUEST_PROBE -> probe unavailable ->
    proceed using the prior`, which is exactly the "a formal decision may
    not rest on a prior" defect C8 exists to remove. The docstring
    previously claimed the launch guard prevented it — it does not:
    `run_launch_self_test(require_probe_runner=True)` has one caller,
    `core.runtime_control.bootstrap.run_bootstrap`, which the chain never
    executes.

    So the rule is now explicit, and scoped by the two facts that decide
    whether the evidence is load-bearing:

    * `result_authority == "scientific"` — this run's results may inform
      science, so an unmeasured formal decision would contaminate it;
    * `not is_trial` — a trial is the cheap screen and its admission
      posture already proceeds while recording what it could not prove.

    Both true and the probe is unavailable -> the ATTEMPT is not launched
    (`"skip"`, the existing attempt-local `skipped_time_risk` lane), with
    the reason persisted. Anything else keeps the advisory, so diagnostic
    runs, pseudo runs, CPU boxes and trials are unchanged.

    **Fail closed for this expensive execution, not for the chain.** The
    campaign continues under normal failure/skip semantics; only the
    unmeasurable attempt is refused.
    """
    breakdown = time_check.get("breakdown") or {}
    if breakdown.get("runtime_decision") != "REQUEST_PROBE":
        return "proceed"

    from core.runtime_control.calibration_policy import classify_model_family
    from core.runtime_control.decision_policy import RuntimeBudget, RuntimeMode
    from core.runtime_control.probe_lifecycle import ProbeRequest
    from core.runtime_control.probe_wiring import (
        build_production_probe_runner,
        build_registry_persist,
        probe_runner_availability,
    )
    from core.runtime_control.provenance import capture_software_stack

    capability = measurement_capability
    if capability is None:
        from core.runtime_control.measurement_capability import (
            ResolvedMeasurementCapability,
        )

        capability = ResolvedMeasurementCapability(
            task_identity="unresolved_task",
            dataset_adapter="unresolved_dataset_adapter",
            data_shape_class="unresolved_data_shape",
            probe_available=False,
            unavailability_reason="no measurement capability was supplied by the caller",
            dataset_root=data_dir,
        )
    available, detail = probe_runner_availability(capability)
    if not available:
        breakdown["probe_resolution"] = "unavailable"
        breakdown["probe_resolution_detail"] = detail
        # The reason is recorded, never a bare False: an unavailable
        # measurement path that does not say why is what let the V19 posture
        # persist unnoticed.
        breakdown["probe_capability_task"] = capability.task_identity
        breakdown["probe_capability_reason"] = capability.unavailability_reason
        # M6. A production scientific formal decision may not rest on a
        # prior. The three keys below are what resume and diagnostics read
        # to tell this apart from a resource rejection, a HealthGate
        # invalidity and a scientific failure.
        if result_authority == "scientific" and not is_trial:
            breakdown["probe_resolution_enforced"] = True
            breakdown["measurement_evidence"] = "not_established"
            breakdown["admission"] = "not_admitted"
            time_check["feasible"] = False
            time_check["verdict"] = (
                "❌ NOT ADMITTED — a formal scientific decision requires a bounded "
                f"probe and none could be resolved in this environment ({detail}). "
                "The prior is not evidence about this candidate."
            )
            time_check["suggestion"] = (
                "Restore the measurement capability (CUDA + the task dataset) and "
                "re-run. This is an infrastructure condition; it says nothing about "
                "the candidate."
            )
            print(
                f"  [PROBE] REQUEST_PROBE could not be resolved ({detail}). "
                f"Formal scientific attempt NOT ADMITTED — refusing to decide "
                f"from the prior."
            )
            return "skip"
        breakdown["probe_resolution_enforced"] = False
        print(
            f"  [PROBE] REQUEST_PROBE could not be resolved by measurement in this "
            f"environment ({detail}). Recorded as advisory — this is NOT a measured "
            f"production decision."
        )
        return "proceed"

    # V20 PR C1 / C-C1. `model_family` was omitted here, so it took
    # `ProbeRequest`'s "unknown" default and reached the calibration bucket
    # key as component 6 -- every probe-produced record on this machine
    # buckets under family=unknown, which is one bucket, not separation.
    # `model_type` was already in scope; it simply was not passed.
    #
    # `classify_model_family` treats a non-empty declared family as
    # authoritative, and the time skill already keys its own store on
    # `model_family=model_type` (evaluate_time_skill/wrapper.py). Declaring
    # it here makes the registry agree with the store instead of writing a
    # second family namespace.
    #
    # C12-P / B11. `workload` is PROVENANCE — what the probe actually ran at.
    # `.get("segmentation_size", 0)` recorded `0` for an omitted key while
    # `production_probe_executors` built the very same dict with
    # `config_cls(**model_config)`, i.e. at the config class's DECLARED default
    # (wavenet 40000, transformer 20000). D4 buckets and C7 applicability
    # ranges are keyed on this field, so a recorded `0` drags
    # `ApplicabilityEnvelope.observed_min` to zero and
    # `applicability_for_request` then labels far smaller requests
    # "interpolation" — and `0` cannot even be read back as a sentinel,
    # because the request side declares `Field(gt=0)`.
    from agent.skills.training_skill.estimator import resolve_model_field

    request = ProbeRequest(
        model_identity=model_type,
        model_family=classify_model_family(declared_family=model_type),
        train_steps=int(breakdown.get("total_train_steps") or 0),
        inference_batches=0,
        workload={
            "batch_size": int((active_params.get("train_config") or {}).get("batch_size", 1)),
            # `safety_margin=0` is unreachable rather than chosen:
            # `production_probe_executors` raises for a model with no
            # registered config class, so no observation is ever recorded on
            # that path. It preserves the pre-existing value for the case that
            # cannot occur instead of inventing a workload number.
            "segment_length": resolve_model_field(
                model_type,
                dict(active_params.get("model_config") or {}),
                "segmentation_size",
                safety_margin=0,
            ),
        },
    )
    print(f"  [PROBE] Resolving REQUEST_PROBE with a bounded live probe of {model_type}...")
    from core.runtime_control.probe_wiring import resolve_request_probe

    resolution = resolve_request_probe(
        request=request,
        budget=RuntimeBudget(
            time_seconds=max(time_budget_minutes, 1e-9) * 60.0,
            # V21 PR B3 Stage B. The policy already grades this correctly
            # (decision_policy:285): a MEASURED peak above the threshold
            # REJECTs, a projected one is ADVISORY. It was inert only
            # because nothing supplied the budget.
            vram_gb=vram_threshold_gb if (vram_threshold_gb or 0) > 0 else None,
        ),
        mode=RuntimeMode(
            phase="trial" if is_trial else "formal",
            candidate_stage="post_implementation",
            probe_available=True,
        ),
        run_probe=build_production_probe_runner(
            model_type=model_type,
            model_config=active_params.get("model_config") or {},
            train_config=active_params.get("train_config") or {},
            loss_config=active_params.get("loss_config") or {},
            data_dir=data_dir,
            # V20 PR C. Resolved ONCE at the orchestration boundary and
            # passed down; the probe never discovers a device of its own.
            device_identity=device_identity,
        ),
        persist=build_registry_persist(
            workload=request.workload,
            # Was `{}`, which `stack_identity` hashes to one constant for
            # every record -- so the stack dimension of the bucket key, the
            # documented drift anchor, was inert. Shared helper so this and
            # the bootstrap CLI describe one stack under one identity.
            software_stack=capture_software_stack(),
            source_run={"run_name": run_name, "exp_id": exp_id},
        ),
    )
    breakdown["probe_resolution"] = resolution.decision.kind
    breakdown["probe_resolution_reasons"] = list(resolution.decision.reasons)
    breakdown["probe_observation_ids"] = list(resolution.observation_ids)
    breakdown["probe_status"] = resolution.probe_status
    if resolution.estimate is not None:
        breakdown["probe_expected_seconds"] = resolution.estimate.expected_seconds

    if resolution.decision.kind == "ABORT":
        return "abort"
    if resolution.decision.kind == "REJECT":
        time_check["feasible"] = False
        time_check["verdict"] = (
            f"❌ REJECTED by bounded live probe — {'; '.join(resolution.decision.reasons)}"
        )
        return "skip"
    return "proceed"


def is_evidence_refusal(time_check: dict) -> bool:
    """Whether an infeasible `time_check` is an EVIDENCE refusal (M6).

    The `skipped_time_risk` lane carries two causes since M6, and three
    call sites must agree about which one they are looking at:

    * the formal time-budget bypass, which may clear a time rejection and
      must NOT clear this one;
    * the skip record's conclusion, which must not blame wall-time;
    * the operator log line.

    Extracted rather than repeated inline in `run()` because that
    function already coordinates unrelated concerns, and three copies of
    a predicate is how they drift apart. A test can call this; it cannot
    call a condition buried in a 2,000-line orchestrator.

    Args:
        time_check: the pre-flight result, already known infeasible.

    Returns:
        True when the attempt was refused because a required bounded
        probe could not be resolved — an infrastructure condition that
        says nothing about the candidate.
    """
    return bool((time_check.get("breakdown") or {}).get("probe_resolution_enforced", False))


def _run_skill(skill_folder: str, sandbox: TidmadSandbox, **params) -> dict:
    """
    Dynamically loads and executes a research skill (Training, Inference, or Scoring).
    """
    module_path = f"agent.skills.{skill_folder}.wrapper"
    try:
        skill_module = importlib.import_module(module_path)
        return skill_module.run_skill(sandbox, **params)
    except Exception as e:
        print(f"Skill Error [{skill_folder}]: {e!s}")
        return {"status": "error", "message": str(e)}


def _evaluate_step_guardrails(
    *,
    n_steps: int | None,
    batch_size: int,
    is_formal: bool,
    max_steps_per_attempt: int | None,
    min_formal_batch_size: int | None,
    allow_extreme_steps: bool,
) -> list[str]:
    """§5 secondary guardrails (RT5) — defense-in-depth only.

    The primary admission criterion is predicted total runtime (the
    in-subprocess verification); these catch degenerate counts even
    when the estimator claims they are cheap. The operator override
    (``allow_extreme_steps``) bypasses both checks — it is a schema
    field recorded in provenance, never a prompt instruction.
    """
    if allow_extreme_steps:
        return []
    violations: list[str] = []
    if (
        max_steps_per_attempt is not None
        and n_steps is not None
        and n_steps > max_steps_per_attempt
    ):
        violations.append(
            f"resolved optimizer steps {n_steps} exceed max_steps_per_attempt "
            f"{max_steps_per_attempt} (§5)"
        )
    if is_formal and min_formal_batch_size is not None and batch_size < min_formal_batch_size:
        violations.append(
            f"formal batch_size {batch_size} below min_formal_batch_size "
            f"{min_formal_batch_size} (§5 launch-overhead pathology — V18 incident shape)"
        )
    return violations


def _resolve_task_scope_guardrail_steps(
    *,
    task_scopes,
    data_dir: str | None,
    train_cfg: dict,
    train_portion: float | None,
    max_samples: int | None,
) -> int | None:
    """The §5 step count for an attempt whose scope its TASK built (B7).

    C12-P / finding B7. ``_resolve_guardrail_steps`` returned ``None`` the
    moment there was no legacy ``SampleSet``, and PR-12d's planning seam B
    made that state reachable for every composed task that declares no
    physical partition geometry. ``_evaluate_step_guardrails`` then
    short-circuits on the ``None`` and ``--max_steps_per_attempt`` decides
    nothing — silently, with no log line, because the early return is taken
    before the ``except`` that would have printed one. An operator hard bound
    that is quietly disabled for a whole class of runs is worse than one that
    refuses loudly.

    **Applicability is decided by the caller and passed down.** This function
    rediscovers nothing: ``task_scopes`` and ``data_dir`` are values
    ``run_admission_preflight`` already holds (``prepared.task_scopes``,
    ``bindings.time_data_dir``). An ABSENT training scope means the legacy
    single-file / un-composed regime, where ``None`` is the correct and
    unchanged answer — that is what ``test_rt5_guardrails.py`` pins.

    **Nothing TIDMAD-physical is resolved here.** The legacy leg needs
    ``segmentation_size`` because it divides PSD segments; a task-owned scope
    is measured by the implementation that built it
    (``resolve_task_scope_training_workload``), so no segment geometry, no
    dataset profile and no task name appears on this path.

    Best-effort like its sibling: a resolver failure prints and returns
    ``None`` rather than aborting an attempt the primary runtime criterion
    still protects. The difference from the defect is that the failure now
    SPEAKS.

    Args:
        task_scopes: this attempt's :class:`AttemptScopes`, or ``None``.
        data_dir: the run's resolved physical data root, or ``None``.
        train_cfg: the plan's training config.
        train_portion: the round's per-epoch subsample fraction.
        max_samples: the validation-envelope row ceiling, or ``None``.

    Returns:
        The resolved optimizer-step count, or ``None`` when this attempt has
        no task-owned scope or the count could not be resolved.
    """
    training = getattr(task_scopes, "training", None)
    if training is None:
        return None  # no task-owned scope — the legacy regime, unchanged
    try:
        from agent.skills.training_skill.estimator import _usable, resolve_train_field
        from execute_tools.workload_resolvers import resolve_task_scope_training_workload

        # B1b's rule, on this leg too: resolve an ABSENT key from the
        # declaration, never substitute for one the plan states impossibly.
        supplied_epochs = train_cfg.get("epochs")
        if supplied_epochs is not None and not _usable(supplied_epochs):
            return None
        if not data_dir:
            raise ValueError(
                "a composed attempt acquired a task-owned training scope but no "
                "resolved data root reached the guardrail, so the scope cannot "
                "be materialized and max_steps_per_attempt cannot be priced."
            )
        return resolve_task_scope_training_workload(
            training,
            data_dir=data_dir,
            batch_size=int(train_cfg.get("batch_size", 1)),
            train_portion=train_portion,
            epochs=resolve_train_field(train_cfg, "epochs", safety_margin=1),
            max_samples=max_samples,
        ).unit_count
    except Exception as exc:
        print(f"[guardrails] task-owned step resolution failed (non-fatal): {exc}")
        return None


def _resolve_guardrail_steps(
    train_sample_set: dict | None,
    model_config: dict,
    train_cfg: dict,
    train_portion: float | None,
    dataset_profile,
    model_type: str = "",
    max_samples: int | None = None,
    *,
    task_scopes=None,
    data_dir: str | None = None,
) -> int | None:
    """Resolved step count for the §5 guardrails. Best-effort: a
    resolver failure returns None (the guardrail is defense-in-depth —
    the primary runtime criterion still protects the attempt).

    V21 PR B1b — the sibling the bounded audit found. ``n_steps`` feeds
    ``max_steps_per_attempt``, a harness-owned hard bound, and it was
    resolved from literals that contradicted what the run would use:

    ```text
    epochs    .get(..., 1)    vs TrainConfig's 10    -> 10x LOW  -> the bound
                                                        UNDER-triggers, i.e.
                                                        is bypassed
    seg_size  .get(..., 1000) vs the class default   -> 40x HIGH -> spurious
                                                        rejection
    ```

    Same shape as the ``--max_epochs`` bypass and the same fix: resolve
    against the declaration, so the bound is evaluated on the workload
    that will actually run.

    ``model_type`` defaults to ``""`` so legacy callers keep working; an
    unknown type simply falls through to the documented safety margins.
    """
    if train_sample_set is None:
        # C12-P / B7. This was `return None` — a SILENT early return that
        # disabled `--max_steps_per_attempt` for every composed task without
        # physical partition geometry. A task-owned scope is priced by the
        # implementation that built it; its absence still means the legacy
        # single-file mode, and still resolves to None.
        return _resolve_task_scope_guardrail_steps(
            task_scopes=task_scopes,
            data_dir=data_dir,
            train_cfg=train_cfg,
            train_portion=train_portion,
            max_samples=max_samples,
        )
    try:
        from agent.skills.training_skill.estimator import (
            _usable,
            resolve_model_field,
            resolve_train_field,
        )
        from execute_tools.workload_resolvers import resolve_training_workload

        # B1b: resolve an ABSENT key from the declaration, but never
        # substitute for one the plan states and states impossibly. B1's
        # rule is explicit — "an explicitly invalid value must not
        # silently become a fallback" — and here the consequence is
        # sharper than in an estimator: inventing a workload for a config
        # that cannot run would have the guardrail judge a fiction. An
        # unresolvable plan keeps the documented best-effort contract and
        # returns None, leaving the primary runtime criterion to protect
        # the attempt.
        for _cfg, _key in ((model_config, "segmentation_size"), (train_cfg, "epochs")):
            _supplied = _cfg.get(_key)
            if _supplied is not None and not _usable(_supplied):
                return None

        return resolve_training_workload(
            train_sample_set,
            seg_size=resolve_model_field(
                model_type, model_config, "segmentation_size", safety_margin=1000
            ),
            profile=dataset_profile,
            batch_size=int(train_cfg.get("batch_size", 1)),
            train_portion=train_portion,
            epochs=resolve_train_field(train_cfg, "epochs", safety_margin=1),
            max_samples=max_samples,
        ).unit_count
    except Exception as exc:
        print(f"[guardrails] step resolution failed (non-fatal): {exc}")
        return None


def _build_guardrail_rejection_record(
    *,
    exp_id: str,
    model_type: str,
    file_index: int,
    record_params: dict,
    expert_advice_str: str,
    hypothesis: str,
    is_trial: bool,
    round_index: int,
    attempt_in_round: int,
    violations: list[str],
    n_steps: int | None,
    agent_input,
) -> dict:
    """Planner-visible §5 guardrail rejection (existing skipped_time_risk
    vocabulary; ``verification_stage="guardrail"`` distinguishes it).
    Config provenance is recorded on the record itself."""
    return {
        "exp_id": exp_id,
        "status": "skipped_time_risk",
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_index": file_index,
        "params": record_params,
        "denoising_score": None,
        "memory": {
            "expert_advice_followed": expert_advice_str,
            "hypothesis": hypothesis,
            "conclusion": "Skipped by §5 guardrails: " + "; ".join(violations),
            "discovery": (
                f"resolved_steps={n_steps}; guardrail config: "
                f"max_steps_per_attempt={agent_input.max_steps_per_attempt}, "
                f"min_formal_batch_size={agent_input.min_formal_batch_size}, "
                f"allow_extreme_steps={agent_input.allow_extreme_steps}"
            ),
            "memory_update": (
                "Reduce the step count (higher batch_size / segmentation_size, "
                "lower portions/epochs) or raise the formal batch size. The "
                "operator can override with allow_extreme_steps=True."
            ),
            "time_mode": "trial" if is_trial else "formal",
            "verification_stage": "guardrail",
            "round_index": round_index,
            "attempt_in_round": attempt_in_round,
        },
    }


def _build_admission_policy(agent_input, *, is_trial: bool, device_identity: Any) -> Any:
    """Assemble this attempt's `GpuAdmissionPolicy` (V20 B-G3).

    The production channel that had been missing: before this, nothing
    set `admission_mode` or `measured_requirements`, so the gate's
    `getattr` defaults made it permanently `trial` with no requirement —
    correct code that could never refuse.

    **Posture is derived, not configured.** It comes from the same
    `is_trial` that drives the time gate and the VRAM budget pick, so
    admission cannot disagree with the round actually executing. There
    is deliberately no `--admission_mode` flag: a second input could
    contradict the first, and the contradiction would be silent.

    **The source is a reference, never a figure.** No raw MiB reaches
    this object, so an operator cannot type a number that then acts as a
    measurement in formal mode. Until PR C resolves the reference, formal
    refuses `policy_unavailable` — the correct answer.

    Extracted as its own helper for the same reason as
    `_build_runtime_policy`: the exact policy the tuner ships is
    unit-testable against the launch configuration, without going
    through `run()`.
    """
    from core.runtime_control.admission import GpuAdmissionPolicy

    # The UUID is provenance, not control: it is recorded so a refusal can
    # be checked against the card it ran on, and it never selects a device.
    # So a device identity that cannot supply a usable string must degrade
    # to "unknown" rather than raise — building provenance may not be able
    # to abort an attempt that the gate itself would have allowed.
    raw_uuid = getattr(device_identity, "uuid", None)
    device_uuid = raw_uuid if isinstance(raw_uuid, str) else None

    return GpuAdmissionPolicy(
        mode="trial" if is_trial else "formal",
        measurement_source=getattr(agent_input, "gpu_admission_measurement_source", None),
        ceiling_gib=getattr(agent_input, "gpu_pair_ceiling_gib", None),
        enforcement=getattr(agent_input, "gpu_admission_enforcement", "observe_only"),
        device_uuid=device_uuid,
        provenance={
            "mode_source": "plan.is_trial",
            "measurement_source_configured": getattr(
                agent_input, "gpu_admission_measurement_source", None
            )
            is not None,
            "ceiling_source": (
                "launcher"
                if getattr(agent_input, "gpu_pair_ceiling_gib", None) is not None
                else "environment_or_default"
            ),
            "device_uuid_source": "hardware_discovery",
            "enforcement_source": (
                "launcher"
                if getattr(agent_input, "gpu_admission_enforcement", None) is not None
                else "compatibility_default"
            ),
        },
    )


def _build_runtime_policy(
    agent_input, *, chosen_time_budget: float | None, is_trial: bool, base_dir: str
) -> dict:
    """Assemble the attempt's RuntimeControlPolicy dict (RT2-G/RT6).

    Formal rounds enforce the operator budget; trial rounds run
    record-only (None budget). Operator-visible policy values —
    safety factor and watchdog enable/floor — come from the input
    schema (Gate 2 wiring, 2026-07-24); watchdog grace/poll keep
    their WatchdogConfig schema defaults (10 s / 1 s), which the
    executor validates and every observation records in
    ``runtime_policy`` provenance. Extracted as a helper so the exact
    policy the tuner ships is unit-testable against the launch
    configuration.

    Safety-factor resolution (Wave-1A split, 2026-07-24): the
    phase-specific factor (trial/formal) wins when provided, else the
    legacy ``runtime_safety_factor``. ``safety_factor`` in the returned
    dict is the EFFECTIVE value for this attempt's phase — enforcement
    reads only it; both configured phase values ride along as
    provenance.
    """
    phase_specific = (
        agent_input.runtime_trial_safety_factor
        if is_trial
        else agent_input.runtime_formal_safety_factor
    )
    effective_safety = (
        phase_specific if phase_specific is not None else agent_input.runtime_safety_factor
    )
    return {
        "operator_budget_seconds": (
            chosen_time_budget * 60.0 if (not is_trial and chosen_time_budget is not None) else None
        ),
        # VALIDATION POSTURE, None in every campaign. The Gate workload
        # envelope: the trainer builds a smaller epoch, so the bound is
        # spent before execution rather than enforced by killing a run.
        "validation_max_train_samples": agent_input.validation_max_train_samples,
        # 07c C6. The VALIDATION-row counterpart, orthogonal to the training
        # ceiling above: it bounds a different set, so neither constrains the
        # other. Same transport, so no new training argv flag.
        "validation_max_samples": agent_input.validation_max_samples,
        "observation_store_root": os.path.join(base_dir, "runtime_observations"),
        "safety_factor": effective_safety,
        "trial_safety_factor": agent_input.runtime_trial_safety_factor,
        "formal_safety_factor": agent_input.runtime_formal_safety_factor,
        "watchdog": {
            "enabled": agent_input.runtime_watchdog_enabled,
            "floor_seconds": agent_input.runtime_watchdog_floor_seconds,
            # V19 split (2026-07-29): watchdog-only multiplier; None →
            # the deadline falls back to the phase-effective
            # safety_factor above (V18 behavior). Admission never reads
            # this field.
            "safety_factor": agent_input.runtime_watchdog_safety_factor,
            # VALIDATION POSTURE, None in every campaign. Deliberately on
            # the watchdog rather than in operator_budget_seconds: the
            # budget is an ADMISSION input, and a small one would reject
            # the attempt before training instead of bounding it — the
            # Gate would then prove nothing at all. Note the trial branch
            # above ships operator_budget_seconds=None, so on a trial
            # round this is the only non-forecast deadline candidate.
            "max_phase_seconds": agent_input.validation_max_phase_seconds,
        },
    }


def _check_and_record_guardrail_skip(
    *,
    sandbox,
    agent_input,
    plan,
    trial_config,
    train_sample_set: dict | None,
    model_config: dict,
    exp_id: str,
    model_type: str,
    file_index: int,
    record_params: dict,
    expert_advice_str: str,
    hypothesis: str,
    round_index: int,
    attempt_in_round: int,
    dataset_profile,
    task_scopes=None,
    data_dir: str | None = None,
) -> bool:
    """Run the §5 guardrails; on violation save the planner-visible
    record and return True (the attempt loop `continue`s). Single call
    site keeps run() under the analyzer's complexity ceiling.

    ``task_scopes`` / ``data_dir`` are C12-P / B7: this is the one
    admission decision that never received the attempt's task-owned scope,
    which is why a composed run had nothing to price and its operator step
    bound went silently inert. Both default to ``None`` so the legacy
    call shape and the legacy resolution are unchanged.
    """
    # The EXECUTED step count, not the planned one. Under a validation
    # envelope the trainer builds a smaller epoch, so judging the planner's
    # unclamped figure would skip an attempt whose real workload is already
    # inside the bound — the Step-03 failure where a low
    # `max_steps_per_attempt` skipped every round and no training ran.
    n_steps = _resolve_guardrail_steps(
        train_sample_set,
        model_config,
        plan.train_cfg,
        trial_config.train_portion,
        dataset_profile,
        model_type=model_type,
        max_samples=agent_input.validation_max_train_samples,
        task_scopes=task_scopes,
        data_dir=data_dir,
    )
    violations = _evaluate_step_guardrails(
        n_steps=n_steps,
        batch_size=int(plan.train_cfg.get("batch_size", 1)),
        is_formal=not plan.is_trial,
        max_steps_per_attempt=agent_input.max_steps_per_attempt,
        min_formal_batch_size=agent_input.min_formal_batch_size,
        allow_extreme_steps=agent_input.allow_extreme_steps,
    )
    if not violations:
        return False
    print("  [Guardrails §5] SKIPPED: " + "; ".join(violations))
    record = _build_guardrail_rejection_record(
        exp_id=exp_id,
        model_type=model_type,
        file_index=file_index,
        record_params=record_params,
        expert_advice_str=expert_advice_str,
        hypothesis=hypothesis,
        is_trial=plan.is_trial,
        round_index=round_index,
        attempt_in_round=attempt_in_round,
        violations=violations,
        n_steps=n_steps,
        agent_input=agent_input,
    )
    _records._emit_record(
        sandbox,
        record,
        candidate_id=agent_input.candidate_id,
        experiment_arm=agent_input.experiment_arm,
    )
    return True


def _handle_in_subprocess_rejection(
    train_status: dict,
    *,
    sandbox,
    run_name: str,
    exp_id: str,
    model_type: str,
    file_index: int,
    record_params: dict,
    expert_advice_str: str,
    hypothesis: str,
    is_trial: bool,
    round_index: int,
    attempt_in_round: int,
    candidate_id: str | None = None,
    experiment_arm: str | None = None,
) -> bool:
    """RT2-G: a clean in-subprocess rejection — real setup was paid, so
    it CONSUMES an attempt (unlike the free pre-flight screen). Saves
    the record + appends the observation; returns True to `continue`."""
    if train_status.get("status") != "rejected_time_risk":
        return False
    rv_block = train_status.get("runtime_verification") or {}
    print("  In-subprocess runtime verification REJECTED the attempt (consumes one attempt).")
    reject_record = _build_in_subprocess_rejection_record(
        exp_id=exp_id,
        model_type=model_type,
        file_index=file_index,
        record_params=record_params,
        expert_advice_str=expert_advice_str,
        hypothesis=hypothesis,
        is_trial=is_trial,
        round_index=round_index,
        attempt_in_round=attempt_in_round,
        rv_block=rv_block,
        fallback_message=train_status.get("message", "runtime verification rejected the attempt"),
    )
    _records._emit_record(
        sandbox, reject_record, candidate_id=candidate_id, experiment_arm=experiment_arm
    )
    _append_runtime_observation(sandbox, run_name, rv_block)
    return True


class RuntimeEvidenceChannelError(RuntimeError):
    """C9c: the runtime evidence channel failed (infrastructure class).

    Distinct from every other terminal signal in this loop: it is not a
    candidate verdict (the model was never judged), not a watchdog kill,
    not gate exhaustion, not an operator stop, and not a budget stop. It
    means the machinery that produces runtime evidence is broken, so the
    chain must stop instead of feeding the next candidate into it.
    """

    def __init__(self, message: str, rv_block: dict | None = None):
        super().__init__(message)
        self.rv_block = dict(rv_block or {})


def _raise_if_evidence_channel_failure(status: dict, sandbox, run_name: str) -> None:
    """Convert an executor infrastructure ABORT into the typed error the
    loop terminates on. The partial observation is appended first — a
    broken channel is still evidence of what happened."""
    if status.get("status") != "aborted_infrastructure":
        return
    rv_block = status.get("runtime_verification")
    _append_runtime_observation(sandbox, run_name, rv_block)
    raise RuntimeEvidenceChannelError(
        status.get("message", "runtime evidence channel failed"), rv_block
    )


class WallClockTimeoutError(RuntimeError):
    """A watchdog deadline kill (RT4, §4). Carries the §4 timeout
    provenance so the attempt_failure record can surface
    ``{elapsed_s, deadline_s, estimate_source}`` to the planner."""

    def __init__(self, message: str, watchdog: dict, rv_block: dict | None):
        super().__init__(message)
        self.watchdog = dict(watchdog or {})
        self.rv_block = rv_block


def _raise_if_wall_clock_timeout(status: dict, sandbox, run_name: str) -> None:
    """RT4: convert an executor watchdog kill into the §4 attempt-failure
    path (the shared except-handler records it with
    failure_type='wall_clock_timeout'). The partial observation is
    appended to the store first — a killed attempt is still evidence
    (§6c excludes it from calibration; the ledger keeps it visible)."""
    if status.get("status") != "wall_clock_timeout":
        return
    rv_block = status.get("runtime_verification")
    _append_runtime_observation(sandbox, run_name, rv_block)
    raise WallClockTimeoutError(
        status.get("message", "watchdog wall-clock timeout"),
        status.get("watchdog") or {},
        rv_block,
    )


def _apply_watchdog_failure_fields(record: dict, exc: Exception) -> None:
    """Stamp §4 timeout provenance onto an attempt_failure record."""
    if not isinstance(exc, WallClockTimeoutError):
        return
    record["watchdog"] = exc.watchdog
    record["runtime_verification"] = exc.rv_block
    memory = record["memory"]
    memory["watchdog_elapsed_s"] = exc.watchdog.get("elapsed_s")
    memory["watchdog_deadline_s"] = exc.watchdog.get("deadline_s")
    memory["watchdog_estimate_source"] = exc.watchdog.get("estimate_source")


def _build_in_subprocess_rejection_record(
    *,
    exp_id: str,
    model_type: str,
    file_index: int,
    record_params: dict,
    expert_advice_str: str,
    hypothesis: str,
    is_trial: bool,
    round_index: int,
    attempt_in_round: int,
    rv_block: dict,
    fallback_message: str,
) -> dict:
    """Attempt record for a clean in-subprocess runtime-verification
    rejection (RT2-G). Existing ``skipped_time_risk`` vocabulary reused
    (§2.11); ``memory.verification_stage`` distinguishes it from the
    free pre-flight screen — this rejection paid real setup and
    CONSUMES an attempt (operator decision 2026-07-23)."""
    admission = rv_block.get("admission") or {}
    reject_reason = admission.get("reason") or fallback_message
    return {
        "exp_id": exp_id,
        "status": "skipped_time_risk",
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_index": file_index,
        "params": record_params,
        "denoising_score": None,
        "memory": {
            "expert_advice_followed": expert_advice_str,
            "hypothesis": hypothesis,
            "conclusion": (
                f"Rejected by IN-SUBPROCESS runtime verification after real setup: {reject_reason}"
            ),
            "discovery": (
                f"admission stage={admission.get('stage')}; "
                f"setup_cost_s={admission.get('setup_cost_seconds')}; "
                f"verification_cost_s={admission.get('verification_cost_seconds')}; "
                f"avoided_predicted_s={admission.get('avoided_predicted_runtime_seconds')}"
            ),
            "memory_update": (
                "The measured runtime prediction exceeded the budget (or "
                "verification failed). Reduce the workload (steps, "
                "segmentation_size, portions, model size) — this rejection "
                "consumed an attempt, unlike pre-flight skips."
            ),
            "time_mode": "trial" if is_trial else "formal",
            "verification_stage": "in_subprocess",
            "round_index": round_index,
            "attempt_in_round": attempt_in_round,
        },
        "runtime_verification": rv_block or None,
    }


def _resolve_effective_epochs(train_cfg: dict) -> int:
    """The epoch count the trainer will ACTUALLY use for this plan.

    V21 PR B1b. A harness-owned hard bound must be applied to what will
    run, not to what the planner happened to write down. ``TrainConfig``
    declares ``epochs=10`` and the trainer builds ``TrainConfig(**t_data)``
    (`train_engine_sandbox.py:1211`), so an absent key resolves to ten —
    while the clamp used to read it as one.

    Delegates to B1's resolver so there is exactly one answer to "what
    will this config actually run as". Duplicating the resolution here is
    how the 40000/1000/0 split for ``segmentation_size`` arose.

    Layering note: ``resolve_train_field`` currently lives in the training
    estimator because that is where B1 needed it. It is really a config
    resolution utility rather than an estimator concern, and a later
    genericization pass may move it beside the config classes; importing
    it is preferred over a second implementation in the meantime.
    """
    from agent.skills.training_skill.estimator import resolve_train_field

    return resolve_train_field(train_cfg, "epochs", safety_margin=1)


def _apply_epoch_bound(
    train_cfg: dict, max_epochs: int | None, *, source: str = "max_epochs"
) -> int | None:
    """Apply the harness's epoch bound to the RESOLVED configuration.

    V21 PR B1b. Extracted rather than left inline for two reasons: the
    tuner's ``run()`` is the orchestrator the decomposition rule names,
    and — the reason that actually forced it — a mutation removing the
    write-back SURVIVED while the clamp lived inline, because no test
    could reach production's copy of it. A boundary that cannot be driven
    cannot be guarded.

    Mutates ``train_cfg`` in place so the effective value travels onward
    to the trainer. That write-back is the whole point: a clamp that only
    informs the admission decision leaves the trainer free to resolve an
    absent key to ``TrainConfig``'s declared 10, which is the bypass.

    ``source`` names the input field that supplied the bound (D-BUD-6
    mode-aware caps: ``trial_max_epochs`` / ``formal_max_epochs`` /
    ``max_epochs``, resolved by ``HyperparamTuningInput.resolve_epoch_cap``).
    It labels the log line ONLY — the clamp arithmetic is source-blind, and
    the default keeps legacy callers' output byte-identical.

    Returns the effective epoch count, or ``None`` when no bound is set.
    """
    if max_epochs is None:
        return None
    resolved = _resolve_effective_epochs(train_cfg)
    effective = min(resolved, max_epochs)
    if effective != train_cfg.get("epochs"):
        print(f"  Clamping epochs: {resolved} → {effective} ({source})")
    train_cfg["epochs"] = effective
    return effective


def _attach_realized_memory(
    final_record: dict,
    resource_check: dict | None,
    rv_block: dict | None,
) -> None:
    """Persist realized-vs-admitted memory, per phase (V21 PR B2).

    Extracted rather than inlined: the tuner's ``run()`` is the giant
    orchestrator the decomposition rule names, and this is a new
    responsibility with its own inputs and its own tests, not another
    branch for that scope to carry.

    **Observation only.** This runs after every admission decision has
    already been made and writes into ``final_record`` alone; no admit,
    refuse, retry or resize path reads what it stores. It also chooses no
    semantics — Q-B-1 is unfrozen until B0, so the stored row is measured
    facts that S1, S2 and S3 must all remain able to interpret.

    Best-effort, like ``_append_runtime_observation`` beside it: this is
    evidence, and a defect in evidence collection must never break the
    attempt loop.
    """
    try:
        from core.runtime_control.realized_memory import (
            realized_vs_admitted,
            render_exceedance_notice,
            threshold_exceedance_notices,
        )

        rows = {}
        typed = {}
        for phase in ("training", "inference"):
            row = realized_vs_admitted(
                phase,
                resource_check=resource_check,
                runtime_verification=rv_block,
            )
            if row is not None:
                rows[phase] = row.model_dump(mode="json")
                typed[phase] = row
        if not rows:
            return
        memory = final_record.setdefault("memory", {})
        memory["realized_vs_admitted"] = rows

        # V21 PR B3 Stage C — the operator-visible half of S3. Derived
        # AFTER every decision; nothing reads it back. Silent when the
        # measurement is unknown, because `realized_above_threshold` is
        # None there and None is not True — an unmeasured phase must not
        # produce a reassuring absence of notice OR a false one.
        notices = threshold_exceedance_notices(
            typed,
            model_identity=final_record.get("model_type"),
            exp_id=final_record.get("exp_id"),
        )
        if notices:
            memory["threshold_exceedance_notices"] = [n.model_dump(mode="json") for n in notices]
            for notice in notices:
                print(render_exceedance_notice(notice))

    except Exception as exc:  # pragma: no cover — defensive
        print(f"  [B2/B3] realized-vs-admitted attach failed (non-fatal): {exc}")


def _append_runtime_observation(sandbox, run_name: str, rv_block: dict | None) -> None:
    """Append a finalized runtime observation to the run's store (RT2-G).

    Best-effort by design: the observation store is calibration
    evidence, and a store I/O problem must never break the attempt loop
    (§6.3 — store failures fail safely). Absent/None blocks are the
    explicit legacy shape and are skipped silently.
    """
    if not rv_block:
        return
    try:
        import re as _re

        from core.runtime_control.observation_store import ObservationStore
        from core.runtime_control.records import RuntimeObservation

        writer = _re.sub(r"[^A-Za-z0-9._-]", "_", run_name)[:128] or "run"
        ObservationStore(os.path.join(sandbox.base_dir, "runtime_observations")).append(
            RuntimeObservation.model_validate(rv_block), writer_id=writer
        )
    except Exception as exc:
        print(f"[runtime_control] observation-store append failed (non-fatal): {exc}")


def _derive_calibration_from_observation(
    sandbox,
    *,
    rv_block: dict | None,
    device_identity,
    data_dir: str | None,
    run_profile: Any = None,
    measurement_capability: Any | None = None,
) -> None:
    """Derive a v2 calibration record from a SUCCESSFUL attempt's observation.

    V20 PR C1 / C-C3c. System A has already persisted the raw measurement by
    the time this runs; this is the derived calibration view of that same
    measurement, never a second one.

    WHY THIS IS NOT INSIDE `_append_runtime_observation`. That helper has
    four production call sites and three of them record failures -- a
    subprocess rejection, an evidence-channel failure and a wall-clock
    timeout. Deriving there would feed failure evidence into throughput
    calibration, which `calibration_policy` forbids and explicitly
    anticipates ("should another producer ever record failure evidence as an
    observation"). This is called only from the success path.

    Best-effort, like the System A append beside it: the scientific result
    is already decided and persisted, and losing a calibration sample must
    never cost an attempt. The loss is printed rather than swallowed, so a
    missing sample is visible.

    C12-P / B5 — WHY `run_profile` IS A PARAMETER AND NOT A LOOKUP.
    The run's resolved profile decides whether TIDMAD's measurement identity
    may be stamped on this run's calibration at all: a task that declares no
    measurement identity of its own must not inherit TIDMAD's, because the
    calibration store is machine-global (`~/.siderius/`) and a wrong
    `task_identity` there silently pollutes every later run on this host.

    It arrives as a VALUE decided by the caller. `run()` is the giant
    orchestrator the decomposition rule governs, so the applicability rule
    lives here — beside the identity it guards — rather than as another
    branch up there. Resolving it here instead would also make the decision
    ambient, which is the defect B1/B4 closed on the sibling surface.
    """
    if not rv_block:
        return
    try:
        from core.runtime_control.calibration_derivation import (
            DERIVABLE_PHASES,
            IdentityContext,
            derive_duration_calibration_record,
            evaluate_affected_bucket_after_write,
            persist_duration_calibration_record,
        )
        from core.runtime_control.calibration_policy import stack_identity
        from core.runtime_control.calibration_registry import CalibrationRegistry
        from core.runtime_control.probe_production import (
            collect_execution_environment_profile,
            collect_hardware_compatibility_profile,
        )
        from core.runtime_control.provenance import capture_software_stack
        from core.runtime_control.records import RuntimeObservation

        observation = RuntimeObservation.model_validate(rv_block)
        uuid = getattr(device_identity, "uuid", None)
        stack = capture_software_stack()

        # A missing dimension drives QUARANTINE, never a fabricated default:
        # `IdentityContext` refuses a blank, so an absent UUID or an
        # INAPPLICABLE task yields `identity=None` and the derivation
        # quarantines with the reason.
        #
        # `uuid` must be checked BEFORE the context is built and this ordering
        # is load-bearing: `IdentityContext.hardware_uuid` is `min_length=1`,
        # so `str(None)` would sail through as the literal `"None"` and produce
        # an ELIGIBLE record naming a device that does not exist. Absence must
        # reach the quarantine path, never a placeholder.
        #
        # C12-P B5 -- the applicability term. The two dropped terms
        # (`capability.task_identity and capability.data_shape_class`) were a
        # TAUTOLOGY: both are `Field(min_length=1)` on
        # `ResolvedMeasurementCapability` and are populated on EVERY return
        # path, refusals included, so they could never be falsy and the guard
        # reduced to `if uuid:`. They are replaced by the question that
        # actually needed asking -- see
        # `_tidmad_calibration_identity_applicable`. The capability is now
        # resolved INSIDE the branch, so a foreign task never even constructs
        # TIDMAD's identity.
        #
        # THE PROBE LANE NEEDS NO TWIN OF THIS GUARD, and adding one would be
        # redundant, not safer. `probe_wiring`'s registry write is reached only
        # through `_resolve_time_check_probe_request`, which sits behind
        # `execution.wall_time_preflight_applicable` (C12-P B1) and is
        # therefore already unreachable for a task declaring no TIDMAD
        # topology. A second guard there would imply the first one is not
        # trusted. Do not reintroduce it.
        identity = None
        if measurement_capability is not None and uuid:
            capability = measurement_capability
            identity = IdentityContext(
                task_identity=capability.task_identity,
                data_shape_class=capability.data_shape_class,
                hardware_uuid=str(uuid),
                runtime_stack_identity=stack_identity(stack),
            )

        registry = CalibrationRegistry()
        hardware_id = registry.put_hardware_profile(collect_hardware_compatibility_profile())
        environment_id = registry.put_environment_profile(
            collect_execution_environment_profile(
                installation_id=registry.installation_id(),
                hardware_compatibility_id=hardware_id,
                concurrency_regime="single_candidate_idle",
            )
        )

        for phase in DERIVABLE_PHASES:
            outcome = persist_duration_calibration_record(
                derive_duration_calibration_record(observation, phase, identity=identity),
                registry=registry,
                hardware_compatibility_id=hardware_id,
                execution_environment_id=environment_id,
                concurrency_identity="single_candidate_idle",
                producer_identity="derived_runtime_observation@1.0.0",
                provenance=(
                    "real_training_verification"
                    if phase == "training"
                    else "real_inference_verification"
                ),
                software_stack=stack,
            )
            if outcome.kind in ("failed", "quarantined"):
                print(f"[runtime_control] calibration {phase}: {outcome.kind} — {outcome.detail}")
                continue
            if outcome.kind != "eligible" or not outcome.record_id:
                continue

            # O-3: an eligible write is the ONLY promotion trigger, and it
            # evaluates only the bucket that write landed in. A refusal is
            # printed too -- "zero authoritative buckets" has to be an
            # explainable state, which is exactly what the live v1 registry
            # (20 observations, 0 promotions, no recorded reason) was not.
            promotion = evaluate_affected_bucket_after_write(
                registry, registry.load_observation(outcome.record_id)
            )
            if promotion.kind == "promoted":
                print(
                    f"[runtime_control] calibration {phase}: bucket promoted to "
                    f"{promotion.level} on {promotion.n_observations} observation(s)"
                )
            elif promotion.kind in ("not_promoted", "failed"):
                print(
                    f"[runtime_control] calibration {phase}: not authoritative — {promotion.reason}"
                )
    except Exception as exc:
        print(f"[runtime_control] calibration derivation failed (non-fatal): {exc}")
