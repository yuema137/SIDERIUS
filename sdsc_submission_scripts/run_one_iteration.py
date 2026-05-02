#!/usr/bin/env python3
"""
Per-iteration runner for the SIDERIUS exploration workflow.

Runs ONE iteration of `run_workflow()` (max_iterations=1) using explicit
source paths. Designed for per-iteration Slurm jobs where each job is
1-4 hours and the workflow is chained across many jobs.

Each iteration:
  1. Loads source data from explicit paths (seeds + previous iterations)
  2. Runs the 5-agent loop (interpret → propose → implement → validate → tune)
  3. Writes a manifest.json summarizing the iteration's output for the next job

Usage:
    python sdsc_submission_scripts/run_one_iteration.py \\
        --workspace /scratch/exploration_v1 \\
        --start_iteration 3 \\
        --source_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json \\
        --max_rounds 20 \\
        --llm_model gemini-3.1-pro-preview \\
        --gpu_memory_limit_gb 10

When ``--start_iteration > 1`` the runner auto-restores plugin classes
from iters [1, N-1] in ``{workspace}/plugins/iter_NNN/`` and prepends
their ``run_output_*.json`` paths onto the seed list — operators no
longer pass prior iters' run_outputs explicitly. The deprecated
``--iteration`` alias is still accepted for one release; use
``--start_iteration`` for new chains.
"""
import argparse
import glob
import json
import os
import sys
import traceback
import warnings

# Ensure SIDERIUS root is importable
SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SIDERIUS_ROOT)
sys.path.insert(0, os.path.join(SIDERIUS_ROOT, "ml_models"))

from dotenv import load_dotenv
load_dotenv()

from workflows.model_exploration import run_workflow
from workflows.llm_config import WorkflowLLMConfig
from core.resume import restore_prior_state, ResumeError


def _positive_int(s: str) -> int:
    """argparse type validator: parse a positive integer (>= 1).

    Used by --max_epochs (Phase 6.8 Commit 11): None / 0 / negative are
    strictly forbidden — every chain run must train for at least one epoch.
    """
    try:
        v = int(s)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"expected a positive integer, got {s!r}"
        )
    if v < 1:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer (>= 1), got {v}"
        )
    return v


def resolve_source_paths(source_paths: list[str]) -> list[str]:
    """
    Resolve source path entries to actual JSON file paths.

    Two formats are supported:
      - Direct path: /scratch/.../run_output_*.json (used as-is)
      - Manifest indirection: @manifest:/path/to/manifest.json (read manifest,
        return manifest['output_path'])

    The manifest indirection is used by the orchestrator script when chaining
    iterations: the manifest path is known at submission time, but the actual
    output file path inside it is only known after the iteration completes.
    """
    resolved = []
    for entry in source_paths:
        if entry.startswith("@manifest:"):
            manifest_path = entry[len("@manifest:"):]
            if not os.path.exists(manifest_path):
                raise FileNotFoundError(
                    f"Manifest not found (previous iteration may have failed): {manifest_path}"
                )
            with open(manifest_path) as f:
                manifest = json.load(f)
            status = manifest.get("status")
            if status != "completed":
                raise ValueError(
                    f"Refusing to chain off manifest with status={status!r}: "
                    f"{manifest_path}. Previous iteration did not produce a "
                    f"valid score (best_score={manifest.get('best_score')!r})."
                )
            output_path = manifest.get("output_path")
            if not output_path:
                raise ValueError(f"Manifest has no output_path: {manifest_path}")
            print(f"  Resolved @manifest:{manifest_path} → {output_path}")
            resolved.append(output_path)
        else:
            resolved.append(entry)
    return resolved


def write_manifest(
    iter_dir: str, run_name: str, results: list, *, crashed: bool = False,
) -> dict:
    """
    Write a manifest.json summarizing this iteration's output.

    The manifest is the discoverable handoff between iterations: the next
    iteration's job reads it to find this iteration's tuning output path.

    Status taxonomy (consumed by ``core/resume.py:_read_manifest``):
      * ``"completed"`` — workflow produced a real best_denoising_score.
        Resume: consume the run_output and restore the plugin.
      * ``"no_records"`` — workflow ran cleanly but every tuner round
        failed/was skipped (gate exhaustion, all-rounds returned None
        score). The chain MUST keep going so the next iter's LLM can see
        the skips and adapt. Resume: skip this iter, no plugin to restore.
      * ``"failed"`` — workflow itself crashed (Python exception, seed-
        resolution error, restore_prior_state error). The chain halts.
        Set via ``crashed=True``.
    """
    if crashed:
        manifest = {
            "status": "failed",
            "iteration_dir": iter_dir,
            "output_path": None,
            "model_name": None,
            "best_score": None,
        }
    elif not results:
        manifest = {
            "status": "no_records",
            "iteration_dir": iter_dir,
            "output_path": None,
            "model_name": None,
            "best_score": None,
        }
    else:
        tune_output = results[0]
        # The tuning output is at {iter_dir}/iteration_001/{model_name}/run_output_{run_name}.json
        # (run_workflow always wraps each iteration in iteration_NNN, even with max_iterations=1)
        model_name = tune_output.model_type
        output_path = os.path.join(
            iter_dir, "iteration_001", model_name, f"run_output_{run_name}.json"
        )
        if not os.path.exists(output_path):
            # Defensive: scan iter_dir for the actual file
            candidates = glob.glob(
                os.path.join(iter_dir, "**", f"run_output_{run_name}.json"),
                recursive=True,
            )
            if candidates:
                output_path = candidates[0]
        # A None best_denoising_score means every tuner round was skipped
        # or returned no score (gate exhaustion or LLM-level dead-end).
        # Mark as no_records so the chain continues; resume will see the
        # null output_path and skip this iter cleanly.
        score = tune_output.best_denoising_score
        manifest = {
            "status": "completed" if score is not None else "no_records",
            "iteration_dir": iter_dir,
            "output_path": output_path if score is not None else None,
            "model_name": model_name,
            "best_score": score,
            "completed_rounds": tune_output.completed_rounds,
        }

    manifest_path = os.path.join(iter_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest written: {manifest_path}")
    return manifest


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
        "--workspace", type=str, required=True,
        help="Root output directory for this exploration (shared across all iterations)."
    )
    # Phase 6.8 Task 2 Commit 8 — rename --iteration → --start_iteration so the
    # name matches the unified resume/chain philosophy ("which iter is this
    # invocation about to run; iters [1, N-1] are absorbed from disk").
    # The positional meaning is unchanged; only the name moves. --iteration is
    # kept as a deprecated alias for one release. See
    # docs/phase68_orchestrator_memory_and_resume.md §3.5 Commit 8.
    parser.add_argument(
        "--start_iteration", type=int, default=None,
        help="Iteration number (1-based) to run *now*. When > 1, the runner "
             "auto-restores plugin classes from iters [1, N-1] via "
             "core.resume.restore_prior_state. Mutually exclusive with the "
             "deprecated --iteration alias."
    )
    parser.add_argument(
        "--iteration", type=int, default=None, dest="iteration_legacy",
        help="DEPRECATED — alias for --start_iteration. Will be removed after "
             "the next stable run. Use --start_iteration instead."
    )
    # Phase 6.8 Commit 11 — rename --source_paths → --seed_paths so the
    # canonical name reflects what the list actually means: *seed* source
    # data, not the full source set (prior iters are auto-discovered from
    # {workspace}/iter_NNN/manifest.json). --source_paths is kept as a
    # deprecated alias for one release. See §3.5 Commit 11.
    parser.add_argument(
        "--seed_paths", type=str, nargs="+", default=None,
        help="Explicit list of HyperparamTuningOutput JSON paths to use as "
             "*seed* source data. Prior iters' run_outputs are auto-discovered "
             "from {workspace}/iter_NNN/manifest.json by restore_prior_state — "
             "they no longer need to be listed here for chain runs (back-compat "
             "still accepts @manifest: indirection in this list). "
             "Mutually exclusive with the deprecated --source_paths alias."
    )
    parser.add_argument(
        "--source_paths", type=str, nargs="+", default=None,
        dest="source_paths_legacy",
        help="DEPRECATED — alias for --seed_paths. Will be removed after "
             "the next stable run. Use --seed_paths instead."
    )
    parser.add_argument(
        "--max_rounds", type=int, default=3,
        help="Tuning rounds per iteration."
    )
    parser.add_argument(
        "--max_proposal_attempts", type=int, default=3,
        help="Retry budget for propose→implement→validate."
    )
    parser.add_argument(
        "--llm_model", type=str, default="gemini-3.1-pro-preview",
        help="Gemini model ID for all 5 agents (the planner sub-call of the "
             "tuner uses this; the reflector sub-call uses --reflect_model_id "
             "if set, else falls back to a provider-aware default)."
    )
    parser.add_argument(
        "--reflect_provider", type=str, default=None, choices=["gemini", "openai"],
        help="Optional separate provider for the tuner's reflector sub-call. "
             "When unset, the reflector uses the same provider as the planner."
    )
    parser.add_argument(
        "--reflect_model_id", type=str, default=None,
        help="Optional separate model for the tuner's reflector sub-call. "
             "When unset for the gemini provider, defaults to 'gemini-2.5-flash' "
             "(GA model with unlimited daily quota). When unset for other "
             "providers, falls back to --llm_model (legacy behavior)."
    )
    parser.add_argument(
        "--gpu_memory_limit_gb", type=int, default=None,
        help="Hard cap on GPU memory per process (Phase 2, not yet implemented end-to-end)."
    )
    parser.add_argument(
        "--max_epochs", type=_positive_int, default=1,
        help="Hard cap on epochs per round. Must be >= 1; None forbidden."
    )
    parser.add_argument(
        "--is_trial", action="store_true",
        help="Enable trial mode (default: True for production)."
    )
    parser.add_argument(
        "--trial_strategy", type=str, default="snapshot",
        choices=["snapshot", "anchors", "target"],
    )
    parser.add_argument(
        "--trial_portion", type=float, default=0.1)
    parser.add_argument(
        "--train_portion", type=float, default=0.1)
    parser.add_argument(
        "--eval_portion", type=float, default=0.1)
    # --- Formal-mode training levers (Phase M, docs/resource_estimator_implement.md §12) ---
    # Eval side in formal mode is hardcoded to snapshot + eval_portion=1.0 in
    # the tuner (intentionally NOT operator-configurable — see §12.2).
    parser.add_argument(
        "--formal_strategy", type=str, default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="Training-side strategy on formal rounds (default snapshot).",
    )
    parser.add_argument(
        "--formal_portion", type=float, default=0.1,
        help="Fraction of segments per file for formal training scope (default 0.1).",
    )
    parser.add_argument(
        "--formal_train_portion", type=float, default=1.0,
        help="Per-epoch iteration fraction for formal training (default 1.0).",
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
            "full_clone", "hybrid_params", "independent",  # canonical
            "inherit_best_trial", "llm_propose",            # legacy aliases
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
        "--cleanup_denoised", action="store_true",
        help="Delete denoised H5 files after scoring (recommended for production)."
    )
    parser.add_argument(
        "--human_advice_file", type=str, default=None,
        help="Path to a JSON file with human advice for each agent. "
             "Schema: {\"interpret\":\"...\", \"propose\":\"...\", "
             "\"implement\":\"...\", \"validate\":\"...\", \"tune\":\"...\"}. "
             "Individual --human_advice_* flags override file values."
    )
    parser.add_argument(
        "--human_advice_interpret", type=str, default=None,
        help="Human guidance for the interpretation agent."
    )
    parser.add_argument(
        "--human_advice_propose", type=str, default=None,
        help="Human guidance for the proposal agent."
    )
    parser.add_argument(
        "--human_advice_implement", type=str, default=None,
        help="Human guidance for the implementor agent."
    )
    parser.add_argument(
        "--human_advice_validate", type=str, default=None,
        help="Human guidance for the validator agent."
    )
    parser.add_argument(
        "--human_advice_tune", type=str, default=None,
        help="Human guidance for the tuning agent."
    )
    parser.add_argument(
        "--plan_overrides", type=str, default=None,
        help="JSON string of hard overrides for the LLM's ExperimentPlan. "
             "E.g. '{\"trial_portion\": 0.2, \"train_portion\": 1.0}'. "
             "Keys must be valid ExperimentPlan fields."
    )
    # --- Flags synced with run_exploration_adaptive.py (Phase 6.8 Commit 11) ---
    parser.add_argument(
        "--llm_config", type=str, default=None,
        help="Path to a WorkflowLLMConfig JSON file for per-node model routing. "
             "Overrides --llm_model when provided.",
    )
    parser.add_argument(
        "--advice", type=str, default=None,
        help="Path to a JSON advice file (propose/implement/tune/mindset keys). "
             "Overrides --human_advice_file when provided.",
    )
    parser.add_argument(
        "--max_impl_attempts", type=int, default=3,
        help="Max implementation retries per proposal when the validator rejects.",
    )
    parser.add_argument(
        "--target_files", type=int, nargs="+", default=None,
        help="File indices for --trial_strategy=target.",
    )
    parser.add_argument(
        "--sampling_seed", type=int, default=None,
        help="Seed for build_sample_set(). None auto-generates per gate.",
    )
    parser.add_argument(
        "--trial_time_budget_minutes", type=float, default=None,
        help="Wall-time budget (minutes) for trial-mode time gate. None disables.",
    )
    parser.add_argument(
        "--formal_time_budget_minutes", type=float, default=None,
        help="Wall-time budget (minutes) for formal-mode time gate. None disables.",
    )
    parser.add_argument(
        "--data_dir", type=str, default=None,
        help="TIDMAD data directory for evaluate_time_skill's real-dataset warmup. "
             "None falls back to the static formula.",
    )
    parser.add_argument(
        "--trial_vram_budget_gb", type=float, default=None,
        help="Per-mode VRAM ceiling (GB) for trial rounds. None uses free×0.8.",
    )
    parser.add_argument(
        "--formal_vram_budget_gb", type=float, default=None,
        help="Per-mode VRAM ceiling (GB) for formal rounds. None uses free×0.8.",
    )
    parser.add_argument(
        "--attempts_per_round", type=int, default=3,
        help="Inner attempt budget for trial rounds.",
    )
    parser.add_argument(
        "--attempts_per_formal_round", type=int, default=5,
        help="Inner attempt budget for the formal-promotion round.",
    )
    parser.add_argument(
        "--max_fail_rounds", type=int, default=3,
        help="Consecutive-failure brake for the tuner outer loop.",
    )
    parser.add_argument(
        "--exploration_mode", type=str, default="auto",
        choices=["auto", "explore", "exploit"],
        help="Reasoning pipeline mode.",
    )
    parser.add_argument(
        "--minimum_boldness", type=float, default=0.05,
        help="Minimum boldness threshold for FalsifiablePrediction.",
    )
    parser.add_argument(
        "--debug_dump_prompts", action="store_true",
        help="Dump rendered proposing-stage prompts to debug/ for audit.",
    )
    return parser


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
        parser.error(
            "one of --start_iteration / --iteration is required."
        )
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
        parser.error(
            f"--start_iteration must be >= 1, got {args.start_iteration}"
        )

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
        parser.error(
            "one of --seed_paths / --source_paths is required."
        )
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

    # Load human advice: --advice (4-key) takes precedence over --human_advice_file (5-key).
    # Both schemas are tolerated during transition; missing keys are None.
    advice_path = args.advice or args.human_advice_file
    if advice_path:
        with open(advice_path) as f:
            advice = json.load(f)
        # Normalise list-of-lines form (same as run_exploration_adaptive.py)
        advice = {k: ("\n".join(v) if isinstance(v, list) else v)
                  for k, v in advice.items()}
        # 4-key schema: propose, implement, tune, mindset
        # 5-key schema: interpret, propose, implement, validate, tune
        for key in ("interpret", "propose", "implement", "validate", "tune"):
            attr = f"human_advice_{key}"
            if getattr(args, attr) is None:
                setattr(args, attr, advice.get(key) or None)
        # 4-key mindset (not a per-agent key, forwarded as-is)
        if not hasattr(args, "human_advice_mindset") or getattr(args, "human_advice_mindset") is None:
            args.human_advice_mindset = advice.get("mindset") or None
    else:
        args.human_advice_mindset = None

    # Parse plan overrides from JSON string into a dict
    if args.plan_overrides:
        args.plan_overrides = json.loads(args.plan_overrides)
    else:
        args.plan_overrides = None

    return args


def main():
    args = normalize_args(build_parser().parse_args())

    # Iteration directory: {workspace}/iter_{N:03d}
    run_name = f"iter_{args.start_iteration:03d}"
    iter_dir = os.path.join(args.workspace, run_name)
    os.makedirs(iter_dir, exist_ok=True)

    # Process-global anchor — ``ml_models.model_descriptions.get_model_description``
    # reads this to resolve agent-generated plugin descriptions written under
    # ``{workspace}/plugins/iter_NNN/{model_type}/description.md`` by
    # ``workflows.model_exploration._register_plugin``. Set as early as
    # possible so any descendant node call sees it.
    os.environ["SIDERIUS_CHAIN_WORKSPACE"] = os.path.abspath(args.workspace)

    print("=" * 60)
    # --- Resolve reflect provider/model defaults ---
    # The tuner's reflector sub-call does templated extraction (not
    # reasoning), so it benefits from a faster/cheaper/higher-quota model
    # than the planner. For the gemini provider, default the reflector to
    # gemini-2.5-flash (GA model, unlimited daily quota, strong JSON-mode).
    # The planner stays on the main --llm_model.
    reflect_provider = args.reflect_provider
    reflect_model_id = args.reflect_model_id
    if reflect_model_id is None and reflect_provider is None:
        # Apply gemini-specific default (the chain runner only supports gemini today)
        reflect_model_id = "gemini-2.5-flash"

    print(f"  SIDERIUS PER-ITERATION RUNNER")
    print(f"  Workspace        : {args.workspace}")
    print(f"  Start iteration  : {args.start_iteration}")
    print(f"  Run name         : {run_name}")
    print(f"  Iter directory   : {iter_dir}")
    print(f"  LLM (planner)    : gemini / {args.llm_model}")
    eff_reflect_provider = reflect_provider or "gemini"
    eff_reflect_model_id = reflect_model_id or args.llm_model
    print(f"  LLM (reflector)  : {eff_reflect_provider} / {eff_reflect_model_id}")
    print(f"  Seed source paths: {len(args.seed_paths)} entries")
    for p in args.seed_paths:
        print(f"    - {p}")
    print("=" * 60)

    # Step 1 — back-compat resolution of @manifest: indirection in the seed
    # list. The legacy chain shell still passes manifests this way; the new
    # run_chain.sh (Commit 11) won't, but we keep the resolver layered in
    # front of restore_prior_state so existing callers don't break.
    # TODO (Phase 6.8 Commit 11): Remove back-compat layer once unified
    #     run_chain.sh ships and no caller still emits @manifest: prefixes.
    try:
        resolved_seeds = resolve_source_paths(args.seed_paths)
    except (FileNotFoundError, ValueError) as e:
        print(f"FAIL: Could not resolve seed source paths: {e}")
        write_manifest(iter_dir, run_name, results=[], crashed=True)
        sys.exit(1)

    # Step 2 — soul restoration. For start_iteration > 1, this re-registers
    # plugin classes from prior iters' on-disk artifacts and prepends the
    # workspace-discovered run_outputs onto the seeds. For start_iteration == 1
    # it is a no-op that returns resolved_seeds verbatim. There is no
    # separate --resume flag — start_iteration > 1 IS resume. See
    # docs/phase68_orchestrator_memory_and_resume.md §3.3.
    try:
        state = restore_prior_state(
            workspace=args.workspace,
            current_iter=args.start_iteration,
            seed_paths=resolved_seeds,
        )
    except ResumeError as e:
        print(f"FAIL: restore_prior_state refused to chain: {e}")
        write_manifest(iter_dir, run_name, results=[], crashed=True)
        sys.exit(1)

    if state.committed_iters:
        print(
            f"[CHAIN] Restored {len(state.restored_plugins)} prior plugin(s) "
            f"from iters {state.committed_iters}"
        )
        if state.restored_plugins:
            print(f"        plugins: {state.restored_plugins}")
    resolved_paths = state.resolved_source_paths

    if args.llm_config:
        llm_config = WorkflowLLMConfig.from_json(args.llm_config)
    else:
        if args.llm_model != "gemini-3.1-pro-preview":
            warnings.warn(
                "--llm_model is deprecated; use --llm_config instead.",
                DeprecationWarning, stacklevel=2,
            )
        llm_config = WorkflowLLMConfig.uniform(
            "gemini", args.llm_model,
            reflect_provider=reflect_provider,
            reflect_model_id=reflect_model_id,
        )

    try:
        results = run_workflow(
            source_paths=resolved_paths,
            workspace=args.workspace,
            run_name=run_name,
            llm_config=llm_config,
            max_iterations=1,
            start_iteration=args.start_iteration,
            max_rounds=args.max_rounds,
            max_proposal_attempts=args.max_proposal_attempts,
            is_trial=args.is_trial or True,  # default to trial mode
            trial_strategy=args.trial_strategy,
            trial_portion=args.trial_portion,
            target_files=args.target_files,
            train_portion=args.train_portion,
            eval_strategy=args.trial_strategy,
            eval_portion=args.eval_portion,
            sampling_seed=args.sampling_seed,
            # Phase M — formal-mode training levers (eval side locked in tuner)
            formal_strategy=args.formal_strategy,
            formal_portion=args.formal_portion,
            formal_train_portion=args.formal_train_portion,
            force_formal_round=args.force_formal_round,
            formal_round_strategy=args.formal_round_strategy,
            degenerate_penalty_score=args.degenerate_penalty_score,
            cleanup_denoised=args.cleanup_denoised,
            max_epochs=args.max_epochs,
            # Time/VRAM budget gates
            trial_time_budget_minutes=args.trial_time_budget_minutes,
            formal_time_budget_minutes=args.formal_time_budget_minutes,
            data_dir=args.data_dir,
            trial_vram_budget_gb=args.trial_vram_budget_gb,
            formal_vram_budget_gb=args.formal_vram_budget_gb,
            # Per-round attempt budget (Phase L)
            attempts_per_round=args.attempts_per_round,
            attempts_per_formal_round=args.attempts_per_formal_round,
            max_fail_rounds=args.max_fail_rounds,
            # Advice
            human_advice_interpret=args.human_advice_interpret,
            human_advice_propose=args.human_advice_propose,
            human_advice_implement=args.human_advice_implement,
            human_advice_validate=args.human_advice_validate,
            human_advice_tune=args.human_advice_tune,
            human_advice_mindset=args.human_advice_mindset,
            plan_overrides=args.plan_overrides,
            # Reasoning pipeline
            exploration_mode=args.exploration_mode,
            minimum_boldness=args.minimum_boldness,
            max_impl_attempts=args.max_impl_attempts,
            debug_dump_prompts=args.debug_dump_prompts,
            # Cross-iter knowledge carry-over (docs/Consistent_growing_vocab_list.md)
            restored_runtime_vocab=state.runtime_vocab,
            accumulated_key_findings=state.accumulated_key_findings,
            # Cross-iter negative-feedback carry-over (docs/V8_Gap_Report.md Domain 1)
            accumulated_physical_rejections=state.accumulated_physical_rejections,
            accumulated_gate_exhaustions=state.accumulated_gate_exhaustions,
        )
    except Exception as e:
        print(f"FAIL: Workflow raised exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        write_manifest(iter_dir, run_name, results=[], crashed=True)
        sys.exit(1)

    manifest = write_manifest(iter_dir, run_name, results)

    if manifest["status"] == "completed":
        print()
        print("=" * 60)
        print(f"  ITERATION {args.start_iteration} COMPLETE")
        print(f"  Model      : {manifest['model_name']}")
        print(f"  Best score : {manifest['best_score']}")
        print(f"  Output     : {manifest['output_path']}")
        print("=" * 60)
        sys.exit(0)

    if manifest["status"] == "no_records":
        # Gate exhaustion or all-rounds-failed without a Python crash.
        # Exit 0 so run_chain.sh's `set -e` does not halt the chain — the
        # next iter's LLM will see the skipped attempts via memory_history
        # restoration and can adapt. See docs/phase68_orchestrator_memory_and_resume.md
        # §3.3 for the no_records contract.
        print()
        print("=" * 60)
        print(
            f"[CHAIN] No models passed gates this iteration. "
            f"Writing manifest and exiting gracefully to allow chain to continue."
        )
        print(f"  Iteration  : {args.start_iteration}")
        print(f"  Manifest   : {os.path.join(iter_dir, 'manifest.json')} (status=no_records)")
        print("=" * 60)
        sys.exit(0)

    # Defensive: any other status is unexpected and should halt the chain.
    print(f"FAIL: Iteration ended with unexpected manifest status={manifest['status']!r}.")
    sys.exit(1)


if __name__ == "__main__":
    main()
