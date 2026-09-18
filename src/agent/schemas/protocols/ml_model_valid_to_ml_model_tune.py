# agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py
"""
Protocol: ml-model-valid -> ml-model-tune
(ml_code_validator_agent -> tune_ml_hyperparam_agent)

Functions:
  local_validated_model  — passes the validated model_type in-memory to HyperparamTuningInput
  database_validated_model — DB-backed transfer (NotImplementedError placeholder)

Naming convention:
  transport: local | database
  data_scope: validated_model — the confirmed model type, ready for tuning

Note: this protocol should only be called when ValidatorOutput.passed is True.
The workflow is responsible for checking passed before traversing this edge.

Fan-in protocol: consumes ValidatorOutput (adjacent node) and ProposalOutput
(non-adjacent, held by the workflow). The validator confirms the model is valid;
the proposal provides expert_advice and baseline_config for the tuning agent.
"""

from typing import Any, Literal

from agent.schemas.hyperparam_tuning import (
    HealthGateMode,
    HyperparamTuningInput,
    ResultAuthority,
    TaskCompositionRef,
    TimeAdmissionSource,
    serialize_expert_advice,
)
from agent.schemas.ordering import OrderStrategy
from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.proposal import ProposalOutput
from agent.schemas.storage import StorageConfig
from agent.schemas.validator import ValidatorOutput
from core.runtime_control.admission import AdmissionEnforcement
from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
from execute_tools.dataset_config import DataScope


def local_validated_model(
    output: ValidatorOutput,
    proposal: ProposalOutput,
    storage: StorageConfig,
    max_rounds: int = 50,
    health_checks_config: str | None = None,
    measurement_capability: ResolvedMeasurementCapability | None = None,
    # Step 12 / PR-12a (D-12a-1) — the run's task-composition PROJECTION.
    # Additive and default-None: an un-composed run passes nothing and the
    # tuner sees `None`, which is regime A byte-for-byte.
    task_composition_ref: TaskCompositionRef | None = None,
    # --- DataScope + HealthGate subsystem (DS6b) — defaults preserve
    #     full-scope, gates-enabled behavior ---
    data_scope: DataScope | None = None,
    health_gate_enabled: bool = True,
    health_gate_files: list[int] | None = None,
    # V21 PR D — the DECLARED scientific posture. `None` is a meaningful
    # value, not a missing one: it means the caller declared nothing, and
    # the authority rule reports that as `legacy_authority_unknown`. There
    # is deliberately no default here — a default would turn a launcher's
    # silence into a declaration it never made (design §0.E).
    healthgate_mode: HealthGateMode | None = None,
    result_authority: ResultAuthority | None = None,
    file_index: int = 6,
    llm_provider: Literal["gemini", "openai", "deepseek"] = "gemini",
    llm_model_id: str = "gemini-3.1-flash-lite-preview",
    reasoning_effort: str | None = None,
    reflect_provider: Literal["gemini", "openai", "deepseek"] | None = None,
    reflect_model_id: str | None = None,
    reflect_reasoning_effort: str | None = None,
    # --- Trial mode (optional — all defaults preserve normal single-file behavior) ---
    # DS7 — trial_strategy / target_files / eval_strategy params deleted
    # alongside the dead HyperparamTuningInput fields they fed.
    is_trial: bool = False,
    trial_portion: float = 0.1,
    train_portion: float = 0.1,
    eval_portion: float = 0.1,
    train_validation_align: bool = True,
    sampling_seed: int | None = None,
    train_base_seed: int | None = None,
    cleanup_denoised: bool = False,
    retain_model_outputs: bool = False,
    retain_training_checkpoints: bool = False,
    max_epochs: int | None = None,
    # D-BUD-6 — per-mode epoch ceilings (trial/formal split). None = the
    # mode-agnostic max_epochs governs that role (legacy behavior).
    trial_max_epochs: int | None = None,
    formal_max_epochs: int | None = None,
    # VALIDATION POSTURE ONLY (FU-D-12) — hard ceiling on the resolved
    # portions, for EVERY round mode. `None` leaves ordinary campaigns
    # unchanged.
    validation_max_portion: float | None = None,
    # VALIDATION POSTURE ONLY — the Gate workload envelope and its
    # emergency wall-clock fuse. Both `None` in every campaign; see the
    # HyperparamTuningInput field docstrings and
    # docs/gates/gate_testing_standard.md.
    validation_max_train_samples: int | None = None,
    validation_max_samples: int | None = None,
    validation_max_phase_seconds: float | None = None,
    # Tuner delta-gates (added in commit 8f1cf52). Defaults match the
    # HyperparamTuningInput schema defaults so omitting them at the
    # CLI surface reproduces pre-v16 behaviour.
    skip_formal_min_delta: float = -1.0,
    bypass_formal_time_budget_min_delta: float = 0.0,
    # Lane F3 — the elevated bypass ceiling; None = no extension (schema
    # default's safety semantics travel through unchanged).
    bypass_formal_time_budget_minutes: float | None = None,
    # V19 PR 1 (P1-C3) — chain formal-incumbent reference as a NAMED
    # protocol parameter (design §3.4; replaces the workflow's post-hoc
    # mutation of the constructed input). ``None`` = no incumbent (both
    # delta gates short-circuit). ``enable_chain_incumbent_formal_gates``
    # controls only whether the gates CONSUME the reference —
    # reconstruction/provenance upstream are unconditional. Default OFF.
    current_run_best_formal_score: float | None = None,
    enable_chain_incumbent_formal_gates: bool = False,
    # V19 PR 2 — operator data-ordering OVERRIDE, threaded as named
    # protocol parameters (same discipline as the incumbent reference
    # above). The workflow supplies the operator's chain-level control;
    # the tuner resolves it against each round's agent proposal. ``None``
    # = no override, so the agent's proposal decides and the default
    # ('shuffle') applies when it proposes nothing.
    order_strategy_override: OrderStrategy | None = None,
    file_order_override: list[int] | None = None,
    # V19 PR 3 — structured-health-feedback POLICY pass-through. The tuner
    # has no PR 3 behavior; it locks the policy into run_invariants and
    # stamps run_config. Must match what the workflow locks for this
    # workspace or the two would write contradictory locks (the PR 2
    # lock-collision lesson).
    enable_structured_health_feedback: bool = False,
    health_feedback_history_window_iterations: int = 3,
    health_feedback_history_max_entries_per_model: int = 8,
    # arXiv U1 (#253 / #254) — run-identity pass-through, same contract as
    # the PR 3 block above: the tuner locks + stamps, never consumes. Must
    # match what the workflow locked for this workspace.
    experiment_arm: str | None = None,
    lit_review_enabled: bool = False,
    data_analysis_enabled: bool | None = None,
    lit_review_config_sha256: str | None = None,
    scientific_evidence_order: Literal[
        "analysis_then_literature", "literature_then_analysis"
    ] = "analysis_then_literature",
    baseline_isolation: bool = False,
    max_retries: int | None = None,
    plan_overrides: dict[str, Any] | None = None,
    workflow_parameter_rules: ParameterRules | None = None,
    # --- Time-budget gate (evaluate_time_skill, Phase I two-budget split) ---
    trial_time_budget_minutes: float | None = None,
    formal_time_budget_minutes: float | None = None,
    trial_time_admission_source: TimeAdmissionSource = "measured",
    formal_time_admission_source: TimeAdmissionSource = "measured",
    data_dir: str | None = None,
    # --- VRAM-budget gate (evaluate_vram_skill, Phase K two-budget split) ---
    gpu_admission_measurement_source: str | None = None,
    gpu_admission_enforcement: AdmissionEnforcement = "observe_only",
    gpu_pair_ceiling_gib: float | None = None,
    trial_vram_budget_gb: float | None = None,
    formal_vram_budget_gb: float | None = None,
    vram_probe_step_timeout_seconds: float = 180.0,
    vram_preflight_total_timeout_seconds: float = 900.0,
    vram_preflight_host_memory_limit_gb: float | None = None,
    # --- Formal-mode training levers (Phase M) + eval-scope (Phase R) ---
    formal_strategy: Literal["snapshot", "anchors", "target"] = "snapshot",
    formal_training_scope_source: Literal["operator", "agent"] = "operator",
    formal_portion: float = 0.1,
    formal_train_portion: float = 1.0,
    formal_eval_portion: float = 1.0,
    force_formal_round: bool = True,
    formal_round_strategy: Literal[
        "full_clone",
        "hybrid_params",
        "independent",
        "inherit_best_trial",  # legacy alias of full_clone
        "llm_propose",  # legacy alias of independent
    ] = "full_clone",
    # --- Degenerate-output reaction (paired with tuner-side HealthGate evaluation) ---
    degenerate_penalty_score: float | None = None,
    # --- Per-round attempt budget (Phase L, §11) ---
    # Tuner-only fan-out; no proposer-side equivalent. Defaults mirror the
    # schema defaults so omitting them at the workflow/CLI surface yields
    # the documented Phase L behaviour. See §11.5.
    attempts_per_round: int = 3,
    attempts_per_formal_round: int = 5,
    max_fail_rounds: int = 3,
    # --- Runtime-control operator surface (RT5/RT6, runtime design §4/§5) ---
    # Defaults mirror the schema (guardrails disabled, watchdog off); the
    # chain/CLI layers supply the §5 provisional operational values.
    max_steps_per_attempt: int | None = None,
    min_formal_batch_size: int | None = None,
    allow_extreme_steps: bool = False,
    runtime_watchdog_enabled: bool = False,
    runtime_safety_factor: float = 1.0,
    runtime_trial_safety_factor: float | None = None,
    runtime_formal_safety_factor: float | None = None,
    runtime_watchdog_safety_factor: float | None = None,
    runtime_watchdog_floor_seconds: float = 60.0,
    runtime_verification_max_wall_seconds: float | None = None,
) -> HyperparamTuningInput:
    """
    Map ValidatorOutput + ProposalOutput -> HyperparamTuningInput in-memory.

    Consumes from ml-model-valid (ValidatorOutput):
      - model_type: the validated plugin key
      - spec_deviation_notes / inheritance_deviation_notes: prepended to
        expert_advice as planner-visible warnings.

    Consumes from ml-model-propose (ProposalOutput, held by workflow):
      - expert_advice  : structured guidance for the tuning agent
      - baseline_config: safe starting configuration for the new model

    Populates in ml-model-tune (HyperparamTuningInput):
      - model_type    : from ValidatorOutput
      - expert_advice : from ProposalOutput, with deviation notes prepended
                        in the order spec → inheritance.
      - storage       : passed through from the workflow
      - max_rounds    : tuning budget (caller-supplied, default 50)
      - health_checks_config : optional HealthGate YAML override; None keeps
        the tuner's shipped default.
      - data_scope / health_gate_enabled / health_gate_files : DataScope +
        HealthGate subsystem inputs (DS6b). ``data_scope=None`` normalizes
        to the explicit full scope; the tuner's startup
        ``validate_runtime_config`` + run-invariants lock enforce the rest.
        See docs/design/enable_partial_file_list.md.
      - file_index    : data split index (caller-supplied, default 6; ignored when is_trial=True)
      - llm_provider  : planner-call provider (caller-supplied, default gemini)
      - llm_model_id  : planner-call model ID (caller-supplied)
      - reflect_provider : optional separate provider for the tuner's
        reflect() call. None means the reflector uses llm_provider.
      - reflect_model_id : optional separate model for the tuner's
        reflect() call. None means the reflector uses llm_model_id.
      - is_trial + trial_*: trial mode configuration (caller-supplied, defaults to single-file)
      - trial_time_budget_minutes / formal_time_budget_minutes / data_dir :
        workflow-supplied run-level context for the tuner's per-round
        evaluate_time_skill gate (Phase I two-budget split). Each budget
        defaults to None; the per-round gate picks the one matching
        plan.is_trial. When the chosen budget is None the gate is skipped
        for that round (one-time warning per mode at startup).
        See §2.7.2 fan-in / Phase I.
      - gpu_admission_measurement_source / gpu_pair_ceiling_gib :
          V20 B-G3 admission configuration. The source is a
          REFERENCE, never a figure; the ceiling is the aggregate
          GPU cap. Both default to None, which is exactly the
          pre-B-G3 behaviour.
      - trial_vram_budget_gb / formal_vram_budget_gb :
        workflow-supplied per-mode VRAM ceilings for the tuner's per-round
        evaluate_vram_skill gate (Phase K two-budget split). Each budget
        defaults to None; the per-round gate picks the one matching
        plan.is_trial. When the chosen budget is None the skill still runs
        but falls back to the defensive free×0.8 behaviour (no operator
        ceiling). **No `proposal.vram_risk` surfacing in Phase K** — the
        proposer-side gate is deferred per §10.17. Resource info reaches
        the planner via the prompt block only (single-channel rule, §10.3).
        See docs/resource_estimator_implement.md §10.9.
      - vram_probe_step_timeout_seconds / vram_preflight_total_timeout_seconds /
        vram_preflight_host_memory_limit_gb : workflow-owned safeguards for one
        footprint forward, the complete isolated preflight, and its process-tree
        resident host memory, respectively. They do not change training epochs,
        optimizer steps, Trial/Formal runtime budgets, or the GPU VRAM ceiling.
      - formal_strategy / formal_portion / formal_train_portion :
        operator-configurable training-side sample-set knobs for any round
        promoted to formal (Phase M). Defaults snapshot / 0.1 / 1.0.
        See docs/resource_estimator_implement.md §12.
      - formal_training_scope_source : ownership of Formal training-side
        strategy and portions. ``operator`` preserves the historical
        operator-owned behavior; ``agent`` lets the validated plan choose
        those training fields while Formal evaluation remains operator-owned.
      - formal_eval_portion :
        Phase R (§13) — eval-side scope knob. Default 1.0 reproduces the
        legacy full-clone behaviour required for cross-architecture score
        comparability in production. Smoke / CI runs may lower this
        (e.g. 0.05) so the formal round fits inside a tight
        ``formal_time_budget_minutes`` without miscalibrating the
        physical estimator constants. Eval strategy stays locked to
        ``snapshot``.
      - degenerate_penalty_score :
        Operator policy for the agent's reaction when tuner-side gate
        evaluation produces a non-``CONTINUE`` ``GateAction``
        (``INVALIDATE_ROUND``; the skip actions were retired, F-SCANC-1)
        on a formal round. ``None`` (default) nulls the ``denoising_score``
        so the round can never be picked as 'best'; a float value
        (typically large-negative) is used as the score so the planner
        can still rank-order the failure. In both cases the record is
        tagged ``status='failed_mode_collapse'`` with the gate's
        ``failure_reason`` (pipe-concatenated per gate_id) preserved
        verbatim. Trial rounds are immune per policy — the gate signal
        still propagates to the record's ``failure_reason`` and
        ``gate_action`` fields, but the trial score itself is preserved
        (see ``_apply_degeneracy_reaction``). Paired with the
        tuner-side HealthGate framework — see
        ``docs/design/pluggable_health_checks.md`` §4.
      - attempts_per_round / attempts_per_formal_round / max_fail_rounds :
        Phase L per-round attempt budget + consecutive-failure brake
        (defaults 3 / 5 / 3). Trial rounds get ``attempts_per_round`` inner
        attempts; the formal-promotion round (the last successful round)
        gets ``attempts_per_formal_round`` because formal is the only
        cross-architecture comparable measurement. The outer loop aborts
        with ``termination_reason='aborted_fail_rounds'`` after
        ``max_fail_rounds`` consecutive rounds exhaust their inner
        budget. See docs/resource_estimator_implement.md §11.
    """
    # Prepend planner-visible warnings to expert_advice so the tuner's planner
    # knows up front about (a) implementation deviating from the spec and
    # (b) unverified inherited components. Order is intentional: spec deviation
    # is the strongest signal about architectural fidelity; inheritance deviation
    # is weaker.
    expert_advice = proposal.expert_advice
    deviation_notes = [
        n
        for n in (
            output.spec_deviation_notes,
            output.inheritance_deviation_notes,
        )
        if n
    ]
    if deviation_notes:
        base = serialize_expert_advice(expert_advice) if expert_advice else ""
        prefix = "\n\n".join(deviation_notes)
        expert_advice = f"{prefix}\n\n{base}" if base else prefix

    return HyperparamTuningInput(
        model_type=output.model_type,
        file_index=file_index,
        max_rounds=max_rounds,
        health_checks_config=health_checks_config,
        measurement_capability=measurement_capability,
        # Step 12 / PR-12a — mapped straight through. This protocol is the
        # field-mapping layer, so the projection crosses the edge here rather
        # than the tuner rediscovering it from the ambient environment.
        task_composition_ref=task_composition_ref,
        workflow_parameter_rules=workflow_parameter_rules,
        # DS6b — None normalizes to the full scope here (not in the schema)
        # so the input always carries an explicit DataScope object.
        data_scope=data_scope if data_scope is not None else DataScope.default(),
        health_gate_enabled=health_gate_enabled,
        health_gate_files=health_gate_files,
        # V21 PR D — carried through unchanged, including `None`.
        healthgate_mode=healthgate_mode,
        result_authority=result_authority,
        # V21 PR E hop 4: from the IMMEDIATE upstream (the validator's echo),
        # for the same end-to-end-visibility reason as the impl->valid hop.
        candidate_id=output.candidate_id,
        expert_advice=expert_advice,
        llm_provider=llm_provider,
        llm_model_id=llm_model_id,
        reasoning_effort=reasoning_effort,
        reflect_provider=reflect_provider,
        reflect_model_id=reflect_model_id,
        reflect_reasoning_effort=reflect_reasoning_effort,
        storage=storage,
        is_trial=is_trial,
        trial_portion=trial_portion,
        train_portion=train_portion,
        eval_portion=eval_portion,
        train_validation_align=train_validation_align,
        sampling_seed=sampling_seed,
        train_base_seed=train_base_seed,
        cleanup_denoised=cleanup_denoised,
        retain_model_outputs=retain_model_outputs,
        retain_training_checkpoints=retain_training_checkpoints,
        max_epochs=max_epochs,
        # D-BUD-6 — carried through unchanged, including `None`.
        trial_max_epochs=trial_max_epochs,
        formal_max_epochs=formal_max_epochs,
        validation_max_portion=validation_max_portion,
        validation_max_train_samples=validation_max_train_samples,
        validation_max_samples=validation_max_samples,
        validation_max_phase_seconds=validation_max_phase_seconds,
        skip_formal_min_delta=skip_formal_min_delta,
        bypass_formal_time_budget_min_delta=bypass_formal_time_budget_min_delta,
        bypass_formal_time_budget_minutes=bypass_formal_time_budget_minutes,
        current_run_best_formal_score=current_run_best_formal_score,
        enable_chain_incumbent_formal_gates=enable_chain_incumbent_formal_gates,
        order_strategy_override=order_strategy_override,
        file_order_override=file_order_override,
        enable_structured_health_feedback=enable_structured_health_feedback,
        health_feedback_history_window_iterations=(health_feedback_history_window_iterations),
        health_feedback_history_max_entries_per_model=(
            health_feedback_history_max_entries_per_model
        ),
        experiment_arm=experiment_arm,
        lit_review_enabled=lit_review_enabled,
        data_analysis_enabled=data_analysis_enabled,
        lit_review_config_sha256=lit_review_config_sha256,
        scientific_evidence_order=scientific_evidence_order,
        baseline_isolation=baseline_isolation,
        max_retries=max_retries,
        plan_overrides=plan_overrides or {},
        trial_time_budget_minutes=trial_time_budget_minutes,
        formal_time_budget_minutes=formal_time_budget_minutes,
        trial_time_admission_source=trial_time_admission_source,
        formal_time_admission_source=formal_time_admission_source,
        data_dir=data_dir,
        gpu_admission_measurement_source=gpu_admission_measurement_source,
        gpu_admission_enforcement=gpu_admission_enforcement,
        gpu_pair_ceiling_gib=gpu_pair_ceiling_gib,
        trial_vram_budget_gb=trial_vram_budget_gb,
        formal_vram_budget_gb=formal_vram_budget_gb,
        vram_probe_step_timeout_seconds=vram_probe_step_timeout_seconds,
        vram_preflight_total_timeout_seconds=vram_preflight_total_timeout_seconds,
        vram_preflight_host_memory_limit_gb=vram_preflight_host_memory_limit_gb,
        formal_strategy=formal_strategy,
        formal_training_scope_source=formal_training_scope_source,
        formal_portion=formal_portion,
        formal_train_portion=formal_train_portion,
        formal_eval_portion=formal_eval_portion,
        force_formal_round=force_formal_round,
        formal_round_strategy=formal_round_strategy,
        degenerate_penalty_score=degenerate_penalty_score,
        attempts_per_round=attempts_per_round,
        attempts_per_formal_round=attempts_per_formal_round,
        max_fail_rounds=max_fail_rounds,
        max_steps_per_attempt=max_steps_per_attempt,
        min_formal_batch_size=min_formal_batch_size,
        allow_extreme_steps=allow_extreme_steps,
        runtime_watchdog_enabled=runtime_watchdog_enabled,
        runtime_safety_factor=runtime_safety_factor,
        runtime_trial_safety_factor=runtime_trial_safety_factor,
        runtime_formal_safety_factor=runtime_formal_safety_factor,
        runtime_watchdog_safety_factor=runtime_watchdog_safety_factor,
        runtime_watchdog_floor_seconds=runtime_watchdog_floor_seconds,
        runtime_verification_max_wall_seconds=runtime_verification_max_wall_seconds,
    )


def database_validated_model(
    output: ValidatorOutput,
    storage: StorageConfig,
    **kwargs,
) -> HyperparamTuningInput:
    """
    DB-backed protocol — reads the validated model record from the database and
    returns a fully populated HyperparamTuningInput. Raises NotImplementedError
    until a Postgres StorageConfig backend is wired.
    """
    raise NotImplementedError(
        "database_validated_model is not yet implemented. "
        "Wire a Postgres StorageConfig backend first."
    )
