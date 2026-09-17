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

import gc
import json
import os
import time
import traceback
from contextlib import suppress
from importlib import import_module as _import_module
from pathlib import Path
from typing import Any

from agent.llm_bridge import LLMBridge
from agent.prompt_templates.tuner.rendering import (
    EFFICIENCY_BAND_FRACTION,
    build_tuner_task_render,
)
from agent.schemas.hyperparam_tuning import (
    ExperimentPlan,
    HyperparamTuningInput,
    HyperparamTuningOutput,
    PhysicalRejection,
    PlanOverridesError,
    serialize_expert_advice,
    validate_runtime_config,
)
from agent.schemas.task_config import ForwardContract
from core.hardware_context import get_or_create
from core.layout import checkout_root
from core.run_invariants import (
    LockLaunchIdentity,
    RunHealthMaterialization,
    build_run_invariants,
    load_run_invariants,
    validate_run_invariants,
)
from core.runtime_control.gpu_accounting import device_identity_from_hardware
from core.sandbox_executor import TidmadSandbox
from execute_tools.data_paths import active_physical_data_root
from execute_tools.dataset_config import (
    resolve_dataset_profile,
)
from execute_tools.deliverable_spec import (
    derive_run_deliverable_spec,
    indexed_cleanup_naming,
)
from execute_tools.evaluation_metric import (
    EvaluationMetric,
    resolve_bound_run_secondary_metrics,
    resolve_run_metric,
)
from execute_tools.health_checks.config import (
    HealthChecksConfig,
    load_composed_health_config,
    load_health_gates_config,
)
from execute_tools.metric_order import MetricOrder
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.scoring_helpers import build_score_table
from execute_tools.task_data_path import (
    LEGACY_TRIAL_ANCHOR_NAME,
    TaskDataPathResolutionError,
    declares_trial_anchoring,
    require_bound_task_data_path,
    resolve_bound_task_data_path,
)
from execute_tools.trial_anchor_map import load_anchor_map
from nodes.ml_hyperparameter_tune_agent.cli import (
    PARTIAL_CAMPAIGN_EXIT_CODE,
    build_agent_input,
    build_parser,
)
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AttemptIdentity,
    AttemptOrdering,
    AttemptSignal,
    AttemptStage,
    RunBindings,
    RunExitSnapshot,
)
from nodes.ml_hyperparameter_tune_agent.execution import (
    _emit_attempt_record,
    run_admission_preflight,
    run_inference_scoring_health,
    run_training,
)
from nodes.ml_hyperparameter_tune_agent.feedback import (
    _build_gate_exhaustion,
    _build_trial_validity_feedback,
    _collect_disallowed_patterns,
    _render_gate_exhaustion_summary,
    _render_gate_exhaustion_trigger_b_summary,
    invoke_reflection,
)
from nodes.ml_hyperparameter_tune_agent.loss_inventory import (
    resolve_run_custom_loss_inventory,
)
from nodes.ml_hyperparameter_tune_agent.planning import prepare_attempt

# --- Node-local submodules (Step 07 PR 07b, C7) ------------------------------
# The tuner node keeps ONE obvious entrypoint — this file — and delegates four
# coherent responsibilities to sibling modules. These imports are load-bearing
# beyond namespacing: the package's __init__ rebinds
# `nodes.ml_hyperparameter_tune_agent` to THIS module, so a submodule is only
# reachable once this file has imported it. Re-exporting the names here also
# keeps every existing importer and every `mock.patch("nodes.ml_hyperparameter_
# tune_agent.X")` working exactly as before the move.
from nodes.ml_hyperparameter_tune_agent.policy import (
    _FORMAL_STRATEGY_REGISTRY,
    _LEGACY_STRATEGY_ALIASES,
    BestTracks,
    RoundDecision,
    _apply_degeneracy_reaction,
    _apply_mode_override_chain,
    _apply_plan_overrides,
    _best_trial_winner,
    _build_reflection_context,
    _canonical_strategy,
    _compute_termination_state,
    _decide_round_outcome,
    _fmt_reference,
    _gate_results_to_score_meta,
    _identity,
    _json_safe_reference,
    _latest_trial_inference_marginal,
    _merge_score_validity_failure,
    _non_retryable_termination_message,
    _resolve_formal_comparison_thresholds,
    _resolve_sample_set_cfg,
    _score_of,
    _select_best_records,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
    _strategy_full_clone,
    _strategy_hybrid_params,
    _strategy_independent,
    _validate_data_config,
    _validate_penalty_for_direction,
)
from nodes.ml_hyperparameter_tune_agent.records import (
    _PHASE_FAILURE_TEXT,
    _STATUS_FOR_REASON,
    INFRASTRUCTURE_FAILURE_STATUS,
    LLM_PROVIDER_FAILURE_REASON,
    RESOURCE_ADMISSION_REASONS,
    RESOURCE_ADMISSION_STATUS,
    _attach_runtime_evidence,
    _attribution_reason,
    _build_denoised_filename,
    _build_execution_failure_record,
    _build_resource_admission_record,
    _build_scoring_failure_record,
    _build_skip_record,
    _copy_seed_plugin,
    _emit_record,
    _interpret_training_status,
    _is_cuda_oom,
    _may_advise_resource_reduction,
    _oom_memory_wording,
    _resume_progress,
    _validate_history_and_lock,
    build_attempt_record,
    classify_attempt_failure_disposition,
    finalize_run_output,
)
from nodes.ml_hyperparameter_tune_agent.runtime import (
    _BLOCKED_KIND_FOR_STATUS,
    _PREPHASE_REASON_CODE,
    PREFLIGHT_CONSUMER_ACTIONS,
    PREPHASE_MEASUREMENT_DEADLINE_SECONDS,
    PREPHASE_MEASUREMENT_SOFT_BUDGET_SECONDS,
    PrephaseOutcome,
    RuntimeEvidenceChannelError,
    WallClockTimeoutError,
    _append_runtime_observation,
    _apply_epoch_bound,
    _apply_watchdog_failure_fields,
    _attach_realized_memory,
    _build_admission_policy,
    _build_guardrail_rejection_record,
    _build_in_subprocess_rejection_record,
    _build_runtime_policy,
    _check_and_record_guardrail_skip,
    _classify_attempt_failure,
    _derive_calibration_from_observation,
    _evaluate_step_guardrails,
    _handle_admission_refusal,
    _handle_in_subprocess_rejection,
    _handle_prephase_gpu_measurement,
    _prephase_device_snapshot,
    _prephase_worker_memory_limit_bytes,
    _raise_if_evidence_channel_failure,
    _raise_if_inconclusive,
    _raise_if_preflight_blocks,
    _raise_if_wall_clock_timeout,
    _resolve_effective_epochs,
    _resolve_guardrail_steps,
    _resolve_time_check_probe_request,
    _run_skill,
    _run_time_preflight,
    _runtime_phase_for,
    _time_skip_memory_extra,
    _vram_skip_memory_extra,
    is_evidence_refusal,
)
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import (
    project_attempt_topology_facts,
)
from workflows.task_config import load_task_config, run_bound_model_io_contract


def load_reference_scores() -> object | None:
    """Return no evidence when a caller has declared no reference source.

    Kept as the narrow dependency seam used by isolated node tests. Production
    never resolves a task-specific path or dataset through this function.
    """
    return None


# `_emit_record` is the node's ONE record-emission point, called from four
# modules. Same reasoning as `_runtime._run_skill`: resolve it through its
# owner so the node has a single binding, and a stub installed on that owner
# intercepts every emission rather than whichever module it was aimed at.
_records = _import_module("nodes.ml_hyperparameter_tune_agent.records")
# `_run_skill` is the node's ONE entry to its tools, and it is called from
# three modules. Calling it through its owning module keeps a single binding:
# whatever `runtime._run_skill` is at call time is what every phase runs. A
# per-module `from ... import _run_skill` would give each module its own
# snapshot, so a stub installed for one would silently miss the others.
_runtime = _import_module("nodes.ml_hyperparameter_tune_agent.runtime")

# --- The node's PUBLIC interface ---------------------------------------------
# `<node>.py` + `<node>.md` are the only stable surface this node offers.
# Everything else in this package is implementation detail (architecture rule,
# operator 2026-08-16; enforced by tests/unit/nodes/test_node_public_boundary.py).
__all__ = [
    "INFRASTRUCTURE_FAILURE_STATUS",
    # F-SCANF-2 — the LLM/provider infrastructure reason, public beside the
    # status vocabulary it resolves through.
    "LLM_PROVIDER_FAILURE_REASON",
    "PARTIAL_CAMPAIGN_EXIT_CODE",
    "PREFLIGHT_CONSUMER_ACTIONS",
    "PREPHASE_MEASUREMENT_DEADLINE_SECONDS",
    "PREPHASE_MEASUREMENT_SOFT_BUDGET_SECONDS",
    "RESOURCE_ADMISSION_REASONS",
    "RESOURCE_ADMISSION_STATUS",
    "BestTracks",
    "HyperparamTuningAgent",
    "PrephaseOutcome",
    "RoundDecision",
    "RuntimeEvidenceChannelError",
    "WallClockTimeoutError",
    "build_agent_input",
    "build_parser",
    "is_evidence_refusal",
    "main",
]

#: COMPATIBILITY ONLY — not part of the node's contract.
#:
#: C7 moved these private helpers into the node-local submodules. They are
#: re-exported here because the package `__init__` and a large body of tests
#: reach them at this path, and because `mock.patch("nodes.ml_hyperparameter_
#: tune_agent.X")` must keep resolving to the object production actually calls.
#:
#: They are NOT documented in ml_hyperparameter_tune_agent.md, they are NOT a
#: promise to callers, and NO new production consumer may be added: import the
#: owning submodule from inside the node instead. The list is expected to
#: shrink, never grow.
#:
#: Listing them here also KEEPS them alive: without a reference the linter
#: prunes the re-export and the package `__init__` fails at import.
_COMPATIBILITY_REEXPORTS = (
    _emit_record,
    _run_skill,
    build_sample_set,
    build_score_table,
    _BLOCKED_KIND_FOR_STATUS,
    _FORMAL_STRATEGY_REGISTRY,
    _LEGACY_STRATEGY_ALIASES,
    _PHASE_FAILURE_TEXT,
    _PREPHASE_REASON_CODE,
    _STATUS_FOR_REASON,
    _append_runtime_observation,
    _apply_degeneracy_reaction,
    _apply_epoch_bound,
    _apply_mode_override_chain,
    _apply_plan_overrides,
    _apply_watchdog_failure_fields,
    _attach_realized_memory,
    _attach_runtime_evidence,
    _attribution_reason,
    _best_trial_winner,
    _build_admission_policy,
    _build_denoised_filename,
    _build_execution_failure_record,
    _build_gate_exhaustion,
    _build_guardrail_rejection_record,
    _build_in_subprocess_rejection_record,
    _build_reflection_context,
    _build_resource_admission_record,
    _build_runtime_policy,
    _build_scoring_failure_record,
    _build_skip_record,
    _build_trial_validity_feedback,
    _canonical_strategy,
    _check_and_record_guardrail_skip,
    _classify_attempt_failure,
    _collect_disallowed_patterns,
    _compute_termination_state,
    _copy_seed_plugin,
    _decide_round_outcome,
    _derive_calibration_from_observation,
    _evaluate_step_guardrails,
    _fmt_reference,
    _gate_results_to_score_meta,
    _handle_admission_refusal,
    _handle_in_subprocess_rejection,
    _handle_prephase_gpu_measurement,
    _identity,
    _interpret_training_status,
    _is_cuda_oom,
    _json_safe_reference,
    _latest_trial_inference_marginal,
    _may_advise_resource_reduction,
    _merge_score_validity_failure,
    _non_retryable_termination_message,
    _oom_memory_wording,
    _prephase_device_snapshot,
    _prephase_worker_memory_limit_bytes,
    _raise_if_evidence_channel_failure,
    _raise_if_inconclusive,
    _raise_if_preflight_blocks,
    _raise_if_wall_clock_timeout,
    _render_gate_exhaustion_summary,
    _render_gate_exhaustion_trigger_b_summary,
    _resolve_effective_epochs,
    _resolve_formal_comparison_thresholds,
    _resolve_guardrail_steps,
    _resolve_sample_set_cfg,
    _resolve_time_check_probe_request,
    _resume_progress,
    _run_time_preflight,
    _runtime_phase_for,
    _score_of,
    _select_best_records,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
    _strategy_full_clone,
    _strategy_hybrid_params,
    _strategy_independent,
    _time_skip_memory_extra,
    _validate_data_config,
    _validate_history_and_lock,
    _validate_penalty_for_direction,
    _vram_skip_memory_extra,
)


SIDERIUS_ROOT = checkout_root()


# `AttemptTransition` and `AttemptDecision` used to live here. Step 07 PR 07b
# REMOVED them (§3.5, operator decision Q-07b-1): they had ZERO production
# consumers — only their own unit tests — and wiring them would have meant
# resetting `resolved_action` per attempt, which would have CHANGED round
# outcomes in the crash-after-a-scored-attempt case. 07b may not change retry
# or round semantics, so "wire it" and "keep round semantics unchanged" could
# not both be satisfied.
#
# F-SCANC-1 CLOSURE (operator decision packet v1, 2026-08-26): what 07b
# declined to wire, the C7 decomposition then silently SEVERED in the other
# direction — the gate verdict died as a local in `execution.py`, so
# `_decide_round_outcome` only ever saw the loop's own CONTINUE initializer
# and SKIP_ITER / SKIP_TO_FORMAL were unreachable (the hazard was never
# "stale", it was severed). The operator ruling is RETIRE for v1, not wire:
# the `resolved_action` round local, the skip branches, the `gate_aborted`
# carrier and the two skip members of `GateAction` are removed, and a config
# declaring a retired action refuses at validation. Gate actions still reach
# the record surface (`gate_action` on the round record) — they no longer
# claim loop control. `RoundDecision` / `_decide_round_outcome` survives as
# the non-retryable-termination arbiter.


# --------------------------------------------------------------------- #
# Strategy handlers
# --------------------------------------------------------------------- #
# Each handler mutates ``plan`` in place using the trial ``winner`` record
# and returns the list of inherited field names (used by the audit log).
# Signature is uniform so the registry can dispatch without special-casing.
# Defensive ``.get()`` reads on ``winner["params"]["train_config"]`` keys —
# legacy/sparse records may omit ``epochs``/``batch_size``; in that case
# the planner's value survives rather than crashing the chain on KeyError.


# ---------------------------------------------------------------------------
# Tuner-side gate-integration helpers (commit-5b).
# ---------------------------------------------------------------------------


# _serialize_expert_advice is now shared — imported as serialize_expert_advice
_serialize_expert_advice = serialize_expert_advice


# ---------------------------------------------------------------------------
# Gate-exhaustion feedback helper (Phase K.7 — see §10.13)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Node implementation
# ---------------------------------------------------------------------------


def _load_trial_anchor_map(*, composed: bool, data_root: str) -> dict | None:
    """The trial-anchoring artifact for this run, or a NAMED absence.

    Step 12 / PR-12bc B7, satellite (e). Extracted from ``run()`` rather than
    inlined: the resolution has three cases and ``run()`` carries a §J branch
    budget it had already spent.

    Before B7 this was two lines in the orchestrator that joined a hardcoded
    ``segment_anchors.json`` onto the run's physical root and raised
    ``FileNotFoundError`` when it was absent — so a COMPOSED non-TIDMAD trial
    run died naming a TIDMAD artifact it had never declared.

    ```text
    un-composed                -> regime A: the legacy artifact name, byte-identical
    composed + declares it     -> the TASK's own artifact path
    composed + declares none   -> None, with a named reason
    composed + not resolvable  -> None, with a named reason
    ```

    ``None`` is an ALREADY LEGAL state, not a new one: ``execution.py:953``
    guards the entire block that reads this, and that block is TIDMAD's
    SCORING reference rather than a precondition of trial rounds (D-BC-15). A
    consumer that genuinely needs an anchor map fails closed on its own; the
    point is that nothing is GUESSED here.

    Raises:
        FileNotFoundError: A path was resolved and the artifact is not there —
            the pre-existing behaviour, now naming whichever artifact the task
            actually declared.
    """
    anchoring = None
    if composed:
        try:
            anchoring = require_bound_task_data_path()
        except TaskDataPathResolutionError:
            # PR-12a's guard follows the INPUT FIELD even with the ContextVars
            # unbound, so "the field says composed" does not imply "something
            # is bound in this process".
            anchoring = None

    if anchoring is None and composed:
        print(
            "[Tuner] trial anchoring SKIPPED — this composed run has no "
            "resolvable task data path to ask for one. Any consumer that needs "
            "an anchor map will fail closed on its own; nothing is guessed here."
        )
        return None
    if anchoring is None:
        anchor_map_path = os.path.join(data_root, LEGACY_TRIAL_ANCHOR_NAME)
    elif declares_trial_anchoring(anchoring):
        # Positive branch on purpose: `declares_trial_anchoring` is a TypeGuard,
        # and a TypeGuard narrows where it is TRUE. Written as
        # `elif not declares(...)` the access below sat in an `else` the checker
        # would not narrow — same behaviour, unprovable types.
        anchor_map_path = anchoring.trial_anchor_path(data_root)
    else:
        print(
            f"[Tuner] trial anchoring SKIPPED — task data path "
            f"{anchoring.task_data_path_id!r} declares none, so there is no "
            f"artifact to load. Any consumer that needs one will fail closed "
            f"on its own; nothing is guessed here."
        )
        return None

    if not os.path.exists(anchor_map_path):
        raise FileNotFoundError(
            f"Trial mode requires {os.path.basename(anchor_map_path)} at "
            f"{anchor_map_path}. Prepare the task-owned anchor artifact first."
        )
    print("Trial mode enabled: anchor map loaded.")
    return load_anchor_map(anchor_map_path)


def _resolve_run_gate_ids(agent_input: Any) -> frozenset[str] | None:
    """The RUN's own scientific gate set — F-12d-30.

    Resolved ONCE, here, so ``records.py`` can read it off ``RunBindings``
    rather than reaching into the input projection: PR-12a C2 pins that the
    record module reads run-scoped AUTHORITIES, because a stamp that read the
    projection instead is what made a composed chain refuse its own output
    (F-11-C10-a).

    Composed runs resolve their declared binding. Uncomposed runs resolve
    their actual effective ``health_checks_config`` (already swapped in before
    RunBindings construction). A missing path uses the run-level loader's
    neutral default; classifiers never load a default themselves.

    Extracted rather than inlined at the construction site: ``run()`` sits on
    a PR-12a C0 structural LOC budget and §E.2 requires new behaviour to
    arrive by EXTRACTION rather than by spending the allowance. Inlining these
    eleven lines put it 88 over an 80-line budget and the guard caught it.

    ``None`` means roles could not be established, not an empty roster.
    """
    from execute_tools.health_checks.candidate_eligibility import (
        resolve_run_scientific_gate_ids,
        resolve_scientific_gate_ids,
    )

    ref = getattr(agent_input, "task_composition_ref", None)
    if ref is not None:
        return resolve_run_scientific_gate_ids(ref.task_health_binding)
    return resolve_scientific_gate_ids(getattr(agent_input, "health_checks_config", None))


def _resolve_run_health_config(agent_input: Any) -> HealthChecksConfig:
    """The roster this run will evaluate, resolved from the run's OWN declaration.

    F-C12P-CP12-1, second half. This is the tuner's FIRST health resolution,
    and the first resolution in a process is authoritative: it binds the
    task's Health plugin set into the run scope, and the Step-08b guard
    refuses every later, differing bind.

    ``load_health_gates_config`` cannot take a binding, so with no explicit
    config path it composes ``LEGACY_OMITTED`` — TIDMAD's family. That is
    correct for an un-composed run and wrong for a composed one, which then
    bound TIDMAD here and had its OWN family refused at
    :func:`_resolve_run_gate_ids`. The path is reachable exactly when this run
    materialized no effective config, i.e. ``health_gate_enabled=False``; with
    gates enabled ``build_run_invariants`` has already composed and bound the
    run's own family and the swapped-in effective path carries its roster,
    which ``load_composed_health_config`` returns untouched.

    Un-composed runs take the identical call they always took.
    """
    ref = getattr(agent_input, "task_composition_ref", None)
    if ref is None:
        return load_health_gates_config(agent_input.health_checks_config)
    config, _task_config, _plugins = load_composed_health_config(
        agent_input.health_checks_config, ref.task_health_binding
    )
    return config


def _lock_launch_identity(agent_input) -> LockLaunchIdentity:
    """The run's arXiv-U1/U3 lock identity, from the tuner's INPUT projection.

    Pure construction, extracted from ``run()`` under the 12a structural
    budget (the SE.2 idiom): pass-through values with one origin and one
    destination are a carrier, not inline kwargs in a 1,100-line method.
    Locked + stamped, never consumed by the tuner (ruling R2).
    """
    return LockLaunchIdentity(
        experiment_arm=agent_input.experiment_arm,
        lit_review_enabled=agent_input.lit_review_enabled,
        data_analysis_enabled=agent_input.data_analysis_enabled,
        lit_review_config_sha256=agent_input.lit_review_config_sha256,
        scientific_evidence_order=agent_input.scientific_evidence_order,
        baseline_isolation=agent_input.baseline_isolation,
        # F-SCANF-1 — the formal round's evaluation FRACTION, CANONICAL, so
        # it is threaded explicitly here rather than read ambiently.
        formal_eval_portion=agent_input.formal_eval_portion,
        trial_time_admission_source=agent_input.trial_time_admission_source,
        formal_time_admission_source=agent_input.formal_time_admission_source,
    )


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
        from core.capability_registry import CapabilityRegistry

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

        # --- The run's ONE dataset profile (Step 05a) ---
        # Resolved once, here, at the earliest point that precedes BOTH the
        # startup consumers (scope stamping / partial-scope detection) and
        # the loop consumers (legality, sample-set construction, legacy
        # accounting). Every one of them receives this value as an argument;
        # none resolves ambiently on its own authority, which is the defect
        # Step 02b removed from sample-set construction and 05a removes from
        # the rest of the tuner.
        #
        # Placement cannot move failure ordering: `resolve_dataset_profile`
        # reads a ContextVar and falls back to the shipped TIDMAD profile, so
        # it has no failure mode of its own and no phase moved to accommodate
        # it.
        run_profile = resolve_dataset_profile()

        # --- The run's ONE Model-I/O declaration (Step 05b) ---
        # Bound here, once, for exactly the same reason the profile above is:
        # the resource pre-flight must price the candidate against the
        # declaration THIS RUN will train against, not against whatever a
        # consumer happens to resolve for itself.
        #
        # `run_bound_model_io_contract` is the one acquisition point. The
        # sandbox executor already materializes its value to `--model_io_json`
        # for every training and inference child, so the pre-flight and the
        # run it is pricing cannot disagree — and `load_task_config` memoizes
        # per path, so this is the same validated object, not a second read.
        # Resolution (preset + dataset cardinality) already happened there;
        # 05b adds no second resolution point.
        #
        # Failure ordering: this makes an unreadable task config fatal at
        # startup rather than at the first training launch. No run that would
        # have SUCCEEDED can now fail — every run that trains already
        # executes this expression — and failing before any GPU work is the
        # direction the fail-closed rule asks for.
        run_model_io = run_bound_model_io_contract()
        run_forward_contract = ForwardContract(**load_task_config()["forward_contract"])

        # --- The run's ONE Deliverable Contract (Step 05c) ---
        # Bound here, from the run profile above, for the same reason: every
        # tuner consumer of a deliverable NAME — the path builder the peek
        # helpers receive, and the `--cleanup_denoised` glob — must resolve it
        # from one authority, or a rename moves some sites and not others and
        # the run writes artifacts nothing can find or clean (failure class 1).
        #
        # It is also what the sandbox is given, so the parent's readers and the
        # child's producers cannot disagree.
        #
        # HOW IT CROSSES (corrected, Step 12 / PR-12a C3 — this comment used to
        # say the spec "crosses no process boundary" and that the subprocess
        # reconstructs it from `--dataset_profile_json` alone, which stopped
        # being the whole truth at Step 11 C5/C6):
        #
        #   naming   a COMPOSED task's DECLARED naming is bound for the run by
        #            `bind_run_task_composition`, and `derive_tidmad_deliverable_spec`
        #            resolves the bound value internally — so this call already
        #            yields the declared naming with no branch here. Children
        #            re-compose it from `--task_manifest`.
        #   storage  still derived from the dataset profile, and still
        #            reconstructed child-side from `--dataset_profile_json`.
        #
        # Step 12 / PR-12d, seam B — B11, the TRANSITIVE blocker. This call
        # reached `tidmad_topology` FOUR times through the storage half and
        # killed the tuner before any training for a Q-12-4-honest profile.
        # `derive_run_deliverable_spec` answers `None` for a task that
        # declares no such geometry — a DECLARED absence — and the conditional
        # lives in the derivation's OWN module so this orchestrator gains no
        # branch. Every surviving consumer here reads `.naming`, which needs
        # no geometry; seam E (D4b) decides what the generic identity IS.
        #
        # The spec object itself is still not serialized.
        run_deliverable_spec = derive_run_deliverable_spec(run_profile)
        # Step 12 / PR-12d seam E: the OPTIONAL indexed naming. `None` for a
        # task that names its own artifacts — its consumers skip rather than
        # sweep with a template the run never writes (F-A4-1). Asking the
        # REFUSING accessor here would kill a composed contrast run at binding
        # time, before anything had asked for a filename.
        run_deliverable_naming = indexed_cleanup_naming()

        # --- The run's ONE evaluation metric (Step 06; bound seam Step 10 P1) ---
        # Still exactly one acquisition site, and still the run's single
        # source for identity, direction and the acceptance contract:
        # PRODUCTION SCORING below invokes the scorer THROUGH this handle
        # (`sandbox.evaluate_metric(run_metric, …)`). Not serialized; crosses
        # no process boundary (the scoring subprocess re-derives it from
        # `--dataset_profile_json`).
        #
        # A composed run supplies the metric its declaration named, resolved
        # once at the composition edge. An uncomposed run refuses here rather
        # than selecting a scientific metric on the framework's authority.
        run_metric: EvaluationMetric = resolve_run_metric()

        # --- The run's DECLARED observational secondaries (Step 10 / P2b) ---
        # Acquired at the SAME site as the primary, from the same composition,
        # and — unlike the primary — with no legacy branch: there is nothing to
        # fall back to, because "this run declared no secondary" is the answer
        # rather than a default. An un-composed run therefore gets `()`, and
        # NOTHING anywhere derives a secondary from task identity.
        #
        # These are OBSERVATIONAL. They are evaluated wherever the primary is
        # (Q-P2b-1) and transported onto the record and the output, but no
        # ordering decision may read them: `run_order` below is the run's ONE
        # order authority and it interprets the PRIMARY spec only.
        run_secondary_metrics = resolve_bound_run_secondary_metrics()

        # --- The run's ONE order authority (Step 07 PR 07b) ---
        # Every ordering decision this tuner makes about the golden metric —
        # trial winner, skip/bypass orientation and their disabled sentinels,
        # the planner's score-table incumbent, the reflector's best/rank/
        # new-best/efficiency band, and the five best_* finalization tracks —
        # asks THIS object, which is the only place `spec.direction` is
        # interpreted. There is deliberately no second direction field: the
        # same-loss `final_loss` rank stays lower-is-better by definition of a
        # loss and never consults it.
        run_order = MetricOrder(run_metric.spec)

        # --- DataScope + HealthGate startup validation (DS5) ---
        # Dataset-resolved checks (schema validators cover only internal
        # consistency), then health-config materialization — all BEFORE any
        # LLM call, sandbox construction, or file I/O. See
        # docs/design/enable_partial_file_list.md.
        # Step 05a: BOTH the scope resolution and the partial-scope predicate
        # read the run-bound topology. They compute the same comparison from
        # the same fact, so supplying the profile to only one of them would
        # let `validate_runtime_config` early-return believing the scope full
        # — skipping every partial-scope legality check — while this line
        # classified and stamped the run as partial.
        resolved_data_scope = validate_runtime_config(agent_input, run_profile.partition_count)
        # Step 07 PR 07b §3.3 row 5 — the one scale-sensitive rule that has no
        # honest generic reading. Refused here, on the same startup path and
        # before the same first LLM call as every other illegal operator flag.
        _validate_penalty_for_direction(agent_input, run_order)
        scope_is_partial = resolved_data_scope != list(range(run_profile.partition_count))
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
            # Step 12 / PR-12a (D-12a-1 / F-P56-3) — the composition-derived
            # invariants, read from the run's INPUT projection.
            #
            # Both were simply absent before. The per-model lock therefore
            # recorded no composition identity at all (a composed workspace
            # could not say which task produced it), and the per-model
            # effective Health config was re-materialized with NO binding —
            # 08b resolved `LEGACY_OMITTED`, stamping `legacy_default` on a
            # document whose roster is the task's. C1 fixed the roster by
            # changing what the workflow HANDS this node; these two kwargs
            # close what the node ASKS FOR, which is the half C1 could not
            # reach.
            #
            # `None` for an un-composed run — the same values the un-composed
            # call already produced by omission — so the legacy lock and the
            # legacy effective document are byte-identical.
            task_composition_fingerprint=(
                agent_input.task_composition_ref.semantic_fingerprint
                if agent_input.task_composition_ref is not None
                else None
            ),
            health_materialization=RunHealthMaterialization(
                task_health_binding=(
                    agent_input.task_composition_ref.task_health_binding
                    if agent_input.task_composition_ref is not None
                    else None
                )
            ),
            # arXiv U1 (#253 / #254) — run-identity pass-through (locked +
            # stamped, never consumed), same contract as the PR 3 block.
            launch_identity=_lock_launch_identity(agent_input),
        )
        health_config_sha256 = run_invariants.health_config_sha256
        # Step 11 C8 / R-11-9 — read from the SAME resolved invariants the
        # lock is built from, exactly as the sha above is. `None` for an
        # un-composed run, which is what keeps legacy outputs unchanged.
        task_composition_fingerprint = run_invariants.task_composition_fingerprint
        if _effective_config_path is not None:
            # Path swap: every downstream path-based loader (gate lookup,
            # evaluation, output persistence) now reads the materialized
            # effective config through the existing plumbing.
            agent_input.health_checks_config = _effective_config_path

        # --- The run's authority-rendered task content (Step 07 PR 07b, P2) ---
        # Built ONCE, here, because every input is now settled: the profile's
        # topology, the run-bound Model-I/O contract, and — critically — the
        # EFFECTIVE health config, whose path was just swapped in above. Built
        # any earlier and the check names would come from the shipped default
        # rather than from what this run will actually evaluate.
        # Step 12 / PR-12d, seam B — the fifth direct decoder. `None` is the
        # declared absence for a task with no physical geometry, and the
        # render authority owns what that renders (it is the only fact here
        # that reaches a prompt).
        run_task_render = build_tuner_task_render(
            dataset=project_attempt_topology_facts(run_profile).physical_dataset,
            model_io_contract=run_model_io,
            health_config=_resolve_run_health_config(agent_input),
            efficiency_band_fraction=EFFICIENCY_BAND_FRACTION,
            # Step 12 / PR-12a C7 (D-12a-5) — composition PRESENCE, from the
            # run's own INPUT projection, so the render authority can gate the
            # LLM-facing task science. `False` for every un-composed run,
            # which renders the legacy bytes.
            composed=agent_input.task_composition_ref is not None,
            objective=(
                agent_input.task_composition_ref.objective
                if agent_input.task_composition_ref is not None
                else None
            ),
        )

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
        # Step 11 C4 (R-11-7) — ONE authority for "where the data physically
        # lives". A COMPOSED run's bound root wins, because that is the root
        # its children read and pricing a warmup against a different one
        # would measure the wrong disk. An UN-COMPOSED run resolves to
        # `agent_input.data_dir` exactly as before — including `None`, which
        # keeps its meaning of "no warmup, use the static-formula estimate".
        # This reconciles the field to the run binding rather than leaving it
        # as a second, independently-supplied concept.
        _bound_data_root = active_physical_data_root()
        time_data_dir = _bound_data_root if _bound_data_root is not None else agent_input.data_dir
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
            deliverable_naming=run_deliverable_naming,
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
            anchor_map_data = _load_trial_anchor_map(
                composed=agent_input.task_composition_ref is not None,
                data_root=sandbox.dirs["data"],
            )

        # Reference evidence is absent unless a caller injects it at the node's
        # dependency seam. The framework never selects a task, path, or baseline
        # table when no evidence was declared.
        reference_scores = load_reference_scores()
        if reference_scores is None:
            print(
                "Reference scores: NOT DECLARED. The framework does not select "
                "task-specific comparison evidence implicitly; comparison tables "
                "are omitted for this run."
            )
        else:
            print("Reference scores: supplied by the caller dependency.")

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
            order=run_order,
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
            "vram_probe_step_timeout_seconds": (agent_input.vram_probe_step_timeout_seconds),
            "vram_preflight_total_timeout_seconds": (
                agent_input.vram_preflight_total_timeout_seconds
            ),
            "vram_preflight_host_memory_limit_gb": (
                agent_input.vram_preflight_host_memory_limit_gb
            ),
            # DataScope + HealthGate subsystem stamps (DS5).
            "resolved_data_scope": resolved_data_scope,
            "health_gate_enabled": agent_input.health_gate_enabled,
            # V20 PR D (D-C1a): declared enforcement/authority axes,
            # echoed from the input so provenance and output cannot
            # disagree with what the run was launched under.
            "healthgate_mode": agent_input.healthgate_mode,
            "result_authority": agent_input.result_authority,
            # V21 PR E — candidate label in the provenance stamp, same
            # cannot-disagree argument as the D-C1a echo above.
            "candidate_id": agent_input.candidate_id,
            "health_checks_config_source": health_checks_config_source,
            "health_checks_config_effective": agent_input.health_checks_config
            if agent_input.health_gate_enabled
            else None,
            "health_config_sha256": health_config_sha256,
            "task_composition_fingerprint": task_composition_fingerprint,
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
        config_manual = _runtime._run_skill("check_config_format_skill", sandbox)
        if config_manual["status"] == "success":
            config_manual_data = config_manual["data"]
        else:
            raise ValueError("Config Manual not provided.")

        # --- Load model description (architecture explanation for the LLM) ---
        model_description = None
        try:
            from ml_models.model_descriptions import (
                DescriptionSourcePolicy,
                get_model_description,
            )

            # arXiv U3 (#260): the loader refuses a BUNDLED baseline under
            # isolation (a built-in candidate never reaches the tuner there).
            source_policy = (
                agent_input.task_composition_ref.description_source_policy
                if agent_input.task_composition_ref is not None
                else DescriptionSourcePolicy.LEGACY
            )
            model_description = get_model_description(
                model_type_setting,
                baseline_isolation=agent_input.baseline_isolation,
                source_policy=source_policy,
            )
            if model_description is None:
                print(
                    f"No authorized model description for '{model_type_setting}' "
                    "(composed source absence)"
                )
            else:
                print(
                    f"Loaded model description for '{model_type_setting}' "
                    f"({len(model_description)} chars)"
                )
        except FileNotFoundError as e:
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
        _validate_history_and_lock(
            workspace,
            run_invariants,
            existing_history,
            _lock_was_present,
            partition_count=run_profile.partition_count,
        )
        consecutive_fails = 0
        # D-C6: set at the skip gate itself, so the feedback can state
        # WHY formal did not run rather than inferring it from the
        # absence of a formal record — which cannot distinguish a
        # no-winner skip from a budget skip.
        _skipped_formal_for_no_valid_winner = False
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

        # --- The run's bound environment (Step 07 PR 07b, C7d) ---------------
        # Everything above this line established an authority or a service whose
        # identity does not change for the rest of the run. Grouping exactly
        # those into ONE frozen carrier is what lets the lifecycle phases below
        # take an honest signature instead of ~28 positional locals.
        #
        # It carries no counters, no current plan and no results: `RunBindings`
        # refuses those structurally, because an object passed this widely is
        # precisely where mutable state would accumulate unnoticed.
        run_bindings = RunBindings(
            agent_input=agent_input,
            sandbox=sandbox,
            brain=brain,
            custom_loss_inventory=resolve_run_custom_loss_inventory(
                self._registry,
                run_model_io,
                agent_input.task_composition_ref,
            ),
            run_profile=run_profile,
            run_model_io=run_model_io,
            run_forward_contract=run_forward_contract,
            run_deliverable_spec=run_deliverable_spec,
            run_deliverable_naming=run_deliverable_naming,
            run_metric=run_metric,
            run_secondary_metrics=run_secondary_metrics,
            run_order=run_order,
            run_scientific_gate_ids=_resolve_run_gate_ids(agent_input),
            run_task_data_path=(
                resolve_bound_task_data_path()
                if agent_input.task_composition_ref is not None
                else None
            ),
            run_task_render=run_task_render,
            run_name=run_name,
            workspace=workspace,
            file_index=file_index,
            max_rounds=max_rounds,
            model_type_setting=model_type_setting,
            trial_allowed=trial_allowed,
            resolved_data_scope=resolved_data_scope,
            scope_is_partial=scope_is_partial,
            expert_advice_str=expert_advice_str,
            config_manual_data=config_manual_data,
            model_description=model_description,
            trial_vram_budget=trial_vram_budget,
            formal_vram_budget=formal_vram_budget,
            trial_time_budget=trial_time_budget,
            formal_time_budget=formal_time_budget,
            attempts_per_round_setting=attempts_per_round_setting,
            attempts_per_formal_round_setting=attempts_per_formal_round_setting,
            max_fail_rounds_setting=max_fail_rounds_setting,
            formal_reference_score=formal_reference_score,
            formal_reference_source=formal_reference_source,
            resolved_skip_formal_threshold=resolved_skip_formal_threshold,
            resolved_bypass_formal_threshold=resolved_bypass_formal_threshold,
            hardware_context=hardware_context,
            device_identity=device_identity,
            time_data_dir=time_data_dir,
            anchor_map_data=anchor_map_data,
            reference_scores=reference_scores,
            started_at=started_at,
            health_checks_config_source=health_checks_config_source,
            health_config_sha256=health_config_sha256,
        )

        while completed_rounds < max_rounds and consecutive_fails < max_fail_rounds_setting:
            round_index = completed_rounds + 1
            is_formal_round = completed_rounds == max_rounds - 1
            N = attempts_per_formal_round_setting if is_formal_round else attempts_per_round_setting
            round_succeeded = False
            # F-SCANC-1: the per-round `resolved_action` local that used to
            # be declared here (with the 07b OD-S7-6 hazard note) is
            # RETIRED — see the closure note at the module's 07b comment.
            # The C7 decomposition had already severed its only real
            # writer, so it was a constant CONTINUE masquerading as loop
            # control.

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
            formal_trial_winner = _best_trial_winner(
                sandbox.get_summary() or [],
                order=run_order,
                required_gate_ids=run_bindings.run_scientific_gate_ids,
            )
            if (
                is_formal_round
                and agent_input.force_formal_round
                and _should_skip_formal(
                    formal_trial_winner,
                    threshold=resolved_skip_formal_threshold,
                    gates_enabled=agent_input.enable_chain_incumbent_formal_gates,
                    order=run_order,
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
                        f"\n  [SkipFormal] Best trial {_best_trial_score:.4f} "
                        f"{run_order.comparison_symbol} "
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
                stage = AttemptStage("planning")
                attempt_ordering = AttemptOrdering()
                exp_id = f"{model_type_setting}_{run_name}_{total_attempts:03d}"
                model_type = model_type_setting
                record_params: dict[str, Any] = {}
                hypothesis = "Attempt failed before a validated hypothesis was available."
                try:
                    prepared = prepare_attempt(
                        run_bindings,
                        attempt_ordering=attempt_ordering,
                        iteration=iteration,
                        attempt_in_round=attempt_in_round,
                        total_attempts=total_attempts,
                        attempts_this_round=N,
                        is_formal_round=is_formal_round,
                        formal_trial_winner=formal_trial_winner,
                    )
                    plan = prepared.plan
                    trial_config = prepared.trial_config
                    active_params = prepared.active_params
                    record_params = prepared.record_params
                    exp_id = prepared.exp_id
                    hypothesis = prepared.hypothesis
                    model_type = prepared.model_type
                    memory_history = prepared.memory_history
                    train_psd_segments = prepared.train_psd_segments
                    eval_psd_segments = prepared.eval_psd_segments
                    _planned_portions = prepared._planned_portions

                    # RT5 §5 guardrails — cheapest pre-flight check, before
                    # any VRAM/time probe. Defense-in-depth only; the primary
                    # criterion stays the in-subprocess runtime verification.
                    identity = AttemptIdentity(
                        round_index=round_index,
                        attempt_in_round=attempt_in_round,
                        is_formal_round=is_formal_round,
                    )
                    admission = run_admission_preflight(
                        run_bindings,
                        prepared,
                        identity,
                        stage,
                        formal_trial_winner=formal_trial_winner,
                        physical_rejections_buffer=physical_rejections_buffer,
                    )
                    if admission.scope_violation_reason is not None:
                        _scope_violation_reason = admission.scope_violation_reason
                    if admission.signal is AttemptSignal.NEXT_ATTEMPT:
                        continue
                    if admission.signal is AttemptSignal.END_ROUND:
                        break
                    trained = run_training(
                        run_bindings,
                        prepared,
                        identity,
                        stage,
                    )
                    if trained.scope_violation_reason is not None:
                        _scope_violation_reason = trained.scope_violation_reason
                    if trained.signal is AttemptSignal.NEXT_ATTEMPT:
                        continue
                    if trained.signal is AttemptSignal.END_ROUND:
                        break
                    train_time = trained.train_time
                    training_results = trained.training_results
                    executed = run_inference_scoring_health(
                        run_bindings,
                        prepared,
                        identity,
                        stage,
                        train_time=train_time,
                        training_results=training_results,
                    )
                    if executed.scope_violation_reason is not None:
                        _scope_violation_reason = executed.scope_violation_reason
                    if executed.signal is AttemptSignal.NEXT_ATTEMPT:
                        continue
                    if executed.signal is AttemptSignal.END_ROUND:
                        break
                    score_results = executed.score_results
                    score_table = executed.score_table
                    train_results = executed.train_results

                    # D. REFLECT: Analyze results and generate insights
                    training_diagnosis = executed.training_diagnosis
                    resource_check = admission.resource_check
                    print("\nGenerating Research Memory...")

                    reflection_context = _build_reflection_context(
                        memory_history=memory_history,
                        current_score=score_results.get("denoising_score"),
                        current_loss_type=active_params["loss_config"].get("loss_type"),
                        current_final_loss=train_results.get("final_loss"),
                        current_params=train_results.get("model_params"),
                        current_epochs=active_params["train_config"].get("epochs"),
                        train_psd_segments=train_psd_segments,
                        eval_psd_segments=eval_psd_segments,
                        trial_config=trial_config,
                        score_table=score_table,
                        order=run_order,
                    )

                    reflect_results = {**train_results, **score_results}
                    reflection = invoke_reflection(
                        brain,
                        exp_id=exp_id,
                        prepared=prepared,
                        reflect_results=reflect_results,
                        reflection_context=reflection_context,
                        metric_spec=run_metric.spec,
                        training_diagnosis=training_diagnosis,
                        task_render=run_task_render,
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
                    final_record = build_attempt_record(
                        run_bindings,
                        prepared,
                        identity,
                        admission,
                        trained,
                        executed,
                        reflection=reflection,
                    )

                    # V21 PR B2 — join the admission forecast to the realized
                    # peak before the record is emitted. One call; the logic
                    # and its tests live in the extracted boundary.
                    _attach_realized_memory(
                        final_record, resource_check, final_record["runtime_verification"]
                    )

                    _emit_attempt_record(sandbox, final_record, agent_input)
                    _append_runtime_observation(
                        sandbox, run_name, final_record["runtime_verification"]
                    )
                    # V20 PR C1 / C-C3c: the derived calibration view of the
                    # SAME measurement System A just persisted. Success path
                    # only -- see the helper's docstring for why not the
                    # shared append helper, and for why C12-P/B5 passes
                    # `run_profile` as a value rather than deciding here.
                    _derive_calibration_from_observation(
                        sandbox,
                        rv_block=final_record["runtime_verification"],
                        device_identity=device_identity,
                        data_dir=time_data_dir,
                        run_profile=run_profile,
                        measurement_capability=agent_input.measurement_capability,
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
                    from core.local_code.failure import raise_if_code_package_failure

                    raise_if_code_package_failure(e)
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
                    failure_type = _classify_attempt_failure(e, stage.name)
                    # F-SCANF-2 — WHOSE failure this is. A provider outage
                    # used to be recorded as `status="error"` with the budget
                    # consumed and a narrative telling the next planner not to
                    # repeat "the failing configuration", so an API timeout
                    # reached the model as a verdict on the candidate. The
                    # decision is a typed boundary in `records` rather than a
                    # branch here: `run()` sits at pyright's complexity
                    # ceiling, and this handler must stay a substitution.
                    disposition = classify_attempt_failure_disposition(e, failure_type=failure_type)
                    traceback_summary = traceback.format_exc()[-4000:]
                    failure_record = {
                        "record_type": "attempt_failure",
                        "exp_id": exp_id,
                        "status": disposition.status,
                        "model_type": model_type,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "file_index": file_index,
                        "params": record_params,
                        "logical_round": round_index,
                        "attempt_index": total_attempts,
                        "failure_stage": stage.name,
                        "failure_type": failure_type,
                        "failure_reason": failure_reason,
                        "proposed_config": record_params,
                        "traceback_summary": traceback_summary,
                        "counts_toward_completed_rounds": False,
                        "counts_toward_attempt_budget": (disposition.counts_toward_attempt_budget),
                        "memory": {
                            "expert_advice_followed": expert_advice_str,
                            "hypothesis": hypothesis,
                            **disposition.memory_narrative(
                                failure_stage=stage.name,
                                failure_reason=failure_reason,
                                record_params=record_params,
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
                        _emit_attempt_record(
                            sandbox, failure_record, agent_input, ordering=attempt_ordering.selected
                        )
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
            )
            if _round_decision is RoundDecision.BREAK_ITERATION:
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
                del prepared
            with suppress(NameError):
                del executed
            with suppress(NameError):
                del reflect_results
            with suppress(NameError):
                del memory_history
            gc.collect()

        # --- Build, validate, and save the run output ---
        return finalize_run_output(
            run_bindings,
            RunExitSnapshot(
                completed_rounds=completed_rounds,
                total_attempts=total_attempts,
                consecutive_fails=consecutive_fails,
                scope_violation_reason=_scope_violation_reason,
                evidence_channel_failure=_evidence_channel_failure,
                skipped_formal_for_no_valid_winner=_skipped_formal_for_no_valid_winner,
                physical_rejections_buffer=physical_rejections_buffer,
                last_plan=plan,
            ),
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Thin CLI wrapper — parses args, builds HyperparamTuningInput, calls run().

    Step 12 / PR-12d D8a. `--task_composition` composes ONCE, here — the same
    object threads into `build_agent_input` (for `task_composition_ref`, the
    tuner's typed record of what it is bound to) and into the binding
    context around `.run()` (which activates `active_task_data_path()`,
    `active_run_model_plugins()`, `active_deliverable_naming()`, etc.).
    Composing twice would be a SECOND resolution — the registry-identity
    rules (Step 12 / PR-12bc CASE A) treat that as a fresh instance, not the
    every un-composed launch is byte-identical to before this flag existed.

    Mirrors the SAME pattern the chain launcher already uses
    (`workflows/model_exploration.py`'s own CLI entry) — this is the second
    composition edge, not a new authority.
    """
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    parser = build_parser()
    args = parser.parse_args()
    from core.generated_library import bind_generated_library_to_workspace

    bind_generated_library_to_workspace(args.workspace)
    run_composition = compose_run_task_bindings(args.task_composition)
    agent_input = build_agent_input(args, parser, run_composition)

    agent = HyperparamTuningAgent()
    with bind_run_task_composition(run_composition, physical_data_root=args.data_dir):
        output = agent.run(agent_input)
    if output.status != "completed" or output.completed_rounds != args.max_rounds:
        return PARTIAL_CAMPAIGN_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
