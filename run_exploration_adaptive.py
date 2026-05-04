#!/usr/bin/env python3
"""
Launch the adaptive exploration workflow.

Uses run_workflow() directly with max_iterations > 1 so the vocabulary
feedback loop (previous_proposal -> interpretation -> discoveries -> proposal)
works across iterations.

Examples
--------
# Run with defaults (adaptive_v1, v1 advice):
  python run_exploration_adaptive.py --run_name adaptive_v1

# Run with custom advice and workspace:
  python run_exploration_adaptive.py \\
      --run_name adaptive_v2 \\
      --advice tuner_advice/chain_v3_proposer_advice_time_sens.json \\
      --workspace /home/klz/Data/SIDEREIS_DATA/exploration_adaptive_v2
"""
import argparse
import datetime
import json
import sys
import os
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_models"))

from workflows.model_exploration import run_workflow
from workflows.llm_config import WorkflowLLMConfig
from core.resume import restore_prior_state, validate_workspace_layout, ResumeError
from sdsc_submission_scripts.run_one_iteration import write_manifest
from agent.schemas.telemetry import LLMBridgeContextError


def _generate_run_id(run_name: str) -> str:
    """Build the immutable per-chain run identifier per §1.4.1.

    Format: ``{run_name}-{utc_ts}-{pid}``. The triple uniqueness comes from
    the wall-clock UTC second and the process id; a re-run within the same
    second from the same pid would collide, but that requires cooperating
    schedulers and is not a concern in the chain runner's workflow.
    """
    ts = (
        datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y%m%dT%H%M%S")
    )
    return f"{run_name}-{ts}-{os.getpid()}"


def _emit_token_iter_rollup(workspace: str, iteration: int,
                            cumulative_total_in: int) -> int:
    """Emit one ``[TOKEN_ITER]`` line for the just-finished iteration.

    Reads ``{workspace}/token_usage.jsonl``, filters rows whose ``iter`` matches
    ``iteration`` (skipping the synthetic ``_iter_flush`` markers), aggregates
    by ``label`` prefix (``proposer``/``tuner``/``interp``), and prints one
    summary line that the Phase-R ``_TeeStream`` mirrors into ``chain_log.txt``.
    Returns the updated cumulative total so the caller can carry it across
    iterations.
    """
    path = os.path.join(workspace, "token_usage.jsonl")
    if not os.path.exists(path):
        return cumulative_total_in

    calls = 0
    iter_total = 0
    by_node: dict[str, int] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("iter") != iteration:
                    continue
                if row.get("label") == "_iter_flush":
                    continue
                calls += 1
                tok_total = (row.get("tokens") or {}).get("total", 0) or 0
                iter_total += tok_total
                label = row.get("label") or "unlabeled"
                node_key = label.split(".", 1)[0]
                by_node[node_key] = by_node.get(node_key, 0) + tok_total
    except OSError:
        return cumulative_total_in

    cumulative_total_out = cumulative_total_in + iter_total
    breakdown = "  ".join(f"{k}={v}" for k, v in sorted(by_node.items()))
    print(
        f"[TOKEN_ITER] iter={iteration:02d}  calls={calls}  "
        f"total_tok={iter_total}  ({breakdown})  "
        f"cumulative_total={cumulative_total_out}"
    )
    return cumulative_total_out


class _TeeStream:
    """Duplex text writer fanning out to multiple streams.

    Mirrors stdout/stderr to a chain log file without losing the original
    console stream. Forces flush after every write so a detached screen's
    chain_log.txt is tail-able in real time. Phase R resilience addition.
    """
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            s.write(data)
            s.flush()
        return len(data)

    def flush(self):
        for s in self._streams:
            s.flush()

    def isatty(self):
        return False

# Default source paths (wavenet + punet seed runs)
DEFAULT_SOURCE_PATHS = [
    "/home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json",
    "/home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json",
]


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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Launch SIDERIUS adaptive exploration workflow.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--run_name", type=str, required=True,
        help="Run identifier, e.g. 'adaptive_v1'. Used for output filenames.",
    )
    parser.add_argument(
        "--workspace", type=str, default=None,
        help="Output workspace directory. Defaults to "
             "/home/klz/Data/SIDEREIS_DATA/exploration_{run_name}.",
    )
    parser.add_argument(
        "--advice", type=str, default="tuner_advice/exploration_adaptive_v1.json",
        help="Path to the JSON advice file (propose/implement/tune/mindset keys).",
    )
    parser.add_argument(
        "--llm_config", type=str, default=None,
        help=(
            "Path to a WorkflowLLMConfig JSON file for per-node model routing "
            "(e.g. llm_configs/openai_tiered_v1.json). "
            "When omitted, defaults to uniform gemini-3.1-pro-preview."
        ),
    )
    parser.add_argument(
        "--start_iteration", type=int, default=1,
        help="First iteration to run (1-based). When > 1, restores prior iters "
             "from disk via restore_prior_state before entering the iter loop.",
    )
    parser.add_argument(
        "--max_iterations", type=int, default=30,
        help=(
            "Number of propose->implement->validate->tune iterations. "
            "Default aligned with the V4 contract; the launch script "
            "(sdsc_submission_scripts/launch_v11_v4.sh) is the authoritative "
            "entry point and always passes this explicitly."
        ),
    )
    parser.add_argument(
        "--max_rounds", type=int, default=4,
        help=(
            "Tuning rounds per iteration. Default aligned with the V4 "
            "contract (3 trial + 1 formal); the launch script is "
            "authoritative."
        ),
    )
    parser.add_argument(
        "--max_proposal_attempts", type=int, default=3,
        help="Max proposal retries per iteration if validation fails.",
    )
    parser.add_argument(
        "--max_impl_attempts", type=int, default=3,
        help=(
            "Max implementation retries per proposal when the validator rejects the code. "
            "Each retry feeds the validator's error back to the implementor so it can fix "
            "spec-alignment issues without requiring a new proposal."
        ),
    )
    parser.add_argument(
        "--trial_portion", type=float, default=0.05,
        help=(
            "Fraction of data used for trial-mode training/eval. Default "
            "aligned with the V4 contract; the launch script is authoritative."
        ),
    )
    parser.add_argument(
        "--train_portion", type=float, default=0.1,
        help="Fraction of trial data used per epoch.",
    )
    parser.add_argument(
        "--eval_portion", type=float, default=0.1,
        help="Fraction of data used for trial-mode evaluation.",
    )
    parser.add_argument(
        "--max_epochs", type=_positive_int, default=1,
        help="Hard cap on epochs per tuning round. Must be >= 1; None forbidden.",
    )
    parser.add_argument(
        "--trial_strategy", type=str, default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help=(
            "Sampling strategy for trial mode. 'snapshot' covers all 20 files, "
            "'anchors' picks files 0/10/19, 'target' restricts to --target_files. "
            "Forwarded to BOTH the proposer's and tuner's evaluate_time_skill gates."
        ),
    )
    parser.add_argument(
        "--target_files", type=int, nargs="+", default=None,
        help=(
            "File indices to sample from (required when --trial_strategy=target). "
            "Modern replacement for legacy single-file mode: pass e.g. --target_files 6."
        ),
    )
    parser.add_argument(
        "--sampling_seed", type=int, default=None,
        help="Seed for build_sample_set(). None auto-generates per gate.",
    )
    parser.add_argument(
        "--trial_time_budget_minutes", type=float, default=None,
        help=(
            "Wall-time budget (minutes) for the evaluate_time_skill gate on "
            "rounds where plan.is_trial=True. Forwarded to BOTH the proposer's "
            "baseline gate and the tuner's per-round gate. None disables the "
            "trial gate (docs/resource_estimator_implement.md §2.7 / Phase I)."
        ),
    )
    parser.add_argument(
        "--formal_time_budget_minutes", type=float, default=None,
        help=(
            "Wall-time budget (minutes) for the evaluate_time_skill gate on "
            "rounds where plan.is_trial=False. Sized independently from the "
            "trial budget because formal runs use the full dataset and are "
            "50–100x longer. None disables the formal gate."
        ),
    )
    parser.add_argument(
        "--data_dir", type=str, default=None,
        help=(
            "TIDMAD data directory used by evaluate_time_skill's real-dataset "
            "warmup. None makes the skill fall back to its static formula."
        ),
    )
    parser.add_argument(
        "--trial_vram_budget_gb", type=float, default=None,
        help=(
            "Per-mode VRAM ceiling (GB) for the evaluate_vram_skill gate on "
            "rounds where plan.is_trial=True. Forwarded to the tuner's "
            "per-round gate only (no proposer-side VRAM gate in Phase K). "
            "None → skill falls back to free×0.8 defensive limit "
            "(docs/resource_estimator_implement.md §10.9 / Phase K)."
        ),
    )
    parser.add_argument(
        "--formal_vram_budget_gb", type=float, default=None,
        help=(
            "Per-mode VRAM ceiling (GB) for the evaluate_vram_skill gate on "
            "rounds where plan.is_trial=False. Sized independently from the "
            "trial budget — formal rounds often use larger batch_size and "
            "segmentation_size so the VRAM ceiling can differ. "
            "None → skill falls back to free×0.8 defensive limit."
        ),
    )
    # --- Formal-mode training levers (Phase M, docs §12) + eval scope (Phase R, §13) ---
    # Formal eval strategy is locked to ``snapshot``; the portion defaults to
    # 1.0 (production full-clone for cross-arch comparability, §12.2) and
    # is operator-configurable via ``--formal_eval_portion`` for smoke / CI
    # runs that must fit a tight ``--formal_time_budget_minutes`` — §13.
    parser.add_argument(
        "--formal_strategy", type=str, default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help=(
            "Training-side sampling strategy on formal rounds. Overrides the "
            "planner's trial_strategy on any round promoted to formal. "
            "Default 'snapshot' (all 20 files) — anchors/target are mostly for "
            "diagnostics."
        ),
    )
    parser.add_argument(
        "--formal_portion", type=float, default=0.1,
        help="Fraction of segments per file for formal training scope (default 0.1).",
    )
    parser.add_argument(
        "--formal_train_portion", type=float, default=1.0,
        help="Per-epoch iteration fraction from the formal training scope (default 1.0).",
    )
    parser.add_argument(
        "--formal_eval_portion", type=float, default=1.0,
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
    # --- Per-round attempt budget (Phase L, docs/resource_estimator_implement.md §11) ---
    parser.add_argument(
        "--attempts_per_round", type=int, default=3,
        help=(
            "Inner attempt budget for trial rounds (default 3). Tuner-only "
            "fan-out — no proposer-side equivalent. Each round runs up to N "
            "attempts; success → break + reset the consecutive-fail counter, "
            "exhaustion → bump it. See docs/resource_estimator_implement.md §11."
        ),
    )
    parser.add_argument(
        "--attempts_per_formal_round", type=int, default=5,
        help=(
            "Inner attempt budget for the formal-promotion round (default 5, "
            "intentionally higher than --attempts_per_round). Formal is the "
            "only cross-architecture comparable measurement, so an iteration "
            "with no formal score is wasted entirely — extra attempts are "
            "worth the cost. Worst-case wall-time per failed formal round at "
            "formal_time_budget=30 min is 5 × 30 = 150 min; per iteration at "
            "max_fail_rounds=3 is ~7.5 h."
        ),
    )
    parser.add_argument(
        "--max_fail_rounds", type=int, default=3,
        help=(
            "Consecutive-failure brake (default 3). The tuner outer loop "
            "aborts with termination_reason='aborted_fail_rounds' after this "
            "many consecutive rounds exhaust their inner attempt budget. "
            "Phase L addition — replaces the pre-Phase-L 'max_rounds * 3' "
            "shared attempt pool which could starve the formal round."
        ),
    )
    parser.add_argument(
        "--max_failed_iterations", type=int, default=3,
        help=(
            "Outer-chain consecutive-failure brake (default 3). After this "
            "many iterations in a row return status != 'completed' (e.g. "
            "no_records, aborted_fail_rounds), the chain stops. A successful "
            "iteration resets the counter. Phase R resilience addition — "
            "replaces the prior single-failure sys.exit so a bad architecture "
            "proposal does not kill the entire 30-iter chain."
        ),
    )
    # Phase 6.8 Commit 11 — canonical name --seed_paths; --source_paths kept
    # as a deprecated alias for one release. See §3.5 Commit 11.
    parser.add_argument(
        "--seed_paths", type=str, nargs="+", default=None,
        help="Seed run output JSON paths. Defaults to wavenet + punet trial runs. "
             "Mutually exclusive with the deprecated --source_paths alias.",
    )
    parser.add_argument(
        "--source_paths", type=str, nargs="+", default=None,
        dest="source_paths_legacy",
        help="DEPRECATED — alias for --seed_paths. Will be removed after "
             "the next stable run. Use --seed_paths instead.",
    )
    parser.add_argument(
        "--exploration_mode", type=str, default="auto",
        choices=["auto", "explore", "exploit"],
        help=(
            "Reasoning pipeline mode. 'auto' resolves dynamically from n_agent_proposed "
            "and vocab_diversity_ratio. 'explore' forces novel architecture search "
            "(use with exploration_adaptive_v3 advice). 'exploit' forces incremental "
            "refinement of the current SOTA."
        ),
    )
    parser.add_argument(
        "--minimum_boldness", type=float, default=0.05,
        help=(
            "Minimum boldness threshold for FalsifiablePrediction: "
            "|predicted - current| / |current| must exceed this value. "
            "Predictions below the threshold trigger a causal_reasoning retry. "
            "Default 0.05 (5%% relative improvement required)."
        ),
    )
    parser.add_argument(
        "--debug_dump_prompts", action="store_true",
        help=(
            "Phase K.8 debug instrumentation: dump each iteration's "
            "rendered proposing-stage system prompt to "
            "{workspace}/{run_name}/debug/iter{N}_attempt{M}_proposing_system_prompt.md "
            "so smoke runs can audit the exact text the LLM saw "
            "(in particular the K.7.6 [PRIOR ITERATION GATE EXHAUSTION] block)."
        ),
    )
    return parser.parse_args()


def _run_one_iter(args, workspace, llm_config, advice, source_paths,
                  iteration, *, run_id: str):
    """Run a single iteration in the chain-in-one-process loop.

    Mirrors ``sdsc_submission_scripts/run_one_iteration.py`` main(): each
    iter re-derives chain-resume state from disk via ``restore_prior_state``
    and threads the cross-iter carry-over fields (vocab + accumulated
    negative feedback) into ``run_workflow``. The in-process loop is then
    structurally identical to the SDSC per-iter chain modulo the process
    boundary, so any future kwargs added to one entry must reach the other
    (Phase 6.8 §3.8 / test_chain_consistency.py Gate B).

    ``source_paths`` is the immutable user-supplied seed list — never the
    growing chain list. ``restore_prior_state`` walks the workspace and
    prepends prior iter outputs onto these seeds to assemble the per-iter
    chain source list.
    """
    run_name = f"iter_{iteration:03d}"
    iter_dir = os.path.join(workspace, run_name)
    os.makedirs(iter_dir, exist_ok=True)

    # Re-derive chain-resume state from disk every iter. For iteration == 1
    # this is a no-op returning seeds verbatim with empty accumulators; for
    # iteration > 1 it walks committed iters and assembles vocab +
    # accumulated_* alongside the chain source-paths list. Single source of
    # truth — replaces both the legacy outer ``if start_iter > 1`` block and
    # the manual ``source_paths.append(manifest["output_path"])`` chain-feed.
    try:
        state = restore_prior_state(
            workspace=workspace,
            current_iter=iteration,
            seed_paths=source_paths,
        )
    except ResumeError as e:
        print(f"ERROR: restore_prior_state refused at iter {iteration}: {e}")
        sys.exit(1)

    if state.committed_iters:
        print(
            f"[CHAIN] Restored {len(state.restored_plugins)} prior plugin(s) "
            f"from iters {state.committed_iters}"
        )

    results = run_workflow(
        source_paths=state.resolved_source_paths,
        workspace=workspace,
        run_name=run_name,
        chain_run_name=args.run_name,
        run_id=run_id,
        max_iterations=1,
        start_iteration=iteration,
        max_rounds=args.max_rounds,
        max_proposal_attempts=args.max_proposal_attempts,
        llm_config=llm_config,
        is_trial=True,
        trial_strategy=args.trial_strategy,
        trial_portion=args.trial_portion,
        target_files=args.target_files,
        train_portion=args.train_portion,
        eval_strategy=args.trial_strategy,
        eval_portion=args.eval_portion,
        sampling_seed=args.sampling_seed,
        max_epochs=args.max_epochs,
        plan_overrides={
            "is_trial": True,
            "trial_portion": args.trial_portion,
            "train_portion": args.train_portion,
            "eval_portion": args.eval_portion,
        },
        trial_time_budget_minutes=args.trial_time_budget_minutes,
        formal_time_budget_minutes=args.formal_time_budget_minutes,
        data_dir=args.data_dir,
        trial_vram_budget_gb=args.trial_vram_budget_gb,
        formal_vram_budget_gb=args.formal_vram_budget_gb,
        formal_strategy=args.formal_strategy,
        formal_portion=args.formal_portion,
        formal_train_portion=args.formal_train_portion,
        formal_eval_portion=args.formal_eval_portion,
        force_formal_round=args.force_formal_round,
        formal_round_strategy=args.formal_round_strategy,
        degenerate_penalty_score=args.degenerate_penalty_score,
        attempts_per_round=args.attempts_per_round,
        attempts_per_formal_round=args.attempts_per_formal_round,
        max_fail_rounds=args.max_fail_rounds,
        human_advice_propose=advice.get("propose"),
        human_advice_implement=advice.get("implement"),
        human_advice_tune=advice.get("tune"),
        human_advice_mindset=advice.get("mindset"),
        cleanup_denoised=True,
        exploration_mode=args.exploration_mode,
        minimum_boldness=args.minimum_boldness,
        max_impl_attempts=args.max_impl_attempts,
        debug_dump_prompts=args.debug_dump_prompts,
        restored_runtime_vocab=state.runtime_vocab,
        accumulated_key_findings=state.accumulated_key_findings,
        accumulated_physical_rejections=state.accumulated_physical_rejections,
        accumulated_gate_exhaustions=state.accumulated_gate_exhaustions,
    )

    manifest = write_manifest(iter_dir, run_name, results)
    return manifest


def _append_evolution_failure(workspace: str, iteration: int, manifest: dict) -> None:
    """Append a kind='iteration_failure' entry to evolution_log.jsonl.

    Phase R resilience: a no-records / aborted iteration never writes a
    normal interpretation row, so without this hook the chain log loses
    any trace of why iter N produced nothing. Pulls the deeper
    `termination_reason` from
    {iter_dir}/iteration_NNN/{model_name}/run_output_iter_NNN.json
    when present (it carries the tuner's Phase-L exit code), and falls
    back to manifest['status']. Best-effort: any IO/JSON error is
    swallowed so observability never breaks the chain.
    """
    arch = manifest.get("model_name") or "<unknown>"
    iter_dir = manifest.get("iteration_dir")
    termination_reason = manifest.get("status") or "unknown"

    if iter_dir and arch != "<unknown>":
        run_out = os.path.join(
            iter_dir, f"iteration_{iteration:03d}", arch,
            f"run_output_iter_{iteration:03d}.json",
        )
        try:
            if os.path.exists(run_out):
                with open(run_out) as f:
                    ro = json.load(f)
                termination_reason = ro.get("termination_reason") or termination_reason
        except (OSError, json.JSONDecodeError):
            pass

    entry = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "iteration": iteration,
        "kind": "iteration_failure",
        "architecture_name": arch,
        "termination_reason": termination_reason,
        "manifest_status": manifest.get("status"),
        "completed_rounds": manifest.get("completed_rounds", 0),
    }
    log_path = os.path.join(workspace, "evolution_log.jsonl")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        print(f"  [evolution_log] WARN: failed to append failure entry: "
              f"{type(e).__name__}: {e}")


def main():
    args = parse_args()

    # Resolve workspace
    workspace = args.workspace or (
        f"/home/klz/Data/SIDEREIS_DATA/exploration_{args.run_name}"
    )

    # Process-global anchor — ``ml_models.model_descriptions.get_model_description``
    # reads this to resolve agent-generated plugin descriptions written under
    # ``{workspace}/plugins/iter_NNN/{model_type}/description.md`` by
    # ``workflows.model_exploration._register_plugin``. Set before any node
    # initialisation so descendant calls see it.
    os.environ["SIDERIUS_CHAIN_WORKSPACE"] = os.path.abspath(workspace)

    # Persistent logging: tee stdout/stderr into {workspace}/chain_log.txt
    # so a detached screen session is not the only stdout sink. Line-buffered
    # for real-time `tail -f`. Phase R resilience addition.
    os.makedirs(workspace, exist_ok=True)
    _chain_log_path = os.path.join(workspace, "chain_log.txt")
    _chain_log_fh = open(_chain_log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = _TeeStream(sys.__stdout__, _chain_log_fh)
    sys.stderr = _TeeStream(sys.__stderr__, _chain_log_fh)
    print(f"[CHAIN] Mirroring stdout/stderr to {_chain_log_path}")

    # Workspace layout guard (§3.9)
    try:
        validate_workspace_layout(workspace)
    except ResumeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # --seed_paths / --source_paths alias collapse (Phase 6.8 Commit 11).
    seed_legacy = getattr(args, "source_paths_legacy", None)
    seed_canonical = args.seed_paths
    if seed_legacy is not None and seed_canonical is not None:
        print("ERROR: --seed_paths and --source_paths are mutually exclusive. "
              "--source_paths is the deprecated alias; use --seed_paths only.")
        sys.exit(1)
    if seed_legacy is not None:
        warnings.warn(
            "--source_paths is deprecated; use --seed_paths instead. "
            "The deprecated alias will be removed after the next stable run.",
            DeprecationWarning,
            stacklevel=2,
        )
        args.seed_paths = seed_legacy

    # Resolve source paths
    source_paths = args.seed_paths or DEFAULT_SOURCE_PATHS
    for p in source_paths:
        if not os.path.exists(p):
            print(f"ERROR: Source path not found: {p}")
            sys.exit(1)

    # Load advice file
    if not os.path.exists(args.advice):
        print(f"ERROR: Advice file not found: {args.advice}")
        sys.exit(1)
    with open(args.advice) as f:
        advice = json.load(f)
    advice = {k: ("\n".join(v) if isinstance(v, list) else v)
              for k, v in advice.items()}

    # LLM config — from file if provided, else default uniform gemini
    if args.llm_config:
        if not os.path.exists(args.llm_config):
            print(f"ERROR: LLM config file not found: {args.llm_config}")
            sys.exit(1)
        llm_config = WorkflowLLMConfig.from_json(args.llm_config)
    else:
        llm_config = WorkflowLLMConfig.uniform("gemini", "gemini-3.1-pro-preview")

    # Validate target-mode wiring early
    if args.trial_strategy == "target" and not args.target_files:
        print("ERROR: --trial_strategy=target requires --target_files (one or more file indices)")
        sys.exit(1)

    start_iter = args.start_iteration

    # Generate the immutable per-chain run_id (§1.4.1). Threaded into every
    # bridge instance via set_run_context — the bridge refuses to write
    # rows tagged with a different run_id, so this string is the audit
    # log's identity-of-record for the entire chain.
    run_id = _generate_run_id(args.run_name)
    print(f"[TOKEN] run_id = {run_id}")

    # Print summary
    print("=" * 60)
    print("  SIDERIUS Adaptive Exploration (chain-in-one-process)")
    print(f"  Run name  : {args.run_name}")
    print(f"  Workspace : {workspace}")
    print(f"  Iterations: {start_iter}..{args.max_iterations}")
    print(f"  Rounds/iter: {args.max_rounds}  |  Max epochs: {args.max_epochs}")
    print(f"  Trial strategy: {args.trial_strategy}"
          + (f"  |  Target files: {args.target_files}" if args.trial_strategy == "target" else ""))
    print(f"  Trial portion: {args.trial_portion}  |  Train portion: {args.train_portion}  |  Eval portion: {args.eval_portion}")
    print(f"  Sampling seed : {args.sampling_seed if args.sampling_seed is not None else 'auto'}")
    trial_budget_str = (f"{args.trial_time_budget_minutes} min"
                        if args.trial_time_budget_minutes is not None
                        else "disabled")
    formal_budget_str = (f"{args.formal_time_budget_minutes} min"
                         if args.formal_time_budget_minutes is not None
                         else "disabled")
    print(f"  Time budget   : trial={trial_budget_str}  |  formal={formal_budget_str}")
    trial_vram_str = (f"{args.trial_vram_budget_gb} GB"
                      if args.trial_vram_budget_gb is not None
                      else "disabled (free×0.8)")
    formal_vram_str = (f"{args.formal_vram_budget_gb} GB"
                       if args.formal_vram_budget_gb is not None
                       else "disabled (free×0.8)")
    print(f"  VRAM budget   : trial={trial_vram_str}  |  formal={formal_vram_str}")
    print(f"  Formal train  : strategy={args.formal_strategy}  portion={args.formal_portion}  train_portion={args.formal_train_portion}")
    print(f"  Last round    : force_formal={args.force_formal_round} (False ⇒ honour planner — testing only)")
    formal_eval_note = (
        " (production full-clone, §12.2)"
        if args.formal_eval_portion == 1.0
        else " (smoke / CI scope-down, Phase R §13)"
    )
    print(f"  Formal eval   : strategy=snapshot  eval_portion={args.formal_eval_portion}{formal_eval_note}")
    print(f"  Attempt budget: trial={args.attempts_per_round}/round  formal={args.attempts_per_formal_round}/round  fail-brake={args.max_fail_rounds} (Phase L)")
    print(f"  Data dir      : {args.data_dir or 'unset (skill uses static formula)'}")
    print(f"  Advice    : {args.advice}")
    print(f"  LLM config: {args.llm_config or 'default (gemini-3.1-pro-preview uniform)'}")
    print(f"  Seeds     : {len(source_paths)} models")
    print(f"  Exploration mode : {args.exploration_mode}")
    print(f"  Min boldness     : {args.minimum_boldness}")
    print("=" * 60)

    # Chain-in-one-process loop with iteration-resilience brake (Phase R).
    # ``source_paths`` here is the immutable user-supplied seed list — the
    # per-iter ``restore_prior_state`` call inside ``_run_one_iter`` walks
    # the workspace and prepends prior iter outputs onto these seeds, so
    # the seed list is never mutated by the loop itself. This matches
    # one-iter's main(): restore is the single source of truth for chain
    # assembly.
    #
    # A failed iteration (no_records / aborted_fail_rounds / etc.) no
    # longer kills the chain — it logs a warning, appends an
    # ``iteration_failure`` row to evolution_log.jsonl, and proceeds to
    # the next architecture. Only ``--max_failed_iterations`` consecutive
    # failures stop the chain; a successful iteration resets the counter.
    consecutive_failed = 0
    cumulative_token_total = 0
    try:
        for iteration in range(start_iter, args.max_iterations + 1):
            print(f"\n{'='*60}")
            print(f"  IN-PROCESS CHAIN — ITERATION {iteration}/{args.max_iterations}")
            print(f"{'='*60}")

            manifest = _run_one_iter(
                args, workspace, llm_config, advice, source_paths, iteration,
                run_id=run_id,
            )

            # Per-iter [TOKEN_ITER] rollup (§1.6). Best-effort: any IO/JSON
            # error in the rollup must never break the chain — the
            # token_usage.jsonl file is itself the source of truth.
            try:
                cumulative_token_total = _emit_token_iter_rollup(
                    workspace=workspace,
                    iteration=iteration,
                    cumulative_total_in=cumulative_token_total,
                )
            except Exception as e:
                print(f"  [TOKEN_ITER] WARN: rollup emit failed: "
                      f"{type(e).__name__}: {e}")

            if manifest["status"] == "completed" and manifest.get("output_path"):
                print(f"  Iteration {iteration} completed: score={manifest['best_score']}")
                consecutive_failed = 0
                continue

            consecutive_failed += 1
            arch = manifest.get("model_name") or "<unknown>"
            print(
                f"\n  *** [WARNING] Iteration {iteration} failed to produce "
                f"records (architecture={arch}, status={manifest['status']}). "
                f"Skipping to next architecture. "
                f"[consecutive failures: {consecutive_failed}/"
                f"{args.max_failed_iterations}] ***\n"
            )
            _append_evolution_failure(workspace, iteration, manifest)

            if consecutive_failed >= args.max_failed_iterations:
                print(
                    f"\n  *** [ABORT] {consecutive_failed} consecutive "
                    f"iterations failed (>= --max_failed_iterations="
                    f"{args.max_failed_iterations}). Stopping chain. ***"
                )
                sys.exit(1)
    except LLMBridgeContextError as e:
        # §1.4.2 fail-fast contract. Telemetry-internal corruption (run_id
        # mismatch, backwards iter) means the audit log can no longer be
        # trusted. Continuing past this point would produce convincing-but-
        # wrong numbers — the worst possible failure mode for an audit log.
        # exit(2) is intentionally distinct from the consecutive-failure
        # brake's exit(1) so a downstream classifier can tell the two apart.
        print(
            f"[FATAL] LLMBridgeContextError: {e} — aborting run to "
            f"prevent telemetry corruption.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
