"""
core/resume.py — Plugin + source-path restoration for chain-mode runs.

Per-iteration Python processes inherit nothing from prior iters' interpreters
— a fresh ``python run_one_iteration.py --start_iteration N`` starts with
``MODEL_REGISTRY`` at the built-in set. This module restores the "soul" of
every prior iter (1..N-1) into the current process before ``run_workflow``
runs.

The same code path serves both:
  * normal sequential chain (iter N+1 launched after iter N completes), and
  * SIGKILL-then-restart resume (iter K relaunched after a crash).

There is no "resume" branch in the Python — the contract is just
"current_iter > 1 means there are prior iters on disk to absorb".

See ``docs/phase68_orchestrator_memory_and_resume.md`` §3.3 for the design.
"""
from __future__ import annotations

import json
import os
import re
import warnings
from dataclasses import dataclass, field
from typing import List, Sequence

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.sandbox_executor import get_plugin_dir
from workflows.model_exploration import _add_plugin_to_registries


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class ResumeError(RuntimeError):
    """Raised when the workspace state is incompatible with resuming.

    Distinct from generic ``RuntimeError`` so the chain runner can surface a
    targeted operator-facing message ("iter 003 manifest is missing — was
    the chain interrupted between iter 002 commit and iter 003 launch?")
    rather than a stack trace.
    """


@dataclass
class RestoredState:
    """Result of :func:`restore_prior_state` — everything the chain runner
    needs to forward to ``run_workflow``.

    Attributes:
        resolved_source_paths: ordered list of source-data JSON paths to
            feed into ``run_workflow(source_paths=...)``. Layout:
            ``seed_paths`` first (in caller order), then prior iters'
            ``run_output`` JSON paths in ascending iter order. Mirrors what
            an in-process run would have accumulated naturally.
        restored_plugins: ``model_type`` strings whose plugin classes were
            re-registered into the four registry surfaces (see
            :func:`workflows.model_exploration._add_plugin_to_registries`).
            Plugin files that were missing on disk are *not* in this list
            (a warning is emitted but the restore continues — the JSON
            record is kept in ``resolved_source_paths`` because
            ``memory_history`` reconstruction doesn't need the class).
        committed_iters: 1-based iter indices successfully restored.
            Equivalent to ``range(1, current_iter)`` for a clean chain.
    """
    resolved_source_paths: List[str] = field(default_factory=list)
    restored_plugins: List[str] = field(default_factory=list)
    committed_iters: List[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iter_run_name(iter_idx: int) -> str:
    """Chain-mode ``run_name`` convention.

    Mirrors ``sdsc_submission_scripts/run_one_iteration.py`` line 271
    (``run_name = f"iter_{args.iteration:03d}"``). Centralising the format
    string here means resume cannot drift from the writer.
    """
    return f"iter_{iter_idx:03d}"


def _read_manifest(workspace: str, iter_idx: int) -> dict:
    """Load + minimally validate ``iter_NNN/manifest.json``.

    Returns the manifest dict for either a completed iter or a clean
    no-records iter. Callers must inspect ``manifest["status"]`` and
    branch accordingly (``"completed"`` → consume; ``"no_records"`` →
    skip with no plugin restore).

    Raises :class:`ResumeError` for missing file, malformed JSON,
    ``status == "failed"`` (true crash → halt), unknown status, or
    ``status == "completed"`` with a missing ``output_path``.
    """
    manifest_path = os.path.join(
        workspace, _iter_run_name(iter_idx), "manifest.json"
    )
    if not os.path.isfile(manifest_path):
        raise ResumeError(
            f"iter {iter_idx:03d}: manifest.json not found at "
            f"{manifest_path}. The chain was interrupted before this iter "
            f"committed; rerun this iter from scratch (or pass "
            f"--start_iteration {iter_idx} to skip the missing prior)."
        )
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        raise ResumeError(
            f"iter {iter_idx:03d}: manifest.json is malformed at "
            f"{manifest_path}: {e}"
        ) from e

    status = manifest.get("status")
    if status == "no_records":
        # Clean no-records exit (gate exhaustion or all-rounds-failed).
        # Caller skips this iter — no output_path, no plugin to restore.
        return manifest
    if status != "completed":
        raise ResumeError(
            f"iter {iter_idx:03d}: manifest status={status!r}, expected "
            f"'completed' or 'no_records'. Refusing to chain off a "
            f"failed/unknown iter."
        )
    output_path = manifest.get("output_path")
    if not output_path:
        raise ResumeError(
            f"iter {iter_idx:03d}: manifest has no output_path: "
            f"{manifest_path}"
        )
    return manifest


def _validate_run_output(
    output_path: str, iter_idx: int,
) -> HyperparamTuningOutput:
    """Validate the run_output JSON against ``HyperparamTuningOutput``.

    Same predicate as ``scripts/inspect_run_state.py:91-104`` so the
    inspector and the resume helper agree on what "committed" means.
    """
    if not os.path.isfile(output_path):
        raise ResumeError(
            f"iter {iter_idx:03d}: manifest points at output_path "
            f"{output_path} but the file does not exist."
        )
    try:
        text = open(output_path, encoding="utf-8").read()
    except OSError as e:
        raise ResumeError(
            f"iter {iter_idx:03d}: cannot read run_output {output_path}: {e}"
        ) from e
    try:
        return HyperparamTuningOutput.model_validate_json(text)
    except Exception as e:  # pydantic ValidationError or json parse
        raise ResumeError(
            f"iter {iter_idx:03d}: run_output failed validation at "
            f"{output_path}: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def restore_prior_state(
    workspace: str,
    current_iter: int,
    seed_paths: Sequence[str],
) -> RestoredState:
    """Restore every prior iter's plugin classes and assemble the
    source-paths list for ``run_workflow``.

    Args:
        workspace: chain workspace root containing ``iter_NNN/`` and
            ``plugins/iter_NNN/`` subdirs. Same value as the ``--workspace``
            flag on ``run_one_iteration.py`` and ``run_chain.sh``.
        current_iter: 1-based index of the iter this process is about to
            run. Iters ``[1, current_iter-1]`` are restored.
            ``current_iter == 1`` is a no-op that returns ``seed_paths``
            verbatim (no prior iters to absorb).
        seed_paths: caller's seed source paths (e.g. baseline punet/wavenet
            run_output JSONs). Prepended to the resolved list in original
            order. May be empty if the caller has no seeds.

    Returns:
        :class:`RestoredState` with ``resolved_source_paths``,
        ``restored_plugins``, and ``committed_iters`` populated.

    Raises:
        ResumeError: workspace state cannot be safely chained off — missing
            workspace dir, missing manifest, malformed JSON, status !=
            ``"completed"``, missing run_output file, or run_output
            validation failure. The shell driver should surface this error
            and refuse to launch.

    Side effects:
        Calls :func:`_add_plugin_to_registries` for each prior iter, which
        mutates the global ``MODEL_REGISTRY``, ``PLUGIN_CONFIG_REGISTRY``,
        and ``PLUGIN_OUTPUT_TYPE_REGISTRY``. Idempotent if the same plugin
        is already registered (overwrites with the same class).

    Warnings:
        Emits a ``UserWarning`` when a plugin file is missing on disk or
        fails ``_load_plugin`` validation. The JSON record is kept in
        ``resolved_source_paths`` either way because ``memory_history``
        reconstruction only reads the JSON; only training would need the
        class, and the chain never re-trains prior iters.
    """
    if current_iter < 1:
        raise ResumeError(
            f"current_iter must be >= 1, got {current_iter}"
        )

    state = RestoredState(
        resolved_source_paths=list(seed_paths),
        restored_plugins=[],
        committed_iters=[],
    )

    if current_iter == 1:
        # No prior iters to absorb — seeds verbatim. This is the iter-1
        # path (clean chain start). Returning early keeps the workspace
        # check below from rejecting a not-yet-created chain dir.
        return state

    abs_workspace = os.path.abspath(workspace)
    if not os.path.isdir(abs_workspace):
        raise ResumeError(
            f"workspace does not exist: {abs_workspace}"
        )

    # Strict ascending order — prior iters must be processed chronologically
    # so the source_paths list mirrors what an in-process run would build,
    # and so any plugin shadow-warnings happen in the same order.
    for iter_idx in range(1, current_iter):
        manifest = _read_manifest(abs_workspace, iter_idx)
        if manifest.get("status") == "no_records":
            # Iter ran cleanly but produced no usable model (gate exhaustion
            # or all-rounds-failed). Skip output absorption + plugin
            # restoration entirely. Not appended to committed_iters because
            # there is nothing to commit; downstream code that reads
            # memory_history reconstructs the skip context from the
            # workspace's per-iter logs, not from the in-process state.
            print(
                f"[resume] iter {iter_idx:03d}: no_records — skipping "
                f"output absorption, no plugin to restore"
            )
            continue
        output_path = manifest["output_path"]
        parsed = _validate_run_output(output_path, iter_idx)

        run_name = _iter_run_name(iter_idx)
        plugin_dir = get_plugin_dir(abs_workspace, run_name)
        plugin_file = os.path.join(plugin_dir, f"{parsed.model_type}.py")

        if os.path.isfile(plugin_file):
            registered = _add_plugin_to_registries(plugin_file)
            if registered is None:
                # The .py is on disk but failed _load_plugin validation —
                # broken plugin contract (missing PLUGIN_MODEL_TYPE etc).
                # Higher tier of corruption than a missing file: warn and
                # continue, so the run can still produce memory_history but
                # the operator is alerted.
                warnings.warn(
                    f"[resume] iter {iter_idx:03d}: plugin file at "
                    f"{plugin_file} failed _load_plugin validation. "
                    f"Continuing with JSON-only history; model class is "
                    f"unavailable for any retraining.",
                    UserWarning,
                    stacklevel=2,
                )
            else:
                state.restored_plugins.append(registered)
                print(
                    f"[resume] iter {iter_idx:03d}: restored plugin "
                    f"'{registered}' from {plugin_file}"
                )
        else:
            warnings.warn(
                f"[resume] iter {iter_idx:03d}: plugin file not found at "
                f"{plugin_file}. JSON record is kept (memory_history is "
                f"still reconstructible); model class is unavailable for "
                f"any retraining.",
                UserWarning,
                stacklevel=2,
            )

        state.resolved_source_paths.append(output_path)
        state.committed_iters.append(iter_idx)

    return state


# ---------------------------------------------------------------------------
# Workspace layout guard (Phase 6.8 §3.9)
# ---------------------------------------------------------------------------

def validate_workspace_layout(workspace: str) -> None:
    """Detect legacy workspace layout and refuse to start.

    The chain layout uses ``{workspace}/iter_NNN/``. The legacy in-process
    layout uses ``{workspace}/{run_name}/iteration_NNN/``. If a workspace
    has legacy artifacts, writing chain artifacts alongside them would
    silently produce an incoherent workspace.

    Raises:
        ResumeError: when legacy layout patterns are detected.
    """
    import glob as _glob

    if not os.path.isdir(workspace):
        return  # nothing to guard

    # Pattern 1: {workspace}/{non-iter}/iteration_001/  (legacy run_name subtree).
    # Chain layout also has iteration_001/ but under iter_NNN/ — exclude those.
    matches = _glob.glob(os.path.join(workspace, "*", "iteration_001", ""))
    legacy_matches = [
        m for m in matches
        if not re.match(r"iter_\d{3}$", os.path.basename(os.path.dirname(os.path.dirname(m))))
    ]
    if legacy_matches:
        _raise_legacy(workspace, legacy_matches[0])

    # Pattern 2: workflow_*.json (workflow summary from in-process runner)
    matches = _glob.glob(os.path.join(workspace, "workflow_*.json"))
    if matches:
        _raise_legacy(workspace, matches[0])

    # Pattern 3: memory_trace.jsonl exists AND no iter_001/ (ambiguous legacy)
    trace = os.path.join(workspace, "memory_trace.jsonl")
    if os.path.exists(trace) and not os.path.isdir(os.path.join(workspace, "iter_001")):
        _raise_legacy(workspace, trace)


def _raise_legacy(workspace: str, matched: str) -> None:
    raise ResumeError(
        f"Legacy workspace layout detected at {workspace}.\n"
        f"  Found: {matched}\n\n"
        f"This workspace was created by the in-process runner (v5/v6 era).\n"
        f"The chain runner uses a different layout ({{workspace}}/iter_NNN/).\n\n"
        f"To proceed:\n"
        f"  (a) Use a new --workspace path for the chain run.\n"
        f"  (b) To resume from legacy results, use the migration tool:\n"
        f"      python scripts/migrate_workspace.py --from {workspace} --to <new>\n"
        f"      (migration tool planned — not yet implemented)"
    )
