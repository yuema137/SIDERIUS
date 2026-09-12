"""Tuner NODE CLI — the argparse surface and args -> HyperparamTuningInput.

Step 07 PR 07b, C7 (operator scope amendment): extracted VERBATIM from
``main()``, which had grown to 578 lines of option declarations. Zero
behaviour change — ``--help`` is byte-identical and the assembled
``HyperparamTuningInput`` is deep-equal, both pinned by tests.

The node's ``main()`` stays where it belongs, in the main module: it is the
entrypoint, and a reader looking for "how is this node invoked" should find it
next to the agent it invokes. What moved here is the *surface* — 60-odd option
declarations and the translation from ``argparse.Namespace`` to the validated
input schema — because that is a self-contained responsibility with one
consumer and one obvious test (parse these flags, get this input).
"""

import argparse
import warnings

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.ordering import parse_file_order_cli
from execute_tools.dataset_config import DataScope

#: Exit code for a campaign that ran but did not complete every round.
#: Lives with the CLI because it is part of the CLI contract.
PARTIAL_CAMPAIGN_EXIT_CODE = 2


def build_parser() -> argparse.ArgumentParser:
    """The node's complete argparse surface.

    Returned unparsed so callers (and tests) can inspect defaults, choices
    and help text without executing a run.
    """
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

    # Trial and Formal own independent budgets and authority selections.
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
        "--data_dir",
        type=str,
        required=True,
        help="Physical data directory for the declared task. ",
    )
    parser.add_argument(
        "--health_checks_config",
        type=str,
        default=None,
        help="Optional HealthGate YAML override; omitted uses configs/health/health_checks.yaml.",
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
        "--trial_time_admission_source",
        choices=("forecast", "measured"),
        default="measured",
        help=(
            "Single Trial wall-time admission authority. Forecast skips "
            "executing-device enforcement; measured skips advance forecast "
            "admission."
        ),
    )
    parser.add_argument(
        "--formal_time_admission_source",
        choices=("forecast", "measured"),
        default="measured",
        help=(
            "Single Formal wall-time admission authority. Forecast skips "
            "executing-device enforcement; measured skips advance forecast "
            "admission."
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
            "in the round loop). Default None = no clamp (LLM plan unchanged). "
            "Per-mode overrides: --trial_max_epochs / --formal_max_epochs "
            "take precedence for their round role (D-BUD-6)."
        ),
    )
    parser.add_argument(
        "--vram_probe_step_timeout_seconds",
        type=float,
        default=180.0,
        help=(
            "Maximum wall time for one training-mode or inference VRAM "
            "footprint forward (default 180). It is not a training-step or "
            "epoch budget."
        ),
    )
    parser.add_argument(
        "--vram_preflight_total_timeout_seconds",
        type=float,
        default=900.0,
        help=("Maximum wall time for the complete isolated VRAM preflight worker (default 900)."),
    )
    parser.add_argument(
        "--vram_preflight_host_memory_limit_gb",
        type=float,
        default=None,
        help=(
            "Maximum resident host memory in GiB for the complete isolated "
            "VRAM-preflight process tree. Omission preserves the deployment "
            "default, normally 24 GiB. This is not the GPU VRAM ceiling."
        ),
    )
    parser.add_argument(
        "--trial_max_epochs",
        type=int,
        default=None,
        help=(
            "TRIAL-role epoch ceiling (campaign decision D-BUD-6). Precedence "
            "for a trial round: this value -> --max_epochs -> no clamp; "
            "formal rounds never read it. Wires into "
            "HyperparamTuningInput.trial_max_epochs (ge=1 — zero/negative "
            "refuse loudly at input validation). Default None = trial rounds "
            "keep the mode-agnostic --max_epochs."
        ),
    )
    parser.add_argument(
        "--formal_max_epochs",
        type=int,
        default=None,
        help=(
            "FORMAL-role epoch ceiling (campaign decision D-BUD-6). "
            "Precedence for a formal round: this value -> --max_epochs -> no "
            "clamp; trial rounds never read it. Wires into "
            "HyperparamTuningInput.formal_max_epochs (ge=1 — zero/negative "
            "refuse loudly at input validation). Default None = formal rounds "
            "keep the mode-agnostic --max_epochs."
        ),
    )
    # --- RT6: runtime-control operator surface (design §4/§5) ---
    # The step ceiling remains an operational default.  The Formal-only batch
    # floor is opt-in: Trial success is executable evidence, so a generic
    # launcher must not silently reject the same batch size in Formal.
    # Pass 0 to disable a numeric guardrail.
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
        default=0,
        help="§5 guardrail: skip FORMAL rounds planned below this batch size "
        "(the V18 launch-overhead pathology; trial rounds exempt). 0 "
        "disables. Default 0 (disabled); set an explicit task/campaign value "
        "only when its execution contract requires one.",
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
        "--runtime_verification_max_wall_seconds",
        type=float,
        default=None,
        help="Maximum wall time for adaptive in-subprocess runtime verification. "
        "Omit to preserve the verifier default.",
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
    parser.add_argument(
        "--task_composition",
        type=str,
        required=True,
        help=(
            "Path to a required YAML task-composition manifest. "
            "Supplied, it binds this run's task data path, dataset profile, "
            "metric, declared secondaries, Health family and task "
            "description/forward contract EXPLICITLY, and every "
            "unresolvable reference fails closed before any LLM call. "
            "Same manifest shape and same composition authority the chain "
            "launcher's --task_composition already uses "
            "(sdsc_submission_scripts/run_chain.sh) — added here (Step 12 "
            "/ PR-12d D8a) so a SINGLE model can be run composed and "
            "--force_model-locked in one launch, without the multi-agent "
            "chain's proposer choosing the architecture. "
            "docs/design/generic_framework_upgrade/"
            "step_10_orchestration_task_binding/"
            "pr_10_p1_run_scoped_task_composition.md."
        ),
    )
    return parser


def build_agent_input(
    args: argparse.Namespace, parser: argparse.ArgumentParser, run_composition: object = None
) -> HyperparamTuningInput:
    """Translate parsed CLI arguments into the validated node input.

    Takes the ``parser`` because one check reports through ``parser.error()``:
    a plugin ``--force_model`` with no ``--seed_plugin_path`` is CLI MISUSE,
    and argparse's usage message plus exit code 2 is the contract for that —
    not an exception from inside the run.

    Every conditional below is the CLI contract: which flags are mutually
    exclusive, which only apply in trial mode, and which stay absent from
    the input entirely when the operator did not pass them (absent is not
    the same as a default, and the schema distinguishes them).
    """
    from ml_models.models_sandbox import MODEL_REGISTRY

    builtin_choices = [*MODEL_REGISTRY.keys(), "auto"]

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
    input_dict["trial_time_admission_source"] = args.trial_time_admission_source
    input_dict["formal_time_admission_source"] = args.formal_time_admission_source
    if args.max_epochs is not None:
        input_dict["max_epochs"] = args.max_epochs
    # D-BUD-6 — forwarded only when set, so an unset per-mode cap leaves the
    # input on its schema default (None = the mode-agnostic max_epochs
    # governs that role) and legacy invocations are byte-identical.
    if args.trial_max_epochs is not None:
        input_dict["trial_max_epochs"] = args.trial_max_epochs
    if args.formal_max_epochs is not None:
        input_dict["formal_max_epochs"] = args.formal_max_epochs
    if args.data_dir is not None:
        input_dict["data_dir"] = args.data_dir
    if args.trial_vram_budget_gb is not None:
        input_dict["trial_vram_budget_gb"] = args.trial_vram_budget_gb
    if args.formal_vram_budget_gb is not None:
        input_dict["formal_vram_budget_gb"] = args.formal_vram_budget_gb
    input_dict["vram_probe_step_timeout_seconds"] = args.vram_probe_step_timeout_seconds
    input_dict["vram_preflight_total_timeout_seconds"] = args.vram_preflight_total_timeout_seconds
    input_dict["vram_preflight_host_memory_limit_gb"] = args.vram_preflight_host_memory_limit_gb

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
    input_dict["runtime_verification_max_wall_seconds"] = args.runtime_verification_max_wall_seconds

    # Step 12 / PR-12d D8a. `run_composition` is the SAME object `main()`
    # binds around `.run()` — passed in rather than re-composed here, so
    # there is exactly ONE composition per process (re-composing a second
    # time from `args.task_composition` would be a second resolution the
    # registry-identity rules (Step 12 / PR-12bc CASE A) treat as a fresh
    # instance, not the same one). `None` for an un-composed run, which is
    # what makes `task_composition_ref` absent and this whole branch
    # invisible to regime A.
    from workflows.task_composition import build_task_composition_ref

    input_dict["task_composition_ref"] = build_task_composition_ref(run_composition)

    agent_input = HyperparamTuningInput.model_validate(input_dict)
    return agent_input
