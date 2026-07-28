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
import hashlib
import json
import os
import sys
import traceback
import warnings
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agent.schemas.telemetry import LLMBridgeContextError
from core.resume import ResumeError, restore_prior_state
from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    build_run_invariants,
)
from execute_tools.dataset_config import TIDMAD, DataScope
from workflows.llm_config import WorkflowLLMConfig
from workflows.model_exploration import run_workflow

SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=Path(SIDERIUS_ROOT) / ".env")


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


def _resolve_chain_run_id(workspace: str, run_name: str) -> str:
    """Resolve the immutable per-chain run_id (§1.4.1) for this iteration.

    The chain runner invokes one fresh subprocess per iter — naive
    ``_generate_run_id`` would yield a different value per process and
    violate the bridge's run_id-immutability contract on iter ≥ 2. A
    sidecar file at ``{workspace}/.token_run_id`` carries the value
    forward: iter 1 generates and writes it; later iters read it back.

    Format: ``{run_name}-{utc_ts}-{pid}``.
    """
    sidecar = os.path.join(workspace, ".token_run_id")
    if os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8") as f:
            existing = f.read().strip()
        if existing:
            return existing

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    new = f"{run_name}-{ts}-{os.getpid()}"
    os.makedirs(workspace, exist_ok=True)
    with open(sidecar, "w", encoding="utf-8") as f:
        f.write(new)
    return new


def _check_halt_marker(workspace: str) -> bool:
    """Return True iff the consecutive-failure brake has already fired
    in this workspace (Stage 4 / Commit 4.6).

    Cheap fail-fast for SDSC ``afterany`` chains: Slurm queues the next
    iter regardless of the previous's exit code, so we need an on-disk
    sentinel for the next process to bail out before doing any work.
    Called first thing in ``main()`` (after argparse), before any dirs
    are created.
    """
    return os.path.exists(os.path.join(workspace, ".chain_halted"))


def _check_consecutive_failure_brake(
    workspace: str,
    max_failed: int,
) -> list[int] | None:
    """Scan the workspace for a ``max_failed``-long streak of consecutive
    ``status="failed"`` manifests (Stage 4 / Commit 4.6).

    Walks ``{workspace}/iter_NNN/manifest.json`` files in descending iter
    order. Returns the list of failing iter numbers (newest first) when
    the most recent ``max_failed`` committed iters all carry
    ``status="failed"``; returns None otherwise.

    The brake is **fail-open**: a missing or malformed manifest counts
    as "not failed" and breaks the streak. A safety brake must never
    halt a chain on its own flaky reads.

    Only ``status="failed"`` trips the brake. ``"completed"`` and
    ``"no_records"`` both break the streak — ``no_records`` is a
    graceful "no model passed gates" signal, not a failure.

    Args:
        workspace: chain workspace root. Need not exist yet (a fresh
            chain with no iter dirs returns None).
        max_failed: streak length to trip the brake. Caller enforces ≥1
            via the ``_positive_int`` argparse validator.
    """
    if not os.path.isdir(workspace):
        return None

    iter_numbers: list[int] = []
    for name in os.listdir(workspace):
        # Match exactly ``iter_<3 digits>`` to avoid sweeping in
        # artefacts like ``iter_001.bak`` or unrelated dirs.
        if len(name) == 8 and name.startswith("iter_") and name[5:].isdigit():
            iter_numbers.append(int(name[5:]))
    iter_numbers.sort(reverse=True)

    if len(iter_numbers) < max_failed:
        return None

    candidate = iter_numbers[:max_failed]
    for n in candidate:
        manifest_path = os.path.join(workspace, f"iter_{n:03d}", "manifest.json")
        if not os.path.exists(manifest_path):
            return None
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        if manifest.get("status") != "failed":
            return None

    return candidate


def _emit_token_iter_rollup(workspace: str, iteration: int) -> int:
    """Emit one ``[TOKEN_ITER]`` line for the just-finished iteration.

    Because each chain iter is a fresh subprocess with no in-memory
    carry, the cumulative seed is recomputed from ``token_usage.jsonl``
    itself by summing rows where ``iter < iteration`` (skipping
    ``_iter_flush`` markers).
    """
    path = os.path.join(workspace, "token_usage.jsonl")
    if not os.path.exists(path):
        return 0

    calls = 0
    iter_total = 0
    cumulative_prior = 0
    by_node: dict[str, int] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("label") == "_iter_flush":
                    continue
                row_iter = row.get("iter")
                tok_total = (row.get("tokens") or {}).get("total", 0) or 0
                if row_iter == iteration:
                    calls += 1
                    iter_total += tok_total
                    label = row.get("label") or "unlabeled"
                    node_key = label.split(".", 1)[0]
                    by_node[node_key] = by_node.get(node_key, 0) + tok_total
                elif isinstance(row_iter, int) and row_iter < iteration:
                    cumulative_prior += tok_total
    except OSError:
        return 0

    cumulative_total = cumulative_prior + iter_total
    breakdown = "  ".join(f"{k}={v}" for k, v in sorted(by_node.items()))
    print(
        f"[TOKEN_ITER] iter={iteration:02d}  calls={calls}  "
        f"total_tok={iter_total}  ({breakdown})  "
        f"cumulative_total={cumulative_total}"
    )
    return cumulative_total


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
            manifest_path = entry[len("@manifest:") :]
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
    iter_dir: str,
    run_name: str,
    results: list,
    *,
    crashed: bool = False,
    chain_incumbent_used: float | None = None,
    chain_incumbent_source: dict | None = None,
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
            "raw_best_score": score,
            "best_valid_score": getattr(tune_output, "best_valid_denoising_score", None),
            "raw_best_formal_score": getattr(tune_output, "best_formal_denoising_score", None),
            "best_valid_formal_score": getattr(
                tune_output, "best_valid_formal_denoising_score", None
            ),
            "completed_rounds": tune_output.completed_rounds,
            "health_checks_config": getattr(tune_output, "health_checks_config", None),
            # DS6c — invariant stamps (scalar comparability boundary).
            "resolved_data_scope": getattr(tune_output, "resolved_data_scope", None),
            "health_gate_enabled": getattr(tune_output, "health_gate_enabled", None),
            "health_config_sha256": getattr(tune_output, "health_config_sha256", None),
            "formal_reference_score": getattr(tune_output, "formal_reference_score", None),
            "resolved_skip_formal_threshold": getattr(
                tune_output, "resolved_skip_formal_threshold", None
            ),
            "resolved_bypass_formal_threshold": getattr(
                tune_output, "resolved_bypass_formal_threshold", None
            ),
            # V19 PR 1 (P1-C3, design §3.4/Invariant II) — the CHAIN
            # incumbent this iteration consumed, under keys DISTINCT from
            # every iteration-local best_* field. ``used`` is what the
            # gates received (null when the coupling flag is OFF or no
            # incumbent existed); ``source`` is the reconstruction
            # provenance (recorded even when unconsumed, so
            # "provided-but-not-consumed" is auditable).
            "chain_incumbent_used": chain_incumbent_used,
            "chain_incumbent_source": chain_incumbent_source,
        }
        # V19 PR 1 (§3.6) — immutable artifact identity: hash the exact
        # run_output this manifest describes, so resume can fail closed
        # on any later mutation (ReplayIntegrityError).
        if manifest["output_path"] is not None and os.path.isfile(manifest["output_path"]):
            digest = hashlib.sha256()
            with open(manifest["output_path"], "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            manifest["run_output_sha256"] = digest.hexdigest()

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
        help="Hard cap on epochs per round. Must be >= 1; None forbidden.",
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
        "--enable_chain_incumbent_formal_gates",
        action="store_true",
        help="V19 PR 1: let the formal delta gates CONSUME the reconstructed "
        "chain incumbent as their reference. Default OFF (gates see no "
        "reference; reconstruction, provenance, and manifest stamps still "
        "run unconditionally). Rollback = omit this flag; the pre-V19 "
        "fixed-0.0 reference is not restorable.",
    )
    parser.add_argument(
        "--is_trial", action="store_true", help="Enable trial mode (default: True for production)."
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
        type=_portion_floor,
        default=0.1,
        help="Floor 0.01 (segment-integrity; mirrors Pydantic ge=0.01).",
    )
    parser.add_argument("--train_portion", type=float, default=0.1)
    parser.add_argument(
        "--eval_portion",
        type=_portion_floor,
        default=0.1,
        help="Floor 0.01 (segment-integrity; mirrors Pydantic ge=0.01).",
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
        "--formal_portion",
        type=float,
        default=0.1,
        help="Fraction of segments per file for formal training scope (default 0.1).",
    )
    parser.add_argument(
        "--formal_train_portion",
        type=float,
        default=1.0,
        help="Per-epoch iteration fraction for formal training (default 1.0).",
    )
    parser.add_argument(
        "--formal_eval_portion",
        type=float,
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
        help="Delete denoised H5 files after scoring (recommended for production).",
    )
    parser.add_argument(
        "--human_advice_file",
        type=str,
        default=None,
        help="Path to a JSON file with human advice for each agent. "
        'Schema: {"interpret":"...", "propose":"...", '
        '"implement":"...", "validate":"...", "tune":"..."}. '
        "Individual --human_advice_* flags override file values.",
    )
    parser.add_argument(
        "--human_advice_interpret",
        type=str,
        default=None,
        help="Human guidance for the interpretation agent.",
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
    # --- Workflow-level CLI flags (Phase 6.8 Commit 11) ---
    parser.add_argument(
        "--llm_config",
        type=str,
        default=None,
        help="Path to a WorkflowLLMConfig JSON file for per-node model routing. "
        "Overrides --llm_model when provided.",
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
        help="Path to a JSON advice file (propose/implement/tune/mindset keys). "
        "Overrides --human_advice_file when provided.",
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
        help="Wall-time budget (minutes) for trial-mode time gate. None disables.",
    )
    parser.add_argument(
        "--formal_time_budget_minutes",
        type=float,
        default=None,
        help="Wall-time budget (minutes) for formal-mode time gate. None disables.",
    )
    # --- Runtime-control operator surface (RT6, runtime design §4/§5) ---
    # The chain is the OPERATIONAL surface: §5 provisional defaults live
    # here (schema defaults stay None). Pass 0 to disable a guardrail.
    parser.add_argument(
        "--max_steps_per_attempt",
        type=int,
        default=150_000,
        help="§5 guardrail: skip plans above this resolved optimizer-step "
        "count. 0 disables. Default 150000 (provisional §5 value).",
    )
    parser.add_argument(
        "--min_formal_batch_size",
        type=int,
        default=4,
        help="§5 guardrail: skip FORMAL rounds planned below this batch "
        "size (V18 pathology; trial exempt). 0 disables. Default 4.",
    )
    parser.add_argument(
        "--allow_extreme_steps",
        action="store_true",
        help="§5 operator override: bypass both step/batch guardrails.",
    )
    parser.add_argument(
        "--runtime_watchdog",
        action="store_true",
        help="§4 runtime watchdog: deadline-kill training/inference "
        "subprocess groups. Default off.",
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
        "--runtime_safety_factor when set. V18 posture 2.0.",
    )
    parser.add_argument(
        "--runtime_formal_safety_factor",
        type=float,
        default=None,
        help="Phase-specific factor for FORMAL attempts; wins over "
        "--runtime_safety_factor when set.",
    )
    parser.add_argument(
        "--runtime_watchdog_floor_seconds",
        type=float,
        default=60.0,
        help="§4 watchdog deadline floor. Default 60.0 (schema-mirroring); "
        "V18 production posture 120.0.",
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        default=None,
        help="TIDMAD data directory for evaluate_time_skill's real-dataset warmup. "
        "None falls back to the static formula.",
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
        default="configs/lit_review_config.yaml",
        help=(
            "Path to the lit-review YAML config (default: "
            "configs/lit_review_config.yaml). Resolved relative to "
            "SIDERIUS_ROOT inside the workflow. Pass an absolute path "
            "or a different relative path to use a non-default config "
            "without editing the default file (Design Decision 2, "
            "2026-06-11)."
        ),
    )
    return parser


def compute_expected_invariants(args: argparse.Namespace) -> RunInvariants:
    """DS6c — compute this run's invariants via the ONE shared path.

    Materializes + hashes the effective HealthGate config into the chain
    workspace root (idempotent — ``run_workflow``'s pre-flight recomputes
    the identical body sha) and returns the ``RunInvariants`` used for
    both ``restore_prior_state`` validation and, transitively, the
    workspace lock. Called BEFORE any resume mutation or LLM work.
    """
    run_scope = args.data_scope if args.data_scope is not None else DataScope.default()
    resolved_scope = run_scope.resolve(TIDMAD)
    invariants, _ = build_run_invariants(
        resolved_data_scope=resolved_scope,
        health_gate_enabled=args.health_gate_enabled,
        health_gate_files=args.health_gate_files,
        health_checks_config=args.health_checks_config,
        workspace=args.workspace,
    )
    return invariants


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

    # Load human advice: --advice (4-key) takes precedence over --human_advice_file (5-key).
    # Both schemas are tolerated during transition; missing keys are None.
    advice_path = args.advice or args.human_advice_file
    if advice_path:
        with open(advice_path) as f:
            advice = json.load(f)
        # Normalise list-of-lines form.
        advice = {k: ("\n".join(v) if isinstance(v, list) else v) for k, v in advice.items()}
        # 4-key schema: propose, implement, tune, mindset
        # 5-key schema: interpret, propose, implement, validate, tune
        for key in ("interpret", "propose", "implement", "validate", "tune"):
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
    except ValueError as e:
        parser.error(str(e))

    return args


def main():
    args = normalize_args(build_parser().parse_args())

    # --- Consecutive-failure brake preflight (Stage 4 / Commit 4.6) ---
    # Two cheap on-disk checks before we touch anything else. Runs before
    # iter_dir creation so a halted chain leaves no orphan dirs behind.
    #
    # (a) Halt-marker check — SDSC ``afterany`` queues the next iter even
    #     when its predecessor exit-3'd. The sentinel file is how we bail
    #     out without doing any work; iter 1 never sees it (fresh workspace).
    # (b) Streak scan — walks the most recent N=args.max_failed_iterations
    #     ``iter_NNN/manifest.json`` files. If all carry status="failed",
    #     write the sentinel + exit 3. ``no_records`` and ``completed``
    #     both break the streak.
    if _check_halt_marker(args.workspace):
        print(
            f"[HALT] consecutive-failure brake already fired in this "
            f"workspace — see {os.path.join(args.workspace, '.chain_halted')}",
            file=sys.stderr,
        )
        sys.exit(3)

    _failed_streak = _check_consecutive_failure_brake(
        args.workspace,
        args.max_failed_iterations,
    )
    if _failed_streak is not None:
        halt_path = os.path.join(args.workspace, ".chain_halted")
        halt_payload = {
            "halted_at": datetime.now(UTC).isoformat(),
            "workspace": os.path.abspath(args.workspace),
            "max_failed_iterations": args.max_failed_iterations,
            "failed_iters": _failed_streak,
            "next_iteration_was": args.start_iteration,
        }
        with open(halt_path, "w", encoding="utf-8") as f:
            json.dump(halt_payload, f, indent=2)
        print(
            f"[HALT] consecutive failure brake fired "
            f"(N={args.max_failed_iterations}); failed iters: "
            f"{_failed_streak}. Marker written: {halt_path}",
            file=sys.stderr,
        )
        sys.exit(3)

    # --- Pseudo-mode factory resolution (Stage 3 / Commit 4.5) ---
    # ``--is_pseudo_llm`` / ``--is_pseudo_training`` request stub
    # implementations of the LLM bridge and sandbox. We resolve the
    # factories here (early, before any other setup) and forward them
    # to ``run_workflow``, which threads them into every agent. ``None``
    # = production class — see ``workflows.model_exploration.run_workflow``.
    # The stderr warning is loud-on-purpose: it must be impossible to
    # mistake a $0-cost smoke run for a real chain when reading logs.
    bridge_factory = None
    sandbox_factory = None
    if args.is_pseudo_llm:
        from agent.llm_bridge import StubLLMBridge

        bridge_factory = StubLLMBridge
    if args.is_pseudo_training:
        from core.sandbox_executor import StubSandbox

        sandbox_factory = StubSandbox
    if args.is_pseudo_llm or args.is_pseudo_training:
        modes = []
        if args.is_pseudo_llm:
            modes.append("LLM")
        if args.is_pseudo_training:
            modes.append("training")
        print(
            f"[PSEUDO-MODE ACTIVE] {' + '.join(modes)} stub(s) engaged — "
            f"this run is a $0-cost wiring smoke; outputs are canned and "
            f"do not reflect real LLM / training behaviour.",
            file=sys.stderr,
        )

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

    # Resolve the immutable per-chain run_id (§1.4.1). The sidecar file at
    # ``{workspace}/.token_run_id`` carries the value across the subprocess
    # boundary so every iter binds the same run_id — the bridge refuses
    # any mutation. Threaded into ``run_workflow`` via ``chain_run_name``
    # + ``run_id`` so each agent's bridge writes audit rows tagged with
    # this identity.
    chain_run_name = args.run_name
    run_id = _resolve_chain_run_id(args.workspace, chain_run_name)
    print(f"[TOKEN] chain_run_name = {chain_run_name}")
    print(f"[TOKEN] run_id = {run_id}")

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

    print("  SIDERIUS PER-ITERATION RUNNER")
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
    # DS6c — compute the run's invariants (materialize + hash the effective
    # HealthGate config) BEFORE restore, so a contradicting workspace lock
    # or incompatible restored history fails with zero resume mutation.
    try:
        expected_invariants = compute_expected_invariants(args)
    except ValueError as e:
        print(f"FAIL: run-invariants computation refused to start: {e}")
        write_manifest(iter_dir, run_name, results=[], crashed=True)
        sys.exit(1)

    try:
        state = restore_prior_state(
            workspace=args.workspace,
            current_iter=args.start_iteration,
            seed_paths=resolved_seeds,
            expected_invariants=expected_invariants,
        )
    except (ResumeError, RunInvariantsViolation) as e:
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

        # Persist the accumulated_key_findings union as an on-disk sidecar so
        # the cross-iter context iter N consumes is auditable without
        # replaying load_latest_knowledge in memory. The union itself is
        # still communicated to the workflow via the runtime kwarg below; this
        # file is a log, not the channel. See
        # docs/Consistent_growing_vocab_list.md §3.3.5.
        snapshot_path = os.path.join(iter_dir, f"accumulated_findings_{run_name}.json")
        snapshot = {
            "iter_index": args.start_iteration,
            "consumed_by": run_name,
            "source_iters": list(state.committed_iters),
            "count": len(state.accumulated_key_findings),
            "produced_at": datetime.now(UTC).isoformat(),
            "findings": list(state.accumulated_key_findings),
        }
        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        print(f"[CHAIN] Wrote {snapshot['count']} accumulated findings → {snapshot_path}")
    resolved_paths = state.resolved_source_paths

    if args.llm_config:
        llm_config = WorkflowLLMConfig.from_json(args.llm_config)
    else:
        if args.llm_model != "gemini-3.1-pro-preview":
            warnings.warn(
                "--llm_model is deprecated; use --llm_config instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        llm_config = WorkflowLLMConfig.uniform(
            "gemini",
            args.llm_model,
            reflect_provider=reflect_provider,
            reflect_model_id=reflect_model_id,
        )

    # Resolve lit-review enable flag per Design Decisions 1 + 2 (2026-06-11).
    # Priority: CLI flag (when explicitly set) > YAML 'enabled' key >
    # default False. The workflow opens + parses the YAML internally
    # (only when lit_review_enabled=True); we peek at the 'enabled'
    # key here only for the CLI-fallback case. Missing YAML or
    # malformed YAML → False (fail-safe: do not run lit-review).
    if args.ml_lit_review_enabled is not None:
        ml_lit_review_enabled_resolved = args.ml_lit_review_enabled
    else:
        _yaml_path = args.ml_lit_review_config
        if not os.path.isabs(_yaml_path):
            _yaml_path = os.path.join(SIDERIUS_ROOT, _yaml_path)
        try:
            with open(_yaml_path, encoding="utf-8") as _f:
                _yaml_data = yaml.safe_load(_f) or {}
            ml_lit_review_enabled_resolved = bool(_yaml_data.get("enabled", False))
        except (FileNotFoundError, yaml.YAMLError):
            ml_lit_review_enabled_resolved = False

    try:
        results = run_workflow(
            source_paths=resolved_paths,
            workspace=args.workspace,
            run_name=run_name,
            chain_run_name=chain_run_name,
            run_id=run_id,
            llm_config=llm_config,
            health_checks_config=args.health_checks_config,
            data_scope=args.data_scope,
            health_gate_enabled=args.health_gate_enabled,
            health_gate_files=args.health_gate_files,
            max_iterations=1,
            start_iteration=args.start_iteration,
            max_rounds=args.max_rounds,
            max_proposal_attempts=args.max_proposal_attempts,
            is_trial=args.is_trial or True,  # default to trial mode
            trial_portion=args.trial_portion,
            train_portion=args.train_portion,
            eval_portion=args.eval_portion,
            sampling_seed=args.sampling_seed,
            # Phase M — formal-mode training levers; Phase R — eval scope.
            formal_strategy=args.formal_strategy,
            formal_portion=args.formal_portion,
            formal_train_portion=args.formal_train_portion,
            formal_eval_portion=args.formal_eval_portion,
            force_formal_round=args.force_formal_round,
            formal_round_strategy=args.formal_round_strategy,
            degenerate_penalty_score=args.degenerate_penalty_score,
            cleanup_denoised=args.cleanup_denoised,
            max_epochs=args.max_epochs,
            skip_formal_min_delta=args.skip_formal_min_delta,
            bypass_formal_time_budget_min_delta=args.bypass_formal_time_budget_min_delta,
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
            # Runtime-control operator surface (RT6). 0 → None (disabled).
            max_steps_per_attempt=args.max_steps_per_attempt or None,
            min_formal_batch_size=args.min_formal_batch_size or None,
            allow_extreme_steps=args.allow_extreme_steps,
            runtime_watchdog_enabled=args.runtime_watchdog,
            runtime_safety_factor=args.runtime_safety_factor,
            runtime_trial_safety_factor=args.runtime_trial_safety_factor,
            runtime_formal_safety_factor=args.runtime_formal_safety_factor,
            runtime_watchdog_floor_seconds=args.runtime_watchdog_floor_seconds,
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
            # Cross-iter knowledge-cache carry-over — Commit 6.1.a precondition for the
            # Stability Filter (docs/audit_and_optimize_token_usage_and_growth.md Rev 8.3).
            # Without this, every chain subprocess starts on an empty model_knowledge_cache,
            # forcing a fresh interpretation.per_model LLM call per model per iter.
            restored_model_knowledge_cache=state.model_knowledge_cache,
            # Cross-iter negative-feedback carry-over (docs/V8_Gap_Report.md Domain 1)
            accumulated_physical_rejections=state.accumulated_physical_rejections,
            accumulated_gate_exhaustions=state.accumulated_gate_exhaustions,
            # Cross-iter proposal carry-over — G1 bridge (docs/Consistent_growing_vocab_list.md §10.3.4)
            restored_previous_proposal=state.previous_proposal_data,
            # V19 PR 1 (P1-C3) — chain formal-incumbent carry-over.
            # Reconstruction is unconditional; the flag controls only
            # whether the tuner's formal gates consume the reference.
            restored_chain_incumbent_score=state.chain_best_valid_formal_score,
            enable_chain_incumbent_formal_gates=args.enable_chain_incumbent_formal_gates,
            # External agents (Commit 6) — see Design Decisions 1 + 2 in
            # docs/commit_plan_ml_literature_review.md. The enable flag is
            # resolved above (CLI > YAML > False); the config path
            # passes through unchanged (workflow resolves relative paths
            # against SIDERIUS_ROOT internally).
            lit_review_enabled=ml_lit_review_enabled_resolved,
            lit_review_config_path=args.ml_lit_review_config,
            # Pseudo-mode factories (Stage 3 / Commit 4.5). None preserves the
            # production code path; non-None swaps the bridge / sandbox class
            # for every agent constructed inside ``run_workflow``.
            bridge_factory=bridge_factory,
            sandbox_factory=sandbox_factory,
        )
    except LLMBridgeContextError as e:
        # §1.4.2 fail-fast contract. Telemetry-internal corruption (run_id
        # mismatch, backwards iter) means the audit log can no longer be
        # trusted. exit(2) is intentionally distinct from the failure
        # exit(1) below so a downstream classifier can tell them apart.
        print(
            f"[FATAL] LLMBridgeContextError: {e} — aborting iteration to "
            f"prevent telemetry corruption.",
            file=sys.stderr,
        )
        write_manifest(iter_dir, run_name, results=[], crashed=True)
        sys.exit(2)
    except Exception as e:
        print(f"FAIL: Workflow raised exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        write_manifest(iter_dir, run_name, results=[], crashed=True)
        sys.exit(1)

    manifest = write_manifest(
        iter_dir,
        run_name,
        results,
        # V19 PR 1 (Invariant II): the chain incumbent this iteration
        # consumed, stamped under its own keys — never as an
        # iteration-local best_* field. ``used`` reflects the coupling
        # flag; ``source`` records the reconstruction provenance even
        # when unconsumed.
        chain_incumbent_used=(
            state.chain_best_valid_formal_score
            if args.enable_chain_incumbent_formal_gates
            else None
        ),
        chain_incumbent_source=state.chain_best_valid_formal_provenance,
    )

    # Per-iter [TOKEN_ITER] rollup (§1.6). Best-effort: any IO/JSON error
    # in the rollup must never break the chain — token_usage.jsonl is
    # itself the source of truth.
    try:
        _emit_token_iter_rollup(
            workspace=args.workspace,
            iteration=args.start_iteration,
        )
    except Exception as e:
        print(f"  [TOKEN_ITER] WARN: rollup emit failed: {type(e).__name__}: {e}")

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
            "[CHAIN] No models passed gates this iteration. "
            "Writing manifest and exiting gracefully to allow chain to continue."
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
