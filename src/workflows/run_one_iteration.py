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
    python src/workflows/run_one_iteration.py \\
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

Iteration manifests are WRITE-ONCE (arXiv-readiness S2 / U5, #258): a
launch into an ``iter_NNN/`` that already holds a ``manifest.json`` is
refused (exit 2) before any work. Rerun an iteration deliberately with
``--replace_iteration_manifest --replacement_reason '<why>'`` — the
previous manifest is set aside as ``manifest.replaced.<stamp>.json`` and
its digests are recorded in the new manifest's ``manifest_replacement``.
#258 refinement (operator ruling): ``--auto_resume`` — forwarded by
``run_chain.sh`` only when the inspector computed the start iteration —
authorizes that SAME replacement path for a manifest whose terminal
status is ``failed`` or ``no_records``; a ``completed`` manifest is never
replaced by auto-resume.
"""

# ruff: noqa: E402 -- bytecode policy must precede third-party and framework imports.

import argparse
import glob
import hashlib
import json
import os
import sys
import traceback
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from workflows.reviewed_launch import ReviewedLaunchContext

# A direct one-iteration launch does not pass through run_chain.sh.  Establish
# the same read-only-checkout policy before importing any SIDERIUS module, and
# transport it to every training, inference, scoring, and probe subprocess.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

from dotenv import load_dotenv

from agent.data_analysis.source_scope import source_prompt_identity
from agent.schemas.ordering import ResolvedOrdering
from agent.schemas.telemetry import LLMBridgeContextError
from agent.skills.evaluate_vram_skill.preflight_adapter import PREFLIGHT_EXECUTION_MODE
from core.iteration_manifest import (
    ManifestAlreadyPublishedError,
    ManifestReplacementError,
    ManifestReplacementRequest,
    classify_manifest_slot,
    manifest_path,
    publish_iteration_manifest,
)
from core.layout import checkout_root
from core.planner_strategy_identity import PlannerStrategyIdentity
from core.record_role import formal_evidence_of
from core.run_invariants import (
    LockLaunchIdentity,
    RunHealthMaterialization,
    RunInvariants,
    RunInvariantsViolation,
    build_run_invariants,
)
from execute_tools.data_paths import DatasetDirectoryUnavailable, resolve_dataset_dir
from execute_tools.dataset_config import DataScope, resolve_dataset_profile
from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.launch_policy import (
    FormalLaunchPolicyError,
    validate_formal_launch,
)
from workflows.advice import (
    ADVICE_INERT_KEY_PREFIX as ADVICE_INERT_KEY_PREFIX,
)
from workflows.advice import (
    ADVICE_PER_AGENT_KEYS as ADVICE_PER_AGENT_KEYS,
)
from workflows.advice import (
    ADVICE_RECOGNISED_KEYS as ADVICE_RECOGNISED_KEYS,
)
from workflows.advice import (
    AdviceArtifact as AdviceArtifact,
)
from workflows.advice import (
    AdviceArtifactError as AdviceArtifactError,
)
from workflows.advice import (
    _validate_advice_consumability as _validate_advice_consumability,
)
from workflows.advice import (
    load_advice_artifact as load_advice_artifact,
)
from workflows.advice import (
    render_advice_value as render_advice_value,
)
from workflows.advice import (
    resolve_advice_artifact as resolve_advice_artifact,
)
from workflows.launch_identity import (
    LaunchIdentity as LaunchIdentity,
)
from workflows.launch_identity import (
    resolve_launch_identity as resolve_launch_identity,
)
from workflows.launch_identity import (
    resolve_lit_review_enabled as resolve_lit_review_enabled,
)
from workflows.llm_config import WorkflowLLMConfig, resolve_standard_llm_config
from workflows.run_config import WorkflowLaunchConfig, validate_launch_trial_overrides
from workflows.runtime_settings import (
    build_required_profile_binding as build_required_profile_binding,
)
from workflows.runtime_settings import (
    resolve_watchdog_policy as resolve_watchdog_policy,
)
from workflows.standard_cli import (
    _experiment_arm_label as _experiment_arm_label,
)
from workflows.standard_cli import (
    _portion_floor as _portion_floor,
)
from workflows.standard_cli import (
    _positive_int as _positive_int,
)
from workflows.standard_cli import (
    build_parser as build_parser,
)
from workflows.standard_cli import (
    normalize_args as normalize_args,
)
from workflows.standard_launch import (
    build_standard_launch_config,
)
from workflows.standard_launch import (
    parse_allowed_output_types as parse_allowed_output_types,
)
from workflows.task_composition import (
    RunTaskComposition,
    bind_run_task_composition,
    compose_run_task_bindings,
    resolve_composed_measurement_capability,
)

_CHECKOUT_ROOT = checkout_root()
SIDERIUS_ROOT = (
    str(_CHECKOUT_ROOT) if _CHECKOUT_ROOT is not None else str(Path(__file__).resolve().parents[2])
)
if _CHECKOUT_ROOT is not None:
    load_dotenv(dotenv_path=Path(SIDERIUS_ROOT) / ".env")


def load_validation_fixed_candidate_plan(path: str | None) -> dict | None:
    """Load a fixed candidate PLAN for a validation run (V20 FU-D-11).

    Returns ``{"plan": ..., "provenance": ...}``, or ``None`` when no path was
    given (the ordinary campaign case — the proposer decides).

    The provenance half is not decoration: an acceptance run that bypassed the
    proposer must be able to prove WHICH plan it used. It records
    ``candidate_source``, the absolute path, a sha256 over the canonicalised
    payload, and the resolved model identity — computed from the bytes
    actually read, so the hash cannot drift from the plan that was used.

    **Fails closed, loudly.** A malformed file, an unreadable path or a
    payload that is not a valid ``ProposalOutput`` refuses the launch. It does
    NOT fall back to the proposer: a run that asked for a fixed candidate and
    silently got an invented one would report a deterministic acceptance it
    never performed.

    **Unknown keys are REFUSED, not dropped.** ``ProposalOutput`` has no field
    for a score, record, gate verdict, authority verdict or incumbent, so
    Pydantic's default ``extra="ignore"`` would silently discard one that
    appeared. Silent discarding is precisely the defect class this PR family
    hit three times, so a stray ``denoising_score`` fails the launch instead.

    Raises:
        SystemExit: on any unreadable, malformed or results-bearing payload.
    """
    if path is None:
        return None

    from pydantic import ValidationError

    from agent.schemas.proposal import ProposalOutput

    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except OSError as exc:
        raise SystemExit(f"--validation_fixed_candidate_plan: cannot read {path!r}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} must hold a JSON object "
            f"describing one candidate plan, got {type(payload).__name__}"
        )

    # V21 PR E: candidate_id became a ProposalOutput field, which silently
    # removed it from the unknown-key refusal below. It must stay refused
    # HERE: the id is SYSTEM-minted at proposal time (O-E-4), and a fixed
    # plan is by definition not a proposer-emitted candidate — an id entering
    # through this seam would be an identity nobody minted.
    if "candidate_id" in payload:
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} carries "
            f"'candidate_id'. Candidate identity is system-generated at "
            f"proposal time and may not be supplied through a plan; remove "
            f"the key. (A fixed-plan candidate deliberately runs with "
            f"candidate_id=None — it is not a proposer-emitted candidate.)"
        )

    known = set(ProposalOutput.model_fields)
    unknown = sorted(set(payload) - known)
    if unknown:
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} carries keys that are "
            f"not part of a candidate plan: {unknown}. This seam injects a PLAN "
            f"only — a prior score, record, gate verdict, authority verdict or "
            f"incumbent must never enter through it, and dropping them silently "
            f"would hide that it happened."
        )

    try:
        plan = ProposalOutput.model_validate(payload)
    except ValidationError as exc:
        raise SystemExit(
            f"--validation_fixed_candidate_plan: {path!r} is not a valid candidate plan: {exc}"
        ) from exc

    # Provenance is computed HERE, from the bytes actually read, so the
    # recorded hash cannot drift from the plan that was used.
    provenance = {
        "candidate_source": "fixed_validation_plan",
        "plan_path": os.path.abspath(path),
        "plan_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "resolved_model_name": plan.model_name,
        "resolved_baseline_config_keys": sorted(plan.baseline_config),
    }
    return {"plan": plan.model_dump(mode="json"), "provenance": provenance}


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


def _infrastructure_abort_reason(results: list) -> str | None:
    """C9c: the tuner's typed infrastructure-abort signal, if it fired.

    ``termination_reason == "infrastructure_abort"`` means the runtime
    EVIDENCE CHANNEL failed — registry, persistence, schema/protocol,
    probe executor, telemetry, communication, or a policy invariant. It is
    deliberately distinct from a candidate rejection (attempt-local), gate
    exhaustion (``no_records``, chain continues), an operator stop, and an
    ordinary subprocess crash.
    """
    for output in results or []:
        if getattr(output, "termination_reason", None) == "infrastructure_abort":
            return getattr(output, "status", None) or "infrastructure_abort"
    return None


def _write_halt_marker(workspace: str, payload: dict) -> str:
    """Write the chain-halt sentinel. Shared by the consecutive-failure
    brake and the C9c infrastructure abort; ``reason`` distinguishes them
    so an operator (and the next process) can tell WHY the chain stopped.
    """
    halt_path = os.path.join(workspace, ".chain_halted")
    with open(halt_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return halt_path


def _check_halt_marker(workspace: str) -> bool:
    """Return True iff a chain halt marker exists in this workspace.

    Cheap fail-fast for SDSC ``afterany`` chains: Slurm queues the next
    iter regardless of the previous's exit code, so we need an on-disk
    sentinel for the next process to bail out before doing any work.
    Called first thing in ``main()`` (after argparse), before any dirs
    are created.
    """
    return os.path.exists(os.path.join(workspace, ".chain_halted"))


def _halt_contract_failure(workspace: str, iteration: int, error: Exception) -> NoReturn:
    """A new candidate cannot repair contradictory or unreadable run history."""
    _write_halt_marker(
        workspace,
        {
            "halted_at": datetime.now(UTC).isoformat(),
            "workspace": os.path.abspath(workspace),
            "reason": "run_contract_failure",
            "iteration": iteration,
            "detail": f"{type(error).__name__}: {error}",
        },
    )
    sys.exit(3)


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


def _ordering_by_experiment(tune_output) -> list[dict]:
    """Per-experiment ordering provenance for the iteration manifest.

    One entry per record, each self-identifying by ``exp_id``, because
    ordering may resolve differently across rounds of a single iteration.
    Collapsing them into one iteration-level value would silently misreport
    every round but one (§3.7 granularity rule).

    Only ``resolved_*`` describes selected execution settings, not completed
    traversal; ``proposed_*`` and
    ``override_*`` explain why, and a rejected proposal is carried AS
    rejected so it is never read as agent silence.

    Best-effort by design: the manifest is a handoff aid, and a malformed
    record must not take down an iteration that otherwise succeeded.
    """
    entries: list[dict] = []
    for record in getattr(tune_output, "all_records", None) or []:
        try:
            ordering = ResolvedOrdering.from_record(record)
            entries.append(
                {
                    "exp_id": getattr(record, "exp_id", None),
                    "round_index": getattr(getattr(record, "memory", None), "round_index", None),
                    "proposed_order_strategy": ordering.proposed_strategy,
                    "proposed_file_order": ordering.proposed_file_order,
                    "ordering_proposal_rejected": ordering.proposal_rejected,
                    "ordering_proposal_rejection_reason": ordering.proposal_rejection_reason,
                    "override_order_strategy": ordering.override_strategy,
                    "override_file_order": ordering.override_file_order,
                    "resolved_order_strategy": ordering.resolved_strategy,
                    "resolved_file_order": ordering.resolved_file_order,
                    "ordering_resolution_source": ordering.resolution_source,
                    **(
                        {"ordering_observation": record.ordering_observation.model_dump()}
                        if getattr(record, "ordering_observation", None) is not None
                        else {}
                    ),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[WARN] could not read ordering provenance for a record: {exc}")
    return entries


def write_manifest(
    iter_dir: str,
    run_name: str,
    results: list,
    *,
    crashed: bool = False,
    healthgate_mode: str | None = None,
    result_authority: str | None = None,
    chain_incumbent_used: float | None = None,
    chain_incumbent_source: dict | None = None,
    health_feedback_policy: dict | None = None,
    fixed_candidate_provenance: dict | None = None,
    launch_identity: LaunchIdentity | None = None,
    replacement: ManifestReplacementRequest | None = None,
) -> dict:
    """
    Write a manifest.json summarizing this iteration's output.

    The manifest is the discoverable handoff between iterations: the next
    iteration's job reads it to find this iteration's tuning output path.

    arXiv U1 — ``launch_identity`` stamps ``experiment_arm``,
    ``lit_review_enabled`` and ``lit_review_config_sha256`` on EVERY branch
    under the lock's own omission rule: a key is written only when it
    departs from the legacy default (arm ``None``, lit-review ``False``, sha
    ``None``), so an unlabelled lit-review-OFF iteration's manifest is
    byte-identical to its pre-U1 form and a reader applies ONE rule to the
    lock and the manifest alike (absent = the default). ``None`` (a caller
    that predates the parameter) stamps nothing.

    S2 / U5 (#258): the manifest is published WRITE-ONCE through
    ``core.iteration_manifest.publish_iteration_manifest`` — it gains a
    ``manifest_sha256`` self-digest, and a second write for the same
    iteration is a named ``ManifestAlreadyPublishedError`` unless
    ``replacement`` carries the explicit operator request, in which case
    the previous manifest is set aside and its digests are recorded under
    ``manifest_replacement``. ``run_output_sha256`` is always computed for
    THIS publication's artifact; it is never copied from a previous
    manifest.

    Status taxonomy (consumed by ``core/resume.py:_read_manifest``):
      * ``"completed"`` — workflow produced a real best_denoising_score.
        Resume: consume the run_output and restore the plugin.
      * ``"no_records"`` — workflow ran cleanly but every tuner round
        failed/was skipped (gate exhaustion, all-rounds returned None
        score). The chain MUST keep going so the next iter's LLM can see
        the bounded negative feedback and adapt. Resume: transport only that
        feedback; skip the invalid artifact and restore no plugin or incumbent.
      * ``"failed"`` — workflow itself crashed (Python exception, seed-
        resolution error, restore_prior_state error). The chain halts.
        Set via ``crashed=True``.
    """
    # `tune_output` is only bound on the completed branch. The stamps at the
    # bottom of this function run on EVERY branch, so it is initialised here
    # rather than guarded there — a crashed or record-less iteration has no
    # tuner output, and `None` is the honest answer for its declared posture.
    tune_output = None

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
        #
        # `score` is CHAINABILITY, not science: it is `top_record` over ALL
        # records, trial and formal mixed (records.py), so it answers "is
        # there an artifact for the next iteration to consume?" and nothing
        # else. `status` keeps deriving from it because the manifest status
        # vocabulary is completed|failed|no_records and is shared by
        # core/resume.py, result consumers, and the inspector. A
        # trial-only iteration DID produce a consumable run_output and a
        # restorable plugin.
        score = tune_output.best_denoising_score
        manifest = {
            "status": "completed" if score is not None else "no_records",
            "iteration_dir": iter_dir,
            "output_path": output_path if score is not None else None,
            "model_name": model_name,
            # The headline number is the FORMAL best — `None` when no formal
            # round produced one. The mixed top score keeps its own key
            # below, under the name that says what it is.
            "best_score": getattr(tune_output, "best_formal_denoising_score", None),
            "raw_best_score": score,
            "best_valid_score": getattr(tune_output, "best_valid_denoising_score", None),
            "raw_best_formal_score": getattr(tune_output, "best_formal_denoising_score", None),
            "best_valid_formal_score": getattr(
                tune_output, "best_valid_formal_denoising_score", None
            ),
            # V19 PR 1 (P1-C4) — read-only trial-best bookkeeping mirror.
            "best_valid_trial_score": getattr(
                tune_output, "best_valid_trial_denoising_score", None
            ),
            "completed_rounds": tune_output.completed_rounds,
            "health_checks_config": getattr(tune_output, "health_checks_config", None),
            # DS6c — invariant stamps (scalar comparability boundary).
            "resolved_data_scope": getattr(tune_output, "resolved_data_scope", None),
            "health_gate_enabled": getattr(tune_output, "health_gate_enabled", None),
            "health_config_sha256": getattr(tune_output, "health_config_sha256", None),
            "formal_reference_score": getattr(tune_output, "formal_reference_score", None),
            # V20 PR D §16.C — the provenance travels WITH the reference.
            # `formal_reference_score: null` alone is ambiguous: it means
            # "no incumbent", "gates off" or "the bound was infinite", and
            # those call for different readings of the iteration.
            "formal_comparison_reference_source": getattr(
                tune_output, "formal_comparison_reference_source", None
            ),
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
            # V19 PR 2 (§3.7) — ordering provenance, KEYED PER EXPERIMENT.
            # Ordering can resolve differently for different rounds of one
            # iteration (the agent may propose differently each round when no
            # operator override is in force), so a single iteration-level
            # value would misreport every round but one. Never collapse this.
            "ordering_by_experiment": _ordering_by_experiment(tune_output),
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

    # F-SCANB-3 — what this iteration produced SCIENTIFICALLY, beside the
    # chainability status rather than inside it, computed by the shared role
    # authority (`core.record_role`) over the persisted record shape. All ten
    # v20 attempt-3 manifests read `status: completed` with a best_score
    # between 0.479 and 10.708 while carrying ZERO formal records, so an
    # operator — and every trajectory built from these manifests — read trial
    # scores as the campaign's results while the status concealed that no
    # formal round had ever run.
    #
    # Stamped on EVERY branch, like the three stamps below: a crashed or
    # record-less iteration produced no formal evidence either, and an
    # all-zero posture is the honest way to say so.
    manifest["formal_evidence"] = formal_evidence_of(tune_output).model_dump()

    # V19 PR 3 (§3.9) — the chain's structured-health-feedback CONTROL
    # POLICY (flag + retention), stamped on EVERY manifest branch
    # (completed / no_records / failed) so failed iterations stay
    # auditable. Policy only: per-round gate evidence lives in the
    # records and the interpretation digest — never duplicated here.
    manifest["health_feedback_policy"] = health_feedback_policy

    # Issue #396 — a scientifically invalid iteration still has evidence.
    #
    # ``no_records`` deliberately names no consumable model artifact: resume
    # must not restore its plugin, score, or incumbent.  A validated tuner
    # output can nevertheless carry the bounded summaries that explain why
    # no candidate was usable.  Persist those summaries on the write-once,
    # self-digested manifest so the next process can learn from the failure
    # without treating the invalid run output as a successful handoff.
    if manifest["status"] == "no_records" and tune_output is not None:
        negative_feedback = {
            field: value.model_dump(mode="json")
            for field in ("gate_exhaustion", "trial_validity_feedback", "formal_validity_feedback")
            if (value := getattr(tune_output, field, None)) is not None
        }
        if negative_feedback:
            manifest["negative_feedback"] = negative_feedback

    # V20 FU-D-11 — WHICH candidate plan this iteration ran, when the
    # proposer was bypassed. Stamped on EVERY branch, like the policy above:
    # an acceptance run that skipped the proposer must be able to prove what
    # it used, and a failed iteration is exactly when that matters. `None`
    # means the proposer chose normally.
    manifest["fixed_candidate_provenance"] = fixed_candidate_provenance

    # V20 PR A (§11) — pre-flight execution provenance, stamped on EVERY
    # branch for the same reason as the policy above: a crashed iteration
    # is exactly when you want to know how the pre-flight ran.
    #
    # Imported from the adapter rather than written as a literal, so the
    # manifest and the mechanism cannot drift apart. This records which
    # mechanism the build ships; that production reaches it is a separate
    # claim, proven by the reachability guardrails.
    manifest["preflight_execution_mode"] = PREFLIGHT_EXECUTION_MODE

    # V20 PR D (D-C1a) — the declared enforcement/authority axes, stamped on
    # EVERY branch for the same reason as the two above: a crashed iteration
    # is exactly when "was this run even allowed to be authoritative?" has
    # to be answerable.
    #
    # V20 PR D — the DECLARATION is a validated LAUNCH fact, not a
    # tuner-result field. D-C1b refuses the launch outright unless both axes
    # are declared and consistent, so by the time any artifact is written
    # they exist — whether the iteration completed, produced no records,
    # degraded, or crashed.
    #
    # CORRECTED after Gate 2 attempt 1: this previously read the posture off
    # `tune_output` and wrote `null` whenever the tuner produced none. A real
    # chain launched with `--healthgate_mode blocking` therefore recorded
    # `healthgate_mode: null` because it failed, which makes its records
    # `unreconstructable_legacy` under D-C4 even though the run DID declare
    # its posture. The caller's validated declaration is authoritative; the
    # tuner output is only a fallback for callers that predate this
    # parameter.
    manifest["healthgate_mode"] = (
        healthgate_mode
        if healthgate_mode is not None
        else getattr(tune_output, "healthgate_mode", None)
    )
    manifest["result_authority"] = (
        result_authority
        if result_authority is not None
        else getattr(tune_output, "result_authority", None)
    )

    # arXiv U1 (#253 / #254) — run identity, on EVERY branch, under the
    # lock's omission rule (see the docstring). A crashed labelled iteration
    # is exactly when "which arm was this?" has to be answerable.
    if launch_identity is not None:
        if launch_identity.experiment_arm is not None:
            manifest["experiment_arm"] = launch_identity.experiment_arm
        if launch_identity.lit_review_enabled:
            manifest["lit_review_enabled"] = True
        if launch_identity.data_analysis_enabled is not None:
            manifest["data_analysis_enabled"] = launch_identity.data_analysis_enabled
        if launch_identity.retain_model_outputs:
            manifest["retain_model_outputs"] = True
        if launch_identity.retain_training_checkpoints:
            manifest["retain_training_checkpoints"] = True
        if launch_identity.lit_review_config_sha256 is not None:
            manifest["lit_review_config_sha256"] = launch_identity.lit_review_config_sha256
        if launch_identity.scientific_evidence_order != "analysis_then_literature":
            manifest["scientific_evidence_order"] = launch_identity.scientific_evidence_order
        # arXiv U3 — the isolation flag, under the same omission rule.
        if launch_identity.baseline_isolation:
            manifest["baseline_isolation"] = True

    # S2 / U5 — self-digest + write-once publish (+ explicit replacement
    # provenance). Stamped LAST so every key above, including any a later
    # producer change adds, is covered by the digest.
    manifest_path = publish_iteration_manifest(iter_dir, manifest, replacement=replacement)
    print(f"Manifest written: {manifest_path}")
    return manifest


@dataclass(frozen=True)
class IterationDirPlan:
    """The iteration's directory, run name and manifest-slot decision."""

    run_name: str
    iter_dir: str
    #: ``None`` for a normal (first) publication; the explicit request when
    #: the operator asked to replace an existing manifest.
    manifest_replacement: ManifestReplacementRequest | None


#: #258 refinement (operator ruling, 2026-08-24): the two TERMINAL states an
#: auto-resume relaunch may replace. A ``completed`` manifest is immutable to
#: auto-resume; anything unrecognisable is refused, never guessed.
_AUTO_RESUME_REPLACEABLE_STATUSES = frozenset({"failed", "no_records"})

#: Recognisable prefix of the provenance reason an auto-resume recovery
#: records — the evidence that the replacement happened BECAUSE of
#: auto-resume, not an operator's explicit destructive operation.
AUTO_RESUME_REPLACEMENT_REASON_PREFIX = "auto_resume recovery"


def _auto_resume_replacement(iter_dir: str) -> ManifestReplacementRequest | None:
    """Classify the manifest slot for an auto-resume relaunch (#258 refinement).

    Auto-resume counts as explicit recovery intent ONLY for a slot whose
    existing manifest is terminally ``failed`` or ``no_records``; the
    replacement then goes through the SAME explicit replacement path (set
    aside + provenance) as ``--replace_iteration_manifest``. Everything else
    returns ``None`` so ``classify_manifest_slot`` refuses exactly as it
    would without the flag: a fresh slot needs no replacement, and a
    ``completed`` — or unreadable / unrecognisable — manifest is never
    replaced by auto-resume. The classification lives HERE, at the
    orchestration boundary; the publish layer never inspects a status.
    """
    path = manifest_path(iter_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            existing = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None  # unclassifiable — fail closed into the write-once refusal
    status = existing.get("status") if isinstance(existing, dict) else None
    if status not in _AUTO_RESUME_REPLACEABLE_STATUSES:
        return None
    return ManifestReplacementRequest(
        reason=(
            f"{AUTO_RESUME_REPLACEMENT_REASON_PREFIX}: prior iteration manifest was "
            f"terminal {status!r} (#258)"
        )
    )


def prepare_iteration_dir(
    workspace: str,
    start_iteration: int,
    *,
    replace_iteration_manifest: bool,
    replacement_reason: str | None,
    auto_resume_recovery: bool = False,
) -> IterationDirPlan:
    """Create ``{workspace}/iter_{N:03d}`` and decide its manifest slot (#258).

    Refuses BEFORE any expensive work, so an hours-long iteration can never
    end in a refused manifest publish. ``auto_resume_recovery`` (the
    ``--auto_resume`` flag, forwarded by ``run_chain.sh`` only when the
    inspector computed the start iteration) authorizes the SAME replacement
    path for a manifest whose terminal status is ``failed`` or
    ``no_records`` — and nothing else.

    Raises:
        ManifestAlreadyPublishedError: a manifest already exists for this
            iteration and no replacement applies (write-once) — including a
            ``completed`` or unclassifiable manifest under auto-resume.
        ManifestReplacementError: ``--replace_iteration_manifest`` without a
            non-empty ``--replacement_reason``, a reason without the flag, or
            an explicit replacement requested where no manifest exists.
    """
    run_name = f"iter_{start_iteration:03d}"
    iter_dir = os.path.join(workspace, run_name)
    os.makedirs(iter_dir, exist_ok=True)
    replacement: ManifestReplacementRequest | None = None
    if replace_iteration_manifest:
        try:
            replacement = ManifestReplacementRequest(reason=replacement_reason or "")
        except ValueError as exc:
            raise ManifestReplacementError(
                f"--replace_iteration_manifest requires --replacement_reason '<why>': {exc}"
            ) from exc
    elif replacement_reason:
        raise ManifestReplacementError(
            "--replacement_reason was given without --replace_iteration_manifest; a "
            "replacement must be requested explicitly, not implied by a reason."
        )
    elif auto_resume_recovery:
        # #258 refinement: recovery intent applies to a failed/no_records
        # slot ONLY; None falls through to the write-once refusal.
        replacement = _auto_resume_replacement(iter_dir)
    classify_manifest_slot(iter_dir, replacement)
    return IterationDirPlan(run_name=run_name, iter_dir=iter_dir, manifest_replacement=replacement)


@dataclass(frozen=True)
class _InvariantLaunchInputs:
    """Already resolved launch inputs, reused by the workspace-lock preflight."""

    identity: LaunchIdentity | None = None
    llm_config: WorkflowLLMConfig | None = None


_UNRESOLVED_LAUNCH_INPUTS = _InvariantLaunchInputs()


def _resolve_launch_planner_identity(
    args: argparse.Namespace, llm_config: WorkflowLLMConfig | None
) -> PlannerStrategyIdentity:
    """Resolve the configured strategy before computing or mutating run locks."""
    from agent.planner_strategy import resolve_planner_strategy

    if llm_config is None:
        config_path = getattr(args, "llm_config", None)
        llm_config = (
            WorkflowLLMConfig.from_json(config_path) if config_path else WorkflowLLMConfig()
        )
    return resolve_planner_strategy(llm_config.get("tune").get("planner_strategy")).identity


def compute_expected_invariants(
    args: argparse.Namespace,
    *,
    run_composition: RunTaskComposition | None = None,
    launch: _InvariantLaunchInputs = _UNRESOLVED_LAUNCH_INPUTS,
) -> RunInvariants:
    """DS6c — compute this run's invariants via the ONE shared path.

    Materializes + hashes the effective HealthGate config into the chain
    workspace root (idempotent — ``run_workflow``'s pre-flight recomputes
    the identical body sha) and returns the ``RunInvariants`` used for
    both ``restore_prior_state`` validation and, transitively, the
    workspace lock. Called BEFORE any resume mutation or LLM work.

    Step 10 / P5+P6 **W7**: that idempotence claim is only true when BOTH
    materializations resolve the SAME Health binding. P1 gave ``run_workflow``
    a ``task_health_binding`` but not this earlier pre-flight, so a COMPOSED
    run materialized ``task_health_binding: legacy_default`` here and then
    ``explicit`` in ``run_workflow`` — two different documents, two different
    body shas, and the workspace-immutability check (correctly) refused the
    run. Found by the FIRST real composed chain run; no test caught it because
    none drove the real chain runner under a composition.

    It takes the **composition object**, not individual derived values, and
    derives every composition-dependent invariant here. That is deliberate: a
    first cut of W7 threaded ``task_health_binding`` alone and forgot its
    sibling ``task_composition_fingerprint``, so iteration 2's pre-flight
    computed ``None`` against a lock that already held the fingerprint and the
    chain refused itself. Passing the composition makes the two call sites
    structurally incapable of diverging, and
    ``test_step10_p56_c5_wiring_closures.py`` censuses that they agree.

    ``None`` reproduces the pre-W7 behaviour exactly, which is what every
    un-composed run gets.

    The private ``launch`` carrier reuses the identity and LLM configuration
    already resolved by ``main``. Missing values resolve from ``args`` through
    their existing authorities, so direct callers lock the same values as the
    workflow; an undeclared planner still requires an installed default provider.
    """
    planner_identity = _resolve_launch_planner_identity(args, launch.llm_config)
    identity = launch.identity if launch.identity is not None else resolve_launch_identity(args)
    run_scope = args.data_scope if args.data_scope is not None else DataScope.default()
    # Step 12 / PR-12a **F-12-1** — resolve against the RUN's topology.
    #
    # This pre-flight runs BEFORE `bind_run_task_composition`, so
    # `resolve_dataset_profile()` cannot see a composition yet and would
    # answer TIDMAD for every run. The composition object is already a
    # parameter here (W7 threads its Health binding and fingerprint below),
    # so the composed branch reads it directly — mirroring `run_workflow`'s
    # own composed-aware site (`model_exploration.py`, `_run_dataset`).
    #
    # Un-composed this is byte-identical to the `TIDMAD` constant it
    # replaces: `resolve_dataset_profile()` returns `TIDMAD_PROFILE` and
    # `TIDMAD_PROFILE.dataset` IS that singleton, the same object. Reading
    # it through the resolver rather than importing the task singleton is
    # also what keeps this launcher clean for the F-12-6 census.
    run_partitions = (
        resolve_dataset_profile().partition_count
        if run_composition is None
        else run_composition.dataset_profile.partition_count
    )
    resolved_scope = run_scope.resolve(run_partitions)
    invariants, _ = build_run_invariants(
        resolved_data_scope=resolved_scope,
        health_gate_enabled=args.health_gate_enabled,
        health_gate_files=args.health_gate_files,
        health_checks_config=args.health_checks_config,
        workspace=args.workspace,
        # V19 PR 2 — the ordering override is chain control policy, so it
        # is locked. Must match what the workflow and tuner lock for this
        # same workspace.
        ordering_override_strategy=args.order_strategy_override,
        ordering_override_file_order=args.file_order_override,
        # V19 PR 3 — same rule for the structured-health-feedback policy.
        structured_health_feedback_enabled=args.enable_structured_health_feedback,
        health_feedback_history_window_iterations=(args.health_feedback_history_window_iterations),
        health_feedback_history_max_entries_per_model=(
            args.health_feedback_history_max_entries_per_model
        ),
        # W7 — EVERY composition-derived invariant `run_workflow` passes, so
        # the pre-flight and the workflow agree on both the materialized
        # document AND the workspace lock.
        health_materialization=RunHealthMaterialization(
            task_health_binding=(
                run_composition.task_health_binding if run_composition is not None else None
            ),
            dataset_partition_count=run_partitions,
        ),
        task_composition_fingerprint=(
            run_composition.semantic_fingerprint if run_composition is not None else None
        ),
        # arXiv U1 — the identity the workflow's pre-flight will lock too.
        launch_identity=LockLaunchIdentity(
            gpu_execution_policy=identity.gpu_execution_policy,
            planner_strategy_identity=planner_identity,
            lit_review_enabled=identity.lit_review_enabled,
            data_analysis_enabled=identity.data_analysis_enabled,
            retain_model_outputs=identity.retain_model_outputs,
            retain_training_checkpoints=identity.retain_training_checkpoints,
            lit_review_config_sha256=identity.lit_review_config_sha256,
            scientific_evidence_order=identity.scientific_evidence_order,
            experiment_arm=identity.experiment_arm,
            baseline_isolation=identity.baseline_isolation,
            # Gold campaign — the OBSERVED advice identity. `run_workflow`
            # locks this SAME workspace, so it must resolve the same pair or
            # the two would write contradictory locks and abort every
            # advice-bound run (the V19 PR 2 rule, one field family over).
            advice_sha256=identity.advice_sha256,
            advice_path=identity.advice_path,
            analysis_source_prompt_sha256=source_prompt_identity(args.analysis_source_prompt),
            # F-SCANF-1 — the formal round's evaluation FRACTION, from the
            # SAME namespace `WorkflowLaunchConfig` receives it from, so this
            # pre-flight and `run_workflow`'s own lock for this workspace
            # cannot contradict each other.
            training_validation_portion=args.training_validation_portion,
            formal_eval_portion=args.formal_eval_portion,
            validation_max_portion=args.validation_max_portion,
            validation_max_samples=args.validation_max_samples,
            formal_training_scope_source=args.formal_training_scope_source,
            workflow_parameter_rules=(
                None
                if args.workflow_parameter_rules is None
                else args.workflow_parameter_rules.model_dump(mode="json", exclude_none=True)
            ),
            trial_time_admission_source=args.trial_time_admission_source,
            formal_time_admission_source=args.formal_time_admission_source,
            runtime_completion_policy=args.runtime_completion_policy,
            runtime_verifier_identity=identity.runtime_verifier_identity,
        ),
    )
    return invariants


def print_resolved_launch_config(args: argparse.Namespace) -> int:
    """arXiv U3 (#259) — print the resolved launch configuration as ONE JSON
    object and return the process exit status, without iteration execution or
    run-artifact writes. Resolving the existing workflow owners can import
    plugins with their own import-time effects and stdout.

    Returns ``0`` after printing; ``1`` (with the reason on stderr) when the
    identity cannot be resolved — an enabled lit-review whose config cannot
    be read has no resolved configuration to print.
    """
    from workflows.literature_config import resolve_lit_review_config_path

    try:
        identity = resolve_launch_identity(args)
    except ValueError as exc:
        print(f"[run_one_iteration] launch identity could not be resolved: {exc}", file=sys.stderr)
        return 1
    # arXiv #261 — idempotent: in the main() path the policy is already
    # resolved and cached on args; a direct caller gets the same one-shot
    # resolution here so the printed values are final, never the raw
    # tri-state defaults.
    watchdog_policy = resolve_watchdog_policy(args)
    resolved = {
        "workspace": os.path.abspath(args.workspace),
        "run_name": args.run_name,
        "start_iteration": args.start_iteration,
        "experiment_arm": identity.experiment_arm,
        "lit_review_enabled": identity.lit_review_enabled,
        "data_analysis_enabled": identity.data_analysis_enabled,
        "retain_model_outputs": identity.retain_model_outputs,
        "retain_training_checkpoints": identity.retain_training_checkpoints,
        "lit_review_config_path": (
            resolve_lit_review_config_path(identity.lit_review_config_path)
            if identity.lit_review_config_path is not None
            else None
        ),
        "lit_review_config_sha256": identity.lit_review_config_sha256,
        "scientific_evidence_order": identity.scientific_evidence_order,
        "baseline_isolation": identity.baseline_isolation,
        "task_composition": args.task_composition or None,
        "advice_file": args.advice or args.human_advice_file or None,
        # The DECLARED path is above, as given. These two are what the launch
        # RESOLVED and OBSERVED: an operator comparing four bands reads the
        # digest, not the path, because the path is where the treatment lives
        # and the digest is what the treatment IS.
        "advice_path": identity.advice_path,
        "advice_sha256": identity.advice_sha256,
        "healthgate_mode": args.healthgate_mode,
        "result_authority": args.result_authority,
        # arXiv #261 — the resolved watchdog policy with its provenance, so
        # a user can see WHICH values were selected and WHERE they came
        # from (cli / shipped profile / measured overlay / uncalibrated)
        # without reading framework source.
        "execution_regime": args.execution_regime,
        "runtime_watchdog_enabled": watchdog_policy.enabled,
        "runtime_watchdog_safety_factor": watchdog_policy.safety_factor,
        "runtime_watchdog_floor_seconds": watchdog_policy.floor_seconds,
        "runtime_verification_max_wall_seconds": (args.runtime_verification_max_wall_seconds),
        "runtime_watchdog_provenance": watchdog_policy.provenance,
        # F-H100-WD-1-PRETAG — the DECLARED requirement, recorded whether or
        # not it was made, so "no binding was declared" is an observable
        # fact rather than an absent key. Whether the declaration was
        # CONSUMED is read from runtime_watchdog_provenance above, which
        # reads 'bound:<path>#sha256=<hex>' exactly when certification ran.
        "required_runtime_profile_path": args.required_runtime_profile_path,
        "required_runtime_profile": args.required_runtime_profile,
        "required_runtime_profile_sha256": args.required_runtime_profile_sha256,
    }
    json.dump(resolved, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None, *, reviewed_setup: "ReviewedLaunchContext | None" = None):
    args = normalize_args(build_parser().parse_args(argv))
    if reviewed_setup is not None:
        reviewed_setup.check_entry(args)
    # Validate the resolved schedule before workspace binding, task imports or LLM work.
    try:
        validate_launch_trial_overrides(
            WorkflowLaunchConfig(
                max_rounds=args.max_rounds,
                is_trial=args.is_trial,
                force_formal_round=args.force_formal_round,
                formal_training_scope_source=args.formal_training_scope_source,
                plan_overrides=args.plan_overrides,
                trial_portion=args.trial_portion,
                train_portion=args.train_portion,
                eval_portion=args.eval_portion,
            )
        )
    except ValueError as exc:
        build_parser().error(str(exc))
    # Generated-capability identity participates in the run-invariants lock,
    # so bind it before composition preflight, resume validation, or any
    # other operation that can build those invariants.
    from core.generated_library import bind_generated_library_to_workspace

    bind_generated_library_to_workspace(args.workspace)
    from core.local_code import root_code_scope

    with ExitStack() as package_scope:
        package_scope.enter_context(root_code_scope())
        try:
            if reviewed_setup is not None:
                return _run_bound_iteration(args, package_scope, reviewed_setup=reviewed_setup)
            return _run_bound_iteration(args, package_scope)
        except Exception as exc:
            from workflows.package_failure import halt_on_package_failure

            halt_on_package_failure(
                exc,
                workspace=args.workspace,
                iteration=args.start_iteration,
                write_marker=_write_halt_marker,
            )
            raise


def _run_bound_iteration(
    args: argparse.Namespace,
    package_scope: ExitStack,
    *,
    reviewed_setup: "ReviewedLaunchContext | None" = None,
):
    """Run the existing lifecycle after root workspace/package decisions."""

    # Both owners transitively load model registries. A cold launch must bind
    # its workspace first so discovery cannot import legacy checkout plugins.
    from core.resume import ResumeError, restore_prior_state
    from workflows.model_exploration import run_workflow

    # Resolve a valid composition before launch-policy validation so the
    # policy reads this run's task-owned Health declaration rather than
    # binding the legacy default first. Preserve the established malformed-
    # composition path below: its error is still recorded after the iteration
    # directory is prepared, so deterministic failures still contribute to
    # the consecutive-failure brake.
    preflight_composition = None
    preflight_composition_error: Exception | None = None
    if args.task_composition:
        try:
            preflight_composition = compose_run_task_bindings(args.task_composition)
        except Exception as exc:
            from core.local_code.failure import raise_if_code_package_failure

            raise_if_code_package_failure(exc)
            preflight_composition_error = exc

    if reviewed_setup is not None and preflight_composition_error is None:
        reviewed_setup.check_composition(preflight_composition)

    # Launch policy and invariants materialize Health before run activation.
    # They must see the same capture, without creating a transport sidecar.
    from core.local_code import bind_code_package

    package_scope.enter_context(
        bind_code_package(
            preflight_composition.code_package if preflight_composition is not None else None
        )
    )

    # --- V20 PR D (D-C1b): formal-launch policy refusal ----------------
    # THE FIRST thing done with the parsed arguments, and deliberately
    # before the failure-brake preflight below: a launch whose declared
    # policy cannot be honoured must not create an iter_dir, touch a
    # sentinel, call an LLM, construct a model or reach a GPU.
    #
    # Enforced HERE rather than in the tuner's schema, because this is the
    # new-formal-launch boundary. `validate_runtime_config` runs for every
    # tuner invocation including diagnostic tooling
    # (`scripts/bg_admission_validation.py` builds a tuner input), and the
    # permissive schema is what keeps historical artifacts readable —
    # `core/resume.py` reads manifests directly and never constructs a
    # HyperparamTuningInput, so tightening the launch path cannot make an
    # old artifact unopenable.
    try:
        validate_formal_launch(
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            health_checks_config=args.health_checks_config,
            gates_enabled=args.enable_chain_incumbent_formal_gates,
            skip_formal_min_delta=args.skip_formal_min_delta,
            bypass_formal_time_budget_min_delta=args.bypass_formal_time_budget_min_delta,
            task_health_binding=(
                preflight_composition.task_health_binding
                if preflight_composition is not None
                else HealthBindingState.LEGACY_OMITTED
            ),
        )
    except FormalLaunchPolicyError as exc:
        print(f"[run_one_iteration] FORMAL LAUNCH REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)

    # arXiv #261 / Q-07c-6 — resolve the watchdog policy (flags > device/
    # regime profile > explicit uncalibrated state) BEFORE the dry-run view
    # and before any consumer reads the watchdog args. The banner goes to
    # STDERR: stdout is a parsed surface (the dry-run JSON, chain captures).
    watchdog_policy = (
        reviewed_setup.resolve_watchdog(args)
        if reviewed_setup is not None
        else resolve_watchdog_policy(args)
    )
    print(
        f"[watchdog_policy] enabled={watchdog_policy.enabled} "
        f"safety_factor={watchdog_policy.safety_factor} "
        f"floor_seconds={watchdog_policy.floor_seconds} "
        f"source={watchdog_policy.provenance}",
        file=sys.stderr,
        flush=True,
    )
    if watchdog_policy.profile_calibrated is False:
        print(
            "[watchdog_policy] no calibrated runtime profile exists for this "
            "device/execution regime — watchdog disabled; the outer time "
            "budgets are the runaway bound. Run qualification (write the "
            "measured overlay in $SIDERIUS_CALIBRATION_DIR), add a reviewed "
            "row to configs/runtime/runtime_profiles.yaml, or pass explicit "
            "--runtime_watchdog flags to change this.",
            file=sys.stderr,
            flush=True,
        )

    # arXiv U3 (#259) — the resolved-configuration view. Placed AFTER the
    # policy refusal (a config that could not launch is not "resolved") and
    # BEFORE iteration-side effects below: no halt marker, iteration directory,
    # run-id sidecar, lock, or LLM. Workspace env binding and plugin imports
    # have already occurred; plugin effects/stdout are not suppressed.
    if args.print_resolved_launch_config:
        sys.exit(print_resolved_launch_config(args))

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
            f"[HALT] chain halt marker present in this "
            f"workspace — see {os.path.join(args.workspace, '.chain_halted')}",
            file=sys.stderr,
        )
        sys.exit(3)

    _failed_streak = _check_consecutive_failure_brake(
        args.workspace,
        args.max_failed_iterations,
    )
    if _failed_streak is not None:
        halt_path = _write_halt_marker(
            args.workspace,
            {
                "halted_at": datetime.now(UTC).isoformat(),
                "workspace": os.path.abspath(args.workspace),
                "reason": "consecutive_failure_brake",
                "max_failed_iterations": args.max_failed_iterations,
                "failed_iters": _failed_streak,
                "next_iteration_was": args.start_iteration,
            },
        )
        print(
            f"[HALT] consecutive failure brake fired "
            f"(N={args.max_failed_iterations}); failed iters: "
            f"{_failed_streak}. Marker written: {halt_path}",
            file=sys.stderr,
        )
        sys.exit(3)

    # --- Dataset-directory resolution preflight -------------------------
    # Resolve WHERE the data physically lives ONCE, here, before anything
    # expensive. `--data_dir` is an explicit caller-owned input; the generic
    # framework never selects a task or machine-local fallback.
    #
    # Before this existed nothing on the launch path performed that
    # resolution, so a chain launched without `--data_dir` carried
    # `data_dir=None` all the way into the tuner's pre-phase GPU
    # measurement, which fails closed — AFTER a real LLM had generated and
    # validated a candidate. Resolving here converts that into a refusal
    # that costs nothing.
    #
    # Deliberately AFTER the halt/brake checks above: a halted chain must
    # still be able to exit without needing readable data.
    try:
        args.data_dir = resolve_dataset_dir(args.data_dir, purpose="this chain iteration")
    except DatasetDirectoryUnavailable as exc:
        print(f"[run_one_iteration] LAUNCH REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)

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

    # Iteration directory: {workspace}/iter_{N:03d}. S2 / U5 (#258): the
    # manifest slot is decided HERE — a second launch into an iteration that
    # already committed a manifest is refused before any LLM, model or GPU
    # work, unless the operator requested the explicit replacement.
    try:
        iteration_plan = prepare_iteration_dir(
            args.workspace,
            args.start_iteration,
            replace_iteration_manifest=args.replace_iteration_manifest,
            replacement_reason=args.replacement_reason,
            auto_resume_recovery=args.auto_resume,
        )
    except (ManifestAlreadyPublishedError, ManifestReplacementError) as exc:
        print(f"[run_one_iteration] LAUNCH REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)
    run_name = iteration_plan.run_name
    iter_dir = iteration_plan.iter_dir
    manifest_replacement = iteration_plan.manifest_replacement

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
    print("  SIDERIUS PER-ITERATION RUNNER")
    print(f"  Workspace        : {args.workspace}")
    print(f"  Start iteration  : {args.start_iteration}")
    print(f"  Run name         : {run_name}")
    print(f"  Iter directory   : {iter_dir}")
    llm_config = resolve_standard_llm_config(args)

    # Report what will actually run. `--llm_config` supersedes
    # `--llm_model` (deprecated) below, so printing the latter announced
    # `gemini / gemini-3.1-pro-preview` on a run whose every role was
    # openai/gpt-5.5 from `openai_tiered_pro.json`. A Gate whose binding
    # policy IS the LLM tier cannot have its banner name a different one:
    # the operator reads this line to confirm the policy was honoured.
    if args.llm_config:
        print(f"  LLM config       : {args.llm_config} (supersedes --llm_model)")
    else:
        print(f"  LLM (planner)    : gemini / {args.llm_model}")
        resolved_tune_routing = llm_config.get("tune")
        eff_reflect_provider = resolved_tune_routing["reflect_provider"]
        eff_reflect_model_id = resolved_tune_routing["reflect_model_id"]
        print(f"  LLM (reflector)  : {eff_reflect_provider} / {eff_reflect_model_id}")
    print(f"  Seed source paths: {len(args.seed_paths)} entries")
    for p in args.seed_paths:
        print(f"    - {p}")
    print("=" * 60)

    # FU-D-11 — resolved BEFORE any manifest can be written, so a validation
    # run's candidate provenance exists on EVERY branch including the early
    # crash paths. This is the §19.1 lesson applied: a launch fact that only
    # survives the healthy path is absent exactly when it is most needed.
    # Refusing here also means a malformed or results-bearing plan stops the
    # launch before any real work begins.
    _fixed = load_validation_fixed_candidate_plan(args.validation_fixed_candidate_plan)
    fixed_candidate_plan = _fixed["plan"] if _fixed else None
    fixed_candidate_provenance = _fixed["provenance"] if _fixed else None
    if fixed_candidate_provenance is not None:
        print(
            f"[FIXED PLAN] validation posture: the proposer will be bypassed for "
            f"candidate {fixed_candidate_provenance['resolved_model_name']!r} "
            f"(sha256={fixed_candidate_provenance['plan_sha256'][:12]}…, "
            f"source={fixed_candidate_provenance['plan_path']})"
        )

    # arXiv U1 (#253 / #254) — the launch IDENTITY (arm label + lit-review
    # topology + config pin), resolved ONCE and before any manifest can be
    # written, for the same reason as the fixed-plan provenance above: a
    # launch fact that only survives the healthy path is absent exactly when
    # it is most needed. The ONE object feeds the invariants pre-flight, the
    # workflow launch config and every manifest, so they cannot diverge.
    # An enabled lit-review whose config cannot be read is refused HERE —
    # before any LLM call — and still leaves a `failed` manifest (carrying
    # the fixed-plan provenance resolved above) for the consecutive-failure
    # brake; the identity itself is what failed to resolve, so it is the one
    # manifest that cannot carry it.
    try:
        launch_identity = resolve_launch_identity(args)
    except ValueError as e:
        print(f"FAIL: launch identity could not be resolved: {e}")
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            # Integration (S1×S2): this branch was added by U1 after the S2
            # write-once census froze at seven sites; like every other
            # branch it publishes through the write-once path and must carry
            # the operator's explicit replacement request (resolved at
            # :2208, before any manifest can be written).
            replacement=manifest_replacement,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
        )
        sys.exit(1)
    print(f"  Experiment arm   : {launch_identity.experiment_arm or '(unlabelled)'}")
    print(
        f"  Lit-review       : {'ON' if launch_identity.lit_review_enabled else 'OFF'}"
        + (
            f" (config sha256 {launch_identity.lit_review_config_sha256[:12]}…)"
            if launch_identity.lit_review_config_sha256 is not None
            else ""
        )
    )
    print(f"  Data Analysis    : {launch_identity.data_analysis_enabled!r} (None=composition)")
    print(f"  Evidence order   : {launch_identity.scientific_evidence_order}")

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
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
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
    #
    # Step 10 / P5+P6 W7 — the composition is resolved HERE, before the
    # pre-flight, because the pre-flight materializes the effective Health
    # config and must resolve the SAME binding `run_workflow` will. Composing
    # is pure resolution; ACTIVATION is still `bind_run_task_composition`
    # below, at the same point P1 put it. Re-composition is idempotent, but the
    # object is resolved once and reused rather than composed twice.
    # The crashed manifest is NOT optional here. Before W7 this composition
    # happened inside the workflow `try` whose handler writes
    # `write_manifest(..., crashed=True)`; resolving it earlier moved it out
    # from under that handler. That matters because the consecutive-failure
    # brake is deliberately fail-OPEN — `_check_consecutive_failure_brake`
    # treats a missing manifest as "not failed" and breaks the streak — and a
    # malformed `--task_composition` is DETERMINISTIC. Without this handler
    # every iteration would crash identically, write nothing, never form a
    # failure streak, and the chain would keep launching iterations that
    # cannot possibly succeed.
    try:
        if preflight_composition_error is not None:
            raise preflight_composition_error
        run_composition = preflight_composition
        if run_composition is None:
            raise ValueError("required task composition was not resolved")
    except Exception as e:
        print(f"FAIL: could not resolve --task_composition {args.task_composition!r}: {e}")
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
        sys.exit(1)

    try:
        expected_invariants = compute_expected_invariants(
            args,
            run_composition=run_composition,
            launch=_InvariantLaunchInputs(identity=launch_identity, llm_config=llm_config),
        )
    except ValueError as e:
        print(f"FAIL: run-invariants computation refused to start: {e}")
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
        sys.exit(1)

    if reviewed_setup is not None:
        reviewed_setup.check_invariants(expected_invariants, llm_config, launch_identity)

    from ml_models.plugin_binding import bind_run_model_plugins

    try:
        with (
            bind_code_package(
                run_composition.code_package if run_composition is not None else None
            ),
            bind_run_model_plugins(
                run_composition.model_plugins if run_composition is not None else None
            ),
        ):
            state = restore_prior_state(
                workspace=args.workspace,
                current_iter=args.start_iteration,
                seed_paths=resolved_seeds,
                expected_invariants=expected_invariants,
                dataset_partition_count=(
                    run_composition.dataset_profile.partition_count
                    if run_composition is not None
                    else resolve_dataset_profile().partition_count
                ),
            )
    except (ResumeError, RunInvariantsViolation) as e:
        print(f"FAIL: restore_prior_state refused to chain: {e}")
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
        _halt_contract_failure(args.workspace, args.start_iteration, e)

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

    # The lit-review enable flag (Design Decisions 1 + 2, 2026-06-11) is
    # resolved ONCE, above, inside `launch_identity` — arXiv U1 moved the
    # peek into `resolve_lit_review_enabled` so the invariants pre-flight,
    # this launch config and every manifest read one resolution.

    try:
        # The launcher is the layer that knows the task, so it resolves the
        # measurement capability and threads it into generic orchestration.
        # `measurement_capability.py` states this contract explicitly:
        # "Callers that know the task supply those." The workflow must not
        # name a task resolver itself.
        # Step 10 / P1 — the composition EDGE.
        #
        # Resolved here, before the workflow, for the same reason the
        # measurement capability is: the launcher is the layer that knows the
        # task. The workflow receives the resolved VALUE and never a path, so
        # it performs no YAML or plugin I/O and rediscovers nothing.
        #
        # The binding is entered HERE too, not inside the workflow, so the
        # binding's lifetime is the composition's lifetime and the region
        # covers the workflow's startup pre-flight as well as its iteration
        # loop — scope resolution and Health materialisation both read the
        # run's profile before iteration 1. `run_workflow` refuses a
        # composition whose authorities are not active, so the split cannot
        # silently produce a half-composed run.
        #
        # `--task_composition` omitted ⇒ `None` ⇒ the context manager is a
        # no-op and the run is byte-identical to its pre-Step-10 behaviour.
        # W7 — resolved once, above, before the invariants pre-flight.
        # ACTIVATION stays exactly where P1 put it.
        # F-MEASCAP-1 — the measurement capability follows the SAME binding
        # the composition does.
        #
        # It used to be `resolve_tidmad_measurement_capability()` written
        # inline in the `run_workflow(...)` call below, twenty-one lines from
        # `task_composition=run_composition`: one argument consulted the bound
        # composition, its neighbour was hardwired to TIDMAD. So a composed
        # non-TIDMAD run declared TIDMAD's identity and tested availability
        # against the import-time `TIDMAD_DATA_DIR` instead of the root it
        # binds — refused up front where TIDMAD data is absent, and silently
        # ADMITTED on the strength of another task's dataset where it is
        # present, which is every campaign host.
        #
        measurement_capability = resolve_composed_measurement_capability(
            run_composition, dataset_root=args.data_dir
        )
        # Step 11 C4 — the run's resolved physical data root travels with
        # the composition binding. `args.data_dir` was already put through
        # `resolve_dataset_dir` above, so this is the SAME authority, not a
        # second convention (R-11-7).
        with bind_run_task_composition(run_composition, physical_data_root=args.data_dir):
            launch_config = build_standard_launch_config(
                args,
                launch_identity,
                resolved_paths=resolved_paths,
                fixed_candidate_plan=fixed_candidate_plan,
            )
            if reviewed_setup is not None:
                reviewed_setup.check_launch(launch_config)
            results = run_workflow(
                launch=launch_config,
                measurement_capability=measurement_capability,
                workspace=args.workspace,
                run_name=run_name,
                chain_run_name=chain_run_name,
                run_id=run_id,
                llm_config=llm_config,
                health_checks_config=args.health_checks_config,
                data_scope=args.data_scope,
                health_gate_enabled=args.health_gate_enabled,
                health_gate_files=args.health_gate_files,
                # Step 10 / P1 C5 — Step 09.5a's C4b hand-off, closed. The nine
                # unpacked kwargs are ONE typed parameter: `RestoredState` is
                # resume's own type and crosses the launcher edge by design
                # (09.5a §16), while `ChainState` still never crosses a process
                # boundary. The workflow unpacks it once, applying the same rules
                # this call site used to apply here.
                restored_state=state,
                order_strategy_override=args.order_strategy_override,
                file_order_override=args.file_order_override,
                enable_structured_health_feedback=args.enable_structured_health_feedback,
                bridge_factory=bridge_factory,
                sandbox_factory=sandbox_factory,
                task_composition=run_composition,
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
        write_manifest(
            iter_dir,
            run_name,
            results=[],
            crashed=True,
            healthgate_mode=args.healthgate_mode,
            result_authority=args.result_authority,
            fixed_candidate_provenance=fixed_candidate_provenance,
            launch_identity=launch_identity,
            replacement=manifest_replacement,
        )
        sys.exit(2)
    except Exception as e:
        print(f"FAIL: Workflow raised exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            write_manifest(
                iter_dir,
                run_name,
                results=[],
                crashed=True,
                healthgate_mode=args.healthgate_mode,
                result_authority=args.result_authority,
                fixed_candidate_provenance=fixed_candidate_provenance,
                launch_identity=launch_identity,
                replacement=manifest_replacement,
            )
        finally:
            from core.local_code.failure import raise_if_code_package_failure

            raise_if_code_package_failure(e)
        from execute_tools.evaluation_metric import MetricIdentityConflictError
        from nodes.result_interpretation_agent import InterpretationContractError

        if isinstance(e, (MetricIdentityConflictError, InterpretationContractError)):
            _halt_contract_failure(args.workspace, args.start_iteration, e)
        sys.exit(1)

    manifest = write_manifest(
        iter_dir,
        run_name,
        results,
        # V20 PR D: the validated launch declaration, on every branch.
        healthgate_mode=args.healthgate_mode,
        result_authority=args.result_authority,
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
        # V19 PR 3 — control policy only (per-round evidence stays in the
        # records / interpretation digest).
        fixed_candidate_provenance=fixed_candidate_provenance,
        health_feedback_policy={
            "enable_structured_health_feedback": (args.enable_structured_health_feedback),
            "history_window_iterations": (args.health_feedback_history_window_iterations),
            "max_entries_per_model": (args.health_feedback_history_max_entries_per_model),
        },
        # arXiv U1 — the same identity object every crash branch stamped.
        launch_identity=launch_identity,
        # S2 / U5 (#258): the operator's explicit replacement request, or None.
        replacement=manifest_replacement,
    )

    # C9c — infrastructure ABORT halts the CHAIN, not just this attempt.
    # Checked immediately after the manifest is written so the iteration's
    # diagnostics and artifacts are preserved before we stop: the operator
    # needs them precisely because the environment is broken. The sentinel
    # is what stops a queued next iteration (SDSC `afterany` starts the
    # next job regardless of exit code), and exit 3 is what stops the
    # foreground loop.
    _abort_reason = _infrastructure_abort_reason(results)
    if _abort_reason is not None:
        halt_path = _write_halt_marker(
            args.workspace,
            {
                "halted_at": datetime.now(UTC).isoformat(),
                "workspace": os.path.abspath(args.workspace),
                "reason": "infrastructure_abort",
                "iteration": args.start_iteration,
                "iteration_dir": iter_dir,
                "manifest_status": manifest.get("status"),
                "detail": _abort_reason,
            },
        )
        print(
            "[HALT] runtime evidence-channel failure (infrastructure) — the chain "
            "stops rather than running another candidate on the same broken "
            f"environment. Iteration artifacts preserved in {iter_dir}. "
            f"Marker: {halt_path}",
            file=sys.stderr,
        )
        sys.exit(3)

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

    # V19 PR 1 (P1-C5) — incremental per-file best table. Best-effort:
    # a table-write failure NEVER breaks the chain (the table is
    # analytical bookkeeping, not decision state); on failure the
    # existing table is preserved by atomic replace and can always be
    # regenerated deterministically via
    # ``scripts/runtime/rebuild_per_file_best.py`` from committed artifacts.
    # Only updates on completed manifests (A6).
    if manifest["status"] == "completed":
        try:
            from execute_tools.per_file_best import write_table

            path = write_table(args.workspace)
            print(f"  [PER_FILE_BEST] wrote {path}")
        except Exception as e:
            print(
                f"  [PER_FILE_BEST] WARN: incremental table write failed for "
                f"workspace {args.workspace!r}: {type(e).__name__}: {e} — "
                f"chain continues; regenerate via "
                f"scripts/runtime/rebuild_per_file_best.py."
            )

    if manifest["status"] == "completed":
        print()
        print("=" * 60)
        print(f"  ITERATION {args.start_iteration} COMPLETE")
        print(f"  Model      : {manifest['model_name']}")
        # F-SCANB-3 — labelled for what it now is. This line used to read
        # "Best score" over whichever score topped the MIXED pool, so a
        # trial-only iteration announced a trial number under the word
        # COMPLETE. It is the formal best, and `None` when no formal round
        # produced one.
        print(f"  Formal best: {manifest['best_score']}")
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
