#!/usr/bin/env python3
"""V18 wave checkpoint summary (read-only).

Aggregates the operator-facing review packet for a wave of split-mode
chains before the next wave is approved (docs/v18_split_run_plan.md §Wave
checkpoint). For each chain workspace it reports: best raw/valid scores,
best proposal, completed iterations/rounds, collapse statistics, a
HealthGate summary, and abnormal observations (failed manifests, scope
stamps that contradict the workspace lock, non-completed terminations).

Usage:
    .venv/bin/python scripts/v18_wave_summary.py WS1 WS2 [WS3 ...]
    (one argument per chain workspace root, e.g.
     /workspace/DATA/SIDERIUS_DATA/v18_loss_04_09)

Purely read-only: walks ``iter_NNN/manifest.json``, the referenced
``run_output_*.json`` files, and per-iteration tuner summaries. Tolerates
partially-complete workspaces (running chains) — missing artifacts are
reported, never raised.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any


def _load_json(path: str) -> Any | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def summarize_workspace(workspace: str) -> dict[str, Any]:
    """Build one chain's summary dict from its on-disk artifacts."""
    out: dict[str, Any] = {
        "workspace": workspace,
        "iterations": [],
        "best_raw_score": None,
        "best_valid_score": None,
        "best_proposal": None,
        "completed_iters": 0,
        "failed_iters": 0,
        "no_records_iters": 0,
        "total_rounds_completed": 0,
        "collapse_records": 0,
        "success_records": 0,
        "error_records": 0,
        "gate_actions": {},
        "resolved_data_scope": None,
        "abnormal": [],
    }
    lock = _load_json(os.path.join(workspace, "run_invariants_lock.json"))
    if lock:
        out["resolved_data_scope"] = lock.get("resolved_data_scope")
        out["health_gate_enabled"] = lock.get("health_gate_enabled")
    else:
        out["abnormal"].append("no run_invariants_lock.json (pre-DataScope or not started)")

    iter_dirs = sorted(
        d for d in glob.glob(os.path.join(workspace, "iter_[0-9][0-9][0-9]")) if os.path.isdir(d)
    )
    if not iter_dirs:
        out["abnormal"].append("no iter_NNN directories found")

    for iter_dir in iter_dirs:
        manifest = _load_json(os.path.join(iter_dir, "manifest.json"))
        if manifest is None:
            out["abnormal"].append(f"{os.path.basename(iter_dir)}: missing/unreadable manifest")
            continue
        status = manifest.get("status")
        entry = {
            "iter": os.path.basename(iter_dir),
            "status": status,
            "model": manifest.get("model_name"),
            "best_score": manifest.get("best_score"),
            "best_valid_score": manifest.get("best_valid_score"),
            "completed_rounds": manifest.get("completed_rounds") or 0,
        }
        out["iterations"].append(entry)
        out["total_rounds_completed"] += entry["completed_rounds"]
        if status == "completed":
            out["completed_iters"] += 1
        elif status == "failed":
            out["failed_iters"] += 1
            out["abnormal"].append(f"{entry['iter']}: manifest status=failed")
        elif status == "no_records":
            out["no_records_iters"] += 1

        # Manifest scope stamp must agree with the workspace lock.
        m_scope = manifest.get("resolved_data_scope")
        if (
            m_scope is not None
            and out["resolved_data_scope"] is not None
            and sorted(m_scope) != sorted(out["resolved_data_scope"])
        ):
            out["abnormal"].append(
                f"{entry['iter']}: manifest scope {m_scope} != lock {out['resolved_data_scope']}"
            )

        # Best-score tracking across iterations (raw + HealthGate-valid).
        for key, field in (
            ("best_raw_score", "best_score"),
            ("best_valid_score", "best_valid_score"),
        ):
            v = manifest.get(field)
            if v is not None and (out[key] is None or v > out[key]):
                out[key] = v
                if key == "best_raw_score":
                    out["best_proposal"] = manifest.get("model_name")

        # Per-record statistics from the iteration's tuner summaries.
        for summary_path in glob.glob(
            os.path.join(iter_dir, "**", "summary_*.json"), recursive=True
        ):
            records = _load_json(summary_path) or []
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                status_r = rec.get("status")
                if status_r == "failed_mode_collapse":
                    out["collapse_records"] += 1
                elif status_r == "success":
                    out["success_records"] += 1
                elif status_r == "error" or str(status_r or "").startswith("skipped"):
                    out["error_records"] += 1
                action = rec.get("gate_action")
                if action:
                    out["gate_actions"][action] = out["gate_actions"].get(action, 0) + 1
    return out


def render(summaries: list[dict[str, Any]]) -> str:
    lines = ["# V18 wave checkpoint summary", ""]
    for s in summaries:
        lines += [
            f"## {os.path.basename(s['workspace'].rstrip('/'))}",
            f"  scope             : {s.get('resolved_data_scope')}",
            f"  iterations        : {s['completed_iters']} completed / "
            f"{s['no_records_iters']} no_records / {s['failed_iters']} failed "
            f"(of {len(s['iterations'])} on disk)",
            f"  rounds completed  : {s['total_rounds_completed']}",
            f"  best raw score    : {s['best_raw_score']}  (proposal: {s['best_proposal']})",
            f"  best valid score  : {s['best_valid_score']}",
            f"  record statuses   : success={s['success_records']} "
            f"collapse={s['collapse_records']} error/skip={s['error_records']}",
            f"  gate actions      : {s['gate_actions'] or '(none recorded)'}",
        ]
        if s["abnormal"]:
            lines.append("  ABNORMAL:")
            lines += [f"    - {a}" for a in s["abnormal"]]
        else:
            lines.append("  abnormal          : none")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    summaries = [summarize_workspace(ws) for ws in sys.argv[1:]]
    print(render(summaries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
