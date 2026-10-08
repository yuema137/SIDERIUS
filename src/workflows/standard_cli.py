"""Shared declarations and normalization for the standard single-iteration CLI.

This is the default authority used by execution and setup inspection. Importing
it does not load dotenv or start a workflow. Normalization reads explicitly
selected advice files; it does not resolve task plugins or create a workspace.
"""

from __future__ import annotations

import argparse
import json
import warnings
from typing import get_args

from pydantic import TypeAdapter

from agent.schemas.health_feedback import HealthFeedbackRetentionPolicy
from agent.schemas.hyperparam_tuning import TrainingValidationPortion
from agent.schemas.ordering import parse_file_order_cli
from agent.schemas.parameter_rules import ParameterRules
from core.runtime_control.watchdog_profile import ExecutionRegime
from execute_tools.dataset_config import DataScope
from workflows.advice import ADVICE_PER_AGENT_KEYS, render_advice_value, resolve_advice_artifact


def _positive_int(s: str) -> int:
    """argparse type validator: parse a positive integer (>= 1).

    Used by --max_epochs (Phase 6.8 Commit 11): None / 0 / negative are
    strictly forbidden — every chain run must train for at least one epoch.
    """
    try:
        v = int(s)
    except (TypeError, ValueError) as e:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {s!r}") from e
    if v < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer (>= 1), got {v}")
    return v


def _portion_floor(s: str) -> float:
    """argparse type validator: a portion in [0.01, 1.0].

    The 0.01 floor enforces a segment-integrity rule: with
    ``SEGMENTS_PER_FILE=200``, anything below 0.01 collapses to one
    segment per file (via the ``max(1, ...)`` floor in
    ``execute_tools.sample_set_builder``), which is statistically too
    noisy for trial-mode signal. Failing here at argparse-time keeps
    the iteration from spending tokens on Interpretation only to crash
    inside the Proposer's Pydantic validator.
    """
    try:
        v = float(s)
    except (TypeError, ValueError) as e:
        raise argparse.ArgumentTypeError(f"expected a float in [0.01, 1.0], got {s!r}") from e
    if not (0.01 <= v <= 1.0):
        raise argparse.ArgumentTypeError(
            f"expected a float in [0.01, 1.0], got {v}. The 0.01 floor "
            f"matches the Pydantic schema (ProposalInput.trial_portion / "
            f"HyperparamTuningInput.{{trial,eval}}_portion ge=0.01); below "
            f"that, sample_set_builder collapses to one segment per file, "
            f"which is too noisy for trial-mode signal."
        )
    return v


def build_parser() -> argparse.ArgumentParser:
    """Build the per-iteration runner's argument parser.

    Extracted from ``main`` so unit tests can exercise the CLI surface
    without invoking the workflow. The parser intentionally accepts both
    ``--start_iteration`` (canonical) and ``--iteration`` (deprecated alias);
    :func:`normalize_args` collapses them after parsing.
    """
    parser = argparse.ArgumentParser(
        description="Run one iteration of the SIDERIUS exploration workflow."
    )
    parser.add_argument(
        "--workspace",
        type=str,
        required=True,
        help="Root output directory for this exploration (shared across all iterations).",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        required=True,
        help="Chain-level run name (e.g. 'explore_v12_0504'). Used as the "
        "audit-log identity (chain_run_name) and seeded into the "
        "immutable run_id sidecar at {workspace}/.token_run_id. "
        "Must remain identical across every iteration of the chain — "
        "the bridge refuses run_id mutation per §1.4.1.",
    )
    # Phase 6.8 Task 2 Commit 8 — rename --iteration → --start_iteration so the
    # name matches the unified resume/chain philosophy ("which iter is this
    # invocation about to run; iters [1, N-1] are absorbed from disk").
    # The positional meaning is unchanged; only the name moves. --iteration is
    # kept as a deprecated alias for one release. See
    # docs/phase68_orchestrator_memory_and_resume.md §3.5 Commit 8.
    parser.add_argument(
        "--start_iteration",
        type=int,
        default=None,
        help="Iteration number (1-based) to run *now*. When > 1, the runner "
        "auto-restores plugin classes from iters [1, N-1] via "
        "core.resume.restore_prior_state. Mutually exclusive with the "
        "deprecated --iteration alias.",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=None,
        dest="iteration_legacy",
        help="DEPRECATED — alias for --start_iteration. Will be removed after "
        "the next stable run. Use --start_iteration instead.",
    )
    # Phase 6.8 Commit 11 — rename --source_paths → --seed_paths so the
    # canonical name reflects what the list actually means: *seed* source
    # data, not the full source set (prior iters are auto-discovered from
    # {workspace}/iter_NNN/manifest.json). --source_paths is kept as a
    # deprecated alias for one release. See §3.5 Commit 11.
    parser.add_argument(
        "--seed_paths",
        type=str,
        nargs="+",
        default=None,
        help="Explicit list of HyperparamTuningOutput JSON paths to use as "
        "*seed* source data. Prior iters' run_outputs are auto-discovered "
        "from {workspace}/iter_NNN/manifest.json by restore_prior_state — "
        "they no longer need to be listed here for chain runs (back-compat "
        "still accepts @manifest: indirection in this list). "
        "Mutually exclusive with the deprecated --source_paths alias. "
        "OPTIONAL: omit the flag entirely to start a cold chain with no prior "
        "experimental evidence (a bare --seed_paths with no values is still an "
        "error).",
    )
    parser.add_argument(
        "--source_paths",
        type=str,
        nargs="+",
        default=None,
        dest="source_paths_legacy",
        help="DEPRECATED — alias for --seed_paths. Will be removed after "
        "the next stable run. Use --seed_paths instead.",
    )
    parser.add_argument("--max_rounds", type=int, default=3, help="Tuning rounds per iteration.")
    parser.add_argument(
        "--max_proposal_attempts",
        type=int,
        default=3,
        help="Retry budget for propose→implement→validate.",
    )
    parser.add_argument(
        "--llm_model",
        type=str,
        default="gemini-3.1-pro-preview",
        help="Gemini model ID for all 5 agents (the planner sub-call of the "
        "tuner uses this; the reflector sub-call uses --reflect_model_id "
        "if set, else falls back to a provider-aware default).",
    )
    parser.add_argument(
        "--reflect_provider",
        type=str,
        default=None,
        choices=["gemini", "openai"],
        help="Optional separate provider for the tuner's reflector sub-call. "
        "When unset, the reflector uses the same provider as the planner.",
    )
    parser.add_argument(
        "--reflect_model_id",
        type=str,
        default=None,
        help="Optional separate model for the tuner's reflector sub-call. "
        "When unset for the gemini provider, defaults to 'gemini-2.5-flash' "
        "(GA model with unlimited daily quota). When unset for other "
        "providers, falls back to --llm_model (legacy behavior).",
    )
    parser.add_argument(
        "--gpu_memory_limit_gb",
        type=int,
        default=None,
        help="Hard cap on GPU memory per process (Phase 2, not yet implemented end-to-end).",
    )
    parser.add_argument(
        "--max_epochs",
        type=_positive_int,
        default=1,
        help="Hard cap on epochs per round. Must be >= 1; None forbidden. "
        "Per-mode overrides: --trial_max_epochs / --formal_max_epochs take "
        "precedence for their round role (D-BUD-6).",
    )
    parser.add_argument(
        "--training_budget_reserve_fraction",
        type=float,
        default=None,
        help="Opt in to cooperative training allocation; reserve a fraction (0,1) of the attempt budget for downstream work. Uses the role epoch ceiling, no loss-based early stopping.",
    )
    parser.add_argument(
        "--trial_max_epochs",
        type=_positive_int,
        default=None,
        help="TRIAL-role epoch ceiling (campaign decision D-BUD-6; frozen "
        "campaign posture: trial 2 / formal 1). Precedence for a trial "
        "round: this value -> --max_epochs -> no clamp; formal rounds never "
        "read it. Must be >= 1; omit to keep the mode-agnostic --max_epochs.",
    )
    parser.add_argument(
        "--formal_max_epochs",
        type=_positive_int,
        default=None,
        help="FORMAL-role epoch ceiling (campaign decision D-BUD-6). "
        "Precedence for a formal round: this value -> --max_epochs -> no "
        "clamp; trial rounds never read it. Must be >= 1; omit to keep the "
        "mode-agnostic --max_epochs.",
    )
    parser.add_argument(
        "--skip_formal_min_delta",
        type=float,
        default=-1.0,
        help="Skip all formal rounds when best_trial_score < "
        "(current_run_best_formal_score + skip_formal_min_delta). "
        "Matches HyperparamTuningInput schema default -1.0. "
        "Set to 0.0 to skip whenever trial does not beat current best.",
    )
    parser.add_argument(
        "--bypass_formal_time_budget_min_delta",
        type=float,
        default=0.0,
        help="Bypass the formal time-budget gate when best_trial_score >= "
        "(current_run_best_formal_score + bypass_formal_time_budget_min_delta). "
        "Matches HyperparamTuningInput schema default 0.0. "
        "Set to 0.5 to only bypass when trial beats current best by >= 0.5 dB.",
    )
    parser.add_argument(
        "--bypass_formal_time_budget_minutes",
        type=float,
        default=None,
        help="Lane F3: ELEVATED wall-time ceiling (minutes) for a score-qualified "
        "bypass formal attempt — one value drives BOTH re-evaluated admission and "
        "the watchdog ceiling. Omitted (None) = a qualified bypass grants NO "
        "extension. Campaign frozen value: 200.",
    )
    parser.add_argument(
        "--order_strategy_override",
        type=str,
        default=None,
        choices=["shuffle", "sequential"],
        help="V19 PR 2: force the training sample visitation order for every "
        "round of this chain, overriding any agent proposal. Unset (default) "
        "= the agent's proposal decides, falling back to 'shuffle' (pre-V19 "
        "behavior). Pinned in the run-invariants lock — changing it mid-chain "
        "is a violation.",
    )
    parser.add_argument(
        "--file_order_override",
        type=str,
        default=None,
        help="V19 PR 2: comma-separated file visitation ORDER for "
        "--order_strategy_override sequential, e.g. '4,6,5,9,7,8'. Order is "
        "preserved as written and must be a full permutation of the resolved "
        "DataScope. Omit for ascending file index.",
    )
    parser.add_argument(
        "--enable_chain_incumbent_formal_gates",
        action="store_true",
        help="V19 PR 1: let the formal delta gates CONSUME the reconstructed "
        "chain incumbent as their reference. Default OFF (gates see no "
        "reference; reconstruction, provenance, and manifest stamps still "
        "run unconditionally). Rollback = omit this flag; the pre-V19 "
        "fixed-0.0 reference is not restorable.",
    )
    parser.add_argument(
        "--enable_structured_health_feedback",
        action="store_true",
        help="V19 PR 3: render structured HealthGate evidence (per-round "
        "gate fields + collapse fingerprints) in the interpreter and "
        "proposer prompts. Default OFF: prompts are byte-identical to "
        "pre-PR3; the deterministic evidence is still recorded in "
        "artifacts. Pinned in the run-invariants lock — changing it "
        "mid-chain is a violation (use a new workspace).",
    )
    parser.add_argument(
        "--health_feedback_history_window_iterations",
        type=int,
        default=3,
        help="V19 PR 3: fingerprint-history retention window — TOTAL "
        "iterations retained including the current one. Must be >= 1. "
        "Pinned in the run-invariants lock.",
    )
    parser.add_argument(
        "--health_feedback_history_max_entries_per_model",
        type=int,
        default=8,
        help="V19 PR 3: retained fingerprint-history entries per model "
        "(deterministic trim bound). Must be >= 1. Pinned in the "
        "run-invariants lock.",
    )
    parser.add_argument(
        # BooleanOptionalAction, not store_true: the consumer below used to
        # read `args.is_trial or True`, so an explicit False was erased and
        # the flag could never express anything. Default stays True, so
        # omitting it behaves exactly as before; `--no-is_trial` is now the
        # way to ask for a formal-from-the-start run.
        "--is_trial",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable trial mode (default: True). Use --no-is_trial for formal.",
    )
    parser.add_argument(
        "--trial_strategy",
        type=str,
        default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="DEPRECATED no-op (DS7) — warns and is ignored. Use --data_scope.",
    )
    # Lane F2 — the three trial-side portions are TRI-STATE: a TYPED value
    # is EXPERIMENT_FIXED (merged into the plan_overrides lock at the
    # workflow layer, so trial planning cannot silently override it);
    # omitted (None) is AGENT_CONTROLLED — the planner's values execute.
    parser.add_argument(
        "--trial_portion",
        type=_portion_floor,
        default=None,
        help="Floor 0.01 (segment-integrity; mirrors Pydantic ge=0.01). "
        "Typed = EXPERIMENT_FIXED; omitted = agent-controlled (Lane F2).",
    )
    # F-RC-1: the shared parser floor (see `_portion_floor`); its target
    # `HyperparamTuningInput.train_portion` declares ge=0.01.
    parser.add_argument("--train_portion", type=_portion_floor, default=None)
    parser.add_argument(
        "--eval_portion",
        type=_portion_floor,
        default=None,
        help="Floor 0.01 (segment-integrity; mirrors Pydantic ge=0.01). "
        "Typed = EXPERIMENT_FIXED; omitted = agent-controlled (Lane F2).",
    )
    # --- Formal-mode training levers (Phase M, docs §12) + eval scope (Phase R, §13) ---
    # Formal eval strategy is locked to ``snapshot``; the portion defaults to
    # 1.0 (production full-clone for cross-arch comparability, §12.2) and
    # is operator-configurable via ``--formal_eval_portion`` for smoke / CI
    # runs that need to fit a tight ``--formal_time_budget_minutes`` — §13.
    parser.add_argument(
        "--formal_strategy",
        type=str,
        default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="Training-side strategy on formal rounds (default snapshot).",
    )
    parser.add_argument(
        "--formal_training_scope_source",
        choices=["operator", "agent"],
        default="operator",
        help="Source of formal training portions; formal evaluation stays operator-owned.",
    )
    parser.add_argument(
        "--formal_portion",
        # F-RC-1: the shared parser floor (see `_portion_floor`).
        type=_portion_floor,
        default=0.1,
        help="Fraction of segments per file for formal training scope (default 0.1).",
    )
    parser.add_argument(
        "--formal_train_portion",
        # F-RC-1: the shared parser floor (see `_portion_floor`).
        type=_portion_floor,
        default=1.0,
        help="Per-epoch iteration fraction for formal training (default 1.0).",
    )
    parser.add_argument(
        "--formal_eval_portion",
        # F-RC-1: the shared parser floor (see `_portion_floor`).
        type=_portion_floor,
        default=1.0,
        help=(
            "Fraction of segments per file for the formal-mode eval scope "
            "(snapshot strategy). Default 1.0 = production full-clone for "
            "cross-architecture score comparability. Lower (e.g. 0.05) for "
            "smoke / CI runs that must fit --formal_time_budget_minutes "
            "(Phase R, §13)."
        ),
    )
    parser.add_argument(
        "--force_formal_round",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "When True (default), the last round of every iteration forces "
            "formal mode (planner is told 'formal mode is MANDATORY' and the "
            "post-LLM override flips is_trial=False). This is the production "
            "contract — produces a cross-architecture comparable formal "
            "score. Pass --no-force_formal_round to let the planner choose "
            "trial mode on the last round (planner is told 'formal mode is "
            "OPTIONAL' and no override fires). Use only for testing / "
            "debugging where the trial-mode portions need to take effect on "
            "the final round."
        ),
    )
    parser.add_argument(
        "--formal_round_strategy",
        type=str,
        choices=[
            "full_clone",
            "hybrid_params",
            "independent",  # canonical
            "inherit_best_trial",
            "llm_propose",  # legacy aliases
        ],
        default="full_clone",
        help=(
            "Orchestration policy for the forced formal round. "
            "'full_clone' (default): inherit model_config, loss_config, lr, "
            "epochs, and batch_size from the highest-scoring trial-mode "
            "success in the iteration. "
            "'hybrid_params': inherit only loss_config + lr (planner keeps "
            "model_config, epochs, batch_size). "
            "'independent': planner's choices honored verbatim. "
            "Legacy aliases accepted: 'inherit_best_trial' -> full_clone, "
            "'llm_propose' -> independent (resolved by schema). "
            "Has no effect when --no-force_formal_round is set."
        ),
    )
    parser.add_argument(
        "--degenerate_penalty_score",
        type=float,
        default=None,
        help=(
            "Operator policy for the agent's reaction when score_vector's "
            "task-specific health check flags a degenerate formal-round output. "
            "Default None nulls the denoising_score (the round can never be "
            "picked as 'best'). A float (typically large-negative, e.g. -5.0) "
            "is used as the round's score, letting the planner rank the "
            "failure below any healthy success. In both cases status is set "
            "to 'failed_mode_collapse' and failure_reason is preserved."
        ),
    )
    parser.add_argument(
        "--cleanup_denoised",
        action="store_true",
        help="Legacy cleanup request; incompatible with --retain_model_outputs.",
    )
    parser.add_argument(
        "--retain_model_outputs",
        action="store_true",
        help="Keep per-sample model outputs after scoring and Health (default: retire them).",
    )
    parser.add_argument(
        "--retain_training_checkpoints",
        action="store_true",
        help="Keep training checkpoint originals (default: retire after their consumers finish).",
    )
    parser.add_argument(
        "--human_advice_file",
        type=str,
        default=None,
        help="Path to a JSON file with human advice for each agent. "
        'Schema: {"interpret":"...", "analysis":"...", "propose":"...", '
        '"implement":"...", "validate":"...", "tune":"...", "mindset":"..."} '
        "— a string or a list of lines per key. The key set is CLOSED: an "
        "unrecognised key is refused as a probable misspelling (prefix it "
        "with '_' to declare it deliberately inert), as is a recognised key "
        "with empty content, and a file with no recognised key at all. "
        "Individual --human_advice_* flags override file values.",
    )
    parser.add_argument(
        "--human_advice_interpret",
        type=str,
        default=None,
        help="Human guidance for the interpretation agent.",
    )
    parser.add_argument(
        "--human_advice_analysis",
        type=str,
        default=None,
        help="Human guidance for the optional Data Analysis Agent.",
    )
    parser.add_argument(
        "--analysis_source_prompt",
        type=str,
        default=None,
        help=(
            "Inline source directive: auto or lock: raw=<asset IDs|all>; "
            "models=<all|none|last:N|last_rounds:N|ids:IDs>. "
            "last:N counts models; last_rounds:N counts prior iterations, including empty ones."
        ),
    )
    parser.add_argument(
        "--human_advice_propose",
        type=str,
        default=None,
        help="Human guidance for the proposal agent.",
    )
    parser.add_argument(
        "--human_advice_implement",
        type=str,
        default=None,
        help="Human guidance for the implementor agent.",
    )
    parser.add_argument(
        "--human_advice_validate",
        type=str,
        default=None,
        help="Human guidance for the validator agent.",
    )
    parser.add_argument(
        "--human_advice_tune", type=str, default=None, help="Human guidance for the tuning agent."
    )
    parser.add_argument(
        "--plan_overrides",
        type=str,
        default=None,
        help="JSON string of hard overrides for the LLM's ExperimentPlan. "
        'E.g. \'{"trial_portion": 0.2, "train_portion": 1.0}\'. '
        "Keys must be valid ExperimentPlan fields.",
    )
    parser.add_argument(
        "--workflow_parameter_rules",
        type=str,
        default=None,
        help=(
            "JSON object using the same ParameterRules schema as a task manifest. "
            "Omitted leaves the workflow unconstrained; exact rules lock values, "
            "while range, allowed, and registered predicate rules validate the "
            "agent's proposal."
        ),
    )
    # --- Workflow-level CLI flags (Phase 6.8 Commit 11) ---
    parser.add_argument(
        "--llm_config",
        type=str,
        default=None,
        help="Path to a WorkflowLLMConfig JSON file for per-node model routing. "
        "Overrides --llm_model when provided.",
    )
    parser.add_argument(
        "--healthgate_mode",
        choices=["blocking", "observe_only"],
        default=None,
        help="V20 PR D: whether HealthGate verdicts ENFORCE (blocking) or "
        "only record (observe_only). REQUIRED for a formal launch — there "
        "is no default, because defaulting would let this run claim "
        "enforcement nobody configured. Must agree with the HealthGate "
        "config's actual enforcement or the launch is refused.",
    )
    parser.add_argument(
        "--result_authority",
        choices=["scientific", "diagnostic"],
        default=None,
        help="V20 PR D: whether this run's results may inform science "
        "(scientific) or are diagnostic only. REQUIRED for a formal "
        "launch. observe_only+scientific is refused as a contradiction; "
        "blocking+diagnostic is legal.",
    )
    parser.add_argument(
        "--health_checks_config",
        type=str,
        default=None,
        help=(
            "Optional HealthGate YAML override forwarded unchanged to the tuner. "
            "None preserves the shipped default configuration."
        ),
    )
    # --- Run-scoped task composition (Step 10 P1) ---
    parser.add_argument(
        "--task_composition",
        type=str,
        required=True,
        help=(
            "Path to a required YAML task-composition manifest. "
            "Supplied, it binds this run's task data path, dataset profile, "
            "metric, Health family, interpretation blocks and task "
            "description/forward contract EXPLICITLY, and every unresolvable "
            "reference fails closed before any LLM call. See "
            "docs/design/generic_framework_upgrade/"
            "step_10_orchestration_task_binding/"
            "pr_10_p1_run_scoped_task_composition.md."
        ),
    )
    # --- DataScope + HealthGate subsystem (DS6c) ---
    parser.add_argument(
        "--data_scope",
        type=str,
        default=None,
        help=(
            "Restrict the chain to a file subset: '4-9', '4,5,6,7,8,9', or "
            "mixed '0-3,7' (both forms canonicalize to one sorted deduplicated "
            "list). Omitted = complete dataset. Pinned per workspace by the "
            "run-invariants lock. See docs/design/enable_partial_file_list.md."
        ),
    )
    parser.add_argument(
        "--health_gate_enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "HealthGate subsystem switch (default: enabled). "
            "--no-health_gate_enabled disables gate evaluation entirely; "
            "successful finite-score records then count as valid candidates. "
            "Pinned per workspace by the run-invariants lock."
        ),
    )
    parser.add_argument(
        "--health_gate_files",
        type=str,
        default=None,
        help=(
            "Run-level shared monitored-file list for ALL HealthGate checks "
            "(same spec format as --data_scope). Omitted + full scope = YAML "
            "defaults; omitted + partial scope = startup error."
        ),
    )
    parser.add_argument(
        "--advice",
        type=str,
        default=None,
        help="Path to a JSON advice file. Recognised keys: interpret, propose, "
        "implement, validate, tune, mindset — a string or a list of lines each. "
        "The key set is CLOSED and an artifact that could inject nothing is "
        "REFUSED at load (unrecognised key, empty declaration, or no recognised "
        "key), because the digest is pinned as the run's treatment identity "
        "whether or not the content ever reaches a prompt. "
        "Overrides --human_advice_file when provided.",
    )
    parser.add_argument(
        "--advice_sha256",
        type=str,
        default=None,
        help=(
            "DECLARED sha256 of the advice artifact's bytes, as observed by "
            "the launcher. Certified against this process's own read and then "
            "discarded — the workspace lock always pins the OBSERVED digest. "
            "A mismatch refuses the launch, which is how an edit between two "
            "band launches of one campaign is caught. Omit for hand-run "
            "chains: the observed digest is still pinned."
        ),
    )
    parser.add_argument(
        "--validation_max_portion",
        # F-RC-1: the SAME `_portion_floor` authority `--trial_portion` and
        # `--eval_portion` already use. This ceiling is clamped onto those
        # very fields, so a value below their 0.01 floor is refused at argv
        # time — before any LLM or GPU spend — instead of failing inside the
        # tuner's retry budget.
        type=_portion_floor,
        default=None,
        help="VALIDATION POSTURE ONLY (V20 FU-D-12). Hard ceiling on the "
        "RESOLVED trial-mode data portions (trial/train/eval), applied as "
        "min(planned, ceiling) beside the existing max_epochs clamp. Those "
        "three values come from the LLM PLAN rather than operator input, so "
        "without this a Gate that requested 0.02 can measure 0.1: time "
        "budgets bound wall time, not workload. A maximum, never a "
        "replacement — it can only reduce a planned portion. Omit for "
        "ordinary campaigns.",
    )
    parser.add_argument(
        "--validation_max_train_samples",
        type=int,
        default=None,
        help="VALIDATION POSTURE ONLY. Absolute ceiling on the ML segments "
        "one training epoch may contain — the Gate workload envelope. "
        "--validation_max_portion bounds the FRACTION; this bounds the "
        "AMOUNT, which the fraction cannot: samples per PSD segment are "
        "psd_segment_length // seg_size and seg_size is the planner's, so "
        "1%% of the scope resolved to 12,500 optimizer steps during "
        "Step 03. Applied where the epoch is BUILT, so fewer segments are "
        "read and fewer steps exist before any run — and it CLAMPS rather "
        "than rejects, unlike --max_steps_per_attempt, whose refusal "
        "skipped every round of a Gate attempt. Omit for ordinary "
        "campaigns.",
    )
    parser.add_argument(
        "--training_validation_portion",
        type=TypeAdapter(TrainingValidationPortion).validate_python,
        default=None,
        help="Task-owned seeded snapshot fraction for epoch loss only; final scoring scope is unchanged.",
    )
    parser.add_argument(
        "--validation_max_samples",
        type=int,
        default=None,
        help="VALIDATION POSTURE ONLY (07c). Absolute ceiling on the ML "
        "segments one VALIDATION pass may contain — the validation-row "
        "counterpart of --validation_max_train_samples, which bounds "
        "TRAINING rows. The two names differ by one word and bound "
        "DIFFERENT sets: 07a's Gate 2 capped the training epoch at 2,000 "
        "rows while validation ran the full 15,000-row eval SampleSet, "
        "7.5x the training work, every epoch. Applied to the REQUESTED "
        "scope before it materializes, so the exact-materialization "
        "invariant is never relaxed. Clamps to whole PSD segments and "
        "never overshoots; a ceiling below one PSD segment's rows is "
        "refused rather than resolving to an empty scope. INTERIM cost "
        "bounding, not the root fix — the priced deadline is. Omit for "
        "ordinary campaigns.",
    )
    parser.add_argument(
        "--validation_max_phase_seconds",
        type=float,
        default=None,
        help="VALIDATION POSTURE ONLY. Emergency wall-clock fuse for one "
        "execution phase, enforced by the existing runtime watchdog and "
        "never by admission (so it cannot skip the attempt). Requires "
        "--runtime_watchdog. NOT a sizing mechanism: normal Gate cost comes "
        "from --validation_max_train_samples and the data scope, which are "
        "enforced BEFORE launch. Set it well above the expected duration — "
        "a run killed at the deadline yields no evidence at all. The "
        "watchdog floor still applies: the effective ceiling is "
        "max(this, --runtime_watchdog_floor_seconds).",
    )
    parser.add_argument(
        "--validation_fixed_candidate_plan",
        type=str,
        default=None,
        help="VALIDATION POSTURE ONLY (V20 FU-D-11). Path to a JSON file "
        "holding a serialised ProposalOutput. When supplied the PROPOSER is "
        "bypassed and this candidate plan is used instead; implement, "
        "validate, trial, HealthGate, formal launch, authority, resume and "
        "aggregation all still run for real. Intended for acceptance runs "
        "that must not depend on which architecture a planner invents. The "
        "file may contain ONLY a candidate plan: unknown keys are REFUSED, "
        "so a stray score, record or verdict fails the launch instead of "
        "being silently dropped. Never use this in a normal campaign.",
    )
    parser.add_argument(
        "--max_impl_attempts",
        type=int,
        default=3,
        help="Max implementation retries per proposal when the validator rejects.",
    )
    parser.add_argument(
        "--target_files",
        type=int,
        nargs="+",
        default=None,
        help="DEPRECATED no-op (DS7) — warns and is ignored. Use --data_scope.",
    )
    parser.add_argument(
        "--sampling_seed",
        type=int,
        default=None,
        help="Seed for build_sample_set(). None auto-generates per gate.",
    )
    parser.add_argument(
        "--trial_time_budget_minutes",
        type=float,
        default=None,
        help="Trial wall-time budget in minutes. None disables Trial time admission.",
    )
    parser.add_argument(
        "--formal_time_budget_minutes",
        type=float,
        default=None,
        help="Formal wall-time budget in minutes. None disables Formal time admission.",
    )
    parser.add_argument(
        "--trial_time_admission_source",
        choices=("forecast", "measured"),
        default="measured",
        help=(
            "Single Trial wall-time admission authority. 'forecast' uses the "
            "advance workload forecast; 'measured' uses executing-device evidence."
        ),
    )
    parser.add_argument(
        "--runtime_completion_policy",
        choices=("completed-workload-v1", "verified-prediction-v1"),
        default="completed-workload-v1",
        help="Use actual completed-phase cost, or explicitly select historical strict verification.",
    )
    parser.add_argument(
        "--formal_time_admission_source",
        choices=("forecast", "measured"),
        default="measured",
        help=(
            "Single Formal wall-time admission authority. 'forecast' uses the "
            "advance workload forecast; 'measured' uses executing-device evidence."
        ),
    )
    # --- Runtime-control operator surface (RT6, runtime design §4/§5) ---
    # The chain is the OPERATIONAL surface: §5 provisional defaults live
    # here (schema defaults stay None). Pass 0 to disable a guardrail.
    parser.add_argument(
        "--max_steps_per_attempt",
        type=int,
        default=0,
        help="§5 guardrail: skip plans above this resolved optimizer-step "
        "count. 0 disables. Default 0 (disabled); time budgets govern runtime.",
    )
    parser.add_argument(
        "--min_formal_batch_size",
        type=int,
        default=0,
        help="§5 guardrail: skip FORMAL rounds planned below this batch "
        "size (V18 pathology; trial exempt). 0 disables. Default 0; "
        "task and campaign launchers may opt in explicitly.",
    )
    parser.add_argument(
        "--allow_extreme_steps",
        action="store_true",
        help="§5 operator override: bypass both step/batch guardrails.",
    )
    parser.add_argument(
        "--runtime_watchdog",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="§4 runtime watchdog: deadline-kill training/inference "
        "subprocess groups. Tri-state (arXiv #261 / Q-07c-6): "
        "--runtime_watchdog forces on, --no-runtime_watchdog forces off, "
        "and when NEITHER is passed the device/execution-regime runtime "
        "profile decides (configs/runtime/runtime_profiles.yaml + the measured "
        "overlay in $SIDERIUS_CALIBRATION_DIR). An uncalibrated pair "
        "resolves to the legacy default: off.",
    )
    parser.add_argument(
        "--runtime_safety_factor",
        type=float,
        default=1.0,
        help="§2.10 safety multiplier for admission + watchdog deadline. "
        "Default 1.0 (schema-mirroring); V18 production posture 1.5.",
    )
    parser.add_argument(
        "--runtime_trial_safety_factor",
        type=float,
        default=None,
        help="Phase-specific factor for TRIAL attempts; wins over "
        "--runtime_safety_factor when set. Effective V18r posture 3.0.",
    )
    parser.add_argument(
        "--runtime_formal_safety_factor",
        type=float,
        default=None,
        help="Phase-specific factor for FORMAL attempts; wins over "
        "--runtime_safety_factor when set.",
    )
    parser.add_argument(
        "--runtime_watchdog_safety_factor",
        type=float,
        default=None,
        help="V19 watchdog-only deadline multiplier (admission/watchdog "
        "split). Omitted -> watchdog uses the phase-effective admission "
        "factor exactly as V18. V19 5090 posture: 3.5.",
    )
    parser.add_argument(
        "--runtime_watchdog_floor_seconds",
        type=float,
        default=None,
        help="§4 watchdog deadline floor. Unset -> the device/execution "
        "profile's floor when the profile governs, else the legacy 60.0 "
        "(schema-mirroring); V18 production posture 120.0.",
    )
    parser.add_argument(
        "--runtime_verification_max_wall_seconds",
        type=float,
        default=None,
        help="Maximum wall time for adaptive in-subprocess runtime verification. "
        "Omit to preserve the verifier default. The verification steps are "
        "the first production steps, not a separate probe workload.",
    )
    parser.add_argument(
        "--execution_regime",
        type=str,
        choices=sorted(get_args(ExecutionRegime)),
        default="single",
        help="arXiv #261 — the launch's DECLARED execution topology, one "
        "half of the (device, regime) runtime-profile key. 'single' = one "
        "resident chain per card (the legacy shape); co-resident fleets "
        "declare their regime so watchdog numbers calibrated for one "
        "topology are never borrowed by another. Consulted only when no "
        "explicit --runtime_watchdog/--no-runtime_watchdog flag is passed.",
    )
    parser.add_argument(
        "--required_runtime_profile_path",
        type=str,
        default=None,
        help="F-H100-WD-1-PRETAG — the ABSOLUTE path of the profile artifact "
        "this launch requires. Part of the declaration and never derived: "
        "while the artifact was located by the ordinary discovery rule "
        "($SIDERIUS_CALIBRATION_DIR/runtime_profiles_<gpu_slug>.json), a "
        "binding certified WHAT was found but not that the right file was "
        "consulted — an overlay was used because the directory happened to "
        "hold it. When declared, resolution reads THIS file and never "
        "consults discovery. Must be paired with --required_runtime_profile "
        "and --required_runtime_profile_sha256; a relative path is refused, "
        "because the consuming subprocess has a different working directory.",
    )
    parser.add_argument(
        "--required_runtime_profile",
        type=str,
        default=None,
        help="F-H100-WD-1-PRETAG — DECLARE the runtime profile this launch "
        "REQUIRES, as '<gpu_slug>/<regime>' (e.g. "
        "'nvidia_h100_80gb_hbm3/single'), exactly as recorded in a prior "
        "qualification run's provenance. Must be paired with "
        "--required_runtime_profile_sha256. When declared, profile "
        "resolution is FAIL-CLOSED: the discovered device/regime must match, "
        "the measured overlay must hash to the declared digest, and it must "
        "carry that row — any miss REFUSES the launch instead of falling "
        "back to the shipped or uncalibrated profile. Omit both flags to "
        "keep the legacy ladder (measured > shipped > uncalibrated).",
    )
    parser.add_argument(
        "--required_runtime_profile_sha256",
        type=str,
        default=None,
        help="F-H100-WD-1-PRETAG — the 64-char lowercase-hex sha256 of the "
        "measured-overlay FILE certified for this run (e.g. `sha256sum "
        "$SIDERIUS_CALIBRATION_DIR/runtime_profiles_<slug>.json`). Must be "
        "paired with --required_runtime_profile. The digest is computed over "
        "the exact bytes parsed, so the profile consumed is provably the one "
        "that was qualified.",
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        required=True,
        help="Physical dataset directory for this run. "
        "The value is resolved and validated at launch, before any LLM "
        "or training work, and the resolved path is what reaches the "
        "real-dataset warmup AND the pre-phase GPU measurement.",
    )
    parser.add_argument(
        "--gpu_execution_policy_json",
        default=None,
        help="Explicit JSON policy for measured and protected native GPU execution.",
    )
    parser.add_argument(
        "--gpu_admission_measurement_source",
        type=str,
        default=None,
        help=(
            "V20 B-G3. Reference naming where an authoritative GPU measurement "
            "would be resolved from. NOT a figure -- there is deliberately no "
            "flag taking a raw MiB number, because one an operator could type "
            "would impersonate a measurement in formal mode. Unresolved before "
            "PR C, so formal rounds refuse with policy_unavailable."
        ),
    )
    parser.add_argument(
        "--gpu_admission_enforcement",
        choices=["observe_only", "enforce", "enforce_resource_limits"],
        default="observe_only",
        help=(
            "V20 B-G3/D-B4/M5. What the run DOES about an adverse GPU "
            "admission decision. Orthogonal to trial/formal. "
            "'observe_only' (default, compatibility) records the decision "
            "and proceeds. 'enforce_resource_limits' is the V20 PRODUCTION "
            "posture: it stops the phase on a resource verdict "
            "(insufficient_headroom) and records an evidence gap. "
            "'enforce' stops on any adverse decision — usable for the B-G "
            "validation harness, but NOT for a campaign, because the "
            "prephase measurement covers training only and every formal "
            "inference phase would refuse policy_unavailable."
        ),
    )
    parser.add_argument(
        "--gpu_pair_ceiling_gib",
        type=float,
        default=None,
        help=(
            "V20 B-G3. Aggregate GPU ceiling (GiB) passed explicitly to the "
            "admission gate. Omitted = defer to SIDERIUS_PAIR_VRAM_CEILING_GIB "
            "or measured device capacity. Host quota independently constrains "
            "the result; no machine-specific ceiling is assumed."
        ),
    )
    parser.add_argument(
        "--trial_vram_budget_gb",
        type=float,
        default=None,
        help="Per-mode VRAM ceiling (GB) for trial rounds. None uses free×0.8.",
    )
    parser.add_argument(
        "--formal_vram_budget_gb",
        type=float,
        default=None,
        help="Per-mode VRAM ceiling (GB) for formal rounds. None uses free×0.8.",
    )
    parser.add_argument(
        "--vram_probe_step_timeout_seconds",
        type=float,
        default=180.0,
        help=(
            "Maximum wall time for one training-mode or inference VRAM "
            "footprint forward (default: 180). This is not an epoch, "
            "optimizer step, or candidate-runtime budget."
        ),
    )
    parser.add_argument(
        "--vram_preflight_total_timeout_seconds",
        type=float,
        default=900.0,
        help=(
            "Maximum wall time for the complete isolated VRAM preflight "
            "worker (default: 900), independent of Trial/Formal runtime budgets."
        ),
    )
    parser.add_argument(
        "--vram_preflight_host_memory_limit_gb",
        type=float,
        default=None,
        help=(
            "Maximum resident host memory in GiB for the complete isolated "
            "VRAM-preflight process tree. Omission preserves the deployment "
            "default, normally 24 GiB. Independent of the GPU VRAM ceiling."
        ),
    )
    parser.add_argument(
        "--attempts_per_round",
        type=int,
        default=3,
        help="Inner attempt budget for trial rounds.",
    )
    parser.add_argument(
        "--attempts_per_formal_round",
        type=int,
        default=5,
        help="Inner attempt budget for the formal-promotion round.",
    )
    parser.add_argument(
        "--max_fail_rounds",
        type=int,
        default=3,
        help="Consecutive-failure brake for the tuner outer loop.",
    )
    parser.add_argument(
        "--exploration_mode",
        type=str,
        default="auto",
        choices=["auto", "explore", "exploit"],
        help="Reasoning pipeline mode.",
    )
    parser.add_argument(
        "--minimum_boldness",
        type=float,
        default=0.05,
        help="Minimum boldness threshold for FalsifiablePrediction.",
    )
    parser.add_argument(
        "--debug_dump_prompts",
        action="store_true",
        help="Dump rendered proposing-stage prompts to debug/ for audit.",
    )
    # --- Pseudo-mode flags (Stage 3 / Commit 4.5) ---
    # When set, the runner swaps the production ``LLMBridge`` /
    # ``TidmadSandbox`` for stateless ``StubLLMBridge`` / ``StubSandbox``
    # instances at the top of ``main()``. The chain still exercises the
    # full propose→implement→validate→tune wiring, but every LLM call
    # returns canned per-label output at $0 token cost and every training
    # call returns canned trial/formal scores. Defaults preserve the
    # production code path bit-for-bit. See
    # ``docs/audit_and_optimize_token_usage_and_growth.md`` Commit 4.5.
    parser.add_argument(
        "--is_pseudo_llm",
        action="store_true",
        help="Swap LLMBridge → StubLLMBridge for all 5 agents "
        "(interpret/propose/implement/validate/tune). Returns canned, "
        "Pydantic-valid per-label outputs at $0 token cost. Use for "
        "chain-wiring smoke tests; not for production runs.",
    )
    parser.add_argument(
        "--is_pseudo_training",
        action="store_true",
        help="Swap TidmadSandbox → StubSandbox in the tuner agent. Skips "
        "real training and returns canned trial / formal scores. Use "
        "for chain-wiring smoke tests; not for production runs.",
    )
    parser.add_argument(
        "--max_failed_iterations",
        type=_positive_int,
        default=3,
        help="Consecutive-failure brake (Stage 4 / Commit 4.6). Halt the "
        "chain when the most recent N iters all carry "
        "manifest.status='failed' (default 3). Brake is fail-open: "
        "missing or malformed manifests count as 'not failed', and "
        "'no_records' is never counted as a failure. On halt, writes "
        "{workspace}/.chain_halted and exits 3.",
    )
    # External agents (Commit 6 — 2026-06-12, Design Decisions 1 + 2):
    # two CLI flags for the ml_literature_review external agent — (1)
    # enable/disable toggle (BooleanOptionalAction), (2) YAML config
    # path. No other lit-review parameters are exposed at the CLI —
    # root_papers / dynamic_search / synthesis / confidence_rubric live
    # in the YAML; LLM routing lives in WorkflowLLMConfig.lit_review.
    # See docs/commit_plan_ml_literature_review.md Commit 6.
    parser.add_argument(
        "--ml_lit_review_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable / disable the ml_literature_review external agent. "
            "When set, overrides the YAML's top-level 'enabled' flag. "
            "When neither --ml_lit_review_enabled nor "
            "--no-ml_lit_review_enabled is passed (default None), the "
            "YAML's 'enabled' value drives the decision. The 'ml_' "
            "prefix establishes a naming convention for future external "
            "agents (e.g. --ml_physics_agent_enabled)."
        ),
    )
    parser.add_argument(
        "--ml_lit_review_config",
        type=str,
        default=None,
        help=(
            "Explicit path to the task or experiment's lit-review YAML config. "
            "Required when literature review is enabled; relative paths resolve "
            "against SIDERIUS_ROOT."
        ),
    )
    parser.add_argument(
        "--data_analysis_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable or disable task-composed Data Analysis. Unset preserves "
            "the composition's legacy behavior; enabled requires a binding."
        ),
    )
    parser.add_argument(
        "--scientific_evidence_order",
        choices=("analysis_then_literature", "literature_then_analysis"),
        default="analysis_then_literature",
        help=(
            "Workflow-owned ordering of the independent Data Analysis and Literature Review "
            "capabilities. The current campaign uses literature_then_analysis."
        ),
    )
    # arXiv U1 (#254) — the OPAQUE experiment-arm label. Pinned into the
    # workspace lock and stamped on every record / output / manifest; never
    # read to decide behaviour (ruling R2). Absent = unlabelled legacy run.
    parser.add_argument(
        "--experiment_arm",
        type=_experiment_arm_label,
        default=None,
        help=(
            "Opaque experiment-arm label for this chain (e.g. "
            "'with-prior-art' / 'without-prior-art'). Pinned into "
            "run_invariants_lock.json and stamped on every record, tuner "
            "output and manifest, so two workspaces differing in arm refuse "
            "to be resumed into one another. Provenance only — it drives NO "
            "behaviour; each arm's behaviour is set by its own explicit "
            "flags. Default: absent (unlabelled). An empty string is refused."
        ),
    )
    # arXiv U3 (#260) — the WITHOUT arm's EXPLICIT behaviour flag (ruling R6).
    parser.add_argument(
        "--baseline_isolation",
        action="store_true",
        default=False,
        help=(
            "Exclude the bundled baselines from this run's LLM-facing surface: "
            "the interpreter and tuner refuse a bundled ml_models/*/description.md "
            "(plugin descriptions still resolve), the proposer's prompts name no "
            "built-in architecture and no baseline score, and a proposal whose "
            "model_type is a bundled built-in is refused before implementation. "
            "Pinned into run_invariants_lock.json (a toggle on the same workspace "
            "is refused) and stamped on the manifest. Default: off."
        ),
    )

    # arXiv #259 (fleet ruling 2026-08-25) — declared output-type constraint.
    parser.add_argument(
        "--allowed_output_types",
        type=str,
        default=None,
        help=(
            "Comma-separated set of output types proposed models may declare "
            "(subset of: classifier,regressor). The proposer's prompt states "
            "the constraint and the deterministic schema gate refuses an "
            "out-of-set proposal before implementation. Omit for the "
            "unconstrained legacy behavior. The X9 campaign pins 'regressor' "
            "via the launcher."
        ),
    )
    parser.add_argument(
        "--print_resolved_launch_config",
        action="store_true",
        default=False,
        help=(
            "Print the resolved launch configuration (lit-review topology and "
            "config sha256, experiment arm, baseline isolation, task "
            "composition, workspace, advice file, declared posture) as ONE JSON "
            "object and exit 0 with NO side effects: no workspace directory, "
            "no LLM call, no lock. Used by the arm launcher's --dry-run."
        ),
    )
    # --- S2 / U5 (#258): explicit same-iteration manifest replacement ---
    parser.add_argument(
        "--replace_iteration_manifest",
        action="store_true",
        default=False,
        help=(
            "Iteration manifests are write-once: launching into an iter_NNN/ that "
            "already holds a manifest.json is REFUSED. Pass this flag (with "
            "--replacement_reason) to rerun the iteration deliberately: the previous "
            "manifest is kept as manifest.replaced.<stamp>.json and its digests are "
            "recorded under the new manifest's 'manifest_replacement' provenance. "
            "Integrity hashes are never regenerated silently."
        ),
    )
    parser.add_argument(
        "--replacement_reason",
        type=str,
        default=None,
        help=(
            "Why the iteration manifest is being replaced (required with "
            "--replace_iteration_manifest; recorded verbatim in the provenance)."
        ),
    )
    parser.add_argument(
        "--auto_resume",
        action="store_true",
        default=False,
        help=(
            "Declares that this launch was selected by the chain's auto-resume "
            "(run_chain.sh forwards it only when scripts/launch/inspect_run_state.py "
            "computed the start iteration). #258 refinement: with this flag, an "
            "existing same-iteration manifest whose terminal status is 'failed' "
            "or 'no_records' is replaced through the EXPLICIT replacement path — "
            "previous manifest kept on disk, provenance recorded with a "
            "recognizable 'auto_resume recovery' reason. A 'completed' manifest "
            "is never replaced by auto-resume; that still requires "
            "--replace_iteration_manifest --replacement_reason."
        ),
    )
    return parser


def _experiment_arm_label(value: str) -> str:
    """argparse type: an arm label is present and non-empty, or absent."""
    if not value.strip():
        raise argparse.ArgumentTypeError(
            "--experiment_arm must be a non-empty label; omit the flag for an "
            "unlabelled run (an empty string is never a label)."
        )
    return value


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    """Resolve the ``--start_iteration`` / ``--iteration`` alias and load
    deferred config (human advice file, plan overrides JSON) into ``args``.

    After this call, ``args.start_iteration`` is guaranteed to be a positive
    int, ``args.iteration_legacy`` is removed, and ``args.plan_overrides`` is
    a dict (or None). The original ``args`` namespace is mutated in place
    and also returned for convenience.

    Raises:
        SystemExit: when both/neither of ``--start_iteration`` and
            ``--iteration`` are supplied, or when ``--start_iteration < 1``.
            ``argparse.ArgumentParser.error`` is used so the message goes to
            stderr with a non-zero exit, matching argparse's own conventions.
    """
    parser = build_parser()  # only used to call .error() with consistent UX

    legacy = getattr(args, "iteration_legacy", None)
    canonical = args.start_iteration

    if legacy is not None and canonical is not None:
        parser.error(
            "--start_iteration and --iteration are mutually exclusive. "
            "--iteration is the deprecated alias; use --start_iteration only."
        )
    if legacy is None and canonical is None:
        parser.error("one of --start_iteration / --iteration is required.")
    if legacy is not None:
        warnings.warn(
            "--iteration is deprecated; use --start_iteration instead. "
            "The deprecated alias will be removed after the next stable run.",
            DeprecationWarning,
            stacklevel=2,
        )
        args.start_iteration = legacy

    # Drop the alias attr so downstream code can't accidentally read it.
    if hasattr(args, "iteration_legacy"):
        delattr(args, "iteration_legacy")

    if args.start_iteration < 1:
        parser.error(f"--start_iteration must be >= 1, got {args.start_iteration}")

    # --seed_paths / --source_paths alias collapse (Phase 6.8 Commit 11).
    # Same pattern as --start_iteration / --iteration above.
    seed_legacy = getattr(args, "source_paths_legacy", None)
    seed_canonical = args.seed_paths

    if seed_legacy is not None and seed_canonical is not None:
        parser.error(
            "--seed_paths and --source_paths are mutually exclusive. "
            "--source_paths is the deprecated alias; use --seed_paths only."
        )
    if seed_legacy is None and seed_canonical is None:
        # Neither flag supplied → cold start: no prior experimental evidence.
        # An empty seed list is valid; the workflow marks the first iteration
        # as cold_start. A bare --seed_paths with zero values is still an
        # argparse error (nargs="+"), so this branch only fires when the flag
        # is omitted entirely.
        args.seed_paths = []
    if seed_legacy is not None:
        warnings.warn(
            "--source_paths is deprecated; use --seed_paths instead. "
            "The deprecated alias will be removed after the next stable run.",
            DeprecationWarning,
            stacklevel=2,
        )
        args.seed_paths = seed_legacy

    if hasattr(args, "source_paths_legacy"):
        delattr(args, "source_paths_legacy")

    # Load human advice through the ONE artifact authority, which resolves
    # the --advice / --human_advice_file precedence, certifies any declared
    # digest and caches the OBSERVED one for `resolve_launch_identity`.
    # Both advice schemas are tolerated during transition; missing keys are
    # None.
    artifact = resolve_advice_artifact(args)
    if artifact is not None:
        advice = artifact.content
        # Normalise list-of-lines form through the SAME authority the loader
        # used to decide these keys carry content (F-SCHED-5): a second
        # rendering rule here is how a key the loader accepted would be
        # dropped in silence anyway.
        advice = {k: render_advice_value(v) for k, v in advice.items()}
        # 4-key schema: propose, implement, tune, mindset
        # Additive schema: analysis is optional and follows the same authority.
        for key in ADVICE_PER_AGENT_KEYS:
            attr = f"human_advice_{key}"
            if getattr(args, attr) is None:
                setattr(args, attr, advice.get(key) or None)
        # 4-key mindset (not a per-agent key, forwarded as-is)
        if not hasattr(args, "human_advice_mindset") or args.human_advice_mindset is None:
            args.human_advice_mindset = advice.get("mindset") or None
    else:
        args.human_advice_mindset = None

    # Parse plan overrides from JSON string into a dict
    if args.plan_overrides:
        args.plan_overrides = json.loads(args.plan_overrides)
    else:
        args.plan_overrides = None
    try:
        args.workflow_parameter_rules = (
            ParameterRules.model_validate_json(args.workflow_parameter_rules)
            if args.workflow_parameter_rules
            else None
        )
    except ValueError as exc:
        parser.error(f"--workflow_parameter_rules is invalid: {exc}")

    # DS7 — deprecated no-op strategy flags (removal tracked as FU-2).
    if args.trial_strategy != "snapshot" or args.target_files is not None:
        warnings.warn(
            "--trial_strategy / --target_files are deprecated and IGNORED "
            "(DS7): the input fields they fed were dead at both ends and have "
            "been removed. Use --data_scope to restrict data.",
            DeprecationWarning,
            stacklevel=2,
        )

    # DS6c — parse DataScope specs. Both '4-9' and '4,5,6,7,8,9' (and mixed)
    # canonicalize to one sorted deduplicated list inside DataScope.
    try:
        args.data_scope = DataScope.from_cli(args.data_scope) if args.data_scope else None
        args.health_gate_files = (
            DataScope.from_cli(args.health_gate_files).file_indices
            if args.health_gate_files
            else None
        )
        # V19 PR 2 — a file ORDER is a sequence, so it must NOT go through
        # DataScope.from_cli, which sorts and dedupes. Doing so would
        # silently rewrite the operator's permutation into ascending order.
        args.file_order_override = (
            parse_file_order_cli(args.file_order_override) if args.file_order_override else None
        )
        # V19 PR 3 — validate the retention policy at STARTUP (fail before
        # any resume mutation or LLM work; ge=1 enforced by the schema).
        # The resolved policy is only consumed by the interpreter, but a
        # bad value must not produce a partial run. Pydantic's
        # ValidationError is a ValueError, so the shared parser.error
        # path below reports it and exits non-zero.
        HealthFeedbackRetentionPolicy(
            history_window_iterations=args.health_feedback_history_window_iterations,
            max_entries_per_model=args.health_feedback_history_max_entries_per_model,
        )
    except ValueError as e:
        parser.error(str(e))

    return args
