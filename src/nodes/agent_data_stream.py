"""
Persistent event stream of structured artefacts shown to LLM agents.

Phase 8 / P-Alpha (``docs/aggregated_score_table_awareness.md``): every
time a ``ScoreComparisonTable`` is built and made available to a downstream
LLM agent, its rendered markdown plus full structured form is appended to

    ``{workspace}/logs/agent_data_stream.jsonl``

so we have an audit trail of *what the agent literally saw* vs *what
actually happened in the data*. This module exists because the V8 cohort
revealed a silent unit mismatch in the per-file model column (linear
values displayed alongside log-space reference columns). The mismatch
went undetected for multiple full-loop runs because the rendered tables
were not persisted in a queryable form — only embedded inside
per-experiment JSON records that are awkward to grep across iterations.

Append-only JSONL. One JSON object per line. Within a single workspace
there is at most one tuner process appending, so no locking is needed.
Failures are caught and logged to stdout — the audit stream must never
crash a 15-hour tuning loop.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from agent.schemas.score_table import ScoreComparisonTable

_LOG_SUBDIR = "logs"
_STREAM_FILENAME = "agent_data_stream.jsonl"


def _stream_path(workspace: str) -> str:
    return os.path.join(workspace, _LOG_SUBDIR, _STREAM_FILENAME)


def append_event(
    *,
    workspace: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Append a single JSON event to the workspace's agent data stream.

    Creates the ``logs/`` subdirectory if it does not yet exist. All
    exceptions are swallowed (printed) — the audit log is best-effort
    and must never break the surrounding pipeline.
    """
    try:
        log_dir = os.path.join(workspace, _LOG_SUBDIR)
        os.makedirs(log_dir, exist_ok=True)
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "event": event_type,
            **payload,
        }
        line = json.dumps(record, ensure_ascii=False)
        with open(_stream_path(workspace), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:
        print(
            f"[agent_data_stream] append_event failed ({event_type}): {type(exc).__name__}: {exc}"
        )


def log_score_table(
    *,
    workspace: str,
    score_table: ScoreComparisonTable,
    metadata: dict[str, Any],
) -> None:
    """Convenience wrapper: log a score-table-build event.

    The full structured ``ScoreComparisonTable`` (including its
    ``rendered_markdown`` field) is dumped, alongside caller-supplied
    metadata such as ``exp_id``, ``model_type``, ``round_index``,
    ``is_trial`` and any iteration identifiers.
    """
    append_event(
        workspace=workspace,
        event_type="score_table_rendered",
        payload={
            "metadata": dict(metadata),
            "score_table": score_table.model_dump(),
        },
    )
