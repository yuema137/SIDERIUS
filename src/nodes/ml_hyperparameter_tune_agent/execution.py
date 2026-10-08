"""Tuner EXECUTION — the physical work of one attempt, in three coarse phases.

Step 07 PR 07b, C7d (operator decision A-prime). PRIVATE node-internal module.

```text
admission / preflight   may this candidate run at all, and under which budgets
        v
training                train, then cross the training-result contract boundary
        v
inference + scoring     produce the deliverable, score it, run the health gates
```

Moved VERBATIM out of ``run()``. The only edit is to the control flow, and it is
mechanical: each phase used to end in a bare ``continue`` or ``break`` against
the attempt loop, and now returns that same decision as an
:class:`~nodes.ml_hyperparameter_tune_agent.contracts.AttemptSignal` for
``run()`` to act on. Every one of the 15 sites sat directly in the attempt loop
— none inside a nested loop — so the translation is 1:1 and the retry/round
semantics are unchanged.

``raise`` is NOT translated: the ``try``/``except`` that classifies attempt
failures stays in ``run()``, and an exception raised in here propagates into it
exactly as before. That is also why
:class:`~nodes.ml_hyperparameter_tune_agent.contracts.AttemptStage` is mutable —
on the raising path the handler still has to know which phase was executing.
"""

import time
from collections.abc import Mapping
from importlib import import_module as _import_module
from typing import Any

from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    PhysicalRejection,
)
from agent.schemas.ordering import OrderingObservation, OrderingRefusalPhase, ResolvedOrdering
from agent.schemas.preflight import StaticPreflightEvidence
from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.training_diagnosis import derive_training_diagnosis
from agent.skills.evaluate_vram_skill.preflight_adapter import run_production_preflight
from core.layout import checkout_root
from core.record_role import AttemptRole, observed_attempt_role
from execute_tools.dataset_config import (
    ScopeViolationError,
)
from execute_tools.evaluation_execution import (
    CandidateEvaluationRefused,
    candidate_evaluation_executor,
)
from execute_tools.evaluation_metric import (
    EvaluationMetric,
    MetricResult,
    NotScoreableResult,
)
from execute_tools.health_checks.config import default_health_policy_path
from execute_tools.health_checks.schemas import (
    PerSampleEvidence,
)
from execute_tools.scoring_helpers import (
    build_score_table,
    file_vector_to_log_space,
)
from ml_models.models_format_sandbox import TrainConfig
from nodes.agent_data_stream import log_score_table
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AdmissionOutcome,
    AttemptExecution,
    AttemptIdentity,
    AttemptStage,
    EvaluationPhaseEvidence,
    PreparedAttempt,
    RunBindings,
    TrainingOutcome,
)
from nodes.ml_hyperparameter_tune_agent.external_evaluation import run_external_evaluation
from nodes.ml_hyperparameter_tune_agent.output_retention import finalize_attempt_outputs
from nodes.ml_hyperparameter_tune_agent.policy import (
    ScoringRoute,
    _apply_degeneracy_reaction,
    _fmt_reference,
    _gate_results_to_score_meta,
    _merge_score_validity_failure,
    _should_bypass_formal_time_budget,
    resolve_measured_time_budget,
    resolve_scoring_route,
)
from nodes.ml_hyperparameter_tune_agent.probe_data import build_task_probe_data
from nodes.ml_hyperparameter_tune_agent.records import (
    _build_denoised_filename,
    _build_execution_failure_record,
    _build_scoring_failure_record,
    _build_skip_record,
    _interpret_training_status,
)
from nodes.ml_hyperparameter_tune_agent.round_health import (
    apply_round_health,
    build_evaluation_payload_fn,
    build_target_path_fn,
)
from nodes.ml_hyperparameter_tune_agent.runtime import (
    PrephaseOutcome,
    RuntimeEvidenceChannelError,
    _build_admission_policy,
    _build_runtime_policy,
    _check_and_record_guardrail_skip,
    _handle_admission_refusal,
    _handle_in_subprocess_rejection,
    _handle_prephase_gpu_measurement,
    _raise_if_evidence_channel_failure,
    _raise_if_preflight_blocks,
    _raise_if_wall_clock_timeout,
    _run_time_preflight,
    _time_skip_memory_extra,
    _vram_skip_memory_extra,
    apply_forecast_time_authority,
    is_evidence_refusal,
)

# `_emit_record` is the node's ONE record-emission point, called from four
# modules. Same reasoning as `_runtime._run_skill`: resolve it through its
# owner so the node has a single binding, and a stub installed on that owner
# intercepts every emission rather than whichever module it was aimed at.
_records = _import_module("nodes.ml_hyperparameter_tune_agent.records")
# NOTE the resolution FORM, which is not stylistic. Both `from <package> import
# <submodule>` and `import <package>.<submodule> as x` resolve the submodule as an
# ATTRIBUTE of the parent — and this package rebinds `sys.modules[__name__]` to the
# main module, whose `__name__` is `...tune_agent.ml_hyperparameter_tune_agent`. The
# fallback then looks for a key one level too deep and raises. `import_module` takes
# the absolute name straight to `sys.modules`, so it holds even when the main module
# is loaded standalone (as `tests/unit/agent/evaluate_vram_skill` does).
#
# `_run_skill` is the node's ONE entry to its tools, and it is called from
# three modules. Calling it through its owning module keeps a single binding:
# whatever `runtime._run_skill` is at call time is what every phase runs. A
# per-module `from ... import _run_skill` would give each module its own
# snapshot, so a stub installed for one would silently miss the others.
_runtime = _import_module("nodes.ml_hyperparameter_tune_agent.runtime")


class ScoringSkillExecutionError(RuntimeError):
    """The scoring subprocess did not complete successfully."""


def _require_successful_scoring_result(score_result: Mapping[str, Any]) -> None:
    """Refuse a failed scoring subprocess before Health/scientific routing.

    A missing scalar after a *successful* scorer is scientific validity
    evidence.  A missing scalar because the scorer crashed is infrastructure
    failure.  Keeping that distinction here, immediately after the subprocess
    boundary, prevents Health from appearing to pass work that was never
    scored and prevents ``failed_mode_collapse`` from hiding a broken scorer.
    """

    status = score_result.get("status")
    if status == "success":
        return
    message = score_result.get("message")
    detail = str(message) if message else "scoring subprocess returned no failure detail"
    raise ScoringSkillExecutionError(f"scoring skill status={status!r}: {detail}")


def _emit_attempt_record(
    sandbox,
    record: dict,
    agent_input,
    *,
    status: dict | None = None,
    ordering: ResolvedOrdering | None,
    refused_before_phase: OrderingRefusalPhase | None = None,
    attempt_role: AttemptRole | None = None,
) -> None:
    """Emit one attempt record with the run's identity kwargs attached.

    Integration extraction (S1 x landed PR-12d, the SE.2 idiom): threading
    ``candidate_id=`` + ``experiment_arm=`` at every emission site expanded
    each call to six lines and pushed ``run_inference_scoring_health`` past
    its frozen structural budget (474 + 80; landed master already sat at
    552). The identity threading is ONE responsibility, so it gets ONE owner;
    call sites shrink back to a line and a site that forgets the label
    becomes impossible rather than censused.

    Still routed through ``_records._emit_record`` — the node's ONE emission
    point — so a stub installed on ``records`` intercepts every emission
    exactly as before. Both branches pass the identity kwargs EXPLICITLY so
    the U1 emission census reads them from this function's own AST.
    """
    if ordering is None:
        # The operator configuration is known even if the planner never returns.
        # Preserve intent without resolving it or implying it was selected.
        record["override_order_strategy"] = agent_input.order_strategy_override
        record["override_file_order"] = agent_input.file_order_override
    observation = OrderingObservation(
        selection_state="selected" if ordering is not None else "unresolved",
        refused_before_phase=refused_before_phase,
    )
    if status is None:
        _records._emit_record(
            sandbox,
            record,
            candidate_id=agent_input.candidate_id,
            experiment_arm=agent_input.experiment_arm,
            ordering=ordering,
            ordering_observation=observation,
            attempt_role=attempt_role,
        )
    else:
        _records._emit_record(
            sandbox,
            record,
            status=status,
            candidate_id=agent_input.candidate_id,
            experiment_arm=agent_input.experiment_arm,
            ordering=ordering,
            ordering_observation=observation,
            attempt_role=attempt_role,
        )


SIDERIUS_ROOT = checkout_root()


def wall_time_preflight_applicable(
    run_profile: object,
    legacy_sample_set: object,
) -> bool:
    """Is the wall-time pre-flight family in this run's domain at all?

    C12-P / B1 + B4. The whole family — the training and inference wall-time
    estimators, and the bounded live probe a ``REQUEST_PROBE`` verdict resolves
    — prices a workload through ``execute_tools/workload_resolvers.py``, whose
    arithmetic is ``psd_segment_length // seg_size``. That is TIDMAD physics.
    There is exactly ONE workload-resolver implementation, no protocol, no
    registry and no task-owned accessor for a step count, so a task that
    declares no TIDMAD topology has no value this family could be computed
    from. It is **semantically outside the subsystem**, which is precisely
    what ``NOT_APPLICABLE`` means; it is not a missing artifact and not an
    error.

    A TIDMAD topology is necessary but not sufficient. The estimator family
    also consumes the legacy physical ``SampleSet`` for training, inference,
    and scoring. A composed task may legitimately declare TIDMAD topology yet
    carry an opaque task-owned scope instead of that mapping. Entering the
    legacy estimator with ``None`` would then crash at ``sample_set.items()``.
    A partial task-scope repair for training would merely move the same defect
    into inference or scoring, whose cost models are also TIDMAD-specific.
    Therefore the family is applicable only when its complete workload input
    is present. The attempt's independently configured in-subprocess runtime
    policy still measures and enforces Formal execution; this decision skips
    only the unsupported advance forecast.

    **ONE decision for the whole family, made caller-side.** B1 (the estimate)
    and B4 (the probe lane) are two consumers of the same assumption, and B1
    fires first, so repairing only B1 moves the failure ~30 lines down into a
    probe that reports ``probe_status="load_failure"`` — blaming the candidate
    model for a task-applicability fact. The applicability layer that owns the
    resolved profile answers once, here, and both consumers inherit it.

    **A MEMBERSHIP TEST, never a caught ``ValueError``.** ``tidmad_topology()``
    raises for two different reasons — sections ABSENT, and sections PRESENT
    but MALFORMED — so inferring non-membership from the exception would
    silently reclassify a broken TIDMAD declaration as "some other task" and
    skip a check that must instead FAIL. A malformed TIDMAD profile therefore
    returns ``True`` here, still runs, and still fails closed.

    ``run_profile`` that is not a ``DatasetProfile`` is Regime A — an
    un-composed run, which IS TIDMAD — but it is applicable only when that
    legacy run supplied its SampleSet. A mapping (including an empty mapping)
    is structurally valid; ``None`` means the task-owned-scope regime.
    """
    from collections.abc import Mapping

    from execute_tools.dataset_config import DatasetProfile, declares_tidmad_topology

    if not isinstance(legacy_sample_set, Mapping):
        return False
    if not isinstance(run_profile, DatasetProfile):
        return True
    return declares_tidmad_topology(run_profile)


def _structured_mapping(value: object) -> dict[str, Any]:
    """``value`` when it is a dict; ``{}`` for every other member of the union.

    F-SCANB-2. The VRAM pre-flight worker deliberately replaces an oversized
    rich diagnostic field with the truncation-marker STRING
    ``"[dropped: exceeded the rich-field budget]"``
    (``agent/skills/evaluate_vram_skill/preflight_worker_main.py``,
    ``_bounded_rich_fields``) so the field's absence is explicit rather than
    silent, and the parent-side schema types the forwarded fields as unions —
    ``IsolatedProbeResult.memory_killer`` / ``offending_config`` are
    ``dict[str, Any] | str | None`` (``isolated_probe.py``). A consumer that
    calls ``.get`` on that union crashes on the ``str`` member: twice
    historically, a CORRECT VRAM rejection died in an ``AttributeError``
    and spent the attempt instead of reaching its ``skipped_oom_risk``
    record. The marker and ``None`` both map to ``{}`` here — the absence of
    structure stays explicit through the record's forwarded
    verdict/suggestion text and through the marker value itself wherever the
    raw union field is carried.
    """
    return value if isinstance(value, dict) else {}


def _structured_items(value: object) -> list[Any]:
    """``value`` when it is a list; ``[]`` for every other member of the union.

    F-SCANB-2, the ``violations`` twin of :func:`_structured_mapping`. The
    worker's ``_bounded_rich_fields``
    (``agent/skills/evaluate_vram_skill/preflight_worker_main.py``)
    substitutes the same ``"[dropped: exceeded the rich-field budget]"``
    marker for an oversized ``violations`` payload, and
    ``IsolatedProbeResult.violations`` is ``list[Any] | str | None``
    (``isolated_probe.py``). Iterating the marker yields CHARACTERS, so
    ``v.get(...)`` raised ``AttributeError`` in the schema-violation branch
    before its ``skipped_schema_violation`` record could be emitted.
    """
    return value if isinstance(value, list) else []


def run_admission_preflight(
    bindings: RunBindings,
    prepared: PreparedAttempt,
    identity: AttemptIdentity,
    stage: AttemptStage,
    *,
    formal_trial_winner: Any,
    physical_rejections_buffer: Any,
) -> AdmissionOutcome:
    """Phase 1 of 3. Body moved verbatim; see the module docstring."""
    agent_input = bindings.agent_input
    expert_advice_str = bindings.expert_advice_str
    file_index = bindings.file_index
    formal_reference_score = bindings.formal_reference_score
    formal_time_budget = bindings.formal_time_budget
    formal_vram_budget = bindings.formal_vram_budget
    hardware_context = bindings.hardware_context
    resolved_bypass_formal_threshold = bindings.resolved_bypass_formal_threshold
    run_model_io = bindings.run_model_io
    run_order = bindings.run_order
    run_profile = bindings.run_profile
    sandbox = bindings.sandbox
    time_data_dir = bindings.time_data_dir
    trial_time_budget = bindings.trial_time_budget
    trial_vram_budget = bindings.trial_vram_budget
    workspace = bindings.workspace
    active_params = prepared.active_params
    exp_id = prepared.exp_id
    hypothesis = prepared.hypothesis
    memory_history = prepared.memory_history
    model_config = prepared.model_config
    model_type = prepared.model_type
    plan = prepared.plan
    record_params = prepared.record_params
    train_sample_set = prepared.train_sample_set
    trial_config = prepared.trial_config
    attempt_in_round = identity.attempt_in_round
    is_formal_round = identity.is_formal_round
    round_index = identity.round_index

    stage.name = "guardrails"
    if _check_and_record_guardrail_skip(
        ordering=prepared.ordering,
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
        dataset_profile=run_profile,
        # C12-P / B7. Applicability is decided HERE, by the layer that owns
        # the resolved context, and passed down — the guardrail must not
        # rediscover either value. `prepared.task_scopes` is what PR-12bc B5
        # already acquired for this attempt; `time_data_dir` is the ONE
        # authority for where the data physically lives (Step 11 C4), which
        # is exactly what the §AB.3 transport repaired.
        task_scopes=prepared.task_scopes,
        data_dir=time_data_dir,
    ):
        return AdmissionOutcome.next_attempt()

    # Phase K: per-mode VRAM-budget pick. plan.is_trial decides
    # which ceiling applies for THIS round; the unselected one is
    # ignored. When the chosen budget is None the skill still runs
    # but falls back to free×0.8 defensive behaviour (no operator
    # ceiling) — the memory's vram_*_gb fields are omitted in that
    # case so the planner sees "this round wasn't operator-budgeted."
    # See docs/resource_estimator_implement.md §10.4 / §10.8.
    chosen_vram_budget = trial_vram_budget if plan.is_trial else formal_vram_budget
    vram_budget_desc = f"{chosen_vram_budget} GB" if chosen_vram_budget is not None else "free×0.8"
    print(
        f"\n[Pre-flight 1/2] VRAM check "
        f"(mode={'trial' if plan.is_trial else 'formal'}, "
        f"budget={vram_budget_desc})..."
    )
    stage.name = "vram_structural_probe"
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
    task_probe_data = build_task_probe_data(
        task_composition_ref=agent_input.task_composition_ref,
        task_scopes=prepared.task_scopes,
        data_dir=time_data_dir,
        epoch_seed=trial_config.train_base_seed,
        train_portion=trial_config.train_portion,
        max_samples=agent_input.validation_max_train_samples,
    )
    resource_check = run_production_preflight(
        model_type=active_params["model_type"],
        model_config=active_params["model_config"],
        train_config=active_params["train_config"],
        loss_config=active_params["loss_config"],
        expected_custom_loss_snapshot=prepared.expected_custom_loss_snapshot,
        vram_budget_gb=chosen_vram_budget,
        hardware_context=hardware_context,
        workspace=workspace,
        label=exp_id,
        # Step 05b — the run's ONE declaration, bound at
        # startup and passed by value. The pre-flight never
        # resolves one of its own: it must price the
        # candidate against the contract this run trains
        # against, and "happens to read the same file" is
        # not that guarantee.
        model_io_contract=run_model_io,
        # Step 11 C1 (F-11-2) — the run-scoped plugin directories, taken
        # from the sandbox that owns them rather than re-derived. The
        # worker previously inherited this parent's environ, which carries
        # no SIDERIUS_PLUGIN_DIRS, and so priced the candidate against the
        # legacy global plugin dir instead of this run's.
        plugin_dir=sandbox.plugin_dir,
        loss_dir=sandbox.loss_dir,
        probe_step_timeout_seconds=(bindings.agent_input.vram_probe_step_timeout_seconds),
        deadline_seconds=(bindings.agent_input.vram_preflight_total_timeout_seconds),
        host_memory_limit_gb=(bindings.agent_input.vram_preflight_host_memory_limit_gb),
        task_probe_data=task_probe_data,
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
        # F-SCANB-2 — the worker may have replaced the list with its
        # truncation-marker string; normalize SHAPE once, at the binding.
        violations = _structured_items(resource_check.get("violations", []))
        offending = resource_check.get("offending_config", {})
        violating_fields = ", ".join(v.get("loc", "?") for v in violations) or "unknown"
        print("Schema violation — this attempt does NOT count as a round.")
        print(f"   Violating fields : {violating_fields}")
        for v in violations:
            print(f"   - {v.get('loc')} ({v.get('type')}): {v.get('msg')}")

        violation_summary = (
            "; ".join(f"{v.get('loc')}={v.get('input')!r} → {v.get('msg')}" for v in violations)
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
        _emit_attempt_record(
            sandbox,
            schema_record,
            agent_input,
            ordering=prepared.ordering,
            refused_before_phase="preflight",
            attempt_role=observed_attempt_role(prepared.plan.is_trial),
        )
        return AdmissionOutcome.next_attempt()

    from core.runtime_control.inference_refusal_verification import (
        preflight_allows_execution,
        preflight_inference_batch,
        preflight_refusal_detail,
        preflight_refusal_suggestion,
        verification_from_result,
    )

    if not preflight_allows_execution(resource_check):
        print("Resource check FAILED — this attempt does NOT count as a round.")
        print(f"   Verdict   : {preflight_refusal_detail(resource_check)}")
        print(f"   Suggestion: {preflight_refusal_suggestion(resource_check)}")

        # Phase 6.6 WS-B B.3 Hop 2 — capture this rejection
        # into the per-run buffer so the orchestrator can
        # aggregate and feed it back to the next Proposer
        # iteration as a [PHYSICAL REJECTION] string.
        # See docs/phase66_ws_b_proposer_hardening.md §2.3.
        # F-SCANB-2 — the union's str member (the worker's truncation
        # marker) must map to "no structure", exactly like None/absent.
        _killer = _structured_mapping(resource_check.get("memory_killer"))
        _evidence = (
            StaticPreflightEvidence.model_validate(resource_check["static_preflight_evidence"])
            if resource_check.get("static_preflight_evidence") is not None
            else None
        )
        _binding = (
            "+".join(_evidence.binding_caps)
            if _evidence is not None
            else _killer.get("binding_cap", "vram")
        )
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
                PhysicalRejection.model_validate(
                    {
                        "static_preflight_evidence": _evidence,
                        "inference_verification": verification_from_result(resource_check),
                        "attempt_config": _attempt_snapshot,
                        "binding_cap": _binding,
                        "dominant_layer": _killer.get("dominant_layer") or "",
                        "dominant_layer_gb": round(_dom_bytes / (1024**3), 4),
                        "dominant_fraction": _killer.get("dominant_fraction") or 0.0,
                        "budget_gb": float(resource_check.get("limit_gb") or 0.0),
                        "estimated_gb": resource_check.get("estimated_gb"),
                        "suggestion": preflight_refusal_suggestion(resource_check),
                    }
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
            conclusion="Skipped: " + preflight_refusal_detail(resource_check),
            discovery=preflight_refusal_detail(resource_check),
            memory_update=preflight_refusal_suggestion(resource_check),
            memory_extra=_vram_skip_memory_extra(resource_check, chosen_vram_budget),
        )
        _emit_attempt_record(
            sandbox,
            oom_record,
            agent_input,
            ordering=prepared.ordering,
            refused_before_phase="preflight",
            attempt_role=observed_attempt_role(prepared.plan.is_trial),
        )
        return AdmissionOutcome.next_attempt()

    # Phase 6.6 A.11 — capture the batch the VRAM skill picked
    # and propagate it through the rest of the attempt. Lands in
    # active_params (so _runtime._run_skill("inference_skill", ...) forwards
    # it to sandbox.execute_inference) and record_params (so the
    # saved record reflects what actually ran, not the legacy
    # registry default). ``inference_batch`` is always present on
    # a feasible resource_check; fall back to None (executor's
    # back-compat path) if the wrapper somehow omits it.
    chosen_inference_batch = preflight_inference_batch(resource_check)
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
    chosen_time_source = (
        agent_input.trial_time_admission_source
        if plan.is_trial
        else agent_input.formal_time_admission_source
    )
    chosen_time_budget = resolve_measured_time_budget(
        base_budget_minutes=chosen_time_budget,
        admission_source=chosen_time_source,
        is_formal_round=is_formal_round,
        formal_trial_winner=formal_trial_winner,
        bypass_threshold=resolved_bypass_formal_threshold,
        bypass_ceiling_minutes=agent_input.bypass_formal_time_budget_minutes,
        order=run_order,
    )
    time_check = None
    # C12-P B1/B4 — decided ONCE, before the gate, for the whole family.
    # `time_check` staying None is the state an unset budget already produces,
    # so an inapplicable run takes a downstream path that has always existed.
    _forecast_selected = chosen_time_source == "forecast"
    _walltime_applicable = wall_time_preflight_applicable(run_profile, train_sample_set)
    if chosen_time_budget is not None and _forecast_selected and not _walltime_applicable:
        raise RuntimeEvidenceChannelError(
            "forecast wall-time admission was selected, but this attempt does "
            "not provide the complete workload required by the advance "
            "forecast; choose measured admission or provide a supported "
            "forecast workload"
        )
    if chosen_time_budget is not None and _forecast_selected and _walltime_applicable:
        stage.name = "time_estimation"
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
            dataset_profile=run_profile,
        )
        if time_check.get("status") == "error":
            # Includes the policy's ABORT path: an
            # evidence-channel failure is an execution-system
            # failure, never a candidate verdict.
            raise RuntimeError(f"Time check error: {time_check.get('message')}")

        apply_forecast_time_authority(time_check)

        # Forecast admission deliberately does not resolve REQUEST_PROBE:
        # doing so would make executing-device measurement a second authority.

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
                order=run_order,
            )
        ):
            _winner = formal_trial_winner
            _best_trial_score = _winner.get("denoising_score") if _winner is not None else None
            _qualified_msg = (
                f"trial {_best_trial_score:.4f} "
                f"{run_order.at_least_symbol} "
                f"reference({_fmt_reference(formal_reference_score)}) "
                f"+ delta({agent_input.bypass_formal_time_budget_min_delta:.4f}) "
                f"= {_fmt_reference(resolved_bypass_formal_threshold)}"
            )
            # Lane F3 / F-BYPASS-WD-1 (supervisor ruling 2026-08-26): the
            # bypass RAISES the ceiling and RE-APPLIES the same gate at it —
            # it never forces `feasible`. The old in-place flip overrode the
            # FORECAST only while the watchdog's operator_budget_seconds
            # stayed at the normal budget: admitted on promised time, killed
            # at the normal deadline. ONE resolved value now feeds BOTH
            # consumers: `chosen_time_budget` is what the runtime policy
            # reads below, so raising it HERE moves the watchdog ceiling
            # with the admission verdict — nothing to drift against.
            _bypass_ceiling = agent_input.bypass_formal_time_budget_minutes
            _estimated = time_check.get("estimated_minutes")
            if _bypass_ceiling is None:
                print(
                    f"  [BypassTimeBudget] score-QUALIFIED ({_qualified_msg}) "
                    "but NO elevated ceiling is configured "
                    "(--bypass_formal_time_budget_minutes unset) — no "
                    "extension granted; the time refusal stands. The None "
                    "default is load-bearing: a bypass can never become a "
                    "global raise through a schema default.",
                    flush=True,
                )
            elif _estimated is not None and _estimated <= _bypass_ceiling:
                print(
                    f"  [BypassTimeBudget] score-QUALIFIED ({_qualified_msg}) "
                    f"and the forecast ({_estimated:.1f} min) FITS the "
                    f"elevated ceiling ({_bypass_ceiling:.0f} min) — admission "
                    "re-evaluated at the bypass ceiling; the watchdog ceiling "
                    "moves WITH it.",
                    flush=True,
                )
                # The one resolved value: the record's budget and the runtime
                # policy's operator_budget_seconds both read this.
                chosen_time_budget = _bypass_ceiling
                # TRUE BY RE-EVALUATION at the elevated ceiling — never a
                # forced flag. Provenance rides beside it.
                time_check["feasible"] = True
                time_check["bypass_ceiling_minutes"] = _bypass_ceiling
            else:
                print(
                    f"  [BypassTimeBudget] score-QUALIFIED ({_qualified_msg}) "
                    f"but the forecast "
                    f"({_estimated if _estimated is not None else 'unavailable'} min) "
                    f"exceeds even the elevated ceiling ({_bypass_ceiling:.0f} "
                    "min) — REFUSED under bypass. The bypass raises the "
                    "ceiling; it never removes the gate (an unavailable "
                    "estimate fails closed).",
                    flush=True,
                )

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
            _emit_attempt_record(
                sandbox,
                time_record,
                agent_input,
                ordering=prepared.ordering,
                refused_before_phase="preflight",
                attempt_role=observed_attempt_role(prepared.plan.is_trial),
            )
            return AdmissionOutcome.next_attempt()

    # RT2-G: operator runtime policy for the in-subprocess verification
    # session (§2.1/§3). The selected source decides whether verification
    # enforces the budget or remains record-only for either candidate role.
    active_params["runtime_policy"] = _build_runtime_policy(
        agent_input,
        chosen_time_budget=chosen_time_budget,
        admission_source=chosen_time_source,
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
    from nodes.ml_hyperparameter_tune_agent.gpu_execution import prepare_phase

    _prephase = prepare_phase(bindings, prepared, identity, phase="training")
    if _prephase is None:
        _prephase = _handle_prephase_gpu_measurement(
            ordering=prepared.ordering,
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
            run_profile=run_profile,
            run_model_io=run_model_io,
            task_probe_data=task_probe_data,
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
        return AdmissionOutcome.end_round()
    if _prephase is PrephaseOutcome.TERMINAL_RESOURCE_REFUSAL:
        # Measured, and it genuinely does not fit. A different
        # candidate may — so this consumes the attempt as
        # before and the loop continues.
        return AdmissionOutcome.next_attempt()

    return AdmissionOutcome(
        chosen_vram_budget=chosen_vram_budget,
        resource_check=resource_check,
        time_check=time_check,
    )


def run_training(
    bindings: RunBindings,
    prepared: PreparedAttempt,
    identity: AttemptIdentity,
    stage: AttemptStage,
) -> TrainingOutcome:
    """Phase 2 of 3. Body moved verbatim; see the module docstring."""
    agent_input = bindings.agent_input
    expert_advice_str = bindings.expert_advice_str
    file_index = bindings.file_index
    run_name = bindings.run_name
    sandbox = bindings.sandbox
    active_params = prepared.active_params
    eval_sample_set = prepared.eval_sample_set
    exp_id = prepared.exp_id
    hypothesis = prepared.hypothesis
    model_type = prepared.model_type
    plan = prepared.plan
    record_params = prepared.record_params
    attempt_in_round = identity.attempt_in_round
    round_index = identity.round_index

    stage.name = "training"
    print("\n[Step 1/3] Training...")
    t0 = time.time()
    train_status = _runtime._run_skill("training_skill", sandbox, **active_params)
    train_time = round(time.time() - t0, 1)
    _raise_if_wall_clock_timeout(train_status, sandbox, run_name)
    _raise_if_evidence_channel_failure(train_status, sandbox, run_name)
    if _handle_admission_refusal(
        train_status,
        ordering=prepared.ordering,
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
        candidate_id=agent_input.candidate_id,
        experiment_arm=agent_input.experiment_arm,
        is_trial=prepared.plan.is_trial,
    ):
        return TrainingOutcome.next_attempt()
    if _handle_in_subprocess_rejection(
        train_status,
        ordering=prepared.ordering,
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
        candidate_id=agent_input.candidate_id,
        experiment_arm=agent_input.experiment_arm,
    ):
        return TrainingOutcome.next_attempt()
    # Step 07a — typed training-results boundary (sequencing call
    # only): a contract violation is rewritten into the existing
    # error shape and recorded by the branch below.
    requested_training = TrainConfig.model_validate(active_params["train_config"])
    train_status, training_results = _interpret_training_status(
        train_status,
        expected_validation=eval_sample_set is not None,
        expected_checkpoint_selection=requested_training.checkpoint_selection,
        expected_target_standardization=requested_training.target_standardization,
    )
    # Step 11 C2 (F-11-1) — ONE authority decides what "the subprocess
    # failed" means. `oom_host_ram` used to miss this branch entirely and
    # was carried on as a normal outcome.
    if _records.is_execution_failure(train_status):
        # DataScope DS5 — scope violations are non-retryable
        # configuration/invariant failures: terminate the run.
        if train_status.get("error_type") == "scope_violation":
            _scope_violation_reason = train_status.get("message", "scope violation in training")
            return TrainingOutcome.end_round(scope_violation_reason=_scope_violation_reason)
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
        _emit_attempt_record(
            sandbox,
            error_record,
            agent_input,
            status=train_status,
            ordering=prepared.ordering,
            attempt_role=observed_attempt_role(prepared.plan.is_trial),
        )
        print(f"  Saved error record: {error_record['status']}")
        return TrainingOutcome.next_attempt()

    return TrainingOutcome(
        train_status=train_status,
        train_time=train_time,
        training_results=training_results,
    )


def _adopt_child_secondaries(
    score_results: Mapping[str, Any],
    *,
    results: list[MetricResult],
    refusals: list[NotScoreableResult],
    errors: dict[str, str],
) -> tuple[list[MetricResult], list[NotScoreableResult], dict[str, str]]:
    """The run's secondaries, from whichever route evaluated them.

    Step 12 / PR-12d. Two routes can produce them and exactly one does per
    attempt:

    * ``ANCHOR_NORMALIZED`` — the tuner evaluates them in-process
      (:func:`_evaluate_secondary_metrics`) and passes them in here, already
      typed. They win, unconditionally.
    * ``TASK_OWNED`` — the tuner CANNOT: the deliverable is read by the
      scoring child, so the child is the only party holding the evaluation
      payload and the scope. It computes them and serialises them into
      ``--output_json``, and this re-types them into the SAME carriers, so
      the record has ONE shape regardless of route and nothing downstream
      needs to know which ran.

    **Total by construction**, which is why the precedence lives here rather
    than at the call site: anything already evaluated passes straight through,
    so a child that reported none can never blank an anchor-route result, and
    the orchestrator gains no branch (§E.2's zero-net-growth budget).

    Validation is deliberate rather than a ``model_construct`` shortcut —
    these values crossed a process boundary as JSON, and nothing reaches an
    execution layer without passing its schema. A malformed entry fails loudly
    here instead of producing a half-typed record.

    A run declaring no secondaries gets three empty containers on both routes,
    and the record is byte-unchanged.
    """
    if results or refusals or errors:
        return results, refusals, errors
    adopted = [
        MetricResult.model_validate(item)
        for item in score_results.get("secondary_metric_results", ())
    ]
    adopted_refusals = [
        NotScoreableResult.model_validate(item)
        for item in score_results.get("secondary_metric_refusals", ())
    ]
    return adopted, adopted_refusals, dict(score_results.get("secondary_metric_errors", {}) or {})


def _adopt_child_metric_result(
    score_results: Mapping[str, Any],
    *,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """The run's PRIMARY metric identity, from whichever route produced it.

    Step 12 / PR-12d, F-12d-32 — the sibling of
    :func:`_adopt_child_secondaries`, and it exists because the primary had
    the defect its own secondaries did not.

    ``metric_payload`` is assigned in exactly one place, inside the
    ``ANCHOR_NORMALIZED`` branch. On the ``TASK_OWNED`` route nothing assigned
    it, so a completed contrast round persisted ``metric_result: null`` beside
    a perfectly good ``denoising_score``: the metric's VALUE crossed the
    process boundary and its IDENTITY did not. §I requires the terminal report
    to carry the metric id and direction and to prove they belong to the
    implementation production actually bound, which a bare scalar cannot.

    **Total, and anchor-wins**, exactly as the secondaries helper is: a value
    already computed in-process passes straight through, so a child that
    reported none can never blank it, and the call site gains no branch
    (§E.2's zero-net-growth budget).

    Validated rather than trusted — the payload crossed as JSON, and
    re-typing it through :class:`MetricResult` means a malformed entry fails
    loudly here instead of persisting a half-typed identity. The value is
    re-dumped so the record's shape is identical on both routes.
    """
    if current is not None:
        return current
    reported = score_results.get("metric_result")
    if not reported:
        return None
    return MetricResult.model_validate(reported).model_dump(mode="json", exclude={"per_sample"})


def _evaluate_secondary_metrics(
    sandbox: Any,
    secondaries: tuple[EvaluationMetric, ...],
    *,
    sample_set: Any,
    anchor_map: dict,
    s_max: float,
    denoised_filename_fn: Any,
) -> tuple[list[MetricResult], list[NotScoreableResult], dict[str, str]]:
    """Evaluate the run's DECLARED OBSERVATIONAL secondaries. Step 10 / P2b C2.

    A typed boundary rather than thirty more lines inside the scoring block:
    it has explicit inputs, a typed three-part result, bounded side effects
    (one diagnostic line per crash) and no access to the attempt's control
    flow. That is what lets the attempt-parity claim be tested at all — the
    caller can run the identical fixture with ``()`` and compare outcomes.

    Called ONLY after a SUCCESSFUL primary result, so an ``error_scoring``
    attempt carries no secondary entries by construction. Each secondary
    evaluates the SAME deliverables through the SAME
    ``sandbox.evaluate_metric`` route and the SAME ``denoised_filename_fn``
    the primary just used — scoreability contract first, then arithmetic.

    A THIN ADAPTER — Step 12 / PR-12d. The per-secondary exception taxonomy
    (design §4.2, Q-P2b-2) moved to
    ``execute_tools.evaluation_metric.evaluate_declared_secondaries``, the
    ONE shared owner both this ANCHOR-NORMALIZED route and the TASK-OWNED
    route (``denoising_score_single.py::_evaluate_task_owned_secondaries``)
    now call, closing the twinning hazard
    ``test_the_secondary_evaluator_has_exactly_one_owner`` exists to catch.
    This function's own job is narrowed to ONE thing: supply the
    anchor-route-specific ``sandbox.evaluate_metric(...)`` call as the
    per-secondary evaluator.

    Returns:
        ``(results, refusals, errors)``, keyed consistently by metric id so
        no id can appear in two of them (the record's validator enforces it).

    Raises:
        ScopeViolationError: re-raised from a secondary call, unchanged.
    """
    from execute_tools.evaluation_metric import evaluate_declared_secondaries

    return evaluate_declared_secondaries(
        secondaries,
        lambda secondary: sandbox.evaluate_metric(
            secondary,
            sample_set=sample_set,
            anchor_map=anchor_map,
            s_max=s_max,
            denoised_filename_fn=denoised_filename_fn,
        ),
    )


def _run_local_evaluation_phase(
    bindings: RunBindings,
    prepared: PreparedAttempt,
    identity: AttemptIdentity,
    stage: AttemptStage,
    *,
    train_time: Any,
) -> EvaluationPhaseEvidence | AttemptExecution:
    """Execute the original local inference, scoring and Health path in order.

    Return early attempt decisions unchanged. The caller owns output cleanup and
    common result interpretation, including on raised failures.
    """
    agent_input = bindings.agent_input
    anchor_map_data = bindings.anchor_map_data
    expert_advice_str = bindings.expert_advice_str
    file_index = bindings.file_index
    # Step 12 / PR-12d (F-12d-5): this phase now reads the run's NAMING
    # authority, which is always present, rather than reaching through the
    # OPTIONAL deliverable spec for it. The spec itself has no consumer
    # here.
    run_deliverable_naming = bindings.run_deliverable_naming
    run_metric = bindings.run_metric
    run_secondary_metrics = bindings.run_secondary_metrics
    run_name = bindings.run_name
    run_profile = bindings.run_profile
    sandbox = bindings.sandbox
    workspace = bindings.workspace
    active_params = prepared.active_params
    eval_sample_set = prepared.eval_sample_set
    exp_id = prepared.exp_id
    hypothesis = prepared.hypothesis
    model_type = prepared.model_type
    record_params = prepared.record_params
    attempt_in_round = identity.attempt_in_round
    round_index = identity.round_index

    from nodes.ml_hyperparameter_tune_agent.gpu_execution import prepare_phase

    if (
        prepare_phase(bindings, prepared, identity, phase="inference")
        is PrephaseOutcome.TERMINAL_RESOURCE_REFUSAL
    ):
        return AttemptExecution.next_attempt()
    stage.name = "inference"
    print("[Step 2/3] Inference...")
    t0 = time.time()
    inf_status = _runtime._run_skill("inference_skill", sandbox, **active_params)
    inference_time = round(time.time() - t0, 1)
    _raise_if_wall_clock_timeout(inf_status, sandbox, run_name)
    _raise_if_evidence_channel_failure(inf_status, sandbox, run_name)
    if _handle_admission_refusal(
        inf_status,
        ordering=prepared.ordering,
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
        candidate_id=agent_input.candidate_id,
        experiment_arm=agent_input.experiment_arm,
        is_trial=prepared.plan.is_trial,
    ):
        return AttemptExecution.next_attempt()
    # Step 11 C2 (F-11-1) — same authority as the training branch.
    if _records.is_execution_failure(inf_status):
        # DataScope DS5 — non-retryable: terminate the run.
        if inf_status.get("error_type") == "scope_violation":
            _scope_violation_reason = inf_status.get("message", "scope violation in inference")
            return AttemptExecution.end_round(scope_violation_reason=_scope_violation_reason)
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
        _emit_attempt_record(
            sandbox,
            error_record,
            agent_input,
            status=inf_status,
            ordering=prepared.ordering,
            attempt_role=observed_attempt_role(prepared.plan.is_trial),
        )
        print(f"  Saved error record: {error_record['status']}")
        return AttemptExecution.next_attempt()

    stage.name = "scoring"
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
    metric_payload: dict[str, Any] | None = None
    # Step 10 / P2b — empty unless the primary scores AND the run declared
    # secondaries. Initialised here, beside `metric_payload`, so every exit
    # from the scoring block (including the two error paths below) carries
    # the honest empty state rather than an unbound name.
    secondary_results: list[MetricResult] = []
    secondary_refusals: list[NotScoreableResult] = []
    secondary_errors: dict[str, str] = {}
    # V8 hardening Domain 2a — wrap the entire scoring block.
    # Pre-V8, an exception in score_vector / denoising_score_skill
    # bubbled past the loop without writing a record, so the
    # tuner's iteration silently lost evidence (training
    # checkpoint preserved on disk but no entry in
    # memory_history). Now we catch, write an error_scoring
    # record (matches the error_training/inference pattern
    # above), and continue. See docs/V8_Gap_Report.md Domain 2a.
    _scoring_route = resolve_scoring_route(anchor_map_data, prepared.task_scopes)

    # F2 — these two resolvers are properties of the ROUND (its model, its
    # deliverable naming, its physical root), not of the scoring route, and
    # they are hoisted out of the anchor branch so the round-boundary
    # HealthGate evaluation below can be reached on EVERY route. Neither
    # construction performs I/O or depends on a score.
    #
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
        naming=run_deliverable_naming,
    ):
        return _build_denoised_filename(
            model_type=model_type,
            run_name=run_name,
            exp_id=exp_id,
            input_identity=fi,
            base_dir=base_dir,
            naming=naming,
        )

    # The RAW validation-file resolver, owned by the health boundary:
    # nothing on the scoring paths calls it, and it resolves lazily so a
    # run with no physical data root does not pay for a peek it never
    # asked for. Rationale in `round_health.build_target_path_fn`.
    _target_fn = build_target_path_fn(sandbox, run_profile)

    try:
        if _scoring_route is ScoringRoute.ANCHOR_NORMALIZED:
            # Anchor-normalized scoring (both trial and formal modes).
            # Trial: sparse SampleSet. Formal: full SampleSet (all 20 × 200).
            # Step 06 — PRODUCTION SCORING through the
            # metric handle: scoreability first, then the
            # frozen TIDMAD arithmetic. A refused
            # deliverable raises NotScoreableError into the
            # scoring `except` below, which is the
            # round-outcome path for every scoring failure.
            metric_result = sandbox.evaluate_metric(
                run_metric,
                sample_set=eval_sample_set,
                anchor_map=anchor_map_data["anchors"],
                s_max=anchor_map_data["s_max"],
                denoised_filename_fn=_denoised_fn,
            )
            # `per_sample` is Optional on the generic result: a
            # scalar-only metric carries NONE, and the Pets
            # AccuracyMetric says so in as many words. The
            # record's `file_vector` still wants a list, so the
            # list is still built — but the STATEMENT is carried
            # separately rather than collapsed into it (D18,
            # Step 08b C6). Collapsing the two made a scalar-only
            # task present per-file checks with `[]`, which reads
            # as "no files" and PASSES: "this question does not
            # arise here" recorded as health.
            per_sample = metric_result.per_sample
            file_vector, final_scalar = (
                list(per_sample or []),
                metric_result.scalar,
            )
            per_sample_evidence = PerSampleEvidence.for_per_sample(per_sample)
            # Step 06 C4 — the record-facing payload. Kept
            # OUT of `score_res["results"]` on purpose: that
            # dict is json-dumped verbatim into the reflector
            # prompt (agent/prompts.py:1343) and Step 06
            # changes no prompt (design §8, §13). The planner's
            # history serialization likewise drops it
            # (`agent/prompts.py::_PLANNER_HIDDEN_RECORD_KEYS`)
            # — persisted for Steps 07a/09, not agent-facing.
            # Per-sample evidence is a POINTER — `file_vector`
            # on the same record — not a second copy (§5).
            metric_payload = metric_result.model_dump(mode="json", exclude={"per_sample"})

            # Step 10 / P2b — the DECLARED observational secondaries,
            # evaluated wherever the primary evaluates (Q-P2b-1). This
            # block runs for BOTH trial and formal modes, so no
            # round-type branch is added here or anywhere else. It sits
            # after the primary result on purpose: an attempt that never
            # produced one carries no secondary entries at all.
            (
                secondary_results,
                secondary_refusals,
                secondary_errors,
            ) = _evaluate_secondary_metrics(
                sandbox,
                run_secondary_metrics,
                sample_set=eval_sample_set,
                anchor_map=anchor_map_data["anchors"],
                s_max=anchor_map_data["s_max"],
                denoised_filename_fn=_denoised_fn,
            )

            # F2 — the gate evaluation that used to sit HERE now runs once
            # at the round boundary below, for every scoring route. It was
            # never anchor-specific: it reads the round's deliverable, not
            # the way that deliverable was scored.
            score_res = {
                "status": "success",
                "results": {
                    "denoising_score": final_scalar,
                    "file_vector": file_vector,
                },
            }
        else:
            # The scoring SUBPROCESS, serving two routes that differ only
            # in what the child is handed:
            #
            # * `TASK_OWNED` — a composed task's own deliverable, scored
            #   through its own metric against the evaluation scope
            #   transported alongside it. Every composed contrast run
            #   takes this route, because no contrast implementation
            #   declares trial anchoring.
            # * `SUBPROCESS_LEGACY` — TIDMAD without anchor normalization.
            #   NOT "legacy single-file mode": `anchor_map_data` is only
            #   ATTEMPTED for a trial round, so this branch is also where
            #   every un-composed FORMAL round has always gone. The old
            #   comment named a condition the code never tested.
            score_res = _runtime._run_skill("denoising_score_skill", sandbox, **active_params)
            _require_successful_scoring_result(score_res)
            # F2 — carry the same three round facts the anchor route
            # produces in-process, so the round-boundary gate evaluation
            # below is genuinely route-independent rather than an anchor
            # branch with a second entrance.
            #
            # `per_sample_evidence` is TRANSPORTED, never inferred. The
            # child sets `file_vector` from `MetricResult.per_sample`,
            # which is `None` exactly when the metric declares no
            # per-sample concept — so D18's mapping applies verbatim. A
            # payload that omits the key entirely has stated NOTHING, and
            # absence must not be read as `scalar_only`: that is the
            # distinction `PerSampleEvidence.UNDECLARED` exists to keep.
            _child_results = score_res.get("results", {}) or {}
            final_scalar = _child_results.get("denoising_score")
            file_vector = list(_child_results.get("file_vector") or [])
            per_sample_evidence = (
                PerSampleEvidence.for_per_sample(_child_results.get("file_vector"))
                if "file_vector" in _child_results
                else PerSampleEvidence.UNDECLARED
            )
    except ScopeViolationError as e:
        # DataScope DS5 — non-retryable: terminate the run
        # (must precede the generic handler below, which
        # would otherwise convert this into a retried
        # error_scoring record).
        _scope_violation_reason = f"error_scope_violation: {e}"
        return AttemptExecution.end_round(scope_violation_reason=_scope_violation_reason)
    except Exception as e:
        from core.local_code.failure import raise_if_code_package_failure

        raise_if_code_package_failure(e)
        scoring_time = round(time.time() - t0, 1)
        probe_memory(
            iter_idx=round_index,
            phase="post_score",
            workspace=workspace,
            scope="tuner",
        )
        error_record = _build_scoring_failure_record(
            e,
            exp_id=exp_id,
            model_type=model_type,
            file_index=file_index,
            record_params=record_params,
            timing={
                "train_time_s": train_time,
                "inference_time_s": inference_time,
                "scoring_time_s": scoring_time,
            },
            expert_advice_str=expert_advice_str,
            hypothesis=hypothesis,
            round_index=round_index,
            attempt_in_round=attempt_in_round,
        )
        _emit_attempt_record(
            sandbox,
            error_record,
            agent_input,
            ordering=prepared.ordering,
            attempt_role=observed_attempt_role(prepared.plan.is_trial),
        )
        print(f"  Saved error record: {error_record['status']}")
        return AttemptExecution.next_attempt()
    scoring_time = round(time.time() - t0, 1)
    probe_memory(
        iter_idx=round_index,
        phase="post_score",
        workspace=workspace,
        scope="tuner",
    )

    # F2 — HealthGates fire at the ROUND boundary, on every scoring route.
    #
    # Placed after the scoring try/except on purpose: reaching this line
    # means scoring SUCCEEDED for whichever route ran, so both routes
    # arrive carrying the same round facts. A scoring failure still takes
    # the `error_scoring` path above and never reaches a gate — a gate that
    # could not be evaluated is not a gate that passed.
    #
    # Evaluate, merge score-validity and stamp the verdict are one
    # responsibility and therefore one call; the boundary owns them, this
    # function keeps sequencing. Full rationale, and the deliberately
    # unpersisted `evaluated` residual, in `round_health`.
    apply_round_health(
        score_res,
        merge_score_validity=_merge_score_validity_failure,
        enabled=agent_input.health_gate_enabled,
        round_index=round_index,
        config_path=agent_input.health_checks_config,
        production_config_path=default_health_policy_path(),
        task_health_binding=(
            agent_input.task_composition_ref.task_health_binding
            if agent_input.task_composition_ref is not None
            else None
        ),
        healthgate_mode=agent_input.healthgate_mode,
        result_authority=agent_input.result_authority,
        model_name=model_type,
        run_name=run_name,
        exp_id=exp_id,
        models_dir=(
            sandbox.dirs.get("models") if isinstance(getattr(sandbox, "dirs", None), dict) else None
        ),
        denoised_filename_fn=_denoised_fn,
        evaluation_payload_fn=build_evaluation_payload_fn(
            task_data_path=bindings.run_task_data_path,
            deliverable_dir=sandbox.base_dir,
            exp_id=exp_id,
            run_name=run_name,
            model_type=model_type,
        ),
        target_path_fn=_target_fn,
        file_vector=file_vector,
        denoising_score=final_scalar,
        per_sample_evidence=per_sample_evidence,
        gate_results_to_score_meta=_gate_results_to_score_meta,
    )

    return EvaluationPhaseEvidence(
        inf_status=inf_status,
        inference_time=inference_time,
        scoring_time=scoring_time,
        score_res=score_res,
        metric_payload=metric_payload,
        secondary_results=secondary_results,
        secondary_refusals=secondary_refusals,
        secondary_errors=secondary_errors,
    )


def _run_evaluation_phase(
    bindings: RunBindings,
    prepared: PreparedAttempt,
    identity: AttemptIdentity,
    stage: AttemptStage,
    *,
    train_time: Any,
) -> EvaluationPhaseEvidence | AttemptExecution:
    """Select an explicit deployment executor, otherwise the unchanged native path."""
    executor = candidate_evaluation_executor()
    if executor is None:
        return _run_local_evaluation_phase(
            bindings, prepared, identity, stage, train_time=train_time
        )
    started = time.perf_counter()
    try:
        return run_external_evaluation(executor, bindings, prepared, stage)
    except CandidateEvaluationRefused as exc:
        record = _build_scoring_failure_record(
            exc,
            exp_id=prepared.exp_id,
            model_type=prepared.model_type,
            file_index=bindings.file_index,
            record_params=prepared.record_params,
            timing={
                "train_time_s": train_time,
                "inference_time_s": 0.0,
                "scoring_time_s": time.perf_counter() - started,
            },
            expert_advice_str=bindings.expert_advice_str,
            hypothesis=prepared.hypothesis,
            round_index=identity.round_index,
            attempt_in_round=identity.attempt_in_round,
        )
        record["external_evaluation"] = exc.evaluation.model_dump(mode="json")
        _emit_attempt_record(
            bindings.sandbox,
            record,
            bindings.agent_input,
            ordering=prepared.ordering,
            attempt_role=observed_attempt_role(prepared.plan.is_trial),
        )
        return AttemptExecution.next_attempt()


def run_inference_scoring_health(
    bindings: RunBindings,
    prepared: PreparedAttempt,
    identity: AttemptIdentity,
    stage: AttemptStage,
    *,
    train_time: Any,
    training_results: Any,
) -> AttemptExecution:
    """Phase 3 of 3. Body moved verbatim; see the module docstring."""
    agent_input = bindings.agent_input
    reference_scores = bindings.reference_scores
    # Step 12 / PR-12d (F-12d-5): this phase now reads the run's NAMING
    # authority, which is always present, rather than reaching through the
    # OPTIONAL deliverable spec for it. The spec itself has no consumer
    # here.
    run_deliverable_naming = bindings.run_deliverable_naming
    run_name = bindings.run_name
    sandbox = bindings.sandbox
    workspace = bindings.workspace
    exp_id = prepared.exp_id
    model_type = prepared.model_type
    plan = prepared.plan
    attempt_in_round = identity.attempt_in_round
    round_index = identity.round_index

    try:
        evaluated = _run_evaluation_phase(
            bindings, prepared, identity, stage, train_time=train_time
        )
        if isinstance(evaluated, AttemptExecution):
            return evaluated
        inf_status = evaluated.inf_status
        inference_time = evaluated.inference_time
        scoring_time = evaluated.scoring_time
        score_res = evaluated.score_res
        metric_payload = evaluated.metric_payload
        secondary_results = evaluated.secondary_results
        secondary_refusals = evaluated.secondary_refusals
        secondary_errors = evaluated.secondary_errors

        # Extract results from each stage. Step 07a: the LEGACY
        # payload (exactly final_loss / loss_history / model_params
        # as present) — the additive training_history never enters
        # the reflect merge; the diagnosis is derived ONCE here.
        train_results = training_results.legacy_payload
        training_diagnosis = derive_training_diagnosis(training_results.history)
        score_results = score_res.get("results", {})

        # Step 12 / PR-12d: the DECLARED secondaries, when the SCORING CHILD
        # evaluated them.
        #
        # On the anchor-normalized route the tuner evaluates secondaries
        # in-process (`_evaluate_secondary_metrics`, above). On the task-owned
        # route it cannot: the deliverable is read by the child, so the child
        # is the only party holding the evaluation payload and the scope — and
        # it is the child that computes them and reports them here.
        #
        # The ADOPTION DECISION lives in the helper, not here: this phase is
        # already a 26-branch orchestrator and §E.2's budget is zero net
        # branch growth achieved by EXTRACTION rather than restraint. The
        # helper is a total function — it returns what the anchor route
        # already produced whenever that is non-empty — so the call site
        # gains no branch and cannot express the wrong precedence.
        secondary_results, secondary_refusals, secondary_errors = _adopt_child_secondaries(
            score_results,
            results=secondary_results,
            refusals=secondary_refusals,
            errors=secondary_errors,
        )
        # F-12d-32 — the PRIMARY's identity, by the same rule and for the same
        # reason as its secondaries one line above. `metric_payload` is only
        # assigned inside the ANCHOR_NORMALIZED branch, so a task-owned round
        # persisted `metric_result: null` beside a valid score. Total function,
        # anchor value wins, no branch at the call site.
        metric_payload = _adopt_child_metric_result(score_results, current=metric_payload)

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
        # Step 10 / P5+P6 W4 — `reference_scores is None` is the COMPOSED run's
        # named absence (C-P56-1), not a failure. Skipping explicitly keeps the
        # `except` below for real build errors instead of logging one every
        # round for a state that is by design.
        if (
            reference_scores is not None
            and _sc_fv is not None
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
        # This runs after inference, scoring, and every reached Health check.
        # The task names exact outputs; a missing inventory fails closed.
        finalize_attempt_outputs(
            task_data_path=bindings.run_task_data_path,
            legacy_naming=run_deliverable_naming,
            deliverable_dir=sandbox.base_dir,
            workspace=workspace,
            run_name=run_name,
            exp_id=str(exp_id),
            model_type=str(model_type),
            retain_model_outputs=agent_input.retain_model_outputs,
        )

    return AttemptExecution(
        failure_reason=failure_reason,
        inf_status=inf_status,
        inference_time=inference_time,
        is_degenerate=is_degenerate,
        metric_payload=metric_payload,
        secondary_metric_results=secondary_results,
        secondary_metric_refusals=secondary_refusals,
        secondary_metric_errors=secondary_errors,
        score_results=score_results,
        score_table=score_table,
        scoring_time=scoring_time,
        train_results=train_results,
        training_diagnosis=training_diagnosis,
        external_evaluation=evaluated.external_evaluation,
    )
