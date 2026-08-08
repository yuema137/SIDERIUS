# nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py
"""
tune_ml_hyperparam_agent — Node 1 in the SIDERIUS graph.

Optimizes hyperparameters for a given ML model architecture over N rounds.
Each round: plan (LLM) → resource check → train → infer → score → reflect (LLM).

Node contract:
  run(input: HyperparamTuningInput) -> HyperparamTuningOutput
  CLI: --provider, --model_id, --expert_advice, --max_rounds, --force_model,
       --run_name, --workspace, --file_index, --progress_bar
"""

import argparse
import gc
import importlib
import json
import math
import os
import time
import traceback
import warnings
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from agent.llm_bridge import LLMBridge
from agent.schemas.health_feedback import (
    InvalidTrialOutcome,
    TrialValidityFeedback,
)
from agent.schemas.hyperparam_tuning import (
    ExperimentPlan,
    ExperimentRecord,
    GateExhaustionInfo,
    HyperparamTuningInput,
    HyperparamTuningOutput,
    PhysicalRejection,
    PlanOverridesError,
    TrialConfig,
    serialize_expert_advice,
    validate_runtime_config,
)
from agent.schemas.ordering import parse_file_order_cli, resolve_ordering
from agent.schemas.score_table import ScoreComparisonTable
from agent.skills.evaluate_time_skill.wrapper import (
    _aggregate_inference_file_timings,
)
from agent.skills.evaluate_vram_skill.preflight_adapter import run_production_preflight
from agent.skills.evaluate_vram_skill.probe_budgets import InconclusivePreflight
from agent.utils.architectural_pattern_tagger import (
    TIME_FACTOR_THRESHOLD,
    VRAM_FACTOR_THRESHOLD,
    tag_architecture,
)
from core.hardware_context import get_or_create
from core.run_invariants import (
    RunInvariants,
    build_run_invariants,
    ensure_run_invariants,
    load_run_invariants,
    validate_run_invariants,
    validate_stamped_invariants,
)
from core.runtime_control.failure_attribution import may_recommend_resource_reduction
from core.runtime_control.gpu_accounting import device_identity_from_hardware
from core.sandbox_executor import TidmadSandbox
from core.scientific_authority import ScientificAuthority
from execute_tools.build_anchor_map import load_anchor_map
from execute_tools.data_paths import TIDMAD_DATA_DIR
from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG
from execute_tools.dataset_config import DataScope, ScopeViolationError
from execute_tools.health_checks.candidate_eligibility import (
    classify_candidate_health,
    formal_validity_of,
    is_valid_candidate,
)
from execute_tools.health_checks.evaluation import evaluate_and_persist_health_gates
from execute_tools.health_checks.runner import get_gates_for_position
from execute_tools.health_checks.schemas import (
    BLOCKING_ACTIONS,
    CandidateHealthValidity,
    GateAction,
    GateResult,
    HealthCheckContext,
)
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.scoring_helpers import (
    build_score_table,
    file_vector_to_log_space,
)
from execute_tools.scoring_utils import coerce_nonfinite_to_none
from nodes.agent_data_stream import log_score_table
from nodes.scoring_reference import load_reference_scores

SIDERIUS_ROOT = str(Path(__file__).resolve().parents[2])


def _may_advise_resource_reduction(status: dict) -> bool:
    """Whether a failed phase's attribution authorises shrink advice.

    The task layer decides what the authority *says*; the generic runtime
    layer decides whether there is any. This reads the second, so a
    contention-caused OOM cannot reach the planner as a reason to shrink
    a candidate that was the right size — the V19 failure.

    Absent attribution means ``unknown``: every record written before
    B-C3b, and any failure the runtime declined to classify. The default
    is therefore False. A missing verdict costs one piece of feedback; a
    wrong one costs a scientific conclusion.

    Authority is read through ``may_recommend_resource_reduction`` rather
    than by testing the attribution string, so an outcome added to the
    vocabulary later cannot silently inherit it here.
    """
    attribution = (status.get("failure_attribution") or {}).get("attribution")
    return may_recommend_resource_reduction(attribution or "unknown")


#: Per-phase wording that is NOT shared. Everything else about a training
#: and an inference failure record is the same algorithm; these three
#: strings are the only real difference, and keeping them in one table
#: is what makes the shared builder honest rather than a near-miss.
_PHASE_FAILURE_TEXT: dict[str, dict[str, str]] = {
    "training": {
        "label": "Training",
        "status_ok": "error_training",
        "status_oom": "error_training_oom",
        "plain_memory": "Fix the error before retrying this config.",
    },
    "inference": {
        "label": "Inference",
        "status_ok": "error_inference",
        "status_oom": "error_inference_oom",
        "plain_memory": "Fix the inference error before retrying.",
    },
}


def _build_execution_failure_record(
    status: dict,
    *,
    phase: str,
    exp_id: str,
    model_type: str,
    file_index: Any,
    record_params: dict,
    expert_advice_str: str,
    hypothesis: str,
    round_index: int,
    attempt_in_round: int,
) -> dict:
    """The record written when a GPU phase's subprocess fails (B-C4a0 E1).

    One builder for training and inference. They were two copies of the
    same algorithm — read the message, classify the OOM, truncate to 500
    characters, ask `_oom_memory_wording` whether the failure may be
    blamed on the candidate, assemble the same eight keys — and the
    copies had already drifted: the OOM test existed in two spellings
    until B-C3b's pyright repair.

    `phase` selects the wording and the status pair, and enables the
    inference-only silent-training-crash re-route. It is deliberately a
    parameter rather than two functions, because the thing worth having
    in one place is the *shared* algorithm, not the differences.

    Pure: builds and returns a dict. Validation, evidence stamping and
    persistence belong to `_emit_record`.
    """
    text = _PHASE_FAILURE_TEXT[phase]
    error_msg = status.get("message", f"Unknown {phase} error")
    is_oom = _is_cuda_oom(error_msg)
    # Truncate long tracebacks — keep last 500 chars for the LLM
    short_msg = error_msg[-500:] if len(error_msg) > 500 else error_msg

    # Phase 6.7 Fix 3 — an inference subprocess that fails because the
    # trainer-side sentinel was missing carries the ``error_training:``
    # prefix (raised by ``inference_single._assert_training_sentinel``).
    # That is a *training* failure surfaced through the inference
    # subprocess, so the category is re-routed and the planner sees the
    # real cause instead of "inference crashed for mysterious reasons".
    # ``execute_training``'s silent-crash check catches the same
    # condition upstream when the process exited 0.
    if phase == "inference" and "error_training:" in error_msg:
        status_tag = "error_training"
        conclusion = f"Training crashed silently (detected at inference preflight): {short_msg}"
        discovery = (
            f"Training subprocess returned 0 but produced no checkpoint sentinel: {short_msg}"
        )
        memory_update = (
            "Silent training crash — investigate the trainer logs for a "
            "post-save segfault, OOM-kill, or GPU watchdog. Do not retry "
            "blindly until the root cause is identified."
        )
    elif is_oom:
        status_tag = text["status_oom"]
        conclusion = f"{text['label']} failed: {short_msg}"
        # B-C3b: only a MEASURED candidate-capacity verdict may ask for a
        # smaller config.
        discovery, memory_update = _oom_memory_wording(status, phase=phase)
    else:
        status_tag = text["status_ok"]
        conclusion = f"{text['label']} failed: {short_msg}"
        discovery = f"{text['label']} crashed: {short_msg}"
        memory_update = text["plain_memory"]

    return {
        "exp_id": exp_id,
        "status": status_tag,
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_index": file_index,
        "params": record_params,
        "denoising_score": None,
        "memory": {
            "expert_advice_followed": expert_advice_str,
            "hypothesis": hypothesis,
            "conclusion": conclusion,
            "discovery": discovery,
            "memory_update": memory_update,
            "round_index": round_index,
            "attempt_in_round": attempt_in_round,
        },
    }


def _is_cuda_oom(message: str) -> bool:
    """The tuner's own device-OOM test, kept in one place."""
    return "CUDA out of memory" in message or "OutOfMemoryError" in message


#: Frozen B-C4a0 C3 vocabulary. `skipped_resource_admission` means the
#: ENVIRONMENT did not permit starting the phase. It is deliberately not
#: `skipped_time_risk`, which already carries three distinct meanings
#: (guardrail, in-subprocess rejection, time gate) and feeds five
#: time-factor consumers — a fourth producer would pollute statistics
#: that mean something else. Like `gpu_contention` in §B-C3, it says
#: nothing about the candidate and carries no authority to shrink it.
RESOURCE_ADMISSION_STATUS = "skipped_resource_admission"
#: An INFRASTRUCTURE condition, not a resource verdict (V20 attempt 2).
#:
#: The status used to be `skipped_resource_admission` for all three reasons
#: below. `reason_code` did distinguish them, but the top-level status read
#: as "the candidate was refused for resources" — and V20 attempt 2 wrote
#: 15 such records while the GPU sat at 1.6 of 32.6 GiB, because the
#: measurement WORKER had failed. An auditor reading those records would
#: conclude the campaign hit resource limits.
#:
#: Deliberately one extra status, not a new taxonomy: the reason vocabulary
#: is unchanged and still carries the detail.
INFRASTRUCTURE_FAILURE_STATUS = "skipped_infrastructure_failure"
RESOURCE_ADMISSION_REASONS = (
    "insufficient_headroom",
    "measurement_unavailable",
    "policy_unavailable",
)
#: reason_code -> top-level status. Only a genuine headroom verdict may
#: claim a resource refusal; everything else is infrastructure.
_STATUS_FOR_REASON = {
    "insufficient_headroom": RESOURCE_ADMISSION_STATUS,
    "measurement_unavailable": INFRASTRUCTURE_FAILURE_STATUS,
    "policy_unavailable": INFRASTRUCTURE_FAILURE_STATUS,
}


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


class AttemptTransition(StrEnum):
    """What the caller must do after a phase result (B-C4a0 E5).

    These map exactly onto what `run()` does inline today — fall
    through, `continue`, or set the termination reason and `break` — so
    a helper can report a decision instead of performing a jump. A
    helper that executed the jump itself would be a `goto` with a
    function signature.
    """

    PROCEED = "proceed"
    RETRY_ATTEMPT = "retry_attempt"
    TERMINATE_RUN = "terminate_run"


@dataclass(frozen=True)
class AttemptDecision:
    """One attempt's own outcome (B-C4a0 E5, constraint C2).

    `resolved_action` is carried **per attempt**, deliberately. The
    outer `resolved_action` variable is round-scoped, written five levels
    deep inside scoring, and never reset between attempts — so it holds
    the value of the last attempt that *reached* scoring. An admission
    refusal short-circuits before scoring, and reading that outer
    variable would apply an earlier attempt's gate action to this one.

    `action_was_produced` distinguishes "this attempt produced no gate
    action" from "it produced CONTINUE". Collapsing the two is how a
    refusal silently inherits a neighbour's verdict.
    """

    transition: AttemptTransition
    attempt_id: str
    resolved_action: GateAction | None = None
    action_was_produced: bool = False
    reason: str | None = None

    @classmethod
    def admission_refused(cls, *, attempt_id: str, reason: str) -> "AttemptDecision":
        """The shape B-C4's admission refusal must use.

        No gate action is produced, so none is carried. B-C4 reads this
        object, never the outer round-scoped variable.
        """
        return cls(
            transition=AttemptTransition.RETRY_ATTEMPT,
            attempt_id=attempt_id,
            resolved_action=None,
            action_was_produced=False,
            reason=reason,
        )


class RoundDecision(StrEnum):
    """What the round loop does once its attempts are exhausted."""

    CONTINUE = "continue"
    BREAK_ITERATION = "break_iteration"
    SKIP_TO_FORMAL = "skip_to_formal"


def _decide_round_outcome(
    *,
    scope_violation_reason: str | None,
    evidence_channel_failure: str | None,
    resolved_action: GateAction,
    is_formal_round: bool,
) -> RoundDecision:
    """Arbitrate the end of a round (B-C4a0 E5).

    A pure function over four already-computed inputs. The `break`, the
    `completed_rounds` fast-forward and the operator-facing prints stay
    in the caller — this decides, it does not act, so it can be tested
    without a loop around it.

    Order is load-bearing: a non-retryable termination outranks a gate
    action, because a scope violation is deterministic on retry.
    """
    if scope_violation_reason or evidence_channel_failure:
        return RoundDecision.BREAK_ITERATION
    if _should_break_iteration(resolved_action):
        return RoundDecision.BREAK_ITERATION
    if _should_skip_to_formal(resolved_action, is_formal_round):
        return RoundDecision.SKIP_TO_FORMAL
    return RoundDecision.CONTINUE


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


def _build_skip_record(
    *,
    status: str,
    exp_id: str,
    model_type: str,
    file_index: Any,
    record_params: dict,
    expert_advice_str: str,
    hypothesis: str,
    round_index: int,
    attempt_in_round: int,
    conclusion: str,
    discovery: str,
    memory_update: str,
    memory_extra: dict[str, Any] | None = None,
) -> dict:
    """A record for an attempt that was skipped before it ran (B-C4a0 E2).

    The three inline skip paths — schema violation, VRAM gate, time gate
    — were the same eight-key shape over the same nine-field identity
    block, differing only in three strings and a few optional memory
    fields. `memory_extra` is applied before the position stamps so the
    resulting key order matches what each site produced inline.

    Pure. Persistence is `_emit_record`'s job.
    """
    memory: dict[str, Any] = {
        "expert_advice_followed": expert_advice_str,
        "hypothesis": hypothesis,
        "conclusion": conclusion,
        "discovery": discovery,
        "memory_update": memory_update,
    }
    if memory_extra:
        memory.update(memory_extra)
    memory["round_index"] = round_index
    memory["attempt_in_round"] = attempt_in_round
    return {
        "exp_id": exp_id,
        "status": status,
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_index": file_index,
        "params": record_params,
        "denoising_score": None,
        "memory": memory,
    }


def _build_resource_admission_record(
    *,
    resource_type: str,
    reason_code: str,
    detail: str,
    exp_id: str,
    model_type: str,
    file_index: Any,
    record_params: dict,
    expert_advice_str: str,
    hypothesis: str,
    round_index: int,
    attempt_in_round: int,
    admission_evidence: dict | None = None,
) -> dict:
    """The record for a phase the environment would not admit (B-C4a0 C3).

    **No production caller yet — emitting this is B-C4.** The typed
    surface exists now so the boundary is in place before the decision
    that uses it, rather than being invented alongside it.

    The wording states what it is *not*: a refusal here is an
    infrastructure condition, and reading it as evidence about the
    candidate is the V19 mistake in a different coordinate.
    """
    if reason_code not in RESOURCE_ADMISSION_REASONS:
        raise ValueError(
            f"unknown admission reason_code {reason_code!r}; "
            f"expected one of {RESOURCE_ADMISSION_REASONS}"
        )
    record = _build_skip_record(
        status=_STATUS_FOR_REASON[reason_code],
        exp_id=exp_id,
        model_type=model_type,
        file_index=file_index,
        record_params=record_params,
        expert_advice_str=expert_advice_str,
        hypothesis=hypothesis,
        round_index=round_index,
        attempt_in_round=attempt_in_round,
        conclusion=(
            (
                f"Not started: the {resource_type} MEASUREMENT could not be "
                f"established ({reason_code}), so no admission decision was "
                f"possible. This is an infrastructure condition and says "
                f"nothing about the candidate's size, speed or capacity. "
                f"{detail}"
            )
            if reason_code != "insufficient_headroom"
            else (
                f"Skipped before starting: the environment did not permit this "
                f"{resource_type} phase ({reason_code}). {detail}"
            )
        ),
        discovery=(
            "This is a statement about the machine at this moment, NOT about "
            "the candidate. It is not evidence that the model was too large."
        ),
        memory_update=(
            "Resource admission refused the phase. Do NOT reduce model "
            "capacity, batch size or segmentation size in response to it."
        ),
        memory_extra={
            "resource_type": resource_type,
            "reason_code": reason_code,
            "admission_evidence": admission_evidence or {},
        },
    )
    # B-C4c budget rule (operator, 2026-08-02): planning, pre-flight and
    # admission really ran, so the attempt slot really was used. Not
    # consuming it risks an unbounded retry loop while the device stays
    # busy. Consuming a control-flow budget is NOT blaming the
    # candidate — the same decoupling `gpu_contention` relies on — so
    # this is deliberately not a completed round and not a failure.
    record["counts_toward_attempt_budget"] = True
    record["counts_toward_completed_rounds"] = False
    return record


def _emit_record(sandbox, record: dict, *, status: dict | None = None) -> None:
    """Stamp evidence, validate, persist — in that order (B-C4a0 E3/E4).

    Every `save_record` in this module must be preceded by
    `ExperimentRecord.model_validate` on the same dict: one unvalidated
    write makes the whole iteration unresumable (`core/resume.py`
    rejects the run_output it cannot parse). That pairing was a
    convention repeated at nine sites; here it is structural.

    `status` is the executor's result dict when there is one. It is the
    single seam through which runtime evidence reaches a record, so a
    later admission refusal has exactly one place to attach its own.
    Passing `None` — the default, and what every non-executor path does
    today — stamps nothing, which is what those paths do now.
    """
    if status is not None:
        _attach_runtime_evidence(record, status)
    ExperimentRecord.model_validate(record)
    sandbox.save_record(record)


def _attach_runtime_evidence(record: dict, status: dict) -> None:
    """Carry the executor's bounded evidence and its verdict onto a record.

    Both keys are optional: absent evidence means it was not captured,
    never that the device was idle, and an absent verdict means
    ``unknown``, never that the candidate was at fault.

    One helper for both failure sites, which also keeps four conditional
    branches out of ``run()`` — pyright's strict mode refuses to analyse
    that method at all once it grows past its complexity ceiling, and a
    method too complex to type-check is one nobody is checking.
    """
    for key in ("gpu_evidence", "failure_attribution"):
        value = status.get(key)
        if value is not None:
            record[key] = value


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
    _emit_record(sandbox, record)
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
) -> PrephaseOutcome:
    """Measure this candidate on this card before a formal GPU launch.

    Returns the disposition `run()` must act on (O-7).

    **This function delegates; it does not decide.** Identity comparison,
    classification, authority validation and PR B admission all live in
    `core.runtime_control.prephase_admission`, which returns ONE
    disposition. `run()` is the giant orchestrator the decomposition rule
    governs, and reimplementing any of that here would put O-7's accounting
    in the one scope where it is hardest to see.

    **Two applicability rules, neither of them a feature flag.**

    *Trial rounds are not measured.* O-7 governs formal execution, and a
    trial round's admission posture already proceeds while recording what it
    could not prove. Measuring every trial round would double the GPU cost
    of the cheap screen.

    *No device identity means nothing to measure.* This is the same rule
    `_admission_refusal` already applies -- a CPU or pseudo run has no card
    to take a driver-visible reading from, and admission has nothing to
    decide. Unchanged behaviour there, not a refusal.
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
    # Resolved from the canonical production source so the probe cannot
    # drift from what `execute_inference` will really run.
    _inference_batch = resolve_inference_batch(model_type)

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
    _emit_record(sandbox, record)
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


def _oom_memory_wording(status: dict, *, phase: str) -> tuple[str, str]:
    """``(discovery, memory_update)`` for a MEASURED out-of-memory.

    One place decides what an OOM tells the planner, for both the
    training and the inference site, so the two cannot drift apart and
    the rule can be tested without standing up a whole agent run.

    Authority comes from the runtime's verdict. Only a measured
    candidate-capacity failure — one that would not have fitted with the
    whole device to itself — may ask for a smaller config. Everything
    else says so explicitly rather than staying silent: the agent can
    still SEE the OOM in memory, and silence lets it infer the shrink
    instruction the measurement refused to support.
    """
    if _may_advise_resource_reduction(status):
        if phase == "inference":
            return (
                "CUDA OOM during inference — reduce batch_size or model size.",
                "Inference OOM — the model trained but can't infer. Try smaller batch.",
            )
        return (
            "CUDA OOM — reduce model size, batch_size, or segmentation_size.",
            "This config exceeds GPU memory. Try smaller architecture.",
        )
    where = " during inference" if phase == "inference" else ""
    return (
        f"CUDA OOM{where}, but the measurement does NOT attribute it to this config "
        f"({_attribution_reason(status)}). This is not evidence that the model was "
        "too large.",
        "OOM not attributed to this config. Do NOT reduce model capacity, batch "
        "size or segmentation size in response to it.",
    )


def _attribution_reason(status: dict) -> str:
    """The runtime's own sentence for why, for the planner to read."""
    payload = status.get("failure_attribution") or {}
    outcome = payload.get("attribution") or "unknown"
    reason = payload.get("reason") or "no attribution was recorded for this failure"
    return f"{outcome}: {reason}"


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


def _build_denoised_filename(
    *,
    model_type: str,
    run_name: str,
    exp_id: str,
    file_index: int,
    base_dir: str,
) -> str:
    """Construct the absolute path to a denoised HDF5 artefact.

    Introduced by Bug A fix (PR #101 Gate 2 forensic, 2026-07-15). The
    inline closure at the round-scoring site previously returned a bare
    filename; downstream consumers that use the string verbatim
    (``HealthCheckContext.get_denoised_path`` per the peek helper's path
    contract in ``execute_tools/health_checks/_peek.py:20-24``) then
    failed to open the file at CWD. Extracting the construction to a
    module-level helper makes it unit-testable in isolation without
    standing up the full tuner loop.

    Args:
        model_type: Plugin model identifier (e.g. ``wavenet``).
        run_name: Chain-level run name (pins the workspace scope).
        exp_id: Per-round experiment id.
        file_index: Validation file index (0-19 for TIDMAD).
        base_dir: Sandbox output directory (usually
            ``TidmadSandbox.base_dir`` — the abspath of the run
            workspace). ``os.path.join(base_dir, absolute_filename)`` is
            safe because ``os.path.join`` discards the base when the
            right-hand side is absolute, so upstream code paths that
            still prepend ``data_dir`` are unaffected.

    Returns:
        Absolute path to the denoised HDF5 file, joinable and openable
        by any caller that receives it verbatim.
    """
    filename = f"abra_validation_denoised_{model_type}_{run_name}_{exp_id}_{file_index:04d}.h5"
    return os.path.join(base_dir, filename)


def _validate_data_config(
    trial_config: TrialConfig,
    segmentation_size: int,
    dataset_config=DATASET_CONFIG,
) -> None:
    """
    Validate integer relationships between dataset, PSD segments, ML segments,
    and sampling portions. Called in the agent loop where all configs converge.

    Raises:
        ValueError: If any constraint is violated.
    """
    psd = dataset_config.psd_segment_length
    segs_per_file = dataset_config.segments_per_file

    # 1. PSD segment must divide evenly into ML segments
    if psd % segmentation_size != 0:
        valid = sorted([d for d in range(100, psd + 1) if psd % d == 0 and d <= 100_000])
        raise ValueError(
            f"psd_segment_length ({psd}) must be divisible by "
            f"segmentation_size ({segmentation_size}). "
            f"Remainder: {psd % segmentation_size}. "
            f"Valid segmentation_size values: {valid}."
        )

    # 2. trial_portion must produce at least 1 PSD segment per file
    if trial_config.mode != "single_file":
        eval_segs = max(1, round(trial_config.trial_portion * segs_per_file))
        if eval_segs < 1:
            raise ValueError(
                f"trial_portion ({trial_config.trial_portion}) produces 0 segments "
                f"from {segs_per_file} segments per file."
            )

        # 3. train_portion must produce at least 1 PSD segment from the scope
        train_segs = max(1, round(trial_config.train_portion * eval_segs))
        if train_segs < 1:
            raise ValueError(
                f"train_portion ({trial_config.train_portion}) of "
                f"{eval_segs} scope segments produces 0 training segments."
            )


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
) -> str:
    """C9d: turn a REQUEST_PROBE pre-flight into a terminal decision.

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

    # V20 PR C1 / C-C3b. The capability is resolved by the TASK layer, which
    # knows which dataset it needs; generic runtime-control used to import
    # `TIDMAD_DATA_DIR` itself and so refused silently on any other task.
    # `data_dir` is already this function's parameter, so the resolved root
    # is the one the probe will actually use.
    from execute_tools.data_paths import resolve_tidmad_measurement_capability

    capability = resolve_tidmad_measurement_capability(dataset_root=data_dir)
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
    request = ProbeRequest(
        model_identity=model_type,
        model_family=classify_model_family(declared_family=model_type),
        train_steps=int(breakdown.get("total_train_steps") or 0),
        inference_batches=0,
        workload={
            "batch_size": int((active_params.get("train_config") or {}).get("batch_size", 1)),
            "segment_length": int(
                (active_params.get("model_config") or {}).get("segmentation_size", 0)
            ),
        },
    )
    print(f"  [PROBE] Resolving REQUEST_PROBE with a bounded live probe of {model_type}...")
    from core.runtime_control.probe_wiring import resolve_request_probe

    resolution = resolve_request_probe(
        request=request,
        budget=RuntimeBudget(time_seconds=max(time_budget_minutes, 1e-9) * 60.0),
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


def _best_trial_winner(memory_history: list) -> dict | None:
    """Highest-scoring HealthGate-valid trial from ``memory_history``.

    Trial metadata must agree in both the typed ``is_trial`` field and the
    persisted ``memory.time_mode`` field. Legacy, collapsed, non-finite, or
    incompletely observed records are not execution candidates.

    Used by both the forced-formal-round hyperparameter inheritance in
    :func:`_apply_mode_override_chain` (trial winner's config drives the
    formal round's plan) and the SkipFormal / bypass-formal-budget gates
    that consult the best trial score before deciding whether to run the
    formal round. The pre-5a ``reference_file_vector`` plumbing into
    ``sandbox.score_vector`` is gone — health checks now run tuner-side
    per ``docs/design/pluggable_health_checks.md`` §14 Option A.
    """
    candidates = [
        r
        for r in memory_history
        if is_valid_candidate(r)
        and r.get("is_trial") is True
        and (r.get("memory") or {}).get("time_mode") == "trial"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["denoising_score"])


def _should_skip_formal(
    winner: dict | None,
    *,
    threshold: float | None,
    gates_enabled: bool,
) -> bool:
    """Whether to skip the formal round.

    Takes the ALREADY-RESOLVED winner so that the skip gate, the bypass
    gate and the formal plan inheritance all judge the same record. Three
    independent `_best_trial_winner` calls would agree today only because
    the history does not change between them — a coincidence, not a
    guarantee.

    Two reasons to skip, and the first is V20 PR D's correction:

    - **no valid trial winner** — no trial ran, all failed, or none passed
      its HealthGate. There is no evidence that justifies the cost of a
      formal round. Previously this returned ``False`` (via
      ``winner is not None and …``), so *absence of evidence* was
      indistinguishable from *sufficient evidence* and the round ran
      anyway. A high-scoring INVALID trial cannot change this: it never
      becomes the winner.
    - the winner is below the skip threshold.

    ``gates_enabled`` is the feature switch. With the gates off this
    behaves exactly as before — including running formal with no valid
    winner — because the deltas are not consumed at all.
    """

    if not gates_enabled:
        return False
    if winner is None:
        return True
    if threshold is None or threshold == float("-inf"):
        return False
    return winner["denoising_score"] < threshold


def _should_bypass_formal_time_budget(
    winner: dict | None,
    *,
    threshold: float | None,
) -> bool:
    """Whether the winner clears the bypass threshold.

    Takes the same resolved winner the skip gate judged. On a chain with
    no formal incumbent the threshold resolves to ``-inf`` (the
    ``negative_infinity_bootstrap``), so the first valid trial always
    clears it and establishes the chain's first formal baseline.
    """

    if winner is None:
        return False
    if threshold is None or threshold == float("inf"):
        return False
    return winner["denoising_score"] >= threshold


def _resolve_formal_comparison_thresholds(
    *,
    reference_score: float | None,
    skip_min_delta: float,
    bypass_min_delta: float,
    gates_enabled: bool,
) -> tuple[float | None, float | None, float | None, str]:
    """Resolve invocation-wide formal comparison values once.

    The returned tuple is
    ``(reference, skip_threshold, bypass_threshold, source)``.
    V19 PR 1: this is the SINGLE authoritative computation — the gates,
    the startup banner, and the durable output metadata all consume these
    values, so the persisted thresholds provably equal what the gates
    used. ``reference_score=None`` (no chain incumbent) resolves to
    ``(None, None, None)`` and both gates short-circuit.
    """

    if reference_score is None:
        if not gates_enabled:
            # Feature off: the deltas are not consumed, so nothing is
            # resolved and both gates stay inert — pre-V20 behaviour,
            # unchanged.
            return (None, None, None, "gates_disabled")
        # V20 PR D §16.C — the negative-infinity bootstrap. A chain with
        # no restored HealthGate-valid formal incumbent has no reference,
        # and the pre-D behaviour was for both gates to fall silent: a
        # valid trial of 0.001 proceeded to formal, while an excellent
        # trial was still budget-blocked because bypass could not fire.
        # That is the v15 failure the bypass gate was written to fix,
        # reappearing because the reference is absent.
        #
        # -inf arms them instead: the first valid trial is never skipped,
        # always clears the bypass threshold, and establishes the chain's
        # first formal baseline. From the next iteration the restored
        # incumbent takes over and the gates tighten as the chain improves.
        #
        # There is no seeded artifact to use instead: every documented
        # paper baseline is trained-but-collapsed, and the historical seed
        # (5.5763) is the class-127 phantom.
        bootstrap = float("-inf")
        return (bootstrap, bootstrap, bootstrap, "negative_infinity_bootstrap")
    return (
        reference_score,
        reference_score + skip_min_delta,
        reference_score + bypass_min_delta,
        "restored_valid_formal_incumbent",
    )


def _json_safe_reference(value: float | None) -> float | None:
    """A reference or threshold that JSON can actually carry.

    ``-inf`` is a RESOLVER value, never a stored one (§16.C). Non-standard
    JSON ``Infinity`` is rejected by strict parsers, and `29ec0542` removed
    a fixed ``0.0`` default precisely because a stored sentinel became a
    silent policy — so an infinite bound persists as ``null`` and
    ``formal_comparison_reference_source`` carries the meaning instead.

    This also covers the pre-existing case of an operator explicitly
    disabling a gate with ``float("-inf")`` / ``float("inf")``, which could
    already put ``Infinity`` in an artifact.

    The test is ``math.isfinite``, deliberately, and NOT
    ``value in (-inf, +inf)``: that form compares by equality, and **NaN is
    not equal to itself**, so a NaN threshold would slip through and
    ``json.dump`` (whose ``allow_nan`` defaults to ``True``) would write a
    bare ``NaN`` into the artifact. One finite check covers all three
    non-standard values.
    """
    if value is None or not math.isfinite(value):
        return None
    return value


def _fmt_reference(value: float | None) -> str:
    """Render a resolved reference/threshold for banners and logs.

    ``None`` renders as ``"none"`` — never as ``0.0`` (the pre-V19
    defect value).
    """

    return "none" if value is None else f"{value:.4f}"


def _latest_trial_inference_marginal(memory_history: list) -> float | None:
    """Return the most recent successful trial round's measured per-PSD-segment
    inference cost in ms, or ``None`` if no qualifying record exists.

    refine_inference_time_estimator.md Commit D — feeds the formal round's
    time gate as ``inference_per_psd_seg_ms_hint`` so the gate uses the
    measured marginal instead of the legacy ``× 2.7`` ratio.

    Looks within the *current iteration's* memory history only — under the
    Commit A (Step 0) ``model_cfg`` inheritance rule, formal rounds within
    an iteration always run the trial-winner architecture, so a measurement
    from an earlier iter is for a different arch and must not be reused.
    The chain runner already partitions ``memory_history`` per iteration,
    so the caller passes whatever in-iter record list it already has.

    Eligibility predicate: ``status == "success"`` AND
    ``memory.time_mode == "trial"`` AND
    ``memory.inference_per_psd_seg_ms_measured`` is a positive float. We
    walk in reverse so an OOM-killed retry between two successful trials
    doesn't displace the most recent useful measurement.
    """
    for r in reversed(memory_history):
        if r.get("status") != "success":
            continue
        mem = r.get("memory") or {}
        if mem.get("time_mode") != "trial":
            continue
        v = mem.get("inference_per_psd_seg_ms_measured")
        if v is not None and v > 0:
            return float(v)
    return None


# --------------------------------------------------------------------- #
# Formal-round strategy aliasing + registry
# (refactor_formal_round_strategy.md — Phase 1 added the alias map; Phase 2
# wires the three handlers + dispatch table consumed below in
# :func:`_apply_mode_override_chain`.)
# --------------------------------------------------------------------- #
# The schema's ``@field_validator`` is the primary canonicalisation point
# and live callers always reach this function with the already-canonical
# name; this helper is a defensive second pass so unit tests, ad-hoc
# constructions, and any future internal caller that bypasses the schema
# still see consistent behavior.
_LEGACY_STRATEGY_ALIASES: dict[str, str] = {
    "inherit_best_trial": "full_clone",
    "llm_propose": "independent",
}


def _canonical_strategy(name: str) -> str:
    """Return the canonical name for ``name``, resolving any legacy alias.

    Unknown names pass through unchanged — schema-layer validation is
    responsible for rejecting them.
    """
    return _LEGACY_STRATEGY_ALIASES.get(name, name)


# --------------------------------------------------------------------- #
# Strategy handlers
# --------------------------------------------------------------------- #
# Each handler mutates ``plan`` in place using the trial ``winner`` record
# and returns the list of inherited field names (used by the audit log).
# Signature is uniform so the registry can dispatch without special-casing.
# Defensive ``.get()`` reads on ``winner["params"]["train_config"]`` keys —
# legacy/sparse records may omit ``epochs``/``batch_size``; in that case
# the planner's value survives rather than crashing the chain on KeyError.


def _strategy_full_clone(plan: ExperimentPlan, winner: dict) -> list[str]:
    """Inherit all five fields: model_cfg, loss_cfg, lr, epochs, batch_size.

    Production default. Required for the trial→formal inference-time
    measurement reuse landed in commits B-D of
    ``docs/refine_inference_time_estimator.md`` — the timing measurement
    must be for the same architecture the formal round runs.
    """
    p = winner["params"]
    plan.model_cfg = dict(p.get("model_config") or {})
    plan.loss_cfg = dict(p["loss_config"])
    plan.train_cfg["lr"] = p["train_config"]["lr"]
    inherited = ["model_cfg", "loss_cfg", "lr"]
    inherited_epochs = p["train_config"].get("epochs")
    if inherited_epochs is not None:
        plan.train_cfg["epochs"] = inherited_epochs
        inherited.append("epochs")
    inherited_bs = p["train_config"].get("batch_size")
    if inherited_bs is not None:
        plan.train_cfg["batch_size"] = inherited_bs
        inherited.append("batch_size")
    return inherited


def _strategy_hybrid_params(plan: ExperimentPlan, winner: dict) -> list[str]:
    """Inherit only loss_cfg + lr; planner keeps model_cfg, epochs, batch_size.

    Audit/exploration use case — lock the evaluation surface (loss + lr)
    but let the LLM scale capacity for the full-data pass. The time gate
    may reject the planner's heavier choice on the formal round; that is
    the intended trade-off, not a bug.
    """
    p = winner["params"]
    plan.loss_cfg = dict(p["loss_config"])
    plan.train_cfg["lr"] = p["train_config"]["lr"]
    return ["loss_cfg", "lr"]


def _strategy_independent(plan: ExperimentPlan, winner: dict) -> list[str]:
    """No-op. Planner's full plan survives verbatim.

    ``winner`` is unused but kept in the signature so the registry can
    dispatch without special-casing.
    """
    return []


_FORMAL_STRATEGY_REGISTRY: dict[str, Callable[[ExperimentPlan, dict], list[str]]] = {
    "full_clone": _strategy_full_clone,
    "hybrid_params": _strategy_hybrid_params,
    "independent": _strategy_independent,
}


def _apply_mode_override_chain(
    plan: ExperimentPlan,
    *,
    trial_allowed: bool,
    is_formal_round: bool,
    force_formal_round: bool,
    formal_round_strategy: str = "full_clone",
    memory_history: list | None = None,
    trial_winner: dict | None,
) -> ExperimentPlan:
    """Apply the run-level + last-round overrides to ``plan``.

    Three independent mutations can fire:

    1. ``trial_allowed=False`` — the run was launched without trial mode
       enabled, so every round forces ``plan.is_trial = False``.
    2. ``is_formal_round and force_formal_round`` — the last round of
       every iteration normally forces ``plan.is_trial = False`` so the
       run produces a cross-architecture comparable score. Operators can
       disable this override by passing ``--no-force_formal_round``.
    3. **Hyperparameter inheritance**, dispatched through
       :data:`_FORMAL_STRATEGY_REGISTRY` keyed by the canonical
       ``formal_round_strategy`` (legacy aliases ``inherit_best_trial`` /
       ``llm_propose`` resolve via :func:`_canonical_strategy`):

       * ``"full_clone"`` (default) — copies all 5 fields from the
         highest-scoring trial-mode success record. Production default;
         required for trial→formal inference-time measurement reuse.
       * ``"hybrid_params"`` — copies only ``loss_cfg`` + ``lr``;
         planner keeps ``model_cfg`` / ``epochs`` / ``batch_size``.
         Audit / exploration use case.
       * ``"independent"`` — no inheritance; planner's plan survives
         verbatim. ``plan.is_trial`` is still flipped to False.

       Shared no-winner fallback for ``full_clone`` and ``hybrid_params``:
       when ``memory_history`` carries no HealthGate-valid trial round, the
       planner's plan is preserved unchanged and a WARNING is logged
       (resilient — a messy trial stage shouldn't kill the chain).
       ``independent`` skips the warning because the strategy explicitly
       disclaims inheritance — there was nothing the user wanted to
       inherit.

       Why the default exists: V7 iter_001/iter_002 of explore_novel
       showed the LLM picking an untested ``focal_cw`` loss for the
       formal round despite all trial rounds using ``focal``; the
       resulting model collapsed to ~0 PSD output. V9 audit §7 found
       the same pattern at the architecture level — formal rounds
       emitting ``kernel_size=2``/``use_same_padding=False`` when both
       trial rounds used ``kernel_size=3``/``use_same_padding=True``.

    Audit log contract (refactor_formal_round_strategy.md §3):

    * ``[STRATEGY] formal_round_strategy=<canonical>`` — emitted once
      per forced formal round. Includes ``(alias_of:<legacy>)`` when
      the caller passed a legacy literal.
    * ``[FORMAL OVERRIDE] strategy=<canonical> winner=<exp_id>
      score=<float> inherited=<comma-list>`` on the inherit path, OR
      a WARNING line on the no-winner path (full_clone / hybrid_params).

    **``trial_winner`` is supplied, never re-derived** (V20 PR D, FU-D-6).
    The tuner resolves the iteration's HealthGate-valid trial winner ONCE
    at the formal-round boundary, and the skip gate, the bypass gate, the
    log line and this inheritance path all judge that same record. This
    function used to call ``_best_trial_winner(memory_history)`` itself.
    That agreed with the gates by construction — a formal round forces
    ``plan.is_trial = False``, so nothing it appends can satisfy the
    winner filter — but agreement by construction is not the same as one
    snapshot, and the frozen design (§16.F) requires the snapshot. Keeping
    the second call would leave a seam where a later state update between
    the gates and inheritance silently diverges the two.

    ``memory_history`` is still required, and is NOT redundant: the
    full-clone OOM-recovery branch inspects the LATEST record and the
    maximum ``round_index`` across the whole history, which a winner alone
    cannot answer.

    Mutates ``plan`` in place and returns it for caller-chaining.
    """
    if not trial_allowed:
        plan.is_trial = False
    if not (is_formal_round and force_formal_round):
        return plan

    plan.is_trial = False
    canonical = _canonical_strategy(formal_round_strategy)
    handler = _FORMAL_STRATEGY_REGISTRY.get(canonical)
    if handler is None:
        # Defensive — schema validation should reject unknown literals
        # before they reach this function. If a caller bypassed the
        # schema (e.g. an ad-hoc test fixture), surface the bypass loudly
        # and treat the request as ``independent`` to avoid silent
        # mis-inheritance.
        print(
            f"  [STRATEGY] WARNING: unknown strategy {formal_round_strategy!r} — "
            "treating as 'independent' (no inheritance)."
        )
        return plan

    print(
        f"  [STRATEGY] formal_round_strategy={canonical}"
        + (f" (alias_of:{formal_round_strategy})" if canonical != formal_round_strategy else "")
    )

    winner = trial_winner
    if winner is None:
        if canonical == "independent":
            # ``independent`` explicitly disclaims inheritance — a missing
            # winner is not a warning condition. Still emit one structured
            # log line so the audit trail is uniform.
            print(f"  [FORMAL OVERRIDE] strategy={canonical} winner=none inherited=(none)")
        else:
            print(
                "  [FORMAL OVERRIDE] WARNING: no successful trial round is HealthGate-valid "
                "in this iteration — planner's plan unchanged. "
                "Score may be unreliable."
            )
        return plan

    latest_record = (memory_history or [])[-1] if memory_history else None
    recovering_from_formal_oom = (
        canonical == "full_clone"
        and isinstance(latest_record, dict)
        and latest_record.get("status") == "error_training_oom"
        and (latest_record.get("memory") or {}).get("round_index")
        == (
            max(
                (
                    (record.get("memory") or {}).get("round_index", 0)
                    for record in (memory_history or [])
                ),
                default=0,
            )
        )
    )
    if recovering_from_formal_oom:
        # A full clone is the right first formal attempt, but repeatedly
        # restoring the winning architecture and batch size makes the
        # planner's OOM recovery proposal impossible to execute. Preserve
        # the validated loss surface and learning rate while allowing the
        # planner to reduce model capacity and/or batch size on retries.
        inherited = _strategy_hybrid_params(plan, winner)
        print(
            "  [FORMAL RECOVERY] prior formal attempt OOMed — "
            "preserving planner model_cfg/batch_size/epochs"
        )
    else:
        inherited = handler(plan, winner)
    print(
        f"  [FORMAL OVERRIDE] strategy={canonical} "
        f"winner={winner['exp_id']!r} score={winner['denoising_score']:.4f} "
        f"inherited={','.join(inherited) if inherited else '(none)'}"
    )
    return plan


def _apply_degeneracy_reaction(
    score_results: dict,
    plan: ExperimentPlan,
    penalty_score: float | None,
) -> tuple[bool, str | None]:
    """Generic policy reaction to tuner-side HealthGate evaluation.

    Post-commit-5b, the health-check verdict is produced by tuner-side
    gate evaluation (``get_gates_for_position`` → ``evaluate_gate`` →
    ``resolve_action``) and mapped to the legacy ``is_degenerate`` /
    ``failure_reason`` contract via ``_gate_results_to_score_meta``. By
    the time this helper runs, ``score_results`` already carries the
    mapping's output — ``is_degenerate=True`` on any non-``CONTINUE``
    gate action, ``failure_reason`` pipe-concatenated across failed
    gates prefixed by gate_id. See
    ``docs/design/pluggable_health_checks.md`` §4 and §8.

    The agent's role here is purely **policy** — translate the task-side
    health signal into the right tuner-level reaction:

    * Trial rounds are immune per policy (AMB-5b-A → A). The reaction
      never nulls the score when ``plan.is_trial`` is True, but the
      ``failure_reason`` and ``gate_action`` fields still propagate to
      the record so the next planner sees the diagnostic.
    * On a degenerate (or gate-flagged) **formal** round:

      - ``penalty_score is None`` → null ``denoising_score`` so the round
        cannot be picked as 'best' by the planner's max-score logic.
      - ``penalty_score`` is a float → use it as ``denoising_score`` so
        the planner's rank-ordering still includes the failure but
        strictly below any healthy success.

      In both cases the caller wraps the record with
      ``status='failed_mode_collapse'`` and preserves ``failure_reason``
      verbatim for the next iteration's planner.

    Args:
        score_results: Mutable dict — the ``score_res["results"]`` block
            written by the scoring branch. Must contain ``is_degenerate``
            and ``failure_reason`` keys (defensive defaults applied if
            absent). ``denoising_score`` is mutated in place when the
            reaction fires.
        plan: The current round's validated ``ExperimentPlan``. Only
            ``plan.is_trial`` is read.
        penalty_score: The operator-supplied
            ``HyperparamTuningInput.degenerate_penalty_score``.

    Returns:
        ``(is_degenerate, failure_reason)`` — the unmutated original
        signal so the caller can populate ``ExperimentRecord.status`` and
        ``ExperimentRecord.failure_reason`` independently of any score
        mutation.
    """
    is_degenerate = score_results.get("is_degenerate", False)
    failure_reason = score_results.get("failure_reason")
    if is_degenerate and not plan.is_trial:
        print(f"  [HEALTH CHECK] {failure_reason}")
        score_results["denoising_score"] = penalty_score
    return is_degenerate, failure_reason


# ---------------------------------------------------------------------------
# Tuner-side gate-integration helpers (commit-5b).
# ---------------------------------------------------------------------------


def _gate_results_to_score_meta(
    gate_results: list[GateResult],
    resolved_action: GateAction,
) -> tuple[bool, str | None, str]:
    """Map gate evaluation output to the legacy score-meta contract.

    Contract: ``(is_degenerate, failure_reason, gate_action_str)`` — the
    first two feed the existing ``_apply_degeneracy_reaction`` policy;
    the third goes into ``ExperimentRecord.gate_action`` for observability.

    Semantic (M8 §3.2 revision, 2026-07-16):

      * ``is_degenerate`` reflects only **blocking** gate failures — a
        failed gate whose ``action`` is in ``BLOCKING_ACTIONS``
        (``INVALIDATE_ROUND``, ``SKIP_TO_FORMAL``, ``SKIP_ITER``). A
        recording-only gate that returns ``passed=False`` with
        ``action=CONTINUE`` never sets ``is_degenerate=True``, so it
        cannot silently zero-out a formal round's score via
        ``_apply_degeneracy_reaction``.
      * ``failure_reason`` still concatenates ALL failed gates (blocking
        and recording) for observability — recording-only diagnostics
        remain visible in the round record without changing routing.
      * ``resolved_action`` controls only routing and is always returned
        unchanged for record observability.

    Pre-M8 behaviour flagged ``is_degenerate=True`` for any failed gate
    (including recording-only). See docs/design/m8_gate_coverage_and_diversity_metrics_execution_plan.md
    §3.2 and Caveat A discussion for the bug this fix addresses.
    """
    failed_gates = [gr for gr in gate_results if not gr.passed]
    if not failed_gates:
        return False, None, resolved_action.value

    # is_degenerate reflects blocking failures only (M8 §3.2 fix).
    failed_blocking = [gr for gr in failed_gates if gr.action in BLOCKING_ACTIONS]

    # failure_reason concatenates ALL failed gates for observability —
    # blocking AND recording. The tuner records this string in the
    # round's failure_reason field regardless of is_degenerate outcome.
    failure_reason: str | None = " | ".join(
        f"[{gr.gate_id}] {gr.failure_reason}" for gr in failed_gates if gr.failure_reason
    )
    if failed_blocking and not failure_reason:
        failure_reason = f"gate action {resolved_action.value} with no reason"
    elif not failure_reason:
        # No blocking failure AND every failed recording gate had an empty
        # reason. There is nothing degenerate to flag and no reason to
        # surface — clean pass-through with the CONTINUE routing.
        failure_reason = None

    is_degenerate = bool(failed_blocking)
    return is_degenerate, failure_reason, resolved_action.value


def _merge_score_validity_failure(
    denoising_score: float | None,
    *,
    is_degenerate: bool,
    failure_reason: str | None,
) -> tuple[bool, str | None]:
    """Treat a missing/non-finite scorer result as a completed collapse.

    HealthGates fire only at configured round positions. Numerical validity,
    however, is an invariant of every completed scoring attempt; otherwise a
    round without a configured gate can be persisted as ``success`` with a
    JSON-null score. This helper changes classification/feedback only and does
    not alter the frozen scoring formula or denominator policy.
    """
    if denoising_score is not None and math.isfinite(denoising_score):
        return is_degenerate, failure_reason
    validity_reason = (
        "[scoring_validity] denoising_score is None or non-finite; "
        "the model produced no valid denoising signal"
    )
    if failure_reason:
        validity_reason = f"{failure_reason} | {validity_reason}"
    return True, validity_reason


def _should_break_iteration(resolved_action: GateAction) -> bool:
    """SKIP_ITER → break the tuner's outer while loop. Chain-level caller
    of ``run()`` moves to the next chain iteration on return."""
    return resolved_action is GateAction.SKIP_ITER


def _should_skip_to_formal(
    resolved_action: GateAction,
    is_formal_round: bool,
) -> bool:
    """SKIP_TO_FORMAL → jump ``completed_rounds`` so the next while
    iteration lands on the formal round. Guarded when already on the
    formal round — no re-run."""
    return resolved_action is GateAction.SKIP_TO_FORMAL and not is_formal_round


def _non_retryable_termination_message(
    *, scope_violation_reason: str | None, evidence_channel_failure: str | None
) -> str:
    """Operator-facing line for a non-retryable termination. The evidence
    channel outranks the scope violation (C9c): if the channel is broken,
    every other classification this run made is suspect."""
    if evidence_channel_failure:
        return (
            "  [RUNTIME] Evidence-channel failure (infrastructure) — terminating "
            f"the chain: {evidence_channel_failure}"
        )
    return (
        f"  [DATASCOPE] Non-retryable scope violation — terminating run: {scope_violation_reason}"
    )


def _compute_termination_state(
    *,
    completed_rounds: int,
    max_rounds: int,
    consecutive_fails: int,
    max_fail_rounds: int,
    gate_aborted: bool,
    scope_violation_reason: str | None = None,
    evidence_channel_failure: str | None = None,
) -> tuple[str, str]:
    """Compute ``(run_status, termination_reason)`` from loop-exit state.

    Precedence (highest → lowest):
     -1. ``evidence_channel_failure`` set (C9c) → ``("failed",
         "infrastructure_abort")``. Outranks everything, including a
         scope violation: when the evidence channel is broken we cannot
         even trust the classification of the other failures, and the
         chain must halt rather than retry into the same environment.
      0. ``scope_violation_reason`` set (DataScope DS5) → ``("failed",
         "scope_violation")``. A configuration/invariant failure —
         deterministic on retry, so it outranks even the deliberate gate
         abort: nothing about this run's results is trustworthy.
      1. ``gate_aborted=True`` (SKIP_ITER from a health gate) →
         ``("partial", "aborted_by_gate")``. Wins over every other
         condition because the gate signal is a deliberate abort, not a
         boundary condition.
      2. ``completed_rounds >= max_rounds`` → ``("completed", "completed")``.
      3. ``consecutive_fails >= max_fail_rounds`` → ``("partial",
         "aborted_fail_rounds")``.
      4. Fallback → ``("partial", "completed")``.

    See ``docs/design/pluggable_health_checks.md`` §4 and the audit
    Gap #3 fix in the follow-up to commit-5b.
    """
    if evidence_channel_failure:
        return "failed", "infrastructure_abort"
    if scope_violation_reason:
        return "failed", "scope_violation"
    if gate_aborted:
        return "partial", "aborted_by_gate"
    if completed_rounds >= max_rounds:
        return "completed", "completed"
    if consecutive_fails >= max_fail_rounds:
        return "partial", "aborted_fail_rounds"
    return "partial", "completed"


def _resolve_sample_set_cfg(
    mode: str,
    agent_input: HyperparamTuningInput,
    plan: ExperimentPlan,
) -> dict:
    """Resolve sample-set config for one round based on trial/formal/single_file mode.

    Formal-mode eval strategy is locked to ``snapshot``; the portion defaults
    to 1.0 (full clone — Phase M §12.2 production contract for cross-arch
    score comparability) but is now operator-controllable via
    ``agent_input.formal_eval_portion`` for smoke / CI runs that need to fit
    a tight ``formal_time_budget_minutes`` (Phase R, §13). Formal training
    levers come from ``agent_input.formal_*``. Trial-mode values come from
    the planner. Single-file mode uses safe defaults.

    Args:
        mode: One of ``"trial"``, ``"formal"``, ``"single_file"``.
        agent_input: Carries the operator-configurable ``formal_*`` knobs.
        plan: Planner-produced ExperimentPlan (source of trial-mode values).

    Returns:
        A dict with exactly 5 keys — ``trial_strategy``, ``trial_portion``,
        ``train_portion``, ``eval_strategy``, ``eval_portion``.
    """
    if mode == "formal":
        return {
            "trial_strategy": agent_input.formal_strategy,
            "trial_portion": agent_input.formal_portion,
            "train_portion": agent_input.formal_train_portion,
            "eval_strategy": "snapshot",
            "eval_portion": agent_input.formal_eval_portion,
        }
    if mode == "trial":
        return {
            "trial_strategy": plan.trial_strategy,
            "trial_portion": plan.trial_portion,
            "train_portion": plan.train_portion,
            "eval_strategy": plan.eval_strategy,
            "eval_portion": plan.eval_portion,
        }
    # single_file
    return {
        "trial_strategy": "snapshot",
        "trial_portion": plan.trial_portion,
        "train_portion": plan.train_portion,
        "eval_strategy": "snapshot",
        "eval_portion": 1.0,
    }


def _copy_seed_plugin(src: str, dst_dir: str) -> str:
    """Copy the seed plugin file into the run's plugin directory.

    The schema validator (``HyperparamTuningInput._validate_seed_plugin_path``)
    already checked that ``src`` exists and declares a matching
    ``PLUGIN_MODEL_TYPE`` — this helper just performs the file copy.

    When ``src`` and the destination resolve to the same file, the copy is
    skipped (avoids ``shutil.SameFileError``). Otherwise the destination is
    overwritten — when ``run_name`` is reused, the most recent caller's
    seed wins.

    See docs/run_scoped_plugins.md (Phase 3).
    """
    import shutil

    dst = os.path.join(dst_dir, os.path.basename(src))
    if os.path.abspath(src) == os.path.abspath(dst):
        return dst
    shutil.copy2(src, dst)
    return dst


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


# _serialize_expert_advice is now shared — imported as serialize_expert_advice
_serialize_expert_advice = serialize_expert_advice


# ---------------------------------------------------------------------------
# Gate-exhaustion feedback helper (Phase K.7 — see §10.13)
# ---------------------------------------------------------------------------


def _collect_disallowed_patterns(
    records: list,
    *,
    vram_budget_gb: float | None,
    time_budget_minutes: float | None,
) -> list:
    """Return the sorted union of architectural-pattern tags for records that
    exceeded the §7 Decision 2 thresholds.

    For each gate-rejected attempt (``status in {"skipped_oom_risk",
    "skipped_time_risk"}``) we compute its individual ``time_factor`` and
    ``vram_factor`` from the per-attempt ``memory`` block. Only attempts that
    overshot by at least ``TIME_FACTOR_THRESHOLD`` (time) or
    ``VRAM_FACTOR_THRESHOLD`` (VRAM) contribute tags — a marginal 1.3× is a
    hyperparameter choice, not an architectural infeasibility, and banning the
    whole class on it would over-constrain the next proposer. See
    ``docs/reliable_resource_proposer.md`` §7 Decision 2 + §9 Commit 3.

    Non-gate failures (code bugs, schema violations) are skipped regardless of
    factor — their failure mode is not resource-structural.

    Returns a deterministic sorted list (empty if no attempt qualifies).
    """
    tags: set = set()
    for r in records:
        if r.get("status") not in {"skipped_oom_risk", "skipped_time_risk"}:
            continue
        mem = r.get("memory") or {}

        vram_factor = None
        if vram_budget_gb and vram_budget_gb > 0:
            vram_est = mem.get("vram_estimate_gb")
            if vram_est is not None:
                vram_factor = float(vram_est) / float(vram_budget_gb)

        time_factor = None
        if time_budget_minutes and time_budget_minutes > 0:
            time_est = mem.get("time_estimate_minutes")
            if time_est is not None:
                time_factor = float(time_est) / float(time_budget_minutes)

        exceeds_time = time_factor is not None and time_factor > TIME_FACTOR_THRESHOLD
        exceeds_vram = vram_factor is not None and vram_factor > VRAM_FACTOR_THRESHOLD
        if not (exceeds_time or exceeds_vram):
            continue

        model_type = r.get("model_type") or ""
        model_config = r.get("model_config") or {}
        tags.update(tag_architecture(model_type, model_config))

    return sorted(tags)


def _build_trial_validity_feedback(
    records: list,
    *,
    formal_skipped_for_no_valid_winner: bool,
    healthgate_mode: str | None,
) -> TrialValidityFeedback | None:
    """Report an iteration whose trials produced no valid candidate.

    V20 PR D (D-C6). Fires when trial-mode records exist but
    :func:`_best_trial_winner` would return ``None`` — the planner
    otherwise sees an iteration that simply produced no good score, with no
    way to tell "nothing ran" from "everything collapsed".

    **A separate carrier from `_build_gate_exhaustion`, and the audit is
    why.** That helper's two triggers both require budget-gated records
    (``skipped_oom_risk`` / ``skipped_time_risk``); an all-invalid
    iteration has records that RAN and SUCCEEDED and then failed their
    scientific gates, so neither trigger fires and the block would be
    ``None``. Merging them would need a third trigger with unrelated
    semantics inside a structure whose every field means "budget
    exhaustion", and would tell the planner to propose something
    *lighter* when the actual evidence says propose something that does
    not *collapse*.

    **Facts only, task-generic.** Gate names, reasons and metrics are
    passed through exactly as the gate system recorded them. Nothing here
    interprets a metric or suggests a remedy — that is the planner's job,
    and task-specific advice in workflow code is what §3.3 forbids.

    Returns ``None`` when at least one trial is valid, so a healthy run's
    downstream prompt is byte-identical to before.
    """
    trials = [
        r
        for r in records
        if r.get("is_trial") is True and (r.get("memory") or {}).get("time_mode") == "trial"
    ]
    if not trials:
        return None  # no trial stage at all is a different fact, not this one
    if any(is_valid_candidate(r) for r in trials):
        return None  # a valid winner exists; nothing to report

    outcomes: list[InvalidTrialOutcome] = []
    invalid = unknown = execution_failures = 0
    evidence_absent: list[str] = []

    for record in trials:
        exp_id = record.get("exp_id")
        status = str(record.get("status", "unknown"))
        validity = classify_candidate_health(record)

        if status != "success":
            # The evidence is ABSENT, not negative: nothing was scored, so
            # no gate could have judged it.
            execution_failures += 1
        elif validity is CandidateHealthValidity.INVALID:
            invalid += 1
        else:
            unknown += 1

        results = [r for r in (record.get("health_gate_results") or []) if isinstance(r, dict)]
        if status == "success" and validity is CandidateHealthValidity.UNKNOWN:
            # UNKNOWN is not a soft "invalid" — it means the gate evidence
            # was incomplete, and saying WHICH way is the difference
            # between "the model collapsed" and "we cannot tell". A
            # partial gate set reads exactly like a pass unless named.
            evidence_absent.append(
                f"{exp_id or '<unidentified>'}: validity unknown — "
                + (
                    "no gate results persisted"
                    if not results
                    else f"only {len(results)} gate result(s) persisted, required set incomplete"
                )
            )

        failed_names = sorted(
            str(r.get("gate_name"))
            for r in results
            if r.get("gate_name")
            and (
                r.get("check_passed") is False or r.get("would_invalidate_under_production_policy")
            )
        )
        reasons = sorted({str(r["failure_reason"]) for r in results if r.get("failure_reason")})
        metrics: dict[str, float | int | str] = {}
        for r in results:
            for key, value in (r.get("key_metrics") or {}).items():
                if isinstance(value, (int, float, str)) and not isinstance(value, bool):
                    metrics[f"{r.get('gate_name')}.{key}"] = value

        outcomes.append(
            InvalidTrialOutcome(
                exp_id=exp_id,
                status=status,
                health_validity=validity,
                failed_gate_names=failed_names,
                failure_reasons=reasons,
                key_metrics=metrics,
            )
        )

    return TrialValidityFeedback(
        trial_records_considered=len(trials),
        invalid_count=invalid,
        unknown_validity_count=unknown,
        execution_failure_count=execution_failures,
        outcomes=outcomes,
        formal_skipped_for_no_valid_winner=formal_skipped_for_no_valid_winner,
        healthgate_mode=healthgate_mode,
        evidence_absent=evidence_absent,
    )


def _build_gate_exhaustion(
    records: list,
    active_mode: Literal["trial", "formal"],
    vram_budget_gb: float | None,
    time_budget_minutes: float | None,
    *,
    consecutive_fail_rounds_at_exit: int = 0,
    max_fail_rounds: int = 0,
    completed_rounds: int = 0,
) -> GateExhaustionInfo | None:
    """
    Build the structured gate-exhaustion report for the next iteration's
    proposer (§10.13). Two triggers can fire:

    **Trigger A (Phase K, §10.13.1)** — *no rounds ever succeeded*. Fires when:

      * ``records`` is non-empty (the tuner actually ran).
      * No record has ``status == "success"``.
      * At least one record has ``status in {"skipped_oom_risk",
        "skipped_time_risk"}`` (failure was budget-related, not a code
        bug or schema violation).

    **Trigger B (Phase L, §11.4)** — *some rounds succeeded then the
    search collapsed*. Fires when:

      * ``consecutive_fail_rounds_at_exit >= max_fail_rounds > 0``
        (the outer loop aborted on the consecutive-failure brake, not
        on ``max_rounds``).
      * ``completed_rounds > 0`` (at least one round succeeded — this
        is the "after K successful rounds" framing that distinguishes
        Trigger B from Trigger A).
      * Burst gate-skip ratio ``>= 0.5`` — the trailing failure burst
        (records whose ``round_index == completed_rounds + 1``) was
        dominated by VRAM/time gate skips, not by code bugs.

    Returns ``None`` if neither trigger fires. When Trigger B fires, the
    report is keyed off the burst records (focused on the round that
    repeatedly failed). When Trigger A fires, the report is keyed off
    the full record list (no successful round to anchor on).
    """
    if not records:
        return None

    def _factor(estimate, budget):
        if estimate is None or budget is None or budget <= 0:
            return None
        return round(float(estimate) / float(budget), 3)

    def _worst_factor(rs, key, budget):
        if budget is None or budget <= 0:
            return None
        ests = [(r.get("memory") or {}).get(key) for r in rs]
        ests = [e for e in ests if e is not None]
        if not ests:
            return None
        return round(max(float(e) for e in ests) / float(budget), 3)

    # --- Trigger B (Phase L) — some successes, then a fail-round burst.
    trigger_b_fired = False
    burst_records: list = []
    if (
        max_fail_rounds > 0
        and consecutive_fail_rounds_at_exit >= max_fail_rounds
        and completed_rounds > 0
    ):
        burst_round_idx = completed_rounds + 1
        burst_records = [
            r for r in records if (r.get("memory") or {}).get("round_index") == burst_round_idx
        ]
        if burst_records:
            burst_gate = [
                r
                for r in burst_records
                if r.get("status") in {"skipped_oom_risk", "skipped_time_risk"}
            ]
            if len(burst_gate) / len(burst_records) >= 0.5:
                trigger_b_fired = True

    # --- Trigger A (Phase K) — no successes at all + budget-gated.
    trigger_a_fired = False
    if not any(r.get("status") == "success" for r in records) and any(
        r.get("status") in {"skipped_oom_risk", "skipped_time_risk"} for r in records
    ):
        trigger_a_fired = True

    if not (trigger_a_fired or trigger_b_fired):
        return None

    # When Trigger B fires, focus the report on the burst (more
    # actionable for the proposer); otherwise fall back to all records.
    report_records = burst_records if trigger_b_fired else records

    vram_gated = [r for r in report_records if r.get("status") == "skipped_oom_risk"]
    time_gated = [r for r in report_records if r.get("status") == "skipped_time_risk"]
    other = [
        r
        for r in report_records
        if r.get("status") not in {"skipped_oom_risk", "skipped_time_risk"}
    ]

    baseline_mem = report_records[0].get("memory") or {}
    baseline_vram = baseline_mem.get("vram_estimate_gb")
    baseline_time = baseline_mem.get("time_estimate_minutes")

    baseline_vram_factor = _factor(baseline_vram, vram_budget_gb)
    baseline_time_factor = _factor(baseline_time, time_budget_minutes)
    worst_vram_factor = _worst_factor(report_records, "vram_estimate_gb", vram_budget_gb)
    worst_time_factor = _worst_factor(report_records, "time_estimate_minutes", time_budget_minutes)

    disallowed_patterns = _collect_disallowed_patterns(
        report_records,
        vram_budget_gb=vram_budget_gb,
        time_budget_minutes=time_budget_minutes,
    )

    if trigger_b_fired:
        summary = _render_gate_exhaustion_trigger_b_summary(
            total=len(report_records),
            vram_gated=len(vram_gated),
            time_gated=len(time_gated),
            other=len(other),
            active_mode=active_mode,
            vram_budget_gb=vram_budget_gb,
            time_budget_minutes=time_budget_minutes,
            baseline_vram=baseline_vram,
            baseline_vram_factor=baseline_vram_factor,
            baseline_time=baseline_time,
            baseline_time_factor=baseline_time_factor,
            worst_vram_factor=worst_vram_factor,
            worst_time_factor=worst_time_factor,
            consecutive_fail_rounds_at_exit=consecutive_fail_rounds_at_exit,
            completed_rounds=completed_rounds,
        )
    else:
        summary = _render_gate_exhaustion_summary(
            total=len(report_records),
            vram_gated=len(vram_gated),
            time_gated=len(time_gated),
            other=len(other),
            active_mode=active_mode,
            vram_budget_gb=vram_budget_gb,
            time_budget_minutes=time_budget_minutes,
            baseline_vram=baseline_vram,
            baseline_vram_factor=baseline_vram_factor,
            baseline_time=baseline_time,
            baseline_time_factor=baseline_time_factor,
            worst_vram_factor=worst_vram_factor,
            worst_time_factor=worst_time_factor,
        )

    return GateExhaustionInfo(
        total_attempts=len(report_records),
        vram_gated_attempts=len(vram_gated),
        time_gated_attempts=len(time_gated),
        other_failure_attempts=len(other),
        active_mode=active_mode,
        vram_budget_gb=vram_budget_gb,
        time_budget_minutes=time_budget_minutes,
        baseline_vram_estimate_gb=baseline_vram,
        baseline_vram_factor=baseline_vram_factor,
        baseline_time_estimate_minutes=baseline_time,
        baseline_time_factor=baseline_time_factor,
        worst_vram_factor=worst_vram_factor,
        worst_time_factor=worst_time_factor,
        summary_message=summary,
        disallowed_architectural_patterns=disallowed_patterns,
    )


def _render_gate_exhaustion_summary(
    *,
    total: int,
    vram_gated: int,
    time_gated: int,
    other: int,
    active_mode: str,
    vram_budget_gb: float | None,
    time_budget_minutes: float | None,
    baseline_vram: float | None,
    baseline_vram_factor: float | None,
    baseline_time: float | None,
    baseline_time_factor: float | None,
    worst_vram_factor: float | None,
    worst_time_factor: float | None,
) -> str:
    """One-paragraph LLM-readable synthesis of the gate-exhaustion state.

    The wording adapts to which axis was the binding ceiling — VRAM-only,
    time-only, or mixed — so the next proposer reads a clear instruction
    rather than a generic "everything failed" line. See §10.13.3.
    """
    parts = []

    # Lead sentence — what failed and how widely.
    if vram_gated and not time_gated:
        parts.append(
            f"All {total} attempt(s) ({vram_gated} VRAM-gated, {other} other "
            f"failures) were rejected by the pre-flight VRAM gate."
        )
    elif time_gated and not vram_gated:
        parts.append(
            f"All {total} attempt(s) ({time_gated} time-gated, {other} other "
            f"failures) were rejected by the pre-flight time gate."
        )
    else:
        parts.append(
            f"Of {total} attempt(s), {vram_gated} were rejected by the VRAM "
            f"gate and {time_gated} by the time gate "
            f"({other} other failures); none ever trained successfully."
        )

    # VRAM diagnostic.
    if vram_budget_gb is not None and baseline_vram is not None:
        parts.append(
            f"The baseline already estimated {baseline_vram:.2f} GB VRAM vs "
            f"the {vram_budget_gb:.2f} GB {active_mode} budget "
            f"(factor {baseline_vram_factor:.2f}×); the tuner's mutations "
            f"reached factor {worst_vram_factor:.2f}× at worst."
        )
    elif vram_budget_gb is not None and worst_vram_factor is not None:
        parts.append(
            f"VRAM estimates reached factor {worst_vram_factor:.2f}× of the "
            f"{vram_budget_gb:.2f} GB {active_mode} budget at worst "
            f"(baseline estimate not recorded)."
        )

    # Time diagnostic.
    if time_budget_minutes is not None and baseline_time is not None:
        parts.append(
            f"The baseline estimated {baseline_time:.2f} min wall-time vs the "
            f"{time_budget_minutes:.2f} min {active_mode} budget "
            f"(factor {baseline_time_factor:.2f}×); worst was factor "
            f"{worst_time_factor:.2f}×."
        )
    elif time_budget_minutes is not None and worst_time_factor is not None:
        parts.append(
            f"Time estimates reached factor {worst_time_factor:.2f}× of the "
            f"{time_budget_minutes:.2f} min {active_mode} budget at worst "
            f"(baseline estimate not recorded)."
        )

    # Verdict line — point the next proposer at the right lever.
    if vram_gated and not time_gated:
        parts.append(
            "Verdict: the proposed architecture is too heavy for the active "
            "VRAM budget. Reduce parameter count and/or layer count so the "
            "next baseline lands below the budget."
        )
    elif time_gated and not vram_gated:
        parts.append(
            "Verdict: the proposed architecture is too slow for the active "
            "time budget. Reduce model depth/width or computation per step "
            "so the next baseline lands below the budget."
        )
    else:
        parts.append(
            "Verdict: the proposed architecture is over budget on multiple "
            "axes. Both parameter count AND per-step compute must come down."
        )

    return " ".join(parts)


def _render_gate_exhaustion_trigger_b_summary(
    *,
    total: int,
    vram_gated: int,
    time_gated: int,
    other: int,
    active_mode: str,
    vram_budget_gb: float | None,
    time_budget_minutes: float | None,
    baseline_vram: float | None,
    baseline_vram_factor: float | None,
    baseline_time: float | None,
    baseline_time_factor: float | None,
    worst_vram_factor: float | None,
    worst_time_factor: float | None,
    consecutive_fail_rounds_at_exit: int,
    completed_rounds: int,
) -> str:
    """One-paragraph LLM-readable synthesis for the Phase L Trigger B
    case — the search collapsed into a fail-round burst after some
    successful rounds (§11.4). Lead sentence makes the
    "model too large after K successful rounds" framing explicit so the
    next proposer reduces model size before exploring further.
    """
    # Lead sentence — Trigger B framing per §11.4 spec.
    if vram_gated and not time_gated:
        gated_axis = "VRAM"
    elif time_gated and not vram_gated:
        gated_axis = "time"
    else:
        gated_axis = "VRAM/time"
    parts = [
        f"Model too large — {consecutive_fail_rounds_at_exit} consecutive "
        f"rounds exhausted attempts at the {gated_axis} gate after "
        f"{completed_rounds} successful round(s); proposer should reduce "
        f"model size before the next iteration."
    ]
    parts.append(
        f"Burst breakdown: {total} attempt(s) "
        f"({vram_gated} VRAM-gated, {time_gated} time-gated, "
        f"{other} other failures)."
    )

    # VRAM diagnostic.
    if vram_budget_gb is not None and baseline_vram is not None:
        parts.append(
            f"Burst baseline estimated {baseline_vram:.2f} GB VRAM vs the "
            f"{vram_budget_gb:.2f} GB {active_mode} budget "
            f"(factor {baseline_vram_factor:.2f}×); worst factor in burst "
            f"reached {worst_vram_factor:.2f}×."
        )
    elif vram_budget_gb is not None and worst_vram_factor is not None:
        parts.append(
            f"Burst VRAM estimates reached factor {worst_vram_factor:.2f}× "
            f"of the {vram_budget_gb:.2f} GB {active_mode} budget at worst "
            f"(burst baseline estimate not recorded)."
        )

    # Time diagnostic.
    if time_budget_minutes is not None and baseline_time is not None:
        parts.append(
            f"Burst baseline estimated {baseline_time:.2f} min wall-time vs "
            f"the {time_budget_minutes:.2f} min {active_mode} budget "
            f"(factor {baseline_time_factor:.2f}×); worst factor in burst "
            f"reached {worst_time_factor:.2f}×."
        )
    elif time_budget_minutes is not None and worst_time_factor is not None:
        parts.append(
            f"Burst time estimates reached factor {worst_time_factor:.2f}× "
            f"of the {time_budget_minutes:.2f} min {active_mode} budget at "
            f"worst (burst baseline estimate not recorded)."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Node implementation
# ---------------------------------------------------------------------------


def _validate_history_and_lock(
    workspace: str,
    run_invariants: RunInvariants,
    existing_history: list[dict[str, Any]],
    lock_was_present: bool,
) -> None:
    """DS6b — ingress validation + deferred lock creation.

    On a lock-less workspace, every restored FINAL record's invariant stamps
    are checked BEFORE the lock is stamped (error records deliberately carry
    no stamps — DS5b — and are skipped), so a legacy workspace is never
    silently locked. A lock-present workspace was already validated at
    startup; its records were produced under that lock.
    """
    if not lock_was_present:
        for rec in existing_history:
            if rec.get("status") in {"success", "failed_mode_collapse"}:
                validate_stamped_invariants(
                    rec,
                    run_invariants,
                    full_scope=list(range(DATASET_CONFIG.num_files)),
                    source=f"workspace summary record {rec.get('exp_id') or '(no exp_id)'}",
                )
    ensure_run_invariants(workspace, run_invariants)


def _apply_plan_overrides(plan: ExperimentPlan, overrides: dict[str, Any]) -> ExperimentPlan:
    """Merge operator ``plan_overrides`` over the LLM plan and revalidate.

    FU-10 — the override lock is a contract: keys were validated and
    alias-normalized at schema level (`HyperparamTuningInput`), so the merge
    over the ``by_alias`` dump replaces exactly the intended fields. An
    effective plan that fails validation raises ``PlanOverridesError``
    (run-terminating, never retried) — the lock is never silently released
    back to the unclamped LLM plan. Empty overrides return the plan as-is.
    """
    if not overrides:
        return plan
    merged = plan.model_dump(by_alias=True) | overrides
    try:
        effective = ExperimentPlan.model_validate(merged)
    except Exception as e:
        raise PlanOverridesError(
            f"plan_overrides produced an invalid effective plan: {e}\n"
            f"  overrides={overrides}\n"
            f"  Fix the operator configuration and rerun — the override "
            f"lock is never silently released."
        ) from e
    print(f"  Plan overrides applied: {list(overrides.keys())}")
    return effective


def _resume_progress(
    existing_history: list[dict[str, Any]],
    *,
    model_type: str,
    run_name: str,
) -> tuple[int, int]:
    """Return completed round count and the highest run-local attempt suffix.

    Baseline records can share the same summary history as tuner records. Their
    timestamp-like suffixes must not be interpreted as tuner attempt counters.
    """
    completed_round_indices = {
        (record.get("memory") or {}).get("round_index")
        for record in existing_history
        if record.get("status") in {"success", "failed_mode_collapse"}
        and (record.get("memory") or {}).get("round_index") is not None
    }
    attempt_prefix = f"{model_type}_{run_name}_"
    attempt_suffixes: list[int] = []
    for record in existing_history:
        exp_id = str(record.get("exp_id") or "")
        if not exp_id.startswith(attempt_prefix):
            continue
        suffix = exp_id.removeprefix(attempt_prefix)
        if suffix.isdigit():
            attempt_suffixes.append(int(suffix))
    return len(completed_round_indices), max(attempt_suffixes, default=0)


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


def _resolve_guardrail_steps(
    train_sample_set: dict | None,
    model_config: dict,
    train_cfg: dict,
    train_portion: float | None,
) -> int | None:
    """Resolved step count for the §5 guardrails. Best-effort: a
    resolver failure returns None (the guardrail is defense-in-depth —
    the primary runtime criterion still protects the attempt)."""
    if train_sample_set is None:
        return None  # single-file legacy mode — no scoped workload to resolve
    try:
        from execute_tools.workload_resolvers import resolve_training_workload

        return resolve_training_workload(
            train_sample_set,
            seg_size=int(model_config.get("segmentation_size", 1000)),
            batch_size=int(train_cfg.get("batch_size", 1)),
            train_portion=train_portion,
            epochs=int(train_cfg.get("epochs", 1)),
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
) -> bool:
    """Run the §5 guardrails; on violation save the planner-visible
    record and return True (the attempt loop `continue`s). Single call
    site keeps run() under the analyzer's complexity ceiling."""
    n_steps = _resolve_guardrail_steps(
        train_sample_set, model_config, plan.train_cfg, trial_config.train_portion
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
    _emit_record(sandbox, record)
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
    _emit_record(sandbox, reject_record)
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
        from core.runtime_control.realized_memory import realized_vs_admitted

        rows = {}
        for phase in ("training", "inference"):
            row = realized_vs_admitted(
                phase,
                resource_check=resource_check,
                runtime_verification=rv_block,
            )
            if row is not None:
                rows[phase] = row.model_dump(mode="json")
        if rows:
            final_record.setdefault("memory", {})["realized_vs_admitted"] = rows
    except Exception as exc:  # pragma: no cover — defensive
        print(f"  [B2] realized-vs-admitted attach failed (non-fatal): {exc}")


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
        from execute_tools.data_paths import resolve_tidmad_measurement_capability

        observation = RuntimeObservation.model_validate(rv_block)
        capability = resolve_tidmad_measurement_capability(dataset_root=data_dir)
        uuid = getattr(device_identity, "uuid", None)
        stack = capture_software_stack()

        # A missing dimension drives QUARANTINE, never a fabricated default:
        # `IdentityContext` refuses a blank, so an absent UUID or task yields
        # `identity=None` and the derivation quarantines with the reason.
        identity = None
        if uuid and capability.task_identity and capability.data_shape_class:
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


class HyperparamTuningAgent:
    """
    Hyperparameter tuning agent — optimizes model configs over N rounds.

    Each round: plan (LLM) → resource check → train → infer → score → reflect (LLM).
    OOM-risk configs are skipped but saved to memory. A hard cap of max_rounds * 3
    total attempts prevents infinite loops.

    Constructor dependency injection (see ``docs/pseudo_test_infra.md`` §4A):
      * ``bridge_factory``: callable that constructs an ``LLMBridge``-compatible
        object. Defaults to the real ``LLMBridge`` class. In pseudo-mode tests,
        the ``tuner_factories`` fixture passes a factory that returns a
        ``RecordingLLMBridge`` pre-loaded with canned responses.
      * ``sandbox_factory``: callable that constructs a ``TidmadSandbox``-
        compatible object. Defaults to the real ``TidmadSandbox``. In
        pseudo-mode tests, the fixture passes a factory that returns a
        ``RecordingSandbox`` pre-loaded with canned subprocess results.

    Production code never passes these — the defaults are the real classes,
    so the existing call ``HyperparamTuningAgent().run(input)`` continues to
    work identically. Only tests inject the fakes.
    """

    def __init__(
        self,
        bridge_factory=None,
        sandbox_factory=None,
        capability_index_path: str | None = None,
    ):
        self._bridge_factory = bridge_factory or LLMBridge
        self._sandbox_factory = sandbox_factory or TidmadSandbox
        # L6b — loss-registry handle. The planner uses this to (a) render
        # the AVAILABLE CUSTOM LOSSES block into PLANNER_PROMPT and (b)
        # know whether to advertise ``loss_type="custom"`` as a legal
        # choice in the per-architecture loss_note. ``index_path=None``
        # defaults to ``agent_generated/_capability_index.json`` —
        # operators can override per-run via the constructor kwarg, same
        # pattern as MLModelProposalAgent (L5b). Built once at agent
        # construction so all rounds in this run see a consistent
        # snapshot; new entries the implementor adds DURING a run are
        # picked up because ``CapabilityRegistry`` reads the file each
        # ``list()`` call.
        from agent_generated._registry import CapabilityRegistry

        self._registry = CapabilityRegistry(index_path=capability_index_path)
        # Token-usage audit plumbing (Phase 1 Commit 4 — design doc §1.4).
        # Unlike interpreter/proposer/implementor/validator, the tuner builds
        # its bridge ("brain") lazily inside ``run()`` after the input has
        # been parsed, so the workflow cannot bind run-context at agent
        # construction time. Instead the workflow calls ``set_run_context``
        # to deposit the four args here; ``run()`` re-applies them to the
        # newly built brain right after the factory call. Default ``None``
        # preserves the legacy / pseudo-mode behaviour: no bind, brain's
        # bridge writes nothing to ``token_usage.jsonl``.
        self._pending_run_context: dict | None = None

    def set_run_context(self, *, workspace, iter: int, run_name: str, run_id: str) -> None:
        """Deposit run-context for the brain that will be built in ``run()``.

        Mirrors :meth:`agent.llm_bridge.LLMBridge.set_run_context` keyword
        signature; the stored dict is forwarded verbatim to the brain
        right after construction. Calling this method twice with different
        args overwrites the prior values silently — the bridge itself
        enforces immutability once it sees them.
        """
        self._pending_run_context = dict(
            workspace=workspace,
            iter=iter,
            run_name=run_name,
            run_id=run_id,
        )

    def run(self, agent_input: HyperparamTuningInput) -> HyperparamTuningOutput:
        """
        Execute the hyperparameter tuning loop.

        Args:
            agent_input: Validated HyperparamTuningInput with model_type, max_rounds,
                         expert_advice, storage config, and LLM config.

        Returns:
            HyperparamTuningOutput with status, best score, best config, and all records.
        """
        # --- Validate input ---
        agent_input = HyperparamTuningInput.model_validate(agent_input)

        # --- Extract frequently used fields ---
        # StorageConfig.local is Optional (only populated when backend='local').
        # The tuner only supports the local backend; surface the precondition
        # explicitly instead of crashing inside the next access.
        storage_local = agent_input.storage.local
        if storage_local is None:
            raise ValueError(
                f"HyperparamTuningInput requires storage.local to be populated "
                f"(got backend={agent_input.storage.backend!r}, local=None)"
            )
        workspace = storage_local.workspace
        run_name = storage_local.run_name

        # --- DataScope + HealthGate startup validation (DS5) ---
        # Dataset-resolved checks (schema validators cover only internal
        # consistency), then health-config materialization — all BEFORE any
        # LLM call, sandbox construction, or file I/O. See
        # docs/design/enable_partial_file_list.md.
        resolved_data_scope = validate_runtime_config(agent_input)
        scope_is_partial = resolved_data_scope != list(range(DATASET_CONFIG.num_files))
        health_checks_config_source = agent_input.health_checks_config
        # DS6b — build_run_invariants is the ONE shared path (tuner +
        # workflow) that materializes/hashes the effective config and then
        # constructs the invariants from the result, so the sha in the lock
        # always describes the exact config this run reads.
        run_invariants, _effective_config_path = build_run_invariants(
            resolved_data_scope=resolved_data_scope,
            health_gate_enabled=agent_input.health_gate_enabled,
            health_gate_files=agent_input.health_gate_files,
            health_checks_config=health_checks_config_source,
            workspace=workspace,
            # V19 PR 2 — the ordering OVERRIDE is chain control policy and is
            # locked; the per-round RESOLVED ordering is deliberately not,
            # since it may vary when no override is in force (§3.8).
            ordering_override_strategy=agent_input.order_strategy_override,
            ordering_override_file_order=agent_input.file_order_override,
            # V19 PR 3 — structured-health-feedback policy (pass-through:
            # the tuner locks + stamps it, never consumes it).
            structured_health_feedback_enabled=(agent_input.enable_structured_health_feedback),
            health_feedback_history_window_iterations=(
                agent_input.health_feedback_history_window_iterations
            ),
            health_feedback_history_max_entries_per_model=(
                agent_input.health_feedback_history_max_entries_per_model
            ),
        )
        health_config_sha256 = run_invariants.health_config_sha256
        if _effective_config_path is not None:
            # Path swap: every downstream path-based loader (gate lookup,
            # evaluation, output persistence) now reads the materialized
            # effective config through the existing plumbing.
            agent_input.health_checks_config = _effective_config_path
        # Run-invariants lock (DS6b): an existing lock is validated NOW so a
        # mismatched configuration fails before any hardware/LLM/sandbox
        # work. CREATION on a lock-less workspace is deferred until the
        # workspace's existing history has been stamp-validated (see the
        # get_summary() site) — a legacy workspace is never silently locked
        # before its records are checked against this run's invariants.
        _lock_was_present = load_run_invariants(workspace) is not None
        if _lock_was_present:
            validate_run_invariants(workspace, run_invariants)
        if scope_is_partial:
            print(
                f"[DATASCOPE] Partial scope active: files={resolved_data_scope} "
                f"| health_gate_enabled={agent_input.health_gate_enabled} "
                f"| monitored={agent_input.health_gate_files}"
            )

        # Per-run hardware manifest (Phase 6.6 §3.9) — file IPC with sandbox children.
        hardware_context = get_or_create(Path(workspace), run_name)
        print(
            f"[Tuner] Hardware context: {hardware_context.device_name} "
            f"| total={hardware_context.total_memory_gb:.1f} GB "
            f"| cap={hardware_context.usable_cap_gb:.1f} GB "
            f"| host={hardware_context.hostname} "
            f"| available={hardware_context.device_available}"
        )

        model_type_setting = agent_input.model_type
        max_rounds = agent_input.max_rounds
        file_index = agent_input.file_index
        trial_allowed = agent_input.is_trial
        expert_advice_str = _serialize_expert_advice(agent_input.expert_advice)
        if agent_input.human_advice:
            human_section = f"\n[Human Guidance (high priority)]:\n{agent_input.human_advice}"
            expert_advice_str = (
                (expert_advice_str + human_section)
                if expert_advice_str
                else agent_input.human_advice
            )

        print(
            f"Input validated: model={model_type_setting} | rounds={max_rounds} "
            f"| file_index={file_index} | trial_allowed={trial_allowed} "
            f"| provider={agent_input.llm_provider}"
        )

        # Per-mode time-budget gate (Phase I). Each mode has its own optional
        # ceiling; the per-round pick happens inside the loop based on
        # plan.is_trial. Mirrors the "additive, opt-in" stance in
        # docs/resource_estimator_implement.md §5 — when both budgets are None the
        # gate never fires; when only one is set, rounds in the other mode skip
        # the gate (one-time warning printed below per mode).
        trial_time_budget = agent_input.trial_time_budget_minutes
        formal_time_budget = agent_input.formal_time_budget_minutes
        time_data_dir = agent_input.data_dir
        if trial_time_budget is None:
            print(
                "[time-gate disabled / trial] trial_time_budget_minutes is None "
                "— evaluate_time_skill will not gate trial-mode rounds."
            )
        if formal_time_budget is None:
            print(
                "[time-gate disabled / formal] formal_time_budget_minutes is None "
                "— evaluate_time_skill will not gate formal-mode rounds."
            )

        # Per-mode VRAM-budget gate (Phase K). Mirrors the time-gate shape: each
        # mode has its own optional ceiling, per-round pick happens inside the
        # loop based on plan.is_trial. When the mode's budget is None, the VRAM
        # skill falls back to the defensive free×0.8 behaviour (no operator
        # ceiling) — the skill still runs, but the vram_*_gb memory fields are
        # omitted so the planner sees "this round wasn't operator-budgeted."
        # See docs/resource_estimator_implement.md §10.4 / §10.8.
        trial_vram_budget = agent_input.trial_vram_budget_gb
        formal_vram_budget = agent_input.formal_vram_budget_gb
        if trial_vram_budget is None:
            print(
                "[vram-gate disabled / trial] trial_vram_budget_gb is None "
                "— evaluate_vram_skill uses free×0.8 defensive limit for "
                "trial-mode rounds."
            )
        if formal_vram_budget is None:
            print(
                "[vram-gate disabled / formal] formal_vram_budget_gb is None "
                "— evaluate_vram_skill uses free×0.8 defensive limit for "
                "formal-mode rounds."
            )

        # --- Initialize sandbox and brain (via factory for DI / pseudo-mode) ---
        # V20 B-C2b — device identity resolved ONCE here, at the
        # orchestration boundary, and passed down explicitly. The executor
        # must never discover a device of its own: implicit rediscovery is
        # how "GPU 0" gets assumed on a multi-GPU host. `None` (a CPU host,
        # or a manifest predating UUIDs) means telemetry unavailable, which
        # is a gap, not a default device.
        device_identity = device_identity_from_hardware(hardware_context)
        if device_identity is None:
            print(
                "[Tuner] GPU telemetry unavailable: the hardware record carries "
                "no device UUID (legacy manifest or CPU-only host). Phase "
                "evidence will be absent rather than attributed to a guessed device."
            )
        sandbox = self._sandbox_factory(
            metadata_source="local",
            run_name=run_name,
            workspace=workspace,
            progress_bar=agent_input.progress_bar,
            file_index=file_index,
            data_scope=agent_input.data_scope,
            device_identity=device_identity,
        )

        # Seed plugin copy — docs/run_scoped_plugins.md (Phase 3). Validation
        # (file exists + PLUGIN_MODEL_TYPE matches model_type) already ran in
        # HyperparamTuningInput; here we just stage the file in the run's
        # plugin dir so the training subprocess picks it up via
        # SIDERIUS_PLUGIN_DIRS.
        if agent_input.seed_plugin_path:
            copied = _copy_seed_plugin(agent_input.seed_plugin_path, sandbox.plugin_dir)
            print(f"[Tuner] Seed plugin staged: {os.path.basename(copied)} -> {sandbox.plugin_dir}")

        brain = self._bridge_factory(
            provider=agent_input.llm_provider,
            model_id=agent_input.llm_model_id,
            reflect_provider=agent_input.reflect_provider,
            reflect_model_id=agent_input.reflect_model_id,
            max_retries=agent_input.max_retries,
        )

        # Apply deposited run-context (workflow → set_run_context → here).
        # Guarded by hasattr so RecordingLLMBridge / other test doubles that
        # don't implement set_run_context never break the run.
        if self._pending_run_context is not None and hasattr(brain, "set_run_context"):
            brain.set_run_context(**self._pending_run_context)

        # --- Pre-load anchor map if any round might use trial mode ---
        anchor_map_data: dict | None = None
        if trial_allowed:
            anchor_map_path = os.path.join(sandbox.dirs["data"], "segment_anchors.json")
            if os.path.exists(anchor_map_path):
                anchor_map_data = load_anchor_map(anchor_map_path)
            else:
                raise FileNotFoundError(
                    f"Trial mode requires segment_anchors.json at {anchor_map_path}. "
                    "Run execute_tools/build_anchor_map.py first."
                )
            print("Trial mode enabled: anchor map loaded.")

        # Pre-load reference scores (raw_baseline + ground_truth per-file
        # logs, linear_sums, n_segments, and full-20 scalars). One disk
        # read per run — cached at module level after the first call.
        # Used every round to build the per-file score-comparison table
        # attached to each ExperimentRecord and substituted into the
        # tuner/reflector/interp/proposer prompts.
        # See docs/aggregated_score_table_awareness.md §7.1.
        reference_scores = load_reference_scores()
        print(
            f"Reference scores loaded: s_max={reference_scores.s_max:.4e}, "
            f"raw_scalar_full={reference_scores.raw_scalar_full:.4f}, "
            f"gt_scalar_full={reference_scores.gt_scalar_full:.4f}."
        )

        # Resolve invocation-wide formal comparison metadata once (V19 PR 1:
        # the SINGLE authoritative computation — startup logging, durable
        # output provenance, AND both delta gates consume these values).
        # ``enable_chain_incumbent_formal_gates`` is a consumption-only
        # switch: OFF (default) short-circuits both formal delta gates to
        # no-reference; ON couples them to ``chain_incumbent +
        # fixed_delta``. Reconstruction / provenance / run_config
        # persistence upstream are unconditional. OFF is NOT a fixed-0.0
        # mode. Full semantics: nodes/ml_hyperparameter_tune_agent/
        # ml_hyperparameter_tune_agent.md under "Chain formal-incumbent
        # reference".
        _consumed_reference = (
            agent_input.current_run_best_formal_score
            if agent_input.enable_chain_incumbent_formal_gates
            else None
        )
        (
            formal_reference_score,
            resolved_skip_formal_threshold,
            resolved_bypass_formal_threshold,
            formal_reference_source,
        ) = _resolve_formal_comparison_thresholds(
            reference_score=_consumed_reference,
            gates_enabled=agent_input.enable_chain_incumbent_formal_gates,
            skip_min_delta=agent_input.skip_formal_min_delta,
            bypass_min_delta=agent_input.bypass_formal_time_budget_min_delta,
        )

        # Save run configuration once
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        run_config = {
            "provider": agent_input.llm_provider,
            "model_id": agent_input.llm_model_id,
            "run_name": run_name,
            "force_model": model_type_setting,
            "max_rounds": max_rounds,
            "file_index": file_index,
            "trial_allowed": trial_allowed,
            "formal_reference_score": _json_safe_reference(formal_reference_score),
            "formal_comparison_reference_source": formal_reference_source,
            "resolved_skip_formal_threshold": _json_safe_reference(resolved_skip_formal_threshold),
            "resolved_bypass_formal_threshold": _json_safe_reference(
                resolved_bypass_formal_threshold
            ),
            # V19 PR 1 audit provenance: the provided incumbent and the
            # coupling-flag state, so "provided but not consumed" (flag
            # OFF) is distinguishable from "no incumbent existed".
            "chain_incumbent_provided": agent_input.current_run_best_formal_score,
            "enable_chain_incumbent_formal_gates": (
                agent_input.enable_chain_incumbent_formal_gates
            ),
            # V19 PR 3 — structured-health-feedback POLICY stamps (flag +
            # retention). Policy only: per-round gate evidence stays in
            # the records / interpretation digest, never duplicated here.
            "enable_structured_health_feedback": (agent_input.enable_structured_health_feedback),
            "health_feedback_history_window_iterations": (
                agent_input.health_feedback_history_window_iterations
            ),
            "health_feedback_history_max_entries_per_model": (
                agent_input.health_feedback_history_max_entries_per_model
            ),
            # DataScope + HealthGate subsystem stamps (DS5).
            "resolved_data_scope": resolved_data_scope,
            "health_gate_enabled": agent_input.health_gate_enabled,
            # V20 PR D (D-C1a): declared enforcement/authority axes,
            # echoed from the input so provenance and output cannot
            # disagree with what the run was launched under.
            "healthgate_mode": agent_input.healthgate_mode,
            "result_authority": agent_input.result_authority,
            "health_checks_config_source": health_checks_config_source,
            "health_checks_config_effective": agent_input.health_checks_config
            if agent_input.health_gate_enabled
            else None,
            "health_config_sha256": health_config_sha256,
            # V19 PR 1 (P1-C5 A4) — formal sampling provenance so the
            # per-file best table can populate formal rows' eval_portion
            # from committed data (never from current defaults). Legacy
            # run_configs without these keys correctly resolve to null.
            "formal_strategy": agent_input.formal_strategy,
            "formal_eval_portion": agent_input.formal_eval_portion,
            # V19 PR 2 — the run's ordering CONTROL POLICY (the operator
            # override, or null for none). Per-round RESOLVED ordering is
            # not recorded here: it may differ round to round when no
            # override is in force, so it lives on each ExperimentRecord.
            "order_strategy_override": agent_input.order_strategy_override,
            "file_order_override": agent_input.file_order_override,
            "started_at": started_at,
        }
        run_config_path = os.path.join(workspace, f"run_config_{run_name}.json")
        with open(run_config_path, "w", encoding="utf-8") as f:
            json.dump(run_config, f, indent=4)

        print("=== TIDMAD Agent Activated ===")
        print(f"Provider: {agent_input.llm_provider} | Model: {agent_input.llm_model_id}")
        print(f"HealthGate config: {agent_input.health_checks_config or '(shipped default)'}")
        print(
            "Formal comparison thresholds: "
            f"reference={_fmt_reference(formal_reference_score)}, "
            f"skip={_fmt_reference(resolved_skip_formal_threshold)}, "
            f"bypass={_fmt_reference(resolved_bypass_formal_threshold)}"
        )
        # V19 PR 1: explicit runtime distinction between the reconstructed
        # incumbent (provided), the coupling-flag state, and the reference
        # actually consumed by the gates. Corrolates with the [resume]
        # incumbent carry-over line (upstream) and the "Formal comparison
        # thresholds" line (downstream = what the gates see).
        _coupling_state = "ON" if agent_input.enable_chain_incumbent_formal_gates else "OFF"
        print(
            f"[chain_incumbent] provided="
            f"{_fmt_reference(agent_input.current_run_best_formal_score)}; "
            f"coupling={_coupling_state}; "
            f"consumed={_fmt_reference(formal_reference_score)}"
        )
        print(f"Expert Advice: {expert_advice_str}")
        print(f"Max Rounds: {max_rounds} | Strategy: {model_type_setting}")

        # --- Get the config manual before starting ---
        print("Reading model configuration manual...")
        config_manual = _run_skill("check_config_format_skill", sandbox)
        if config_manual["status"] == "success":
            config_manual_data = config_manual["data"]
        else:
            raise ValueError("Config Manual not provided.")

        # --- Load model description (architecture explanation for the LLM) ---
        model_description = None
        try:
            from ml_models.model_descriptions import get_model_description

            model_description = get_model_description(model_type_setting)
            print(
                f"Loaded model description for '{model_type_setting}' ({len(model_description)} chars)"
            )
        except (FileNotFoundError, Exception) as e:
            print(f"No model description found for '{model_type_setting}': {e}")

        # --- Autonomous Research Loop ---
        # Phase L (§11) — success-counted outer loop with per-round inner
        # attempt budget. Pre-Phase-L the tuner used a single shared
        # ``max_rounds * 3`` attempt pool and counted both successes and
        # failures against ``max_rounds``; that meant a few unlucky rounds
        # could exhaust the pool before any formal round ever ran. Phase L
        # gives each round its own budget (``attempts_per_round`` for
        # trial rounds, ``attempts_per_formal_round`` for the formal
        # round) and only increments ``completed_rounds`` on success.
        # ``consecutive_fails`` aborts the iteration after
        # ``max_fail_rounds`` rounds in a row exhaust their inner budget.
        existing_history = sandbox.get_summary()
        completed_rounds, total_attempts = _resume_progress(
            existing_history,
            model_type=model_type_setting,
            run_name=run_name,
        )
        if completed_rounds:
            print(
                f"[RESUME] Found {completed_rounds}/{max_rounds} completed "
                f"round(s) and {total_attempts} prior attempt(s); continuing."
            )
        # DS6b — ingress validation + deferred lock creation, still before
        # any LLM call (the first plan call happens in the round loop below).
        _validate_history_and_lock(workspace, run_invariants, existing_history, _lock_was_present)
        consecutive_fails = 0
        # D-C6: set at the skip gate itself, so the feedback can state
        # WHY formal did not run rather than inferring it from the
        # absence of a formal record — which cannot distinguish a
        # no-winner skip from a budget skip.
        _skipped_formal_for_no_valid_winner = False
        # Set to True when a SKIP_ITER gate action breaks the outer while
        # loop before max_rounds. Consumed by _compute_termination_state
        # to distinguish gate-driven aborts from fail-round-driven aborts
        # and healthy completions (audit Gap #3, follow-up to commit-5b).
        _gate_aborted = False
        # DataScope DS5 — non-retryable configuration/invariant failure flag.
        # A scope violation reaching an executor means the scope plumbing has
        # a bug; it is deterministic on retry, so the run terminates instead
        # of consuming attempt retries or waiting for max_fail_rounds.
        _scope_violation_reason: str | None = None
        # C9c: set when the runtime EVIDENCE CHANNEL fails. Terminates
        # the chain, not just the attempt (infrastructure class).
        _evidence_channel_failure: str | None = None
        # Phase 6.6 WS-B B.3 — per-attempt VRAM-gate rejection buffer.
        # Appended to on every evaluate_vram_skill feasible=False event.
        # Flushed to HyperparamTuningOutput.physical_rejections at run exit.
        # See docs/phase66_ws_b_proposer_hardening.md §2.3 / §2.4.
        physical_rejections_buffer: list[PhysicalRejection] = []
        attempts_per_round_setting = agent_input.attempts_per_round
        attempts_per_formal_round_setting = agent_input.attempts_per_formal_round
        max_fail_rounds_setting = agent_input.max_fail_rounds
        # Pre-initialise so finalisation can safely read `plan` for the
        # gate-exhaustion mode lookup even if the loop never assigns it
        # (e.g. max_rounds=0 or an early-exit path).
        plan: ExperimentPlan | None = None

        while completed_rounds < max_rounds and consecutive_fails < max_fail_rounds_setting:
            round_index = completed_rounds + 1
            is_formal_round = completed_rounds == max_rounds - 1
            N = attempts_per_formal_round_setting if is_formal_round else attempts_per_round_setting
            round_succeeded = False
            # Per-round gate evaluation state (commit-5b). Updated inside
            # the attempts loop on the score_vector success path and
            # consumed after the attempts loop for SKIP_ITER /
            # SKIP_TO_FORMAL loop control. Stays CONTINUE when all attempts
            # crash (gates only fire on completed scoring outputs; failed
            # rounds are handled by consecutive_fails).
            resolved_action: GateAction = GateAction.CONTINUE

            # Post-v15 skip-formal gate: bail before starting the formal round
            # when the best trial score is well below the current run's best
            # formal score. Saves the formal-round attempt budget (typically
            # 5 attempts at 100+ minutes each) for configurations that have a
            # plausible chance of beating the current best.
            #
            # The gate fires only when (a) we're about to enter the
            # forced-formal round, (b) at least one trial winner exists, and
            # (c) ``best_trial_score < resolved_skip_formal_threshold`` —
            # the startup-resolved value (V19 PR 1: single-source
            # arithmetic; ``None`` = no chain incumbent = gate inert).
            # Disabled by ``skip_formal_min_delta=float('-inf')``.
            # V20 PR D (D-C3): the winner is resolved ONCE here and reused
            # by the skip gate, the bypass gate and the log line below.
            # Three independent `_best_trial_winner` calls would agree only
            # because the history does not change between them — a
            # coincidence, not a guarantee.
            formal_trial_winner = _best_trial_winner(sandbox.get_summary() or [])
            if (
                is_formal_round
                and agent_input.force_formal_round
                and _should_skip_formal(
                    formal_trial_winner,
                    threshold=resolved_skip_formal_threshold,
                    gates_enabled=agent_input.enable_chain_incumbent_formal_gates,
                )
            ):
                _winner = formal_trial_winner
                _best_trial_score = _winner.get("denoising_score") if _winner is not None else None
                if _best_trial_score is None:
                    # D-C3's correction: no valid trial winner is no
                    # evidence, and no evidence does not justify the cost
                    # of a formal round. Previously this case returned
                    # False and the round ran anyway.
                    _skipped_formal_for_no_valid_winner = True
                    print(
                        "\n  [SkipFormal] no HealthGate-valid trial winner in this "
                        "iteration (reason=no_valid_trial_winner) — skipping the "
                        "formal round rather than spending it on no evidence.",
                        flush=True,
                    )
                else:
                    print(
                        f"\n  [SkipFormal] Best trial {_best_trial_score:.4f} < "
                        f"reference({_fmt_reference(formal_reference_score)}) "
                        f"+ delta({agent_input.skip_formal_min_delta:.4f}) = "
                        f"{_fmt_reference(resolved_skip_formal_threshold)} — "
                        "skipping formal round.",
                        flush=True,
                    )
                break  # exit the while loop; this iter has no formal score

            for attempt_in_round in range(1, N + 1):
                total_attempts += 1
                iteration = round_index  # legacy alias for prints + brain.plan(current_round=...)
                failure_stage = "planning"
                exp_id = f"{model_type_setting}_{run_name}_{total_attempts:03d}"
                model_type = model_type_setting
                record_params: dict[str, Any] = {}
                hypothesis = "Attempt failed before a validated hypothesis was available."
                try:
                    print(
                        f"\n\n{'=' * 60}\nROUND {iteration}/{max_rounds} "
                        f"(attempt {attempt_in_round}/{N}, total {total_attempts}): "
                        f"Planning...\n{'=' * 60}"
                    )

                    # A. OBSERVE: Retrieve full Research Memory from summary.json
                    memory_history = sandbox.get_summary()

                    # Build exploration checklist from config schema + past records
                    from agent.prompts import (
                        build_exploration_checklist,
                        format_plugin_source_excerpt_block,
                    )
                    from ml_models.models_format_sandbox import get_config_class

                    config_cls = get_config_class(model_type_setting)
                    config_schema = config_cls.model_json_schema() if config_cls else {}
                    checklist = build_exploration_checklist(
                        config_schema=config_schema,
                        memory_history=memory_history,
                    )
                    # Phase D.1 — surface the raw config class source (validator
                    # bodies included) so the planner sees cross-field invariants
                    # that ``model_json_schema()`` drops. See
                    # docs/improving_validation_awareness.md §D.1.
                    plugin_source_excerpt = format_plugin_source_excerpt_block(config_cls)

                    # Phase K (K.6) — extract the most recent prior attempt's
                    # resource snapshot so the [ACTIVE RESOURCE BUDGETS] block can
                    # show the LLM a concrete number to react to. Looks at the
                    # last memory entry regardless of status (success / skipped):
                    # the resource fields are absent on records produced with the
                    # gates disabled and on schema-violation records. Round 1
                    # gives None on every field, which collapses to "(no prior
                    # estimate)" in the rendered block.
                    # See docs/resource_estimator_implement.md §10.3 / §10.11.
                    last_record = memory_history[-1] if memory_history else {}
                    last_memory = last_record.get("memory") or {}
                    last_train_cfg = (last_record.get("params") or {}).get("train_config") or {}
                    last_vram_estimate_gb = last_memory.get("vram_estimate_gb")
                    last_time_estimate_minutes = last_memory.get("time_estimate_minutes")
                    last_batch_size = last_train_cfg.get("batch_size")
                    last_mode = last_memory.get("time_mode")

                    # Pick the best HealthGate-valid score_table for the
                    # planner prompt. Raw collapsed winners remain persisted
                    # but are not presented as the viable incumbent. Empty
                    # history or no
                    # populated score_table → None, which the bridge replaces
                    # with the "no prior round yet" fallback. See
                    # docs/aggregated_score_table_awareness.md §9.1.
                    best_score_table_md: str | None = None
                    _records_with_table: list[dict] = [
                        r
                        for r in memory_history
                        if is_valid_candidate(r)
                        and isinstance(r.get("score_table"), dict)
                        and r["score_table"].get("rendered_markdown")
                    ]
                    if _records_with_table:
                        _best_rec = max(
                            _records_with_table,
                            key=lambda r: r["denoising_score"],
                        )
                        best_score_table_md = _best_rec["score_table"]["rendered_markdown"]

                    # B. THINK: Plan next experiment
                    decision = brain.plan(
                        memory_history,
                        expert_advice=expert_advice_str,
                        force_model=model_type_setting,
                        config_manual=config_manual_data,
                        model_description=model_description,
                        exploration_checklist=checklist,
                        plugin_source_excerpt=plugin_source_excerpt,
                        current_round=iteration,
                        max_rounds=max_rounds,
                        trial_allowed=trial_allowed,
                        force_formal_round=agent_input.force_formal_round,
                        plan_overrides=agent_input.plan_overrides,
                        max_epochs=agent_input.max_epochs,
                        # DS5c — partial-scope disclosure (None = full scope).
                        resolved_data_scope=resolved_data_scope if scope_is_partial else None,
                        trial_vram_budget_gb=trial_vram_budget,
                        formal_vram_budget_gb=formal_vram_budget,
                        trial_time_budget_minutes=trial_time_budget,
                        formal_time_budget_minutes=formal_time_budget,
                        last_vram_estimate_gb=last_vram_estimate_gb,
                        last_time_estimate_minutes=last_time_estimate_minutes,
                        last_batch_size=last_batch_size,
                        last_mode=last_mode,
                        score_table_md=best_score_table_md,
                        # T4a — task config injection. Substituted into the
                        # {TASK_DESCRIPTION} placeholder in PLANNER_PROMPT.
                        # See docs/design/enable_global_task_config.md § T4a.
                        task_description=agent_input.task_description,
                        # L6b — loss-registry awareness. Drives both the
                        # AVAILABLE CUSTOM LOSSES system-prompt block and
                        # the per-architecture loss_note advertisement of
                        # ``loss_type="custom"`` as a legal choice. See
                        # docs/design/enable_loss_inventory.md § L6b.
                        registry=self._registry,
                    )

                    # Validate LLM output into ExperimentPlan (with fallback).
                    # parse_with_fallback also reports an ordering proposal
                    # that the fallback discarded, so a rejected proposal is
                    # recorded rather than looking like agent silence.
                    plan, rejected_ordering = ExperimentPlan.parse_with_fallback(decision)

                    # Apply hard overrides from operator config (before other
                    # overrides). FU-10 — an invalid effective plan raises
                    # PlanOverridesError (run-terminating); see the helper.
                    plan = _apply_plan_overrides(plan, agent_input.plan_overrides)

                    # Override chain: trial-allowed lockout + last-round override
                    # + forced-formal hyperparameter inheritance gated on
                    # formal_round_strategy. See _apply_mode_override_chain.
                    plan = _apply_mode_override_chain(
                        plan,
                        trial_allowed=trial_allowed,
                        is_formal_round=is_formal_round,
                        force_formal_round=agent_input.force_formal_round,
                        formal_round_strategy=agent_input.formal_round_strategy,
                        memory_history=memory_history,
                        # FU-D-6: the SAME winner the skip and bypass gates
                        # judged, resolved once at the formal-round
                        # boundary above — not re-derived here.
                        trial_winner=formal_trial_winner,
                    )

                    # DataScope DS5 — normalize LLM-planned strategies under a
                    # partial scope. LLM plans are proposals (normalized with
                    # persisted provenance, not failed); operator config was
                    # already validated at startup; the sandbox boundary
                    # still fails hard if anything slips through.
                    planned_trial_strategy = plan.trial_strategy
                    planned_eval_strategy = plan.eval_strategy
                    strategy_normalization_reason: str | None = None
                    if (
                        scope_is_partial
                        and plan.is_trial
                        and (plan.trial_strategy != "snapshot" or plan.eval_strategy != "snapshot")
                    ):
                        print(
                            f"  [DATASCOPE] normalized strategies: "
                            f"trial {plan.trial_strategy} → snapshot, "
                            f"eval {plan.eval_strategy} → snapshot "
                            f"(partial scope {resolved_data_scope})"
                        )
                        plan.trial_strategy = "snapshot"
                        plan.eval_strategy = "snapshot"
                        strategy_normalization_reason = "partial_data_scope"

                    # Enforce max_epochs hard cap (prevents LLM from choosing excessively long training)
                    if agent_input.max_epochs is not None:
                        planned_epochs = plan.train_cfg.get("epochs", 1)
                        if planned_epochs > agent_input.max_epochs:
                            print(
                                f"  Clamping epochs: {planned_epochs} → {agent_input.max_epochs} (max_epochs)"
                            )
                            plan.train_cfg["epochs"] = agent_input.max_epochs

                    # Build and validate TrialConfig from plan + overrides
                    if plan.is_trial:
                        mode = "trial"
                    elif trial_allowed:
                        mode = "formal"
                    else:
                        mode = "single_file"

                    # Phase M / Phase R — mode-gated sample-set config. Formal-mode
                    # eval strategy is locked to ``snapshot``; the portion defaults
                    # to 1.0 (production full-clone, §12.2) but is operator-
                    # configurable via ``agent_input.formal_eval_portion`` (Phase R,
                    # §13). Formal training levers come from agent_input.formal_*.
                    # See docs/resource_estimator_implement.md §12 and §13.
                    _cfg = _resolve_sample_set_cfg(mode, agent_input, plan)
                    cfg_trial_strategy = _cfg["trial_strategy"]
                    cfg_trial_portion = _cfg["trial_portion"]
                    cfg_train_portion = _cfg["train_portion"]
                    cfg_eval_strategy = _cfg["eval_strategy"]
                    cfg_eval_portion = _cfg["eval_portion"]

                    # FU-D-12 — VALIDATION-ONLY workload ceiling, applied to
                    # the RESOLVED values so it holds whichever branch
                    # produced them.
                    #
                    # Trial-mode portions come from the LLM PLAN, not from
                    # operator input, so a Gate that requested 0.02 measured
                    # 0.1. Time budgets bound wall time but not WORKLOAD, and
                    # the harness must own the maximum. Formal-mode portions
                    # already come from `agent_input.formal_*` and are
                    # unaffected.
                    #
                    # A maximum, never a replacement: `min` can only reduce.
                    _planned_portions = {
                        "trial_portion": cfg_trial_portion,
                        "train_portion": cfg_train_portion,
                        "eval_portion": cfg_eval_portion,
                    }
                    if agent_input.validation_max_portion is not None:
                        _ceiling = agent_input.validation_max_portion
                        for _label, _planned in (
                            ("trial_portion", cfg_trial_portion),
                            ("train_portion", cfg_train_portion),
                            ("eval_portion", cfg_eval_portion),
                        ):
                            if _planned > _ceiling:
                                print(
                                    f"  Clamping {_label}: {_planned} → {_ceiling} "
                                    f"(validation_max_portion)"
                                )
                        # Assigned unconditionally: BOTH branches of
                        # `_resolve_sample_set_cfg` yield a non-optional float
                        # (`ExperimentPlan.trial_portion` and
                        # `HyperparamTuningInput.formal_*` are both `float`),
                        # and `TrialConfig` requires `float`. Guarding on
                        # `is not None` here would widen the inferred type to
                        # `float | None` and break the TrialConfig contract —
                        # which is exactly what CI caught.
                        cfg_trial_portion = min(cfg_trial_portion, _ceiling)
                        cfg_train_portion = min(cfg_train_portion, _ceiling)
                        cfg_eval_portion = min(cfg_eval_portion, _ceiling)

                    # Generate deterministic seeds for reproducibility.
                    import hashlib

                    seed_input = f"{run_name}_{total_attempts}".encode()
                    seed_hash = int(hashlib.sha256(seed_input).hexdigest(), 16)
                    train_sampling_seed = (
                        agent_input.sampling_seed
                        if agent_input.sampling_seed is not None
                        else seed_hash % (2**31)
                    )
                    train_base_seed = (
                        agent_input.train_base_seed
                        if agent_input.train_base_seed is not None
                        else (seed_hash >> 31) % (2**31)
                    )
                    # Eval seed: same as train when aligned, different otherwise
                    if plan.train_validation_align:
                        eval_sampling_seed = train_sampling_seed
                    else:
                        eval_sampling_seed = (seed_hash >> 62) % (2**31)

                    # V19 PR 2 — the ONE ordering resolution point. Combines
                    # the agent's proposal (or its rejection) with the
                    # operator's chain override; nothing downstream re-derives
                    # precedence, and only the resolved values execute.
                    ordering = resolve_ordering(
                        resolved_scope=resolved_data_scope,
                        proposed_strategy=plan.order_strategy,
                        proposed_file_order=plan.file_order,
                        override_strategy=agent_input.order_strategy_override,
                        override_file_order=agent_input.file_order_override,
                        rejected_proposal=rejected_ordering,
                    )
                    print(f"[data_order] {ordering.describes_execution()}")

                    trial_config = TrialConfig(
                        is_trial=plan.is_trial,
                        mode=mode,
                        # Training
                        trial_strategy=cfg_trial_strategy,
                        trial_portion=cfg_trial_portion,
                        train_portion=cfg_train_portion,
                        target_files=plan.target_files if plan.is_trial else [],
                        # Validation
                        eval_strategy=cfg_eval_strategy,
                        eval_portion=cfg_eval_portion,
                        # Alignment
                        train_validation_align=plan.train_validation_align,
                        # Legacy
                        file_index=file_index if mode == "single_file" else None,
                        # Seeds
                        train_sampling_seed=train_sampling_seed,
                        eval_sampling_seed=eval_sampling_seed,
                        train_base_seed=train_base_seed,
                        # Ordering — RESOLVED values only (V19 PR 2).
                        # executed_strategy() narrows to non-null inside
                        # ordering.py; doing it here pushed pyright past its
                        # per-function complexity budget for run().
                        resolved_order_strategy=ordering.executed_strategy(),
                        resolved_file_order=ordering.resolved_file_order,
                    )

                    # Validate integer relationships between dataset, PSD, ML segments
                    _validate_data_config(
                        trial_config, plan.model_cfg.get("segmentation_size", 10000)
                    )

                    # Build TWO independent SampleSets — training and validation
                    if trial_config.mode in ("trial", "formal"):
                        train_sample_set = build_sample_set(
                            is_trial=True,
                            trial_strategy=trial_config.trial_strategy,
                            trial_portion=trial_config.trial_portion,
                            target_files=trial_config.target_files or None,
                            seed=trial_config.train_sampling_seed,
                            scope=agent_input.data_scope,
                        )
                        eval_sample_set = build_sample_set(
                            is_trial=True,
                            trial_strategy=trial_config.eval_strategy,
                            trial_portion=trial_config.eval_portion,
                            target_files=trial_config.target_files or None,
                            seed=trial_config.eval_sampling_seed,
                            scope=agent_input.data_scope,
                        )
                        print(
                            f"  {trial_config.mode.capitalize()} mode: "
                            f"train: {trial_config.trial_strategy} portion={trial_config.trial_portion} "
                            f"| eval: {trial_config.eval_strategy} portion={trial_config.eval_portion} "
                            f"| train_portion/epoch={trial_config.train_portion} "
                            f"| align={trial_config.train_validation_align}"
                        )
                    else:
                        train_sample_set = None
                        eval_sample_set = None
                        print(f"  Legacy mode: file_index={file_index}")

                    # Segment counts for records and reflector context
                    if train_sample_set:
                        train_psd_segments = sum(len(v) for v in train_sample_set.values())
                    else:
                        train_psd_segments = DATASET_CONFIG.segments_per_file  # legacy single-file

                    if eval_sample_set:
                        eval_psd_segments = sum(len(v) for v in eval_sample_set.values())
                    else:
                        eval_psd_segments = DATASET_CONFIG.segments_per_file  # legacy single-file

                    # When force_model is set, override the LLM's model_type choice.
                    if model_type_setting != "auto":
                        model_type = model_type_setting
                    else:
                        model_type = plan.model_type
                    exp_id = f"{model_type}_{run_name}_{total_attempts:03d}"
                    hypothesis = plan.hypothesis

                    print(f"Action: {model_type.upper()} | ID: {exp_id}")
                    print(f"Hypothesis: {hypothesis}")
                    print(f"Reasoning: {plan.reasoning or 'No reasoning provided.'}")

                    # Save validated TrialConfig
                    trial_config_path = os.path.join(
                        sandbox.dirs["configs"], f"trial_config_{exp_id}.json"
                    )
                    with open(trial_config_path, "w", encoding="utf-8") as f:
                        json.dump(trial_config.model_dump(), f, indent=2)

                    # C. ACT: Execute the Atomic Skill Pipeline (Train -> Inf -> Score)
                    model_config = plan.model_cfg.copy()
                    # Ensure model_config.model_type matches the forced model type
                    model_config["model_type"] = model_type
                    active_params = {
                        "exp_id": exp_id,
                        "run_name": run_name,
                        "model_type": model_type,
                        "model_config": model_config,
                        "train_config": plan.train_cfg,
                        "loss_config": plan.loss_cfg,
                        "sample_set": train_sample_set,  # training data (from training files)
                        "train_portion": trial_config.train_portion,
                        "train_base_seed": trial_config.train_base_seed,
                        "eval_sample_set": eval_sample_set,  # validation data (from validation files)
                        # Ordering — resolved values only (V19 PR 2)
                        "order_strategy": trial_config.resolved_order_strategy,
                        "file_order": trial_config.resolved_file_order,
                    }

                    # Clean params for records — exclude bulky SampleSet dicts
                    record_params = {
                        "exp_id": exp_id,
                        "run_name": run_name,
                        "model_type": model_type,
                        "model_config": model_config,
                        "train_config": plan.train_cfg,
                        "loss_config": plan.loss_cfg,
                    }

                    # RT5 §5 guardrails — cheapest pre-flight check, before
                    # any VRAM/time probe. Defense-in-depth only; the primary
                    # criterion stays the in-subprocess runtime verification.
                    failure_stage = "guardrails"
                    if _check_and_record_guardrail_skip(
                        sandbox=sandbox,
                        agent_input=agent_input,
                        plan=plan,
                        trial_config=trial_config,
                        train_sample_set=train_sample_set,
                        model_config=model_config,
                        exp_id=exp_id,
                        model_type=model_type,
                        file_index=file_index,
                        record_params=record_params,
                        expert_advice_str=expert_advice_str,
                        hypothesis=hypothesis,
                        round_index=round_index,
                        attempt_in_round=attempt_in_round,
                    ):
                        continue

                    # Phase K: per-mode VRAM-budget pick. plan.is_trial decides
                    # which ceiling applies for THIS round; the unselected one is
                    # ignored. When the chosen budget is None the skill still runs
                    # but falls back to free×0.8 defensive behaviour (no operator
                    # ceiling) — the memory's vram_*_gb fields are omitted in that
                    # case so the planner sees "this round wasn't operator-budgeted."
                    # See docs/resource_estimator_implement.md §10.4 / §10.8.
                    chosen_vram_budget = trial_vram_budget if plan.is_trial else formal_vram_budget
                    vram_budget_desc = (
                        f"{chosen_vram_budget} GB" if chosen_vram_budget is not None else "free×0.8"
                    )
                    print(
                        f"\n[Pre-flight 1/2] VRAM check "
                        f"(mode={'trial' if plan.is_trial else 'formal'}, "
                        f"budget={vram_budget_desc})..."
                    )
                    failure_stage = "vram_structural_probe"
                    # V20 PR A / A-C4. The pre-flight runs in a CHILD process.
                    #
                    # It used to run here, in the chain parent, which then held
                    # a CUDA context and the allocator's reserved pool for the
                    # whole iteration — 6,962 MiB measured, still held three
                    # minutes after the training child had exited, while
                    # training and inference held their own copies in
                    # subprocesses. Two orchestration-only parents accounted
                    # for 55 % of all GPU memory in use.
                    #
                    # `empty_cache()` in the parent would not fix it: it frees
                    # unused cached blocks but cannot release the context or
                    # live references. Process exit is an unambiguous resource
                    # boundary; a cache call is not.
                    #
                    # Phase 6.6 A.11 still holds — the per-run hardware manifest
                    # decides the cap — but it is now FROZEN into a snapshot by
                    # this parent rather than rediscovered in the worker, so
                    # both sides share one resolved cap, device and fingerprint.
                    # A worker failure surfaces as a typed infrastructure
                    # outcome and is NEVER retried in-process; that fallback is
                    # exactly how the original defect would return, on the
                    # exception paths nobody watches.
                    # See docs/design/v20_priorities/pr_a_isolated_preflight_wiring.md
                    resource_check = run_production_preflight(
                        model_type=active_params["model_type"],
                        model_config=active_params["model_config"],
                        train_config=active_params["train_config"],
                        loss_config=active_params["loss_config"],
                        vram_budget_gb=chosen_vram_budget,
                        hardware_context=hardware_context,
                        workspace=workspace,
                        label=exp_id,
                    )
                    if resource_check.get("status") == "error":
                        raise RuntimeError(f"Resource check error: {resource_check.get('message')}")

                    _raise_if_preflight_blocks(resource_check)

                    # Phase D.4 — constraint-aware retry. The wrapper returns
                    # ``status="schema_violation"`` when the plugin's
                    # ``PLUGIN_CONFIG_CLASS(**model_cfg)`` call raised a
                    # ``ValidationError``. This typically happens when the tuner
                    # planner proposes a config that violates a cross-field
                    # invariant (e.g. U-Net non-decreasing channels) that
                    # ``model_json_schema()`` cannot represent. Save a
                    # ``skipped_schema_violation`` record so the violating
                    # fields/values surface in next round's ``memory_history``;
                    # the attempt does NOT count as a completed round.
                    # See docs/improving_validation_awareness.md §D.4.
                    if resource_check.get("status") == "schema_violation":
                        violations = resource_check.get("violations", [])
                        offending = resource_check.get("offending_config", {})
                        violating_fields = (
                            ", ".join(v.get("loc", "?") for v in violations) or "unknown"
                        )
                        print("Schema violation — this attempt does NOT count as a round.")
                        print(f"   Violating fields : {violating_fields}")
                        for v in violations:
                            print(f"   - {v.get('loc')} ({v.get('type')}): {v.get('msg')}")

                        violation_summary = (
                            "; ".join(
                                f"{v.get('loc')}={v.get('input')!r} → {v.get('msg')}"
                                for v in violations
                            )
                            or "unspecified schema violation"
                        )
                        schema_record = _build_skip_record(
                            status="skipped_schema_violation",
                            exp_id=exp_id,
                            model_type=model_type,
                            file_index=file_index,
                            record_params=record_params,
                            expert_advice_str=expert_advice_str,
                            hypothesis=hypothesis,
                            round_index=round_index,
                            attempt_in_round=attempt_in_round,
                            conclusion=(
                                f"Skipped: plugin schema rejected the proposed model_config. "
                                f"Violating fields: {violating_fields}. "
                                f"Offending values: {offending}."
                            ),
                            discovery=resource_check.get("verdict", ""),
                            memory_update=(
                                f"DO NOT repeat this exact combination — plugin schema requires: "
                                f"{violation_summary}. Propose a config that satisfies every "
                                f"@model_validator(mode='after') and per-field bound in the "
                                f"plugin's PLUGIN_CONFIG_CLASS."
                            ),
                        )
                        _emit_record(sandbox, schema_record)
                        continue

                    if not resource_check.get("feasible", True):
                        print("Resource check FAILED — this attempt does NOT count as a round.")
                        print(f"   Verdict   : {resource_check.get('verdict', '')}")
                        print(f"   Suggestion: {resource_check.get('suggestion', '')}")

                        # Phase 6.6 WS-B B.3 Hop 2 — capture this rejection
                        # into the per-run buffer so the orchestrator can
                        # aggregate and feed it back to the next Proposer
                        # iteration as a [PHYSICAL REJECTION] string.
                        # See docs/phase66_ws_b_proposer_hardening.md §2.3.
                        _killer = resource_check.get("memory_killer") or {}
                        _binding = _killer.get("binding_cap", "vram")
                        _dom_bytes = _killer.get("dominant_layer_bytes") or 0
                        _attempt_snapshot = {
                            "model_type": model_type,
                            "batch_size": active_params.get("batch_size"),
                            "segmentation_size": active_params.get("segmentation_size"),
                        }
                        # Include architecture knobs if present — the Proposer
                        # reads these to see which dimension overshot.
                        for _k in (
                            "depth",
                            "width",
                            "hidden_dim",
                            "n_heads",
                            "d_model",
                            "kernel_size",
                            "num_layers",
                        ):
                            if _k in active_params:
                                _attempt_snapshot[_k] = active_params[_k]
                        try:
                            physical_rejections_buffer.append(
                                PhysicalRejection(
                                    attempt_config=_attempt_snapshot,
                                    binding_cap=_binding,
                                    dominant_layer=_killer.get("dominant_layer") or "",
                                    dominant_layer_gb=round(_dom_bytes / (1024**3), 4),
                                    dominant_fraction=_killer.get("dominant_fraction") or 0.0,
                                    budget_gb=float(resource_check.get("limit_gb") or 0.0),
                                    estimated_gb=float(resource_check.get("estimated_gb") or 0.0),
                                    suggestion=resource_check.get("suggestion", ""),
                                )
                            )
                        except ValidationError as _rej_err:
                            # Never let a malformed rejection abort the run;
                            # log and continue. The feedback-loop contract is
                            # best-effort — the scored path must survive even
                            # if the rejection-capture payload is malformed.
                            print(f"   [B.3] PhysicalRejection capture skipped: {_rej_err}")

                        oom_record = _build_skip_record(
                            status="skipped_oom_risk",
                            exp_id=exp_id,
                            model_type=model_type,
                            file_index=file_index,
                            record_params=record_params,
                            expert_advice_str=expert_advice_str,
                            hypothesis=hypothesis,
                            round_index=round_index,
                            attempt_in_round=attempt_in_round,
                            conclusion=(
                                f"Skipped: estimated VRAM ({resource_check.get('estimated_gb', '?')} GB) "
                                f"exceeds 80% safety limit ({resource_check.get('limit_gb', '?')} GB)."
                            ),
                            discovery=resource_check.get("verdict", ""),
                            memory_update=resource_check.get(
                                "suggestion", "Reduce batch_size or segmentation_size."
                            ),
                            memory_extra=_vram_skip_memory_extra(
                                resource_check, chosen_vram_budget
                            ),
                        )
                        _emit_record(sandbox, oom_record)
                        continue

                    # Phase 6.6 A.11 — capture the batch the VRAM skill picked
                    # and propagate it through the rest of the attempt. Lands in
                    # active_params (so _run_skill("inference_skill", ...) forwards
                    # it to sandbox.execute_inference) and record_params (so the
                    # saved record reflects what actually ran, not the legacy
                    # registry default). ``inference_batch`` is always present on
                    # a feasible resource_check; fall back to None (executor's
                    # back-compat path) if the wrapper somehow omits it.
                    chosen_inference_batch = resource_check.get("inference_batch")
                    active_params["inference_batch"] = chosen_inference_batch
                    record_params["inference_batch"] = chosen_inference_batch

                    # [Pre-flight 2/2] Wall-time gate. Mirrors the VRAM gate above:
                    # error → raise; infeasible → emit skipped_time_risk record
                    # and continue without consuming a round. Skipped entirely
                    # when the budget for the active mode is None (one-time
                    # warning per mode printed at startup).
                    # See docs/resource_estimator_implement.md §2.7 / E1 / Phase I.
                    # The result is stashed so the post-flight calibration update
                    # (Phase F) can compare warmup vs actual ms/step.
                    # Phase I: per-mode budget pick. plan.is_trial decides which
                    # ceiling applies for THIS round; the unselected one is
                    # ignored. The skill itself stays mode-agnostic — it gets a
                    # single time_budget_minutes kwarg.
                    chosen_time_budget = trial_time_budget if plan.is_trial else formal_time_budget
                    time_check = None
                    if chosen_time_budget is not None:
                        failure_stage = "time_estimation"
                        # refine_inference_time_estimator.md Commit D — pull
                        # the most recent successful trial round's measured
                        # per-PSD-segment inference cost out of this iter's
                        # memory_history (Commit C populated the field) and
                        # pass it as a hint. The wrapper prefers it over the
                        # legacy × 2.7 ratio when present and >0; absent or
                        # zero falls through to the existing fallback
                        # branches. ``memory_history`` is fetched from
                        # ``sandbox.get_summary()`` earlier in this attempt
                        # and is iter-scoped under the chain runner.
                        time_check = _run_time_preflight(
                            sandbox=sandbox,
                            active_params=active_params,
                            time_budget_minutes=chosen_time_budget,
                            data_dir=time_data_dir,
                            memory_history=memory_history,
                            is_trial=plan.is_trial,
                        )
                        if time_check.get("status") == "error":
                            # Includes the policy's ABORT path: an
                            # evidence-channel failure is an execution-system
                            # failure, never a candidate verdict.
                            raise RuntimeError(f"Time check error: {time_check.get('message')}")

                        # C9d — resolve a REQUEST_PROBE by taking the
                        # measurement (see _resolve_time_check_probe_request).
                        if (
                            _resolve_time_check_probe_request(
                                time_check,
                                model_type=model_type,
                                active_params=active_params,
                                time_budget_minutes=chosen_time_budget,
                                is_trial=plan.is_trial,
                                data_dir=time_data_dir,
                                run_name=run_name,
                                exp_id=exp_id,
                                device_identity=device_identity,
                                # M6: the declared authority decides whether
                                # an unresolvable probe may fail open.
                                result_authority=getattr(agent_input, "result_authority", None),
                            )
                            == "abort"
                        ):
                            raise RuntimeEvidenceChannelError(
                                "bounded live probe could not produce evidence: "
                                + "; ".join(
                                    (time_check.get("breakdown") or {}).get(
                                        "probe_resolution_reasons", []
                                    )
                                )
                            )

                        # Post-v15 bypass-time-budget gate: when the formal
                        # round is gated by the time estimator, but the
                        # underlying trial winner clearly beats the current
                        # run best, run it anyway. Without this gate, v15's
                        # mamba_multirate_fuser (trial 7.65) and
                        # dualpath_spectral_router (trial 7.77) never got
                        # formal validation despite being the strongest
                        # candidates in the run. The gate only loosens the
                        # time guard for the formal round (trial rounds
                        # still respect it) and only when the trial winner
                        # has already beat the current best.
                        # V19 PR 1: consume the startup-resolved
                        # threshold (single-source arithmetic;
                        # ``None`` = no chain incumbent = gate inert).
                        # M6 (2026-08-06): the bypass may loosen the TIME
                        # guard and nothing else. An attempt refused because
                        # its required measurement evidence does not exist is
                        # not time-gated, and the bypass must not clear it —
                        # otherwise the `-inf` bootstrap, which makes the
                        # bypass fire unconditionally on a fresh chain, would
                        # erase the refusal on the very first formal round and
                        # M6 would never be reached in a new campaign.
                        if (
                            is_formal_round
                            and not time_check.get("feasible", True)
                            and not is_evidence_refusal(time_check)
                            # D-C3: the SAME winner the skip gate judged,
                            # resolved once at the formal-round boundary.
                            and _should_bypass_formal_time_budget(
                                formal_trial_winner,
                                threshold=resolved_bypass_formal_threshold,
                            )
                        ):
                            _winner = formal_trial_winner
                            _best_trial_score = (
                                _winner.get("denoising_score") if _winner is not None else None
                            )
                            print(
                                f"  [BypassTimeBudget] Trial "
                                f"{_best_trial_score:.4f} >= "
                                f"reference("
                                f"{_fmt_reference(formal_reference_score)}) "
                                f"+ delta("
                                f"{agent_input.bypass_formal_time_budget_min_delta:.4f}) "
                                f"= {_fmt_reference(resolved_bypass_formal_threshold)} — "
                                f"bypassing time gate for this "
                                f"formal attempt.",
                                flush=True,
                            )
                            # Force the feasibility flag so the
                            # downstream skipped_time_risk path is
                            # skipped. The estimator's verdict and
                            # suggestion stay in time_check for the
                            # downstream record, just not as a hard
                            # rejection.
                            time_check["feasible"] = True

                        if not time_check.get("feasible", True):
                            # M6: this lane now carries two different causes,
                            # and the record must not describe one as the
                            # other. A wall-time conclusion on an
                            # evidence refusal would tell the interpreter and
                            # the proposer that the CANDIDATE was too slow —
                            # the exact contamination V19 suffered, where an
                            # infrastructure condition was read as evidence
                            # about the model.
                            _evidence_refusal = is_evidence_refusal(time_check)
                            print(
                                "Attempt NOT ADMITTED — this attempt does NOT count as a round."
                                if _evidence_refusal
                                else "Time check FAILED — this attempt does NOT count as a round."
                            )
                            print(f"   Verdict   : {time_check.get('verdict', '')}")
                            print(f"   Suggestion: {time_check.get('suggestion', '')}")

                            time_record = _build_skip_record(
                                status="skipped_time_risk",
                                exp_id=exp_id,
                                model_type=model_type,
                                file_index=file_index,
                                record_params=record_params,
                                expert_advice_str=expert_advice_str,
                                hypothesis=hypothesis,
                                round_index=round_index,
                                attempt_in_round=attempt_in_round,
                                conclusion=(
                                    "Not admitted: a formal scientific decision requires a "
                                    "bounded probe and none could be resolved. This is an "
                                    "infrastructure condition and says nothing about the "
                                    "candidate's size, speed or design."
                                    if _evidence_refusal
                                    else (
                                        f"Skipped: estimated wall-time "
                                        f"({time_check.get('estimated_minutes', '?')} min) "
                                        f"exceeds budget "
                                        f"({time_check.get('limit_minutes', '?')} min)."
                                    )
                                ),
                                discovery=time_check.get("verdict", ""),
                                # The M6 branch always sets `suggestion`, so
                                # this default is only ever the time-gated
                                # one; a second evidence-refusal string here
                                # would be unreachable.
                                memory_update=time_check.get(
                                    "suggestion",
                                    "Reduce model size, batch_size, segmentation_size, or train_portion.",
                                ),
                                memory_extra=_time_skip_memory_extra(time_check, plan),
                            )
                            _emit_record(sandbox, time_record)
                            continue

                    # RT2-G: operator runtime policy for the in-subprocess
                    # verification session (§2.1/§3). Formal rounds enforce
                    # the operator budget (the in-subprocess measured
                    # verification is the sole formal authority; the
                    # pre-flight gate above stays as the cheap screen);
                    # trial rounds run record-only so observations and
                    # priors accrue with zero behavior change.
                    active_params["runtime_policy"] = _build_runtime_policy(
                        agent_input,
                        chosen_time_budget=chosen_time_budget,
                        is_trial=plan.is_trial,
                        base_dir=sandbox.base_dir,
                    )
                    # B-G3: resolved per round, because posture follows the
                    # round actually executing. Set on the sandbox rather
                    # than threaded through every phase signature — the gate
                    # fires inside the executor for both training and
                    # inference, and one authoritative value per attempt is
                    # what keeps them from disagreeing.
                    sandbox.admission_policy = _build_admission_policy(
                        agent_input,
                        is_trial=plan.is_trial,
                        device_identity=getattr(sandbox, "device_identity", None),
                    )

                    # V20 PR C2 / C2-7. Measure this exact candidate on this
                    # card BEFORE any formal GPU work, and consume the
                    # disposition. The whole chain — planned/realized
                    # identity check, classification, authority validation,
                    # PR B admission — lives behind one call; nothing about
                    # it is reimplemented here.
                    _prephase = _handle_prephase_gpu_measurement(
                        agent_input=agent_input,
                        sandbox=sandbox,
                        is_trial=plan.is_trial,
                        active_params=active_params,
                        exp_id=exp_id,
                        model_type=model_type,
                        file_index=file_index,
                        record_params=record_params,
                        expert_advice_str=expert_advice_str,
                        hypothesis=hypothesis,
                        round_index=round_index,
                        attempt_in_round=attempt_in_round,
                    )
                    if _prephase is PrephaseOutcome.TERMINAL_INFRASTRUCTURE_FAILURE:
                        # The measurement could not be established. Retrying
                        # re-enters the identical deterministic condition —
                        # V20 attempt 2 did exactly that 15 times, burning
                        # attempts_per_round while the GPU was idle. So the
                        # ROUND ends here. `break` leaves the attempt loop
                        # without consuming further attempts, and the round's
                        # own no-success handling records the outcome; it does
                        # not fabricate a completed round or a score.
                        print(
                            "  Ending this round: the pre-phase measurement "
                            "infrastructure is unavailable, so further attempts "
                            "would repeat an identical failure."
                        )
                        break
                    if _prephase is PrephaseOutcome.TERMINAL_RESOURCE_REFUSAL:
                        # Measured, and it genuinely does not fit. A different
                        # candidate may — so this consumes the attempt as
                        # before and the loop continues.
                        continue

                    failure_stage = "training"
                    print("\n[Step 1/3] Training...")
                    t0 = time.time()
                    train_status = _run_skill("training_skill", sandbox, **active_params)
                    train_time = round(time.time() - t0, 1)
                    _raise_if_wall_clock_timeout(train_status, sandbox, run_name)
                    _raise_if_evidence_channel_failure(train_status, sandbox, run_name)
                    if _handle_admission_refusal(
                        train_status,
                        phase="training",
                        sandbox=sandbox,
                        exp_id=exp_id,
                        model_type=model_type,
                        file_index=file_index,
                        record_params=record_params,
                        expert_advice_str=expert_advice_str,
                        hypothesis=hypothesis,
                        round_index=round_index,
                        attempt_in_round=attempt_in_round,
                    ):
                        continue
                    if _handle_in_subprocess_rejection(
                        train_status,
                        sandbox=sandbox,
                        run_name=run_name,
                        exp_id=exp_id,
                        model_type=model_type,
                        file_index=file_index,
                        record_params=record_params,
                        expert_advice_str=expert_advice_str,
                        hypothesis=hypothesis,
                        is_trial=plan.is_trial,
                        round_index=round_index,
                        attempt_in_round=attempt_in_round,
                    ):
                        continue
                    if train_status.get("status") == "error":
                        # DataScope DS5 — scope violations are non-retryable
                        # configuration/invariant failures: terminate the run.
                        if train_status.get("error_type") == "scope_violation":
                            _scope_violation_reason = train_status.get(
                                "message", "scope violation in training"
                            )
                            break
                        error_record = _build_execution_failure_record(
                            train_status,
                            phase="training",
                            exp_id=exp_id,
                            model_type=model_type,
                            file_index=file_index,
                            record_params=record_params,
                            expert_advice_str=expert_advice_str,
                            hypothesis=hypothesis,
                            round_index=round_index,
                            attempt_in_round=attempt_in_round,
                        )
                        _emit_record(sandbox, error_record, status=train_status)
                        print(f"  Saved error record: {error_record['status']}")
                        continue

                    # Inference + scoring + result extraction wrapped in
                    # try/finally so the per-attempt HDF5 cleanup ALWAYS fires
                    # — including on inference-OOM ``continue``, scoring-crash
                    # ``continue``, and any uncaught exception. Pre-fix the
                    # cleanup lived inline at the end of the success path and
                    # silently leaked ~80 GB of denoised HDF5 files per failed
                    # attempt (see docs/design/enable_loss_inventory.md
                    # § Checkpoint L "tmpfs leak fix").
                    try:
                        failure_stage = "inference"
                        print("[Step 2/3] Inference...")
                        t0 = time.time()
                        inf_status = _run_skill("inference_skill", sandbox, **active_params)
                        inference_time = round(time.time() - t0, 1)
                        _raise_if_wall_clock_timeout(inf_status, sandbox, run_name)
                        _raise_if_evidence_channel_failure(inf_status, sandbox, run_name)
                        if _handle_admission_refusal(
                            inf_status,
                            phase="inference",
                            sandbox=sandbox,
                            exp_id=exp_id,
                            model_type=model_type,
                            file_index=file_index,
                            record_params=record_params,
                            expert_advice_str=expert_advice_str,
                            hypothesis=hypothesis,
                            round_index=round_index,
                            attempt_in_round=attempt_in_round,
                        ):
                            continue
                        if inf_status.get("status") == "error":
                            # DataScope DS5 — non-retryable: terminate the run.
                            if inf_status.get("error_type") == "scope_violation":
                                _scope_violation_reason = inf_status.get(
                                    "message", "scope violation in inference"
                                )
                                break
                            error_record = _build_execution_failure_record(
                                inf_status,
                                phase="inference",
                                exp_id=exp_id,
                                model_type=model_type,
                                file_index=file_index,
                                record_params=record_params,
                                expert_advice_str=expert_advice_str,
                                hypothesis=hypothesis,
                                round_index=round_index,
                                attempt_in_round=attempt_in_round,
                            )
                            _emit_record(sandbox, error_record, status=inf_status)
                            print(f"  Saved error record: {error_record['status']}")
                            continue

                        failure_stage = "scoring"
                        print("[Step 3/3] Scoring...")
                        # Fix 4 — memory probe around the scoring block. See
                        # docs/optimize_inference_and_scoring.md §3 Fix 4. The
                        # tuner's ``round_index`` is the iter axis inside the
                        # tuner scope; workflow-scope probes (different
                        # ``scope`` field) give the outer iteration index.
                        from core.memory_probe import probe_memory

                        probe_memory(
                            iter_idx=round_index,
                            phase="pre_score",
                            workspace=workspace,
                            scope="tuner",
                        )
                        t0 = time.time()
                        # V8 hardening Domain 2a — wrap the entire scoring block.
                        # Pre-V8, an exception in score_vector / denoising_score_skill
                        # bubbled past the loop without writing a record, so the
                        # tuner's iteration silently lost evidence (training
                        # checkpoint preserved on disk but no entry in
                        # memory_history). Now we catch, write an error_scoring
                        # record (matches the error_training/inference pattern
                        # above), and continue. See docs/V8_Gap_Report.md Domain 2a.
                        try:
                            if anchor_map_data is not None:
                                # Anchor-normalized scoring (both trial and formal modes).
                                # Trial: sparse SampleSet. Formal: full SampleSet (all 20 × 200).
                                # B023 — default-arg locking pins the captured loop
                                # variables at definition time; without it a future
                                # refactor that defers the call would hit the last
                                # iteration's model_type / exp_id.
                                # Bug A fix (PR #101 Gate 2 forensic): return an
                                # absolute path so downstream consumers that use the
                                # string verbatim (HealthCheckContext.get_denoised_path
                                # per the peek helper's path contract in
                                # execute_tools/health_checks/_peek.py:20-24) can open
                                # the file directly. Callers that also os.path.join a
                                # data_dir (scoring_utils.process_segment) are
                                # unaffected — os.path.join discards the base when
                                # the second arg is absolute.
                                def _denoised_fn(
                                    fi,
                                    model_type=model_type,
                                    exp_id=exp_id,
                                    base_dir=sandbox.base_dir,
                                ):
                                    return _build_denoised_filename(
                                        model_type=model_type,
                                        run_name=run_name,
                                        exp_id=exp_id,
                                        file_index=fi,
                                        base_dir=base_dir,
                                    )

                                file_vector, final_scalar = sandbox.score_vector(
                                    sample_set=eval_sample_set,
                                    anchor_map=anchor_map_data["anchors"],
                                    s_max=anchor_map_data["s_max"],
                                    denoised_filename_fn=_denoised_fn,
                                )

                                # Tuner-side gate evaluation (commit-5b).
                                # score_vector is pure scoring post-5a; the HealthGate
                                # model runs here at the round boundary per
                                # docs/design/pluggable_health_checks.md §8.
                                # Loop control (SKIP_ITER, SKIP_TO_FORMAL) is applied
                                # after the attempts loop; see the block below.
                                # Target-signal path resolver for CH2-comparing
                                # recording checks (pearson_dispersion, etc.).
                                # M8 §3.4: the check module stays task-agnostic;
                                # the tuner constructs the task-specific path here.
                                def _target_fn(i: int, _base: str = TIDMAD_DATA_DIR) -> str:
                                    return os.path.join(_base, f"abra_validation_{i:04d}.h5")

                                if agent_input.health_gate_enabled:
                                    _gate_ids = (
                                        get_gates_for_position(
                                            round_index,
                                            config_path=agent_input.health_checks_config,
                                        )
                                        if agent_input.health_checks_config
                                        else get_gates_for_position(round_index)
                                    )
                                    _sandbox_dirs = getattr(sandbox, "dirs", {})
                                    _models_dir = (
                                        _sandbox_dirs.get("models")
                                        if isinstance(_sandbox_dirs, dict)
                                        else None
                                    )
                                    _checkpoint_path = (
                                        os.path.join(
                                            _models_dir,
                                            f"model_{model_type}_{exp_id}_agent.pth",
                                        )
                                        if _gate_ids and _models_dir
                                        else None
                                    )
                                    _hc_ctx = HealthCheckContext(
                                        model_name=model_type,
                                        run_name=run_name,
                                        round_index=round_index,
                                        denoised_filename_fn=_denoised_fn,
                                        target_path_fn=_target_fn,
                                        checkpoint_path=_checkpoint_path,
                                        file_vector=file_vector,
                                        denoising_score=final_scalar,
                                    )
                                    _gate_results, _persisted_gate_results, resolved_action = (
                                        evaluate_and_persist_health_gates(
                                            _hc_ctx,
                                            config_path=agent_input.health_checks_config,
                                            production_config_path=os.path.join(
                                                SIDERIUS_ROOT, "configs", "health_checks.yaml"
                                            ),
                                            gate_ids=_gate_ids,
                                            # D-C7b: the run's declaration
                                            # travels onto every gate result,
                                            # so an external reader never has
                                            # to infer the posture from a
                                            # gate id's spelling.
                                            healthgate_mode=agent_input.healthgate_mode,
                                            result_authority=agent_input.result_authority,
                                        )
                                    )
                                    is_degenerate, failure_reason, _gate_action_str = (
                                        _gate_results_to_score_meta(_gate_results, resolved_action)
                                    )
                                else:
                                    # DataScope DS5 — HealthGate subsystem
                                    # explicitly disabled: no gate evaluation,
                                    # no gate persistence. Score-validity
                                    # classification (the merge below) stays
                                    # active regardless.
                                    _persisted_gate_results = []
                                    resolved_action = GateAction.CONTINUE
                                    is_degenerate, failure_reason, _gate_action_str = (
                                        False,
                                        None,
                                        None,
                                    )
                                is_degenerate, failure_reason = _merge_score_validity_failure(
                                    final_scalar,
                                    is_degenerate=is_degenerate,
                                    failure_reason=failure_reason,
                                )
                                score_res = {
                                    "status": "success",
                                    "results": {
                                        "denoising_score": final_scalar,
                                        "file_vector": file_vector,
                                        "is_degenerate": is_degenerate,
                                        "failure_reason": failure_reason,
                                        "gate_action": _gate_action_str,
                                        "health_gate_results": [
                                            item.model_dump(mode="json")
                                            for item in _persisted_gate_results
                                        ],
                                    },
                                }
                            else:
                                # Legacy single-file mode (trial_allowed=False, no anchor map)
                                score_res = _run_skill(
                                    "denoising_score_skill", sandbox, **active_params
                                )
                        except ScopeViolationError as e:
                            # DataScope DS5 — non-retryable: terminate the run
                            # (must precede the generic handler below, which
                            # would otherwise convert this into a retried
                            # error_scoring record).
                            _scope_violation_reason = f"error_scope_violation: {e}"
                            break
                        except Exception as e:
                            scoring_time = round(time.time() - t0, 1)
                            probe_memory(
                                iter_idx=round_index,
                                phase="post_score",
                                workspace=workspace,
                                scope="tuner",
                            )
                            error_msg = f"{type(e).__name__}: {e}"
                            short_msg = error_msg[-500:] if len(error_msg) > 500 else error_msg
                            error_record = {
                                "exp_id": exp_id,
                                "status": "error_scoring",
                                "model_type": model_type,
                                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "file_index": file_index,
                                "params": record_params,
                                "denoising_score": None,
                                "timing": {
                                    "train_time_s": train_time,
                                    "inference_time_s": inference_time,
                                    "scoring_time_s": scoring_time,
                                },
                                "memory": {
                                    "expert_advice_followed": expert_advice_str,
                                    "hypothesis": hypothesis,
                                    "conclusion": f"Scoring crashed: {short_msg}",
                                    "discovery": (
                                        f"Training and inference completed but scoring "
                                        f"raised {type(e).__name__}: {short_msg}"
                                    ),
                                    "memory_update": (
                                        "Scoring crash — training succeeded so the "
                                        "checkpoint may be reusable. Investigate the "
                                        "scoring path (anchor map, sample_set, file "
                                        "vector shape) before retrying this config."
                                    ),
                                },
                            }
                            error_record["memory"]["round_index"] = round_index
                            error_record["memory"]["attempt_in_round"] = attempt_in_round
                            _emit_record(sandbox, error_record)
                            print(f"  Saved error record: {error_record['status']}")
                            continue
                        scoring_time = round(time.time() - t0, 1)
                        probe_memory(
                            iter_idx=round_index,
                            phase="post_score",
                            workspace=workspace,
                            scope="tuner",
                        )

                        # Extract results from each stage
                        train_results = train_status.get("results", {})
                        score_results = score_res.get("results", {})

                        # Generic degeneracy reaction. The task-specific predicate
                        # already ran tuner-side (evaluate_gate + resolve_action +
                        # _gate_results_to_score_meta) and produced is_degenerate /
                        # failure_reason / gate_action on score_results.
                        # Here we only translate that signal into the tuner-level
                        # policy: penalize the formal score so the round can't be
                        # picked as 'best', and surface failure_reason on the record.
                        # See _apply_degeneracy_reaction for predicate details.
                        is_degenerate, failure_reason = _apply_degeneracy_reaction(
                            score_results,
                            plan,
                            agent_input.degenerate_penalty_score,
                        )
                        _is_degenerate_formal = is_degenerate and not plan.is_trial

                        # Build the per-file score-comparison table (model vs
                        # raw_baseline vs ground_truth) with subset-scoped
                        # aggregates. Defensive try/except — the 15-hour tuning
                        # loop must not crash on a rendering bug; a None
                        # score_table simply skips the enriched prompt block in
                        # the next round. See docs/aggregated_score_table_awareness.md §7.1.
                        # Skipped on degenerate-formal rounds even when a non-None
                        # penalty leaves the scalar populated — rendering the
                        # penalty into the markdown 'model' column would mislead
                        # the next planner. failure_reason carries the signal.
                        # Phase 8 / P0 (docs/aggregated_score_table_awareness.md):
                        # ``score_vector`` returns ``file_vector`` in LINEAR space
                        # (per-file mean of the normalised score), but
                        # ``build_score_table`` expects the model column in LOG
                        # space so it is unit-consistent with the log-space
                        # reference columns. Convert via the project-standard
                        # log_{5.27}(v) helper before handing off.
                        score_table: ScoreComparisonTable | None = None
                        _sc_fv = score_results.get("file_vector")
                        _sc_scalar = score_results.get("denoising_score")
                        if (
                            _sc_fv is not None
                            and _sc_scalar is not None
                            and not _is_degenerate_formal
                        ):
                            try:
                                _sc_fv_log = file_vector_to_log_space(_sc_fv)
                                score_table = build_score_table(
                                    model_fv_log=_sc_fv_log,
                                    model_fv_linear=_sc_fv,
                                    model_scalar=_sc_scalar,
                                    reference=reference_scores,
                                )
                            except Exception as e:
                                print(
                                    f"[score_table] build_score_table failed: "
                                    f"{type(e).__name__}: {e} — continuing with "
                                    f"score_table=None."
                                )
                                score_table = None

                        # Phase 8 / P-Alpha: append every successfully-built
                        # score_table to the workspace audit stream so we have
                        # a queryable record of exactly what was rendered for
                        # the next agent. Best-effort — failures are logged
                        # inside ``log_score_table`` and never raised.
                        if score_table is not None:
                            log_score_table(
                                workspace=workspace,
                                score_table=score_table,
                                metadata={
                                    "run_name": run_name,
                                    "model_type": agent_input.model_type,
                                    "exp_id": exp_id,
                                    "round_index": round_index,
                                    "attempt_in_round": attempt_in_round,
                                    "is_trial": plan.is_trial,
                                    "table_kind": "trial" if plan.is_trial else "formal",
                                },
                            )

                    finally:
                        # Cleanup denoised files — fires on success, on
                        # ``continue`` from the inference/scoring error handlers
                        # above, AND on any uncaught exception. Glob is keyed to
                        # this attempt's ``exp_id`` so other attempts' files
                        # (e.g. from a not-yet-cleaned prior leak) are untouched.
                        if agent_input.cleanup_denoised:
                            import glob as _glob

                            pattern = os.path.join(
                                sandbox.base_dir,
                                f"abra_validation_denoised_*_{exp_id}_*.h5",
                            )
                            denoised_files = _glob.glob(pattern)
                            if denoised_files:
                                total_bytes = sum(os.path.getsize(f) for f in denoised_files)
                                for f in denoised_files:
                                    os.remove(f)
                                print(
                                    f"  Cleaned up {len(denoised_files)} denoised files "
                                    f"({total_bytes / (1024**3):.1f} GB freed)"
                                )

                    # D. REFLECT: Analyze results and generate insights
                    print("\nGenerating Research Memory...")

                    current_score = score_results.get("denoising_score")
                    current_loss_type = active_params["loss_config"].get("loss_type")
                    successful: list[dict] = [
                        r
                        for r in memory_history
                        if r.get("status") == "success" and r.get("denoising_score") is not None
                    ]
                    baseline_record = next(
                        (r for r in memory_history if "baseline" in r.get("exp_id", "")), None
                    )
                    all_scores = [r["denoising_score"] for r in successful]
                    best_score = max(all_scores) if all_scores else None
                    best_record = (
                        max(successful, key=lambda r: r["denoising_score"]) if successful else None
                    )
                    sorted_scores = sorted(all_scores, reverse=True)
                    rank = (
                        sorted_scores.index(current_score) + 1
                        if current_score in sorted_scores
                        else None
                    )

                    same_loss_finals = [
                        r["final_loss"]
                        for r in successful
                        if r.get("params", {}).get("loss_config", {}).get("loss_type")
                        == current_loss_type
                        and r.get("final_loss") is not None
                    ]
                    current_final_loss = train_results.get("final_loss")
                    if current_final_loss is not None:
                        all_same_loss_finals = [*same_loss_finals, current_final_loss]
                        sorted_finals = sorted(all_same_loss_finals)
                        same_loss_loss_rank = sorted_finals.index(current_final_loss) + 1
                        same_loss_total = len(all_same_loss_finals)
                    else:
                        same_loss_loss_rank = None
                        same_loss_total = len(same_loss_finals)

                    current_params = train_results.get("model_params")
                    current_epochs = active_params["train_config"].get("epochs")
                    baseline_params = (
                        baseline_record.get("model_params") if baseline_record else None
                    )
                    baseline_epochs = (
                        baseline_record.get("params", {}).get("train_config", {}).get("epochs")
                        if baseline_record
                        else None
                    )
                    params_ratio = (
                        round(current_params / baseline_params, 3)
                        if (current_params and baseline_params)
                        else None
                    )
                    epochs_ratio = (
                        round(current_epochs / baseline_epochs, 3)
                        if (current_epochs and baseline_epochs)
                        else None
                    )

                    worst_score = min(all_scores) if all_scores else None
                    score_range = (
                        (best_score - worst_score)
                        if (
                            best_score is not None
                            and worst_score is not None
                            and best_score != worst_score
                        )
                        else None
                    )
                    score_threshold = (
                        (best_score - 0.05 * score_range) if score_range is not None else best_score
                    )
                    best_params = best_record.get("model_params") if best_record else None
                    best_epochs = (
                        best_record.get("params", {}).get("train_config", {}).get("epochs")
                        if best_record
                        else None
                    )
                    is_more_efficient = (
                        score_threshold is not None
                        and current_score is not None
                        and current_score >= score_threshold
                        and (
                            (
                                current_params is not None
                                and best_params is not None
                                and current_params < best_params
                            )
                            or (
                                current_epochs is not None
                                and best_epochs is not None
                                and current_epochs < best_epochs
                            )
                        )
                    )

                    reflection_context = {
                        "baseline_score": baseline_record.get("denoising_score")
                        if baseline_record
                        else None,
                        "best_score_so_far": best_score,
                        "is_new_best": current_score is not None
                        and (best_score is None or current_score > best_score),
                        "rank": rank,
                        "total_experiments": len(successful),
                        "best_config_so_far": best_record.get("params") if best_record else None,
                        "best_same_loss_final_loss": min(same_loss_finals)
                        if same_loss_finals
                        else None,
                        "current_loss_type": current_loss_type,
                        "same_loss_loss_rank": same_loss_loss_rank,
                        "same_loss_total": same_loss_total,
                        "baseline_params": baseline_params,
                        "baseline_epochs": baseline_epochs,
                        "current_params": current_params,
                        "current_epochs": current_epochs,
                        "params_ratio": params_ratio,
                        "epochs_ratio": epochs_ratio,
                        "is_more_efficient": is_more_efficient,
                        "training_psd_segments": train_psd_segments,
                        "eval_psd_segments": eval_psd_segments,
                        "baseline_psd_segments": baseline_record.get("training_psd_segments")
                        if baseline_record
                        else None,
                        "trial_portion": trial_config.trial_portion
                        if trial_config.mode != "single_file"
                        else None,
                        "eval_portion": trial_config.eval_portion
                        if trial_config.mode != "single_file"
                        else None,
                        # Pre-rendered per-file comparison table (model vs
                        # raw_baseline vs ground_truth) — consumed verbatim
                        # by the reflector prompt in sub-commit C. None on
                        # failed/skipped rounds so the prompt can branch.
                        "score_comparison_table": score_table.rendered_markdown
                        if score_table
                        else None,
                    }

                    # Pass both training and scoring results to the reflector
                    reflect_results = {**train_results, **score_results}
                    reflection = brain.reflect(
                        exp_id, hypothesis, reflect_results, reflection_context
                    )

                    # Defensive unwrap: LLM occasionally emits [{...}] instead of {...}.
                    if (
                        isinstance(reflection, list)
                        and len(reflection) == 1
                        and isinstance(reflection[0], dict)
                    ):
                        print("[reflect] LLM returned a single-element list — unwrapping to dict.")
                        reflection = reflection[0]
                    if not isinstance(reflection, dict):
                        print(
                            f"[reflect] LLM returned non-dict ({type(reflection).__name__}); using empty reflection."
                        )
                        reflection = {}

                    print(f"{'-' * 30}")
                    print(f"RESEARCH REFLECTION for {exp_id}:")
                    print(f"Conclusion  : {reflection.get('conclusion', 'N/A')}")
                    print(f"Key Factor  : {reflection.get('key_factor', 'N/A')}")
                    print(f"Discovery   : {reflection.get('discovery', 'N/A')}")
                    print(f"Memory Update: {reflection.get('memory_update', 'N/A')}")
                    print(f"{'-' * 30}")

                    # E. COMMIT: Build, validate, and save the finalized record
                    final_record = {
                        "exp_id": exp_id,
                        # Collapse is a completed result in both trial and formal modes.
                        "status": "failed_mode_collapse" if is_degenerate else "success",
                        "model_type": model_type,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "file_index": file_index,
                        "params": record_params,
                        # Training results
                        "final_loss": train_results.get("final_loss"),
                        "loss_history": train_results.get("loss_history"),
                        "model_params": train_results.get("model_params"),
                        # Scoring results
                        "denoising_score": score_results.get("denoising_score"),
                        "file_vector": score_results.get("file_vector"),
                        # Per-file comparison table enrichment. Stored as a
                        # plain dict on the record (ExperimentRecord.model_validate
                        # coerces it back to ScoreComparisonTable below). None
                        # when scoring failed or no scalar was produced.
                        "score_table": score_table.model_dump() if score_table else None,
                        # Health-check failure reason from tuner-side gate
                        # evaluation (commit-5b). Written unconditionally when
                        # non-None — trial-round SKIP_ITER also propagates its
                        # reason string so the next planner iteration sees the
                        # diagnostic even though _apply_degeneracy_reaction
                        # preserves the trial score (audit Gap #1 fix,
                        # follow-up to commit-5b).
                        "failure_reason": failure_reason,
                        # Resolved gate action string from tuner-side gate
                        # evaluation. "continue" on healthy rounds where gates
                        # ran; "skip_iter" / "skip_to_formal" / "invalidate_round"
                        # on failed gates; None on error paths and single-file
                        # legacy mode where scoring didn't run through the gate
                        # path (audit Gap #2 fix, follow-up to commit-5b).
                        "gate_action": score_results.get("gate_action"),
                        "health_gate_results": score_results.get("health_gate_results", []),
                        # Data volume
                        "training_psd_segments": train_psd_segments,
                        "eval_psd_segments": eval_psd_segments,
                        "timing": {
                            "train_time_s": train_time,
                            "inference_time_s": inference_time,
                            "scoring_time_s": scoring_time,
                        },
                        "memory": {
                            "expert_advice_followed": expert_advice_str,
                            "hypothesis": hypothesis,
                            "conclusion": reflection.get("conclusion"),
                            "key_factor": reflection.get("key_factor"),
                            "discovery": reflection.get("discovery"),
                            "memory_update": reflection.get("memory_update"),
                        },
                    }
                    # Phase J — surface pre-flight time-estimator context to the
                    # planner via the next round's experiment_history. Only added
                    # when the gate actually ran (chosen_time_budget was set);
                    # the keys are absent on records produced with the gate
                    # disabled, so the reflector doesn't have to filter None.
                    # See docs/resource_estimator_implement.md §J.1.
                    if time_check is not None:
                        final_record["memory"]["time_estimate_minutes"] = time_check.get(
                            "estimated_minutes"
                        )
                        final_record["memory"]["time_budget_minutes"] = time_check.get(
                            "limit_minutes"
                        )
                        final_record["memory"]["time_mode"] = "trial" if plan.is_trial else "formal"
                        # refine_inference_time_estimator.md Commit D — record
                        # which branch of the 3-way inference-ms derivation
                        # the gate took. Audit logs distinguish a measured
                        # ``trial_inference_warmup`` verdict from the legacy
                        # ``training_warmup_x2.7_fallback`` and the
                        # ``static_formula`` paths. Source is None on records
                        # where the breakdown didn't carry it (defensive).
                        final_record["memory"]["inference_ms_source"] = (
                            time_check.get("breakdown") or {}
                        ).get("inference_ms_source")
                        # RT3 — planner-visible training-estimate provenance:
                        # which §3 branch produced the pre-flight training
                        # ms/step (real_dataset_warmup | store |
                        # static_uncalibrated) and whether the store-reuse
                        # policy fired.
                        final_record["memory"]["training_ms_source"] = (
                            time_check.get("breakdown") or {}
                        ).get("source")
                        if (time_check.get("breakdown") or {}).get("store_reuse"):
                            final_record["memory"]["time_store_reuse"] = True
                    # Phase K — surface pre-flight VRAM-estimator context to the
                    # planner the same way Phase J surfaces time context. Only
                    # added when the gate ran with a budget (chosen_vram_budget
                    # was set); omitted when the gate fell back to free×0.8.
                    # Mode is inferred from `time_mode` above when present.
                    # See docs/resource_estimator_implement.md §10.4.
                    if chosen_vram_budget is not None:
                        final_record["memory"]["vram_estimate_gb"] = resource_check.get(
                            "estimated_gb"
                        )
                        final_record["memory"]["vram_budget_gb"] = resource_check.get("limit_gb")
                    # K.2.5-8 — soft-fallback flag from the inference estimator.
                    # Independent of vram_budget being set; recorded whenever
                    # the gate reported a substitution so post-hoc audit can
                    # identify success rounds that ran against a guessed batch.
                    if resource_check.get("inference_batch_uncalibrated"):
                        final_record["memory"]["inference_batch_uncalibrated"] = True
                    # refine_inference_time_estimator.md Commit C — persist the
                    # measured per-PSD-segment inference cost into the round's
                    # memory whenever the trial-mode subprocess emitted a
                    # populated sidecar. Commit D will read this value back via
                    # ``_latest_trial_inference_marginal`` to feed the formal
                    # round's time gate as a hint, replacing the hand-calibrated
                    # × 2.7 ratio that drove V9 §8 over-prediction. The fields
                    # are written even when the aggregator returns ``None`` —
                    # an absent sidecar (legacy / OOM-killed trial / non-trial
                    # round) falls through to ``inf_status.get(...)`` returning
                    # an empty list, the aggregator returning ``None``, and the
                    # measurement keys staying ``None``. The schema accepts None
                    # for all six (Optional[T] = None), so nothing breaks for
                    # legacy or fallback rounds.
                    inf_per_file = inf_status.get("per_file_timings_ms", []) or []
                    inf_per_psd_seg_ms, inf_breakdown = _aggregate_inference_file_timings(
                        inf_per_file
                    )
                    final_record["memory"]["inference_per_psd_seg_ms_measured"] = inf_per_psd_seg_ms
                    final_record["memory"]["inference_warmup_aggregator"] = inf_breakdown.get(
                        "aggregator"
                    )
                    final_record["memory"]["inference_n_timed_files"] = inf_breakdown.get(
                        "n_timed_files"
                    )
                    final_record["memory"]["inference_warmup_fraction"] = inf_breakdown.get(
                        "warmup_fraction"
                    )
                    final_record["memory"]["inference_process_startup_ms"] = inf_status.get(
                        "process_startup_ms"
                    )
                    # Phase L — round bookkeeping for the per-round budget audit.
                    final_record["memory"]["round_index"] = round_index
                    final_record["memory"]["attempt_in_round"] = attempt_in_round
                    # DataScope DS5 — run-invariant stamps (scope-homogeneity
                    # ingress checks + self-describing disabled-mode records
                    # for candidate eligibility) and strategy-normalization
                    # provenance. The existing trial_strategy / eval_strategy
                    # fields below hold the EFFECTIVE strategies.
                    final_record["resolved_data_scope"] = resolved_data_scope
                    final_record["health_gate_enabled"] = agent_input.health_gate_enabled
                    # FU-D-12 — workload-ceiling provenance. Recorded on EVERY
                    # round so a Gate can PROVE the workload was bounded rather
                    # than merely that a CLI flag was accepted. Carries the
                    # planned values as well as the resolved ones: without the
                    # before/after pair, a clamp that silently stopped firing
                    # would be indistinguishable from a planner that happened
                    # to choose small values.
                    final_record["validation_workload_ceiling"] = {
                        "enabled": agent_input.validation_max_portion is not None,
                        "configured_ceiling": agent_input.validation_max_portion,
                        "planned": _planned_portions,
                        "resolved": {
                            "trial_portion": cfg_trial_portion,
                            "train_portion": cfg_train_portion,
                            "eval_portion": cfg_eval_portion,
                        },
                    }
                    # V19 PR 2 — data-ordering provenance. Stamped for EVERY
                    # round (trial and formal alike), unlike the trial-only
                    # block below: ordering applies to all training. Only the
                    # resolved_* pair describes execution; proposed/override
                    # explain why, and a rejected proposal is recorded AS
                    # rejected so it is never read as agent silence.
                    final_record["proposed_order_strategy"] = ordering.proposed_strategy
                    final_record["proposed_file_order"] = ordering.proposed_file_order
                    final_record["ordering_proposal_rejected"] = ordering.proposal_rejected
                    final_record["ordering_proposal_rejection_reason"] = (
                        ordering.proposal_rejection_reason
                    )
                    final_record["override_order_strategy"] = ordering.override_strategy
                    final_record["override_file_order"] = ordering.override_file_order
                    final_record["resolved_order_strategy"] = ordering.resolved_strategy
                    final_record["resolved_file_order"] = ordering.resolved_file_order
                    final_record["ordering_resolution_source"] = ordering.resolution_source
                    # --- V20 PR D (D-C2b): formal authority verdict -----
                    # Attached to EVERY formal record — valid, invalid,
                    # diagnostic and validity-unknown alike — because the
                    # question "may this inform science?" has an answer in
                    # all four cases, and a field present only on successes
                    # would make absence ambiguous.
                    #
                    # Trial records get NO block at all. Writing
                    # `authoritative: False` on a trial would conflate
                    # "formal authority does not apply here" with "this
                    # formal result was judged untrustworthy".
                    #
                    # The verdict comes ONLY from `from_context`; this site
                    # never assembles `authoritative` / `primary_basis` /
                    # `blocking_reasons` itself. Validity comes from THIS
                    # record's own role-aware gate results — never from the
                    # trial winner, a trial count, the score, the
                    # skip/bypass decision or `force_formal_round`.
                    if not trial_config.is_trial:
                        final_record["scientific_authority"] = ScientificAuthority.from_context(
                            healthgate_mode=agent_input.healthgate_mode,
                            declared_result_authority=agent_input.result_authority,
                            formal_validity=formal_validity_of(
                                final_record,
                                config_path=agent_input.health_checks_config,
                            ),
                        ).model_dump()

                    # Trial context
                    if trial_config.is_trial:
                        final_record["is_trial"] = True
                        final_record["trial_strategy"] = trial_config.trial_strategy
                        final_record["trial_portion"] = trial_config.trial_portion
                        final_record["eval_strategy"] = trial_config.eval_strategy
                        final_record["eval_portion"] = trial_config.eval_portion
                        final_record["train_portion"] = trial_config.train_portion
                        final_record["planned_trial_strategy"] = planned_trial_strategy
                        final_record["planned_eval_strategy"] = planned_eval_strategy
                        final_record["strategy_normalization_reason"] = (
                            strategy_normalization_reason
                        )
                        if trial_config.trial_strategy == "target":
                            final_record["target_files"] = trial_config.target_files

                    # RT2-G (§7.3 additive): the attempt's runtime observation.
                    # The inference-side block is the most complete (it RESUMED
                    # the training subprocess's observation — RT2-D); fall back
                    # to the training-side block; explicit None otherwise.
                    final_record["runtime_verification"] = (
                        (inf_status or {}).get("runtime_verification")
                        or train_status.get("runtime_verification")
                        or None
                    )

                    # V21 PR B2 — join the admission forecast to the realized
                    # peak before the record is emitted. One call; the logic
                    # and its tests live in the extracted boundary.
                    _attach_realized_memory(
                        final_record, resource_check, final_record["runtime_verification"]
                    )

                    _emit_record(sandbox, final_record)
                    _append_runtime_observation(
                        sandbox, run_name, final_record["runtime_verification"]
                    )
                    # V20 PR C1 / C-C3c: the derived calibration view of the
                    # SAME measurement System A just persisted. Success path
                    # only -- see the helper's docstring for why not the
                    # shared append helper.
                    _derive_calibration_from_observation(
                        sandbox,
                        rv_block=final_record["runtime_verification"],
                        device_identity=device_identity,
                        data_dir=time_data_dir,
                    )

                    # Phase F post-flight REMOVED (operator decision 2026-08-03).
                    # A successful run used to feed its observed-vs-predicted
                    # ratio through an asymmetric EMA into the legacy v1 per-GPU
                    # k table. That table is now PRESERVED READ-ONLY for
                    # compatibility and audit: production neither reads it into
                    # a verdict nor writes to it.
                    #
                    # Stopping the write is not cosmetic. A legacy store that
                    # keeps growing still looks like a live production system,
                    # and a live-looking store is what invites someone to wire it
                    # back into a decision. New evidence goes to the v2 registry
                    # only (C-C3c, just above), where drift analysis belongs.

                    # Phase L — success path: mark the round landed, reset the
                    # consecutive-failure counter, and break out of the inner
                    # attempt loop so the outer while moves on to the next round.
                    round_succeeded = True
                    completed_rounds += 1
                    consecutive_fails = 0
                    print(
                        f"Round {completed_rounds}/{max_rounds} Complete. "
                        f"Score: {score_results.get('denoising_score', 'N/A')}"
                    )

                    time.sleep(2)  # Cool-down to avoid API rate limits
                    break

                except Exception as e:
                    if isinstance(e, RuntimeEvidenceChannelError):
                        # C9c: infrastructure class — the machinery that
                        # produces runtime evidence is broken, so no further
                        # candidate can be judged. Terminates the chain.
                        _evidence_channel_failure = str(e)
                        break
                    if isinstance(e, PlanOverridesError):
                        # FU-10 — deterministic operator-configuration error;
                        # retrying cannot change it and recording it as an
                        # attempt failure would burn the retry budget.
                        # Propagate out of run(). (Folded into this handler
                        # rather than an own except clause: one more clause
                        # on this try pushes run() past pyright's
                        # complexity-analysis ceiling.)
                        raise
                    print(f"Loop Error: {e}")
                    traceback.print_exc()
                    failure_reason = str(e)
                    failure_type = _classify_attempt_failure(e, failure_stage)
                    traceback_summary = traceback.format_exc()[-4000:]
                    failure_record = {
                        "record_type": "attempt_failure",
                        "exp_id": exp_id,
                        "status": "error",
                        "model_type": model_type,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "file_index": file_index,
                        "params": record_params,
                        "logical_round": round_index,
                        "attempt_index": total_attempts,
                        "failure_stage": failure_stage,
                        "failure_type": failure_type,
                        "failure_reason": failure_reason,
                        "proposed_config": record_params,
                        "traceback_summary": traceback_summary,
                        "counts_toward_completed_rounds": False,
                        "counts_toward_attempt_budget": True,
                        "memory": {
                            "expert_advice_followed": expert_advice_str,
                            "hypothesis": hypothesis,
                            "conclusion": f"Attempt failed during {failure_stage}: {failure_reason}",
                            "discovery": (
                                f"{failure_type} in {failure_stage}; proposed_config="
                                f"{record_params}"
                            ),
                            "memory_update": (
                                "Do not repeat the failing configuration unchanged. "
                                f"Correct the {failure_stage} failure before retrying."
                            ),
                            "round_index": round_index,
                            "attempt_in_round": attempt_in_round,
                        },
                    }
                    _apply_watchdog_failure_fields(failure_record, e)
                    try:
                        # The RAW dict is saved (validation is the gate, not
                        # the serializer): model_dump() drops extra keys, which
                        # would silently lose the §4 watchdog provenance.
                        _emit_record(sandbox, failure_record)
                        print(f"  Saved structured attempt failure: {exp_id}")
                    except Exception as persist_error:
                        print(f"  [ERROR] Could not persist attempt failure: {persist_error}")
                    time.sleep(5)

            # DataScope DS5 — a scope violation is deterministic on retry:
            # terminate the run immediately, before any retry/fail-round
            # bookkeeping.
            _round_decision = _decide_round_outcome(
                scope_violation_reason=_scope_violation_reason,
                evidence_channel_failure=_evidence_channel_failure,
                resolved_action=resolved_action,
                is_formal_round=is_formal_round,
            )
            if _scope_violation_reason or _evidence_channel_failure:
                print(
                    _non_retryable_termination_message(
                        scope_violation_reason=_scope_violation_reason,
                        evidence_channel_failure=_evidence_channel_failure,
                    )
                )
                break

            # Phase L — inner attempt loop ended without a successful
            # break. Bump the consecutive-failure counter so the outer
            # while can decide whether to abort the iteration.
            if not round_succeeded:
                consecutive_fails += 1
                print(
                    f"Round {round_index} exhausted all {N} attempt(s) "
                    f"without a successful experiment "
                    f"(consecutive_fail_rounds={consecutive_fails}/"
                    f"{max_fail_rounds_setting})."
                )

            # Post-round gate-action loop control (commit-5b).
            # SKIP_ITER: break the while loop entirely; chain-level caller
            #   of tuner.run() moves to the next chain iteration.
            # SKIP_TO_FORMAL: jump completed_rounds so the next while
            #   iteration lands on the formal round. Guarded when already
            #   on the formal round — no re-run.
            # See docs/design/pluggable_health_checks.md §4 for action
            # semantics and §8 for severity resolution.
            if _round_decision is RoundDecision.BREAK_ITERATION:
                print(f"  [HEALTH GATE] SKIP_ITER at round {round_index} — aborting iteration.")
                _gate_aborted = True
                break
            if _round_decision is RoundDecision.SKIP_TO_FORMAL:
                print(
                    f"  [HEALTH GATE] SKIP_TO_FORMAL at round {round_index} — "
                    f"jumping to formal round {max_rounds}."
                )
                completed_rounds = max_rounds - 1

            # Phase 6.8 §2 Layer C (Commit 4) — per-round cleanup. Drop
            # local refs to the largest per-round transients before the
            # next round's plan() call so inter-round RSS stays flat.
            # NameError-guarded because early-exit paths (gate skip,
            # training crash before score) leave some names unbound.
            # See docs/phase68_task1_memory_diagnostic_20260427.md §2 Commit 4.
            with suppress(NameError):
                del train_results
            with suppress(NameError):
                del score_results
            with suppress(NameError):
                del score_table
            with suppress(NameError):
                del file_vector
            with suppress(NameError):
                del final_scalar
            with suppress(NameError):
                del reflect_results
            with suppress(NameError):
                del memory_history
            gc.collect()

        # --- Build, validate, and save the run output ---
        finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        # Phase L (§11) — termination_reason captures *why* the outer
        # loop exited. Precedence: gate-driven abort (SKIP_ITER) wins
        # over the fail-round brake wins over the max_rounds completion
        # check. See _compute_termination_state.
        run_status, termination_reason = _compute_termination_state(
            completed_rounds=completed_rounds,
            max_rounds=max_rounds,
            consecutive_fails=consecutive_fails,
            max_fail_rounds=max_fail_rounds_setting,
            gate_aborted=_gate_aborted,
            scope_violation_reason=_scope_violation_reason,
            evidence_channel_failure=_evidence_channel_failure,
        )
        all_records = sandbox.get_summary()
        successful_records = [
            r
            for r in all_records
            if r.get("status") == "success"
            and isinstance(r.get("denoising_score"), int | float)
            and math.isfinite(r["denoising_score"])
        ]
        top_record = (
            max(successful_records, key=lambda r: r["denoising_score"])
            if successful_records
            else None
        )

        # Dual-track best-record selection for score_table propagation:
        #   best_*  — highest denoising_score across all successful records
        #             (may be a trial-mode record on subset indices).
        #   formal_* — highest denoising_score among formal-mode records only
        #             (full 20-file subset). Formal records have no "is_trial"
        #             key (it's set to True only when trial_config.is_trial);
        #             absence == formal. Surfaces the "canonical" table to
        #             downstream nodes without the trial-mode subset caveat.
        formal_records = [r for r in successful_records if not r.get("is_trial", False)]
        formal_top_record = (
            max(formal_records, key=lambda r: r["denoising_score"]) if formal_records else None
        )
        valid_records = [r for r in successful_records if is_valid_candidate(r)]
        valid_top_record = (
            max(valid_records, key=lambda r: r["denoising_score"]) if valid_records else None
        )
        valid_formal_records = [r for r in valid_records if not r.get("is_trial", False)]
        valid_formal_top_record = (
            max(valid_formal_records, key=lambda r: r["denoising_score"])
            if valid_formal_records
            else None
        )
        # V19 PR 1 (P1-C4) — persisted trial-best bookkeeping. NOTE: this
        # is the BOOKKEEPING notion (HealthGate-valid trial records only);
        # it is deliberately NOT identical to ``_best_trial_winner``'s gate
        # predicate, which additionally requires ``memory.time_mode ==
        # "trial"`` (design doc §3.5). Read-only: nothing consumes these
        # fields in V19.
        valid_trial_records = [r for r in valid_records if r.get("is_trial", False)]
        valid_trial_top_record = (
            max(valid_trial_records, key=lambda r: r["denoising_score"])
            if valid_trial_records
            else None
        )

        # Phase K.7 — gate-exhaustion feedback for the next iteration's
        # proposer (§10.13). active_mode comes from the most recent plan;
        # the helper returns None unless the trigger criterion fires.
        gate_active_mode = "trial" if (plan is not None and plan.is_trial) else "formal"
        gate_vram_budget = trial_vram_budget if gate_active_mode == "trial" else formal_vram_budget
        gate_time_budget = trial_time_budget if gate_active_mode == "trial" else formal_time_budget
        gate_exhaustion = _build_gate_exhaustion(
            records=all_records,
            active_mode=gate_active_mode,
            vram_budget_gb=gate_vram_budget,
            time_budget_minutes=gate_time_budget,
            consecutive_fail_rounds_at_exit=consecutive_fails,
            max_fail_rounds=max_fail_rounds_setting,
            completed_rounds=completed_rounds,
        )
        # V20 PR D (D-C6): the OTHER failure mode — trials ran, succeeded,
        # and then failed their scientific gates. Distinct carrier because
        # gate_exhaustion's triggers require budget-gated records and would
        # stay None here. `_skipped_formal_for_no_valid_winner` is set at
        # the skip gate itself, so the report states WHY formal did not run
        # rather than inferring it from the absence of a formal record.
        trial_validity_feedback = _build_trial_validity_feedback(
            all_records,
            formal_skipped_for_no_valid_winner=_skipped_formal_for_no_valid_winner,
            healthgate_mode=agent_input.healthgate_mode,
        )
        if trial_validity_feedback is not None:
            print(
                f"[trial-validity] no HealthGate-valid trial winner: "
                f"{trial_validity_feedback.invalid_count} gate-invalid, "
                f"{trial_validity_feedback.unknown_validity_count} validity-unknown, "
                f"{trial_validity_feedback.execution_failure_count} execution failures "
                f"of {trial_validity_feedback.trial_records_considered} trial(s). "
                f"Surfacing to next proposer.",
                flush=True,
            )

        if gate_exhaustion is not None:
            print(
                f"[gate-exhaustion] iteration ended without ever training; "
                f"{gate_exhaustion.vram_gated_attempts} VRAM-gated, "
                f"{gate_exhaustion.time_gated_attempts} time-gated, "
                f"{gate_exhaustion.other_failure_attempts} other failures. "
                f"Surfacing to next proposer."
            )

        agent_output_dict = {
            "run_name": run_name,
            "model_type": model_type_setting,
            "file_index": file_index,
            "health_checks_config": agent_input.health_checks_config,
            # DataScope + HealthGate subsystem stamps (DS5).
            "resolved_data_scope": resolved_data_scope,
            "health_gate_enabled": agent_input.health_gate_enabled,
            # V20 PR D (D-C1a): declared enforcement/authority axes,
            # echoed from the input so provenance and output cannot
            # disagree with what the run was launched under.
            "healthgate_mode": agent_input.healthgate_mode,
            "result_authority": agent_input.result_authority,
            "health_checks_config_source": health_checks_config_source,
            "health_config_sha256": health_config_sha256,
            "formal_reference_score": _json_safe_reference(formal_reference_score),
            "formal_comparison_reference_source": formal_reference_source,
            "resolved_skip_formal_threshold": _json_safe_reference(resolved_skip_formal_threshold),
            "resolved_bypass_formal_threshold": _json_safe_reference(
                resolved_bypass_formal_threshold
            ),
            "status": run_status,
            "completed_rounds": completed_rounds,
            "total_attempts": total_attempts,
            "best_exp_id": top_record.get("exp_id") if top_record else None,
            "best_denoising_score": top_record.get("denoising_score") if top_record else None,
            "best_formal_denoising_score": formal_top_record.get("denoising_score")
            if formal_top_record
            else None,
            "best_valid_exp_id": valid_top_record.get("exp_id") if valid_top_record else None,
            "best_valid_denoising_score": valid_top_record.get("denoising_score")
            if valid_top_record
            else None,
            "best_valid_formal_exp_id": valid_formal_top_record.get("exp_id")
            if valid_formal_top_record
            else None,
            "best_valid_formal_denoising_score": valid_formal_top_record.get("denoising_score")
            if valid_formal_top_record
            else None,
            "best_valid_trial_exp_id": valid_trial_top_record.get("exp_id")
            if valid_trial_top_record
            else None,
            "best_valid_trial_denoising_score": valid_trial_top_record.get("denoising_score")
            if valid_trial_top_record
            else None,
            "best_valid_config": valid_top_record.get("params") if valid_top_record else None,
            "best_valid_file_vector": valid_top_record.get("file_vector")
            if valid_top_record
            else None,
            "best_valid_score_table": valid_top_record.get("score_table")
            if valid_top_record
            else None,
            "best_valid_formal_score_table": valid_formal_top_record.get("score_table")
            if valid_formal_top_record
            else None,
            "best_config": top_record.get("params") if top_record else None,
            "best_file_vector": top_record.get("file_vector") if top_record else None,
            "best_score_table": top_record.get("score_table") if top_record else None,
            "formal_score_table": formal_top_record.get("score_table")
            if formal_top_record
            else None,
            "all_records": all_records,
            "started_at": started_at,
            "finished_at": finished_at,
            "gate_exhaustion": gate_exhaustion,
            "trial_validity_feedback": trial_validity_feedback,
            # Phase 6.6 WS-B B.3 — flush per-attempt VRAM-gate rejections.
            # Empty list when every attempt was feasible. Orchestrator
            # aggregates (worst-offender per architecture) before rendering
            # into the next Proposer's previous_failures.
            "physical_rejections": physical_rejections_buffer,
            # Phase L (§11) — echo budget settings + termination metadata.
            "attempts_per_round": attempts_per_round_setting,
            "attempts_per_formal_round": attempts_per_formal_round_setting,
            "max_fail_rounds": max_fail_rounds_setting,
            "consecutive_fail_rounds_at_exit": consecutive_fails,
            "termination_reason": termination_reason,
        }

        output_path = os.path.join(workspace, f"run_output_{run_name}.json")
        # V8 hardening Domain 2c — wrap final output validation + write so
        # a partial file lands on disk even if Pydantic validation or JSON
        # serialization raises. Without this, a malformed all_records entry
        # left no run_output_*.json at all, and core.resume.restore_prior_state
        # halted the entire chain on "run_output file missing". The fallback
        # writes a minimal status="failed" record carrying just the chain-
        # restoration essentials so the next iter can keep going.
        # See docs/V8_Gap_Report.md Domain 2c.
        try:
            agent_output = HyperparamTuningOutput.model_validate(agent_output_dict)
            # Coerce float('-inf') no-signal sentinels to JSON null at the
            # storage boundary — model_dump_json would otherwise emit
            # non-standard ``-Infinity`` tokens that break the dashboard's
            # ``JSON.parse``.
            safe_output = coerce_nonfinite_to_none(agent_output.model_dump())
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(safe_output, f, indent=4)
            print(f"Output validated and saved -> {output_path}")
        except Exception as e:
            print(
                f"  [DEGRADED] HyperparamTuningOutput serialization failed: "
                f"{type(e).__name__}: {e}. Writing best-effort partial output."
            )
            partial_dict = {
                "run_name": run_name,
                "model_type": model_type_setting,
                "file_index": file_index,
                "status": "failed",
                # V20 PR D — the DECLARATION is a launch fact, validated at
                # the D-C1b boundary before any work began. It does not stop
                # existing because the tuner later failed, so every
                # post-launch branch carries it. Sourced from the validated
                # input, never echoed back from a healthy output that may
                # not exist. (Gate 2 attempt 1 found this: a real run
                # launched with --healthgate_mode blocking wrote
                # healthgate_mode: null because it failed.)
                "healthgate_mode": agent_input.healthgate_mode,
                "result_authority": agent_input.result_authority,
                "completed_rounds": completed_rounds,
                "total_attempts": total_attempts,
                "formal_reference_score": _json_safe_reference(formal_reference_score),
                "formal_comparison_reference_source": formal_reference_source,
                "resolved_skip_formal_threshold": _json_safe_reference(
                    resolved_skip_formal_threshold
                ),
                "resolved_bypass_formal_threshold": _json_safe_reference(
                    resolved_bypass_formal_threshold
                ),
                "started_at": started_at,
                "finished_at": finished_at,
                "termination_reason": termination_reason,
                "_partial_reason": f"{type(e).__name__}: {e}",
            }
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(partial_dict, f, indent=4, default=str)
            print(f"  [DEGRADED] Partial output written -> {output_path}")
            # Also build a minimal-but-valid in-memory output so callers
            # downstream (run_one_iteration manifest writer) don't crash on
            # a None reference. This second validate is on a strictly
            # smaller payload — re-raising here means a true bug.
            agent_output = HyperparamTuningOutput.model_validate(partial_dict)

        if termination_reason == "completed":
            print(f"\nCompleted {completed_rounds} research rounds. Loop terminated.")
        elif termination_reason == "aborted_fail_rounds":
            print(
                f"\nAborted after {consecutive_fails} consecutive fail-rounds "
                f"(max_fail_rounds={max_fail_rounds_setting}); "
                f"{completed_rounds}/{max_rounds} rounds completed across "
                f"{total_attempts} total attempts."
            )
        else:
            print(
                f"\nLoop ended with status={run_status}; "
                f"{completed_rounds}/{max_rounds} rounds completed across "
                f"{total_attempts} total attempts."
            )

        return agent_output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


PARTIAL_CAMPAIGN_EXIT_CODE = 2


def main() -> int:
    """Thin CLI wrapper — parses args, builds HyperparamTuningInput, calls run()."""
    # Import MODEL_REGISTRY here (not at module level) because it depends on
    # ml_models/ being on PYTHONPATH, which is only guaranteed in CLI/pytest contexts.
    from ml_models.models_sandbox import MODEL_REGISTRY

    parser = argparse.ArgumentParser(description="TIDMAD Autonomous Agent Kernel")

    parser.add_argument(
        "--provider",
        type=str,
        choices=["gemini", "openai"],
        default="gemini",
        help="LLM provider for the planner sub-call (default for reflector when not overridden).",
    )
    parser.add_argument(
        "--model_id",
        type=str,
        default="gemini-3.1-flash-lite-preview",
        help="Model ID for the planner sub-call (default for reflector when not overridden).",
    )
    parser.add_argument(
        "--reflect_provider",
        type=str,
        choices=["gemini", "openai"],
        default=None,
        help="Optional separate provider for the reflector sub-call. "
        "When None, the reflector uses --provider.",
    )
    parser.add_argument(
        "--reflect_model_id",
        type=str,
        default=None,
        help="Optional separate model for the reflector sub-call (e.g., gemini-2.5-flash). "
        "When None, the reflector uses --model_id.",
    )
    parser.add_argument(
        "--expert_advice",
        type=str,
        default="None",
        help="Initial advice from a human expert to guide exploration.",
    )
    parser.add_argument(
        "--max_rounds",
        type=int,
        default=10,
        help="Maximum number of experiment rounds to prevent token drain.",
    )

    # ``--force_model`` accepts any string (not just MODEL_REGISTRY keys),
    # because plugin models seeded via ``--seed_plugin_path`` are not in the
    # registry at CLI parse time — the seed plugin only gets registered
    # after the tuner copies it into the run-scoped plugin dir
    # (docs/run_scoped_plugins.md, Phase 3/4). The schema validator and the
    # planner reject unknown model_types at runtime with a clearer error.
    builtin_choices = [*MODEL_REGISTRY.keys(), "auto"]
    parser.add_argument(
        "--force_model",
        type=str,
        default="auto",
        help=(
            "Force a specific architecture or let the agent decide "
            "('auto'). Built-in choices: "
            f"{', '.join(builtin_choices)}. Plugin model_types are "
            "also accepted when paired with --seed_plugin_path."
        ),
    )
    parser.add_argument(
        "--seed_plugin_path",
        type=str,
        default=None,
        help=(
            "Path to a plugin .py file used as the seed model "
            "for this run. Required when --force_model is a "
            "plugin model_type (i.e. not a built-in). The file's "
            "PLUGIN_MODEL_TYPE must equal --force_model. The "
            "tuner copies the file into "
            "<workspace>/plugins/<run_name>/ at run start so "
            "the training subprocess sees it via "
            "SIDERIUS_PLUGIN_DIRS. See "
            "docs/run_scoped_plugins.md (Phase 3)."
        ),
    )

    parser.add_argument(
        "--run_name", type=str, default="test_run", help="Run name for the auto-exploration."
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default="./siderius_workspace",
        help="Root directory for all agent-generated outputs.",
    )
    parser.add_argument(
        "--progress_bar",
        action="store_true",
        help="Stream live tqdm progress bars from training/inference subprocesses.",
    )
    parser.add_argument(
        "--file_index",
        type=int,
        default=6,
        help="Validation/training file index (default: 6). Ignored when --is_trial.",
    )

    # Trial mode arguments
    parser.add_argument(
        "--is_trial",
        action="store_true",
        help="Enable trial-explore mode with multi-file sparse sampling.",
    )
    parser.add_argument(
        "--trial_strategy",
        type=str,
        default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="DEPRECATED no-op (DS7) — warns and is ignored. Use --data_scope.",
    )
    parser.add_argument(
        "--trial_portion",
        type=float,
        default=0.1,
        help="Fraction of segments per file for training scope (default: 0.1).",
    )
    parser.add_argument(
        "--eval_strategy",
        type=str,
        default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="DEPRECATED no-op (DS7) — warns and is ignored. Use --data_scope.",
    )
    parser.add_argument(
        "--eval_portion",
        type=float,
        default=0.1,
        help="Fraction of segments per file for validation (default: 0.1).",
    )
    parser.add_argument(
        "--train_portion",
        type=float,
        default=0.1,
        help="Per-epoch subsample from training scope (default: 0.1).",
    )

    # Formal-mode training levers (Phase M). Eval scope defaults to full
    # snapshot (formal_eval_portion=1.0) for production score comparability,
    # but is now operator-configurable for smoke / CI runs that need to fit
    # a tight budget — Phase R, docs/resource_estimator_implement.md §13.
    parser.add_argument(
        "--formal_strategy",
        type=str,
        default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="Training-side sampling strategy in formal mode (default: snapshot).",
    )

    # V19 PR 2 — data-ordering OVERRIDE. Ordering is agent-proposable; these
    # flags let an operator force one value for the whole chain (e.g. for a
    # controlled comparison). Unset = the agent's proposal decides, falling
    # back to 'shuffle'. The override is pinned in the run-invariants lock.
    parser.add_argument(
        "--order_strategy_override",
        type=str,
        default=None,
        choices=["shuffle", "sequential"],
        help="Force the training sample visitation order for every round, "
        "overriding any agent proposal. Unset (default) = the agent decides, "
        "falling back to 'shuffle' (the pre-V19 behavior).",
    )
    parser.add_argument(
        "--file_order_override",
        type=str,
        default=None,
        help="Comma-separated file visitation ORDER for "
        "--order_strategy_override sequential, e.g. '4,6,5,9,7,8'. Order is "
        "preserved as written and must be a full permutation of the resolved "
        "DataScope. Range syntax is rejected — a range cannot express an "
        "order. Omit for ascending file index.",
    )
    parser.add_argument(
        "--formal_portion",
        type=float,
        default=0.1,
        help="Fraction of segments per file for formal training scope (default: 0.1).",
    )
    parser.add_argument(
        "--formal_train_portion",
        type=float,
        default=1.0,
        help="Per-epoch iteration fraction for formal training (default: 1.0).",
    )
    parser.add_argument(
        "--formal_eval_portion",
        type=float,
        default=1.0,
        help="Fraction of segments per file for the formal-mode eval "
        "scope (snapshot strategy). Default 1.0 = legacy full-clone "
        "behaviour. Lower (e.g. 0.05) for smoke / CI runs that need "
        "to fit the formal_time_budget_minutes gate.",
    )

    parser.add_argument(
        "--human_advice",
        type=str,
        default=None,
        help="Human guidance for the agent (injected alongside expert_advice).",
    )
    parser.add_argument(
        "--cleanup_denoised",
        action="store_true",
        help="Delete denoised HDF5 files after scoring each round to save disk space.",
    )

    # evaluate_time_skill gate (Phase E1, Phase I two-budget split). Each
    # default is None, which keeps that mode's gate off — matches the
    # chain-runner CLI defaults.
    parser.add_argument(
        "--trial_time_budget_minutes",
        type=float,
        default=None,
        help="Wall-time budget (minutes) for the evaluate_time_skill "
        "gate on rounds where plan.is_trial=True. None disables "
        "the trial gate.",
    )
    parser.add_argument(
        "--formal_time_budget_minutes",
        type=float,
        default=None,
        help="Wall-time budget (minutes) for the evaluate_time_skill "
        "gate on rounds where plan.is_trial=False. None disables "
        "the formal gate. Sized independently from the trial "
        "budget because formal runs use the full dataset and "
        "are 50-100x longer.",
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        default=None,
        help="TIDMAD data directory used by evaluate_time_skill's real-dataset "
        "warmup. None makes the skill fall back to its static formula.",
    )
    parser.add_argument(
        "--health_checks_config",
        type=str,
        default=None,
        help="Optional HealthGate YAML override; omitted uses configs/health_checks.yaml.",
    )
    # --- DataScope + HealthGate subsystem (DS5c) ---
    parser.add_argument(
        "--data_scope",
        type=str,
        default=None,
        help=(
            "Restrict the run to a file subset: '4-9', '4,5,6,7,8,9', or "
            "mixed '0-3,7'. Omitted = complete dataset. Under a partial "
            "scope only 'snapshot' sampling is legal and "
            "--health_gate_files is required when gates are enabled. "
            "See docs/design/enable_partial_file_list.md."
        ),
    )
    parser.add_argument(
        "--health_gate_enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "HealthGate subsystem switch (default: enabled). "
            "--no-health_gate_enabled disables gate evaluation entirely; "
            "successful finite-score records then count as valid candidates."
        ),
    )
    parser.add_argument(
        "--health_gate_files",
        type=str,
        default=None,
        help=(
            "Run-level shared monitored-file list for ALL HealthGate checks "
            "(same spec format as --data_scope). Omitted + full scope = "
            "YAML defaults; omitted + partial scope = startup error."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from validated completed rounds already in this workspace.",
    )

    # evaluate_vram_skill gate (Phase K two-budget split). Each default is
    # None which keeps that mode's budget disabled — skill falls back to the
    # defensive free×0.8 limit. Matches the chain-runner CLI defaults.
    parser.add_argument(
        "--trial_vram_budget_gb",
        type=float,
        default=None,
        help="Per-mode VRAM ceiling (GB) for the evaluate_vram_skill "
        "gate on rounds where plan.is_trial=True. None → "
        "skill uses free×0.8 defensive limit.",
    )
    parser.add_argument(
        "--formal_vram_budget_gb",
        type=float,
        default=None,
        help="Per-mode VRAM ceiling (GB) for the evaluate_vram_skill "
        "gate on rounds where plan.is_trial=False. None → "
        "skill uses free×0.8 defensive limit. Sized "
        "independently from the trial budget because formal "
        "rounds often use larger batch_size / segmentation_size.",
    )

    # Per-round attempt budget (Phase L, §11). All three default to the
    # schema defaults so the CLI surface matches the schema-only path.
    parser.add_argument(
        "--attempts_per_round",
        type=int,
        default=3,
        help="Inner attempt budget for trial rounds (default 3). "
        "Each round runs up to N attempts; success → break + "
        "reset the consecutive-fail counter, exhaustion → "
        "bump it. See docs/resource_estimator_implement.md §11.",
    )
    parser.add_argument(
        "--attempts_per_formal_round",
        type=int,
        default=5,
        help="Inner attempt budget for the formal-promotion round "
        "(default 5, intentionally higher than --attempts_per_round). "
        "Formal is the only cross-architecture comparable "
        "measurement, so an iteration with no formal score is "
        "wasted entirely — extra attempts are worth the cost.",
    )
    parser.add_argument(
        "--max_fail_rounds",
        type=int,
        default=3,
        help="Consecutive-failure brake (default 3). The outer "
        "loop aborts with termination_reason='aborted_fail_rounds' "
        "after this many consecutive rounds exhaust their inner "
        "attempt budget.",
    )
    parser.add_argument(
        "--max_epochs",
        type=int,
        default=None,
        help=(
            "Hard cap on epochs per round. When set, the tuner clamps the "
            "LLM's planned epochs to min(planned_epochs, max_epochs). "
            "Wires into HyperparamTuningInput.max_epochs (already enforced "
            "in the round loop). Default None = no clamp (LLM plan unchanged)."
        ),
    )
    # --- RT6: runtime-control operator surface (design §4/§5) ---
    # The CLI carries the §5 PROVISIONAL operational defaults (150k / 4);
    # the schema defaults stay None so programmatic callers keep pre-RT5
    # behavior. Pass 0 to disable a numeric guardrail.
    parser.add_argument(
        "--max_steps_per_attempt",
        type=int,
        default=150_000,
        help="§5 guardrail: skip plans whose resolved optimizer-step count "
        "exceeds this (planner-visible record). 0 disables. Default 150000 "
        "(provisional §5 value).",
    )
    parser.add_argument(
        "--min_formal_batch_size",
        type=int,
        default=4,
        help="§5 guardrail: skip FORMAL rounds planned below this batch size "
        "(the V18 launch-overhead pathology; trial rounds exempt). 0 "
        "disables. Default 4 (provisional §5 value).",
    )
    parser.add_argument(
        "--allow_extreme_steps",
        action="store_true",
        help="§5 operator override: bypass both step/batch guardrails "
        "(recorded in run provenance).",
    )
    parser.add_argument(
        "--runtime_watchdog",
        action="store_true",
        help="§4 runtime watchdog: run training/inference subprocesses in "
        "their own process group under the deadline max(floor, "
        "min(budget, verified_estimate x safety)). Default off.",
    )
    parser.add_argument(
        "--runtime_safety_factor",
        type=float,
        default=1.0,
        help="§2.10 safety multiplier for admission and the watchdog "
        "deadline. Default 1.0 (schema-mirroring); V18 production "
        "posture is 1.5, passed explicitly by the launch config.",
    )
    parser.add_argument(
        "--runtime_trial_safety_factor",
        type=float,
        default=None,
        help="§2.10 phase-specific factor for TRIAL attempts; wins over "
        "--runtime_safety_factor when set. V18 posture 2.0 (Wave-1A "
        "diagnostic: systematic 1.54-1.61x post-verification drift).",
    )
    parser.add_argument(
        "--runtime_formal_safety_factor",
        type=float,
        default=None,
        help="§2.10 phase-specific factor for FORMAL attempts; wins over "
        "--runtime_safety_factor when set. Default None keeps formals "
        "on the base factor.",
    )
    parser.add_argument(
        "--runtime_watchdog_floor_seconds",
        type=float,
        default=60.0,
        help="§4 watchdog deadline floor. Default 60.0 "
        "(schema-mirroring); V18 production posture is 120.0.",
    )
    parser.add_argument(
        "--enable_chain_incumbent_formal_gates",
        action="store_true",
        help="V19 PR 1: consumption-only switch. When set, the two "
        "formal delta gates use chain_incumbent + fixed_delta as their "
        "thresholds. Default OFF: incumbent is still reconstructed and "
        "recorded; the gates simply do not consume it. OFF is NOT a "
        "fixed-0.0 mode. Full semantics: nodes/ml_hyperparameter_tune_agent/"
        "ml_hyperparameter_tune_agent.md under 'Chain formal-incumbent "
        "reference'.",
    )

    parser.add_argument(
        "--healthgate_mode",
        choices=["blocking", "observe_only"],
        default=None,
        help="V20 PR D: whether HealthGate verdicts ENFORCE (blocking) or "
        "only record (observe_only). Declared, never inferred from the "
        "config file. No default: a formal campaign that omits it is "
        "refused at launch, because defaulting would silently claim "
        "authority the run may not have.",
    )
    parser.add_argument(
        "--result_authority",
        choices=["scientific", "diagnostic"],
        default=None,
        help="V20 PR D: whether this run's results may inform science "
        "(scientific) or are for diagnosis only (diagnostic). A SEPARATE "
        "axis from --healthgate_mode: observe_only+scientific is a "
        "contradiction and is refused, while blocking+diagnostic is "
        "coherent — enforced, and deliberately not promoted.",
    )

    args = parser.parse_args()

    # Preflight: catch the "plugin model_type without seed file" mistake
    # before any sandbox setup. The schema validator would catch this later
    # (planner crashes on get_config_class), but flagging it here gives the
    # operator an actionable message instead of a stack trace mid-run.
    if (
        args.force_model != "auto"
        and args.force_model not in MODEL_REGISTRY
        and args.seed_plugin_path is None
    ):
        parser.error(
            f"--force_model={args.force_model!r} is not a built-in model "
            f"({', '.join(builtin_choices)}). If this is a plugin model, "
            f"pass --seed_plugin_path /path/to/{args.force_model}.py so the "
            f"tuner can stage it into the run-scoped plugin dir."
        )

    input_dict = {
        "model_type": args.force_model,
        "seed_plugin_path": args.seed_plugin_path,
        "file_index": args.file_index,
        "max_rounds": args.max_rounds,
        "health_checks_config": args.health_checks_config,
        # DS5c — DataScope + HealthGate subsystem. from_cli parses "4-9" /
        # "4,5,6,7,8,9" / mixed; schema + validate_runtime_config do the rest.
        "data_scope": DataScope.from_cli(args.data_scope)
        if args.data_scope
        else DataScope.default(),
        "health_gate_enabled": args.health_gate_enabled,
        # V20 PR D (D-C1a): declared, never inferred. No default here —
        # the launcher refuses omission in D-C1b.
        "healthgate_mode": args.healthgate_mode,
        "result_authority": args.result_authority,
        "health_gate_files": DataScope.from_cli(args.health_gate_files).file_indices
        if args.health_gate_files
        else None,
        "resume": args.resume,
        "expert_advice": args.expert_advice,
        "llm_provider": args.provider,
        "llm_model_id": args.model_id,
        "reflect_provider": args.reflect_provider,
        "reflect_model_id": args.reflect_model_id,
        "storage": {
            "backend": "local",
            "local": {"workspace": args.workspace, "run_name": args.run_name},
        },
        "progress_bar": args.progress_bar,
        "cleanup_denoised": args.cleanup_denoised,
        "is_trial": args.is_trial,
        # V19 PR 1 — consumption-only coupling switch (default OFF).
        "enable_chain_incumbent_formal_gates": args.enable_chain_incumbent_formal_gates,
    }
    # DS7 — deprecated no-op strategy flags (removal tracked as FU-2).
    if args.trial_strategy != "snapshot" or args.eval_strategy != "snapshot":
        warnings.warn(
            "--trial_strategy / --eval_strategy are deprecated and IGNORED "
            "(DS7): the input fields they fed were dead at both ends and "
            "have been removed. Use --data_scope to restrict data.",
            DeprecationWarning,
            stacklevel=2,
        )
    if args.is_trial:
        input_dict.update(
            {
                "trial_portion": args.trial_portion,
                "eval_portion": args.eval_portion,
                "train_portion": args.train_portion,
            }
        )
        # Clamp trial/eval scope to the operator's CLI values. The planner
        # remains free to choose train_portion, which controls the per-epoch
        # subsample within that fixed training scope.
        input_dict["plan_overrides"] = {
            "is_trial": True,
            "trial_portion": args.trial_portion,
            "eval_portion": args.eval_portion,
        }
    # Phase M — formal-mode training levers. Always forwarded (trial or not)
    # because they apply whenever a round is promoted to formal.
    input_dict["formal_strategy"] = args.formal_strategy
    input_dict["formal_portion"] = args.formal_portion
    input_dict["formal_train_portion"] = args.formal_train_portion
    input_dict["formal_eval_portion"] = args.formal_eval_portion
    # V19 PR 2 — ordering OVERRIDE (operator control). Forwarded only when
    # set, so an unset override leaves the agent's proposal (or the default)
    # in charge and produces exactly the pre-PR2 configuration.
    if args.order_strategy_override is not None:
        input_dict["order_strategy_override"] = args.order_strategy_override
    if args.file_order_override is not None:
        # NOT DataScope.from_cli — that sorts and dedupes, which would
        # silently rewrite the operator's permutation into ascending order.
        input_dict["file_order_override"] = parse_file_order_cli(args.file_order_override)

    if args.human_advice:
        input_dict["human_advice"] = args.human_advice
    if args.trial_time_budget_minutes is not None:
        input_dict["trial_time_budget_minutes"] = args.trial_time_budget_minutes
    if args.formal_time_budget_minutes is not None:
        input_dict["formal_time_budget_minutes"] = args.formal_time_budget_minutes
    if args.max_epochs is not None:
        input_dict["max_epochs"] = args.max_epochs
    if args.data_dir is not None:
        input_dict["data_dir"] = args.data_dir
    if args.trial_vram_budget_gb is not None:
        input_dict["trial_vram_budget_gb"] = args.trial_vram_budget_gb
    if args.formal_vram_budget_gb is not None:
        input_dict["formal_vram_budget_gb"] = args.formal_vram_budget_gb

    # Phase L (§11) — per-round attempt budget. Always forwarded so a CLI
    # invocation matches the workflow path. Schema validators enforce ge=1.
    input_dict["attempts_per_round"] = args.attempts_per_round
    input_dict["attempts_per_formal_round"] = args.attempts_per_formal_round
    input_dict["max_fail_rounds"] = args.max_fail_rounds

    # RT6 — runtime-control operator surface. 0 → None (guardrail disabled).
    input_dict["max_steps_per_attempt"] = args.max_steps_per_attempt or None
    input_dict["min_formal_batch_size"] = args.min_formal_batch_size or None
    input_dict["allow_extreme_steps"] = args.allow_extreme_steps
    input_dict["runtime_watchdog_enabled"] = args.runtime_watchdog
    input_dict["runtime_safety_factor"] = args.runtime_safety_factor
    input_dict["runtime_trial_safety_factor"] = args.runtime_trial_safety_factor
    input_dict["runtime_formal_safety_factor"] = args.runtime_formal_safety_factor
    input_dict["runtime_watchdog_floor_seconds"] = args.runtime_watchdog_floor_seconds

    agent_input = HyperparamTuningInput.model_validate(input_dict)

    agent = HyperparamTuningAgent()
    output = agent.run(agent_input)
    if output.status != "completed" or output.completed_rounds != args.max_rounds:
        return PARTIAL_CAMPAIGN_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
