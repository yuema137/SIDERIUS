"""Tuner RECORDS — construction, classification and the one persist seam.

Step 07 PR 07b, C7 (operator scope amendment): moved VERBATIM out of
``ml_hyperparameter_tune_agent.py``. Zero behaviour change; the REC goldens and
the differential oracle are the evidence.

What belongs here: every ``ExperimentRecord`` a round can produce — success,
skip, resource-admission refusal, execution failure, scoring refusal — plus the
status vocabulary they share, the failure classification that chooses between
them, and the single ``_emit_record`` validate/persist seam.

One seam, deliberately: a second record builder that "just differs slightly at
this call site" is how status vocabularies drift apart, and the resume path
reads exactly what this module wrote.
"""

import json
import os
import time
from typing import Any

from agent.schemas.hyperparam_tuning import (
    ExperimentRecord,
    HyperparamTuningOutput,
)
from agent.skills.evaluate_time_skill.wrapper import _aggregate_inference_file_timings
from core.run_invariants import (
    RunInvariants,
    ensure_run_invariants,
    validate_stamped_invariants,
)
from core.runtime_control.failure_attribution import may_recommend_resource_reduction
from core.scientific_authority import ScientificAuthority
from execute_tools.dataset_config import (
    DatasetConfig,
)
from execute_tools.deliverable_spec import (
    DeliverableNaming,
    default_deliverable_naming,
)
from execute_tools.evaluation_metric import (
    NotScoreableError,
)
from execute_tools.health_checks.candidate_eligibility import formal_validity_of
from execute_tools.scoring_utils import coerce_nonfinite_to_none
from execute_tools.training_history import (
    TrainingResults,
    TrainingResultsContractError,
    interpret_training_results,
)

# --- node-local, one-way (Step 07 PR 07b, C7d) -------------------------------
# `finalize_run_output` below assembles the run's output, so it consumes the
# policy that selects the best records and the feedback the next agent reads.
# records -> policy, feedback (both leaves); runtime -> records. Still acyclic,
# and enforced by tests/unit/nodes/test_node_public_boundary.py.
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AdmissionOutcome,
    AttemptExecution,
    AttemptIdentity,
    PreparedAttempt,
    RunBindings,
    RunExitSnapshot,
    TrainingOutcome,
)
from nodes.ml_hyperparameter_tune_agent.feedback import (
    _build_gate_exhaustion,
    _build_trial_validity_feedback,
)
from nodes.ml_hyperparameter_tune_agent.policy import (
    _compute_termination_state,
    _json_safe_reference,
    _select_best_records,
)


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


def _interpret_training_status(
    train_status: dict, *, expected_validation: bool
) -> tuple[dict, TrainingResults]:
    """Step 07a — the tuner's typed training-results boundary (design §3.4a, §3.5).

    Applies :func:`interpret_training_results` — the ONE validation site of the
    trainer→tuner contract — to a SUCCESSFUL training status, where the
    expectation is known: ``expected_validation`` is ``eval_sample_set is not
    None`` for the attempt. A contract violation (schema-invalid
    ``training_history``, R2 ≠ ``loss_history``, ``final_loss`` ≠ last R2, or
    an EXPECTED R3 that did not arrive) is converted into the EXISTING
    training-failure status shape (``status="error"``, an ``error_training:``
    message) so the orchestrator's pre-existing ``error`` branch records it
    through :func:`_build_execution_failure_record` (phase ``training`` →
    ``error_training``) — never a success record with
    ``validation_state="absent"``. ``run()`` gains a sequencing call, not a
    branch.

    A non-success status passes through untouched with the honest
    "no results" interpretation (``legacy_payload={}``, ``history=None``,
    ``history_state="absent"``) — exactly what ``train_status.get("results",
    {})`` meant before 07a on those paths (they never consume it).

    Returns:
        ``(train_status, results)`` — the (possibly rewritten) status and the
        typed results whose ``legacy_payload`` is EXACTLY the legacy keys that
        feed the reflect merge and the record.
    """
    if train_status.get("status") != "success":
        return train_status, TrainingResults(
            legacy_payload={}, history=None, history_state="absent"
        )
    try:
        results = interpret_training_results(
            train_status.get("results", {}), expected_validation=expected_validation
        )
    except TrainingResultsContractError as exc:
        rewritten = {
            **train_status,
            "status": "error",
            "error_type": "training_results_contract",
            "message": f"error_training: training results contract violated: {exc}",
        }
        print(f"--- Training results contract violated ---\n{exc}")
        return rewritten, TrainingResults(legacy_payload={}, history=None, history_state="absent")
    return train_status, results


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


def _emit_record(
    sandbox,
    record: dict,
    *,
    status: dict | None = None,
    candidate_id: str | None = None,
) -> None:
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
    # V21 PR E: the candidate's observational identity is stamped at this
    # single validate-and-persist seam so no record-construction site can
    # forget it. None stays None — never synthesised (O-E-4/O-E-5).
    record["candidate_id"] = candidate_id
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


def _build_denoised_filename(
    *,
    model_type: str,
    run_name: str,
    exp_id: str,
    file_index: int,
    base_dir: str,
    naming: DeliverableNaming | None = None,
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
        naming: Step 05c — the run's deliverable naming authority. The
            production caller threads the run's spec; ``None`` resolves the
            shipped TIDMAD default, which is what every legacy caller and
            every existing test gets. Optional rather than required
            precisely so this function's keyword-only contract is unchanged
            for them.

    Returns:
        Absolute path to the denoised HDF5 file, joinable and openable
        by any caller that receives it verbatim.
    """
    resolved = naming if naming is not None else default_deliverable_naming()
    filename = resolved.name(
        model_type=model_type,
        run_name=run_name,
        exp_id=exp_id,
        file_index=file_index,
    )
    return os.path.join(base_dir, filename)


def _build_scoring_failure_record(
    exc: Exception,
    *,
    exp_id: str,
    model_type: str,
    file_index: int,
    record_params: dict[str, Any],
    timing: dict[str, Any],
    expert_advice_str: str,
    hypothesis: str,
    round_index: int,
    attempt_in_round: int,
) -> dict[str, Any]:
    """The ``error_scoring`` record for a scoring-phase failure (V8 Domain 2a).

    Extracted from ``run()``'s scoring ``except`` (Step 06 C2) so that the
    ONE new scoring outcome — a deliverable REFUSED by the metric's
    scoreability contract, carried as :class:`NotScoreableError` — can be
    described honestly without adding a branch to ``run()``, which sits at
    pyright's complexity ceiling (see the ``PlanOverridesError`` note in the
    outer handler). Behaviour for every other exception is byte-identical to
    the inlined dict it replaces.

    Both outcomes share ``status="error_scoring"``: no score was produced and
    the attempt terminated before any gate evidence (the status's documented
    meaning, ``health_feedback.PRE_GATE_ERROR_STATUSES``). They differ in what
    the planner is told: a crash inside the scorer versus a deliverable that
    never reached the scorer, named requirement by requirement.
    """
    if isinstance(exc, NotScoreableError):
        failures = exc.result.verdict.failures
        named = "; ".join(
            f"{f.requirement}"
            + (f"[file {f.input_identity}]" if f.input_identity is not None else "")
            + f": {f.detail}"
            for f in failures
        )
        short_named = named[-500:] if len(named) > 500 else named
        conclusion = (
            f"Deliverable not scoreable under {exc.result.verdict.contract_id!r} "
            f"(metric {exc.result.metric_id!r}); scoring did not run: {short_named}"
        )
        discovery = (
            "Training and inference completed but the produced deliverable failed the "
            f"metric's scoreability contract ({len(failures)} requirement(s) violated). "
            "No scorer arithmetic was reached."
        )
        memory_update = (
            "Not-scoreable deliverable — the checkpoint trained, but its output does not "
            "satisfy what the metric requires (missing file, channel, attrs or wrong "
            "storage dtype). Inspect the inference/output path before retrying this config."
        )
        failure_type = "not_scoreable"
    else:
        error_msg = f"{type(exc).__name__}: {exc}"
        short_msg = error_msg[-500:] if len(error_msg) > 500 else error_msg
        conclusion = f"Scoring crashed: {short_msg}"
        discovery = (
            f"Training and inference completed but scoring raised {type(exc).__name__}: {short_msg}"
        )
        memory_update = (
            "Scoring crash — training succeeded so the "
            "checkpoint may be reusable. Investigate the "
            "scoring path (anchor map, sample_set, file "
            "vector shape) before retrying this config."
        )
        failure_type = None
    record: dict[str, Any] = {
        "exp_id": exp_id,
        "status": "error_scoring",
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_index": file_index,
        "params": record_params,
        "denoising_score": None,
        "timing": timing,
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
    if failure_type is not None:
        record["failure_stage"] = "scoring"
        record["failure_type"] = failure_type
    if isinstance(exc, NotScoreableError):
        # Step 06 C4 — the structured refusal, on the record (additive).
        record["metric_refusal"] = exc.result.model_dump(mode="json")
    return record


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


def _validate_history_and_lock(
    workspace: str,
    run_invariants: RunInvariants,
    existing_history: list[dict[str, Any]],
    lock_was_present: bool,
    *,
    dataset: DatasetConfig,
) -> None:
    """DS6b — ingress validation + deferred lock creation.

    On a lock-less workspace, every restored FINAL record's invariant stamps
    are checked BEFORE the lock is stamped (error records deliberately carry
    no stamps — DS5b — and are skipped), so a legacy workspace is never
    silently locked. A lock-present workspace was already validated at
    startup; its records were produced under that lock.

    Args:
        dataset: The run's dataset topology, from the run-bound
            ``DatasetProfile``. Step 05a: an unstamped legacy record is
            assumed to have been produced under the FULL scope, and "full"
            is only meaningful relative to *this run's* file count — reading
            it from the ambient TIDMAD singleton would validate a bound
            task's history against TIDMAD's twenty files. Required, not
            defaulted: a default here would silently restore that.
    """
    if not lock_was_present:
        for rec in existing_history:
            if rec.get("status") in {"success", "failed_mode_collapse"}:
                validate_stamped_invariants(
                    rec,
                    run_invariants,
                    full_scope=list(range(dataset.num_files)),
                    source=f"workspace summary record {rec.get('exp_id') or '(no exp_id)'}",
                )
    ensure_run_invariants(workspace, run_invariants)


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


def finalize_run_output(
    bindings: RunBindings,
    exit_snapshot: RunExitSnapshot,
) -> Any:
    """Build, validate and persist the run's output after the loop has ended.

    Moved VERBATIM out of ``run()``. It is the one phase with no loop-control
    exits at all — nothing here can ``break`` a round or ``continue`` an
    attempt — which is exactly why it extracts cleanly while the execution
    phases do not.

    Everything it reads is either a run-scoped binding or one of the nine
    end-of-loop facts in :class:`RunExitSnapshot`; the local names below are
    rebound so the moved body reads as it did inside ``run()``.
    """
    agent_input = bindings.agent_input
    sandbox = bindings.sandbox
    run_order = bindings.run_order
    run_name = bindings.run_name
    workspace = bindings.workspace
    file_index = bindings.file_index
    max_rounds = bindings.max_rounds
    model_type_setting = bindings.model_type_setting
    resolved_data_scope = bindings.resolved_data_scope
    trial_vram_budget = bindings.trial_vram_budget
    formal_vram_budget = bindings.formal_vram_budget
    trial_time_budget = bindings.trial_time_budget
    formal_time_budget = bindings.formal_time_budget
    started_at = bindings.started_at
    attempts_per_round_setting = bindings.attempts_per_round_setting
    attempts_per_formal_round_setting = bindings.attempts_per_formal_round_setting
    max_fail_rounds_setting = bindings.max_fail_rounds_setting
    formal_reference_score = bindings.formal_reference_score
    formal_reference_source = bindings.formal_reference_source
    resolved_skip_formal_threshold = bindings.resolved_skip_formal_threshold
    resolved_bypass_formal_threshold = bindings.resolved_bypass_formal_threshold
    health_checks_config_source = bindings.health_checks_config_source
    health_config_sha256 = bindings.health_config_sha256
    completed_rounds = exit_snapshot.completed_rounds
    total_attempts = exit_snapshot.total_attempts
    consecutive_fails = exit_snapshot.consecutive_fails
    _gate_aborted = exit_snapshot.gate_aborted
    _scope_violation_reason = exit_snapshot.scope_violation_reason
    _evidence_channel_failure = exit_snapshot.evidence_channel_failure
    _skipped_formal_for_no_valid_winner = exit_snapshot.skipped_formal_for_no_valid_winner
    physical_rejections_buffer = exit_snapshot.physical_rejections_buffer
    plan = exit_snapshot.last_plan

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
    _best_tracks = _select_best_records(all_records, order=run_order)
    top_record = _best_tracks.top
    formal_top_record = _best_tracks.formal
    valid_top_record = _best_tracks.valid
    valid_formal_top_record = _best_tracks.valid_formal
    valid_trial_top_record = _best_tracks.valid_trial

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
        # V21 PR E — run-level candidate label, echoed like the two above.
        "candidate_id": agent_input.candidate_id,
        "health_checks_config_source": health_checks_config_source,
        "health_config_sha256": health_config_sha256,
        "formal_reference_score": _json_safe_reference(formal_reference_score),
        "formal_comparison_reference_source": formal_reference_source,
        "resolved_skip_formal_threshold": _json_safe_reference(resolved_skip_formal_threshold),
        "resolved_bypass_formal_threshold": _json_safe_reference(resolved_bypass_formal_threshold),
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
        "best_valid_file_vector": valid_top_record.get("file_vector") if valid_top_record else None,
        "best_valid_score_table": valid_top_record.get("score_table") if valid_top_record else None,
        "best_valid_formal_score_table": valid_formal_top_record.get("score_table")
        if valid_formal_top_record
        else None,
        "best_config": top_record.get("params") if top_record else None,
        "best_file_vector": top_record.get("file_vector") if top_record else None,
        "best_score_table": top_record.get("score_table") if top_record else None,
        "formal_score_table": formal_top_record.get("score_table") if formal_top_record else None,
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
        # Step 09a C2 — the ONE writer of the run's bound MetricSpec. The
        # tuner already resolved it (`ml_hyperparameter_tune_agent.py:541`);
        # this transports THAT value so the interpreter never derives a
        # second one. Passed as the instance: the field's validator accepts
        # a MetricSpec unchanged and rebinds only a mapping.
        "metric_spec": bindings.run_metric.spec,
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
            # V21 PR E — the degraded exit keeps the label too; losing it
            # here would make crashed candidates silently unjoinable.
            "candidate_id": agent_input.candidate_id,
            "completed_rounds": completed_rounds,
            "total_attempts": total_attempts,
            "formal_reference_score": _json_safe_reference(formal_reference_score),
            "formal_comparison_reference_source": formal_reference_source,
            "resolved_skip_formal_threshold": _json_safe_reference(resolved_skip_formal_threshold),
            "resolved_bypass_formal_threshold": _json_safe_reference(
                resolved_bypass_formal_threshold
            ),
            "started_at": started_at,
            "finished_at": finished_at,
            "termination_reason": termination_reason,
            # Step 09a C2 — the same rule the healthgate_mode comment above
            # states: the run's metric binding is a LAUNCH fact and does not
            # stop existing because the tuner later failed. Dumped rather
            # than passed as an instance because this dict is written with
            # `json.dump(..., default=str)`, which would stringify the model.
            "metric_spec": bindings.run_metric.spec.model_dump(),
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


def build_attempt_record(
    bindings: RunBindings,
    prepared: PreparedAttempt,
    identity: AttemptIdentity,
    admission: AdmissionOutcome,
    trained: TrainingOutcome,
    executed: AttemptExecution,
    *,
    reflection: Any,
) -> dict:
    """Build the successful attempt's record, attach its evidence, emit it.

    Step 07 PR 07b, C7d. Moved VERBATIM out of ``run()``: 32 statements that
    assemble one dict, decorate it with the round's runtime, ordering, scope
    and validation evidence, and hand it to the sandbox. Record CONSTRUCTION
    is this module's stated responsibility, which is why it lands here rather
    than in a phase module.

    It BUILDS and returns the record; it does not emit it. ``run()`` still
    performs the emission and the runtime-observation append, because those
    live in ``runtime.py`` — which imports this module. Pulling them in here
    would rebuild the records <-> runtime cycle C7 removed, and the record
    dict is exactly the seam where the two responsibilities part.
    """
    agent_input = bindings.agent_input
    expert_advice_str = bindings.expert_advice_str
    file_index = bindings.file_index
    resolved_data_scope = bindings.resolved_data_scope
    _planned_portions = prepared._planned_portions
    cfg_eval_portion = prepared.cfg_eval_portion
    cfg_train_portion = prepared.cfg_train_portion
    cfg_trial_portion = prepared.cfg_trial_portion
    eval_psd_segments = prepared.eval_psd_segments
    exp_id = prepared.exp_id
    hypothesis = prepared.hypothesis
    model_type = prepared.model_type
    ordering = prepared.ordering
    plan = prepared.plan
    planned_eval_strategy = prepared.planned_eval_strategy
    planned_trial_strategy = prepared.planned_trial_strategy
    record_params = prepared.record_params
    strategy_normalization_reason = prepared.strategy_normalization_reason
    train_psd_segments = prepared.train_psd_segments
    trial_config = prepared.trial_config
    attempt_in_round = identity.attempt_in_round
    round_index = identity.round_index
    chosen_vram_budget = admission.chosen_vram_budget
    resource_check = admission.resource_check
    time_check = admission.time_check
    train_status = trained.train_status
    train_time = trained.train_time
    training_results = trained.training_results
    failure_reason = executed.failure_reason
    inf_status = executed.inf_status
    inference_time = executed.inference_time
    is_degenerate = executed.is_degenerate
    metric_payload = executed.metric_payload
    score_results = executed.score_results
    score_table = executed.score_table
    scoring_time = executed.scoring_time
    train_results = executed.train_results
    training_diagnosis = executed.training_diagnosis

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
        # Step 07a — persisted evidence, hidden from both LLM-facing
        # renders (planner hidden-key set; reflector gets
        # train_results only). Additive; None on legacy producers.
        "training_history": training_results.history_payload(),
        "training_diagnosis": training_diagnosis.model_dump(),
        # Scoring results
        "denoising_score": score_results.get("denoising_score"),
        "file_vector": score_results.get("file_vector"),
        # Per-file comparison table enrichment. Stored as a
        # plain dict on the record (ExperimentRecord.model_validate
        # coerces it back to ScoreComparisonTable below). None
        # when scoring failed or no scalar was produced.
        "score_table": score_table.model_dump() if score_table else None,
        # Step 06 — the metric's identity/direction/value, machine-
        # readable (additive; None where scoring did not go through
        # the handle, e.g. a legacy child that predates C3).
        "metric_result": metric_payload,
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
        final_record["memory"]["time_estimate_minutes"] = time_check.get("estimated_minutes")
        final_record["memory"]["time_budget_minutes"] = time_check.get("limit_minutes")
        final_record["memory"]["time_mode"] = "trial" if plan.is_trial else "formal"
        # refine_inference_time_estimator.md Commit D — record
        # which branch of the 3-way inference-ms derivation
        # the gate took. Audit logs distinguish a measured
        # ``trial_inference_warmup`` verdict from the legacy
        # ``training_warmup_x2.7_fallback`` and the
        # ``static_formula`` paths. Source is None on records
        # where the breakdown didn't carry it (defensive).
        final_record["memory"]["inference_ms_source"] = (time_check.get("breakdown") or {}).get(
            "inference_ms_source"
        )
        # RT3 — planner-visible training-estimate provenance:
        # which §3 branch produced the pre-flight training
        # ms/step (real_dataset_warmup | store |
        # static_uncalibrated) and whether the store-reuse
        # policy fired.
        final_record["memory"]["training_ms_source"] = (time_check.get("breakdown") or {}).get(
            "source"
        )
        if (time_check.get("breakdown") or {}).get("store_reuse"):
            final_record["memory"]["time_store_reuse"] = True
    # Phase K — surface pre-flight VRAM-estimator context to the
    # planner the same way Phase J surfaces time context. Only
    # added when the gate ran with a budget (chosen_vram_budget
    # was set); omitted when the gate fell back to free×0.8.
    # Mode is inferred from `time_mode` above when present.
    # See docs/resource_estimator_implement.md §10.4.
    if chosen_vram_budget is not None:
        final_record["memory"]["vram_estimate_gb"] = resource_check.get("estimated_gb")
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
    inf_per_psd_seg_ms, inf_breakdown = _aggregate_inference_file_timings(inf_per_file)
    final_record["memory"]["inference_per_psd_seg_ms_measured"] = inf_per_psd_seg_ms
    final_record["memory"]["inference_warmup_aggregator"] = inf_breakdown.get("aggregator")
    final_record["memory"]["inference_n_timed_files"] = inf_breakdown.get("n_timed_files")
    final_record["memory"]["inference_warmup_fraction"] = inf_breakdown.get("warmup_fraction")
    final_record["memory"]["inference_process_startup_ms"] = inf_status.get("process_startup_ms")
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
    final_record["ordering_proposal_rejection_reason"] = ordering.proposal_rejection_reason
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
        final_record["strategy_normalization_reason"] = strategy_normalization_reason
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

    return final_record
