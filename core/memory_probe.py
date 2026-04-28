"""
Parent-process memory probe (Fix 4 of docs/optimize_inference_and_scoring.md).

Why this module exists
----------------------
The 2026-04-20 OOM-kill of ``explore_novel_v3_0420`` iter 4 was driven by an
orchestrator process whose RSS had grown to ~37 GB over ~5 h 30 m across
three prior iterations. We hypothesised three contributing sources
(``all_records`` accumulation, LLM conversation state, per-experiment
``memory`` dicts), but we do not yet have a *measured* RSS-vs-iteration
curve — only the terminal snapshot at the moment of death.

This helper emits a structured memory probe at two scopes:

  * **Workflow scope** — at the start and end of each iteration in
    ``workflows/model_exploration.py``. Answers: "does the parent's RSS
    grow monotonically across iterations, and by how much per iteration?"
  * **Tuner scope** — pre/post ``score_vector`` in
    ``nodes/ml_hyperparameter_tune_agent.py``. Answers: "what is the
    transient cost of a single scoring block, and does it leave residue?"

Output format
-------------
Each probe emits two things:

1. One stdout line, human-readable::

       [MEM] iter=N phase=pre_score rss=12.34 GB vms=56.78 GB

2. When a ``workspace`` is supplied, one JSON row appended to
   ``{workspace}/memory_trace.jsonl``::

       {"scope": "tuner", "iter": 2, "phase": "pre_score",
        "rss_gb": 12.3456, "vms_gb": 56.7890,
        "timestamp": "2026-04-20T08:15:03.123456Z"}

The JSONL is append-only and parseable by any downstream plotter. Missing
``psutil`` is not an error — the helper logs a warning and writes a row
with ``rss_gb=None``, so a workflow on a host without ``psutil`` still
runs (just without the probe data).
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Any, Optional

try:
    import psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False


_GIB = 1024 ** 3

TRACE_FILENAME = "memory_trace.jsonl"


def probe_memory(
    iter_idx: Any,
    phase: str,
    workspace: Optional[str] = None,
    scope: str = "workflow",
) -> dict:
    """Record a parent-process memory snapshot.

    Args:
        iter_idx: The iteration identifier meaningful to ``scope``. For
            ``scope="workflow"`` this is the workflow iteration number;
            for ``scope="tuner"`` this is the tuner's ``round_index``.
            Any JSON-serialisable value is accepted (int preferred).
        phase: Free-form phase tag. Canonical values used in-tree:
            ``start``, ``end``, ``post_gc`` (workflow scope);
            ``pre_score``, ``post_score`` (tuner scope). ``post_gc`` is
            emitted right after the per-iter ``del`` + ``gc.collect()``
            block in the workflow loop so a trace consumer can compute
            the freed-memory delta as ``end.rss_gb - post_gc.rss_gb``.
            The schema is open — new phases may be added without
            breaking the log consumer.
        workspace: Output directory. When provided, a JSON row is
            appended to ``{workspace}/memory_trace.jsonl``. When ``None``,
            the probe prints only to stdout.
        scope: Disambiguates concurrent probe streams in the JSONL when a
            single run mixes workflow-level and tuner-level probes.
            Defaults to ``"workflow"``.

    Returns:
        The dict that was printed + appended. Exposed so callers (and
        tests) can inspect the row without re-reading the file.
    """
    timestamp = (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(tzinfo=None)
        .isoformat()
        + "Z"
    )

    if not _PSUTIL_AVAILABLE:
        row = {
            "scope": scope,
            "iter": iter_idx,
            "phase": phase,
            "rss_gb": None,
            "vms_gb": None,
            "timestamp": timestamp,
            "note": "psutil_unavailable",
        }
        print(
            f"[MEM] scope={scope} iter={iter_idx} phase={phase} "
            "rss=NA vms=NA (psutil unavailable)"
        )
    else:
        mem = psutil.Process(os.getpid()).memory_info()
        rss_gb = mem.rss / _GIB
        vms_gb = mem.vms / _GIB
        row = {
            "scope": scope,
            "iter": iter_idx,
            "phase": phase,
            "rss_gb": round(rss_gb, 4),
            "vms_gb": round(vms_gb, 4),
            "timestamp": timestamp,
        }
        print(
            f"[MEM] scope={scope} iter={iter_idx} phase={phase} "
            f"rss={rss_gb:.2f} GB vms={vms_gb:.2f} GB"
        )

    if workspace:
        try:
            os.makedirs(workspace, exist_ok=True)
            trace_path = os.path.join(workspace, TRACE_FILENAME)
            with open(trace_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except OSError as e:
            # A failure to persist must never take down the probed run.
            # We still have the stdout line; just warn and continue.
            print(f"[MEM] warning: failed to append to memory_trace.jsonl: {e}")

    return row
