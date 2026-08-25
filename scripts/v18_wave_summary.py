#!/usr/bin/env python3
"""V18 wave checkpoint summary (read-only).

Aggregates the operator-facing review packet for a wave of split-mode
chains (docs/v18_split_run_plan.md §Wave checkpoint). Two modes:

- default (interim): tolerant of live/incomplete workspaces — everything
  is reported, nothing exits nonzero.
- ``--strict`` (final checkpoint): every hard check must pass; any
  ABNORMAL finding makes the script exit 1. Wave 2 must not be approved
  unless strict mode exits 0.

Hard checks per chain (strict):
  * workspace exists and has a readable ``run_invariants_lock.json``;
  * the locked scope matches the scope encoded in the run name
    (``v18_{flavor}_{AA}_{BB}`` → files AA..BB inclusive);
  * ``health_checks_effective.yaml`` exists and EVERY check's effective
    ``peek_file_indices`` equals the locked scope;
  * every iteration manifest carries the locked scope;
  * every recorded HealthGate ``files_requested``/``files_completed``
    entry is in scope;
  * no out-of-scope denoised artifact (``abra_validation_denoised_*_NNNN
    .h5``) remains anywhere under the workspace;
  * exit marker ``{exit_dir}/{run}.exit`` exists and contains exactly
    ``EXIT=0`` (absent → still running/never launched; nonzero → chain
    failed; malformed → abnormal);
  * no failed iteration manifests.

Scope-conformance note: per-round SampleSets are not persisted on
records; in-scope execution is evidenced by (a) the DS3 sandbox boundary
(out-of-scope I/O terminates the run — a completed chain proves none
occurred), (b) gate file-requests ⊆ scope, and (c) the denoised-artifact
sweep above.

Analysis contract: aggregate scalars are comparable only WITHIN one
scope. The renderer groups chains by scope and never ranks scalars
across scopes — cross-scope review uses per-file vectors.

Usage:
    .venv/bin/python scripts/v18_wave_summary.py [--strict] \
        [--exit-dir /tmp] WS1 WS2 [...]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from typing import Any

from execute_tools.deliverable_spec import default_deliverable_naming

_RUN_NAME_RE = re.compile(r"v18_[a-z]+_(\d{2})_(\d{2})$")


def expected_scope_from_name(name: str) -> list[int] | None:
    """``v18_loss_04_09`` → ``[4..9]``; None when the name doesn't encode one."""
    m = _RUN_NAME_RE.search(name)
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    return list(range(lo, hi + 1)) if lo <= hi else None


def read_exit_marker(path: str) -> tuple[str, int | None]:
    """Classify an exit marker: (state, code).

    state ∈ absent | ok | failed | malformed. ``code`` is the parsed
    integer when available.
    """
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
    except FileNotFoundError:
        return "absent", None
    except OSError:
        return "malformed", None
    m = re.fullmatch(r"EXIT=(\d+)", content)
    if not m:
        return "malformed", None
    code = int(m.group(1))
    return ("ok" if code == 0 else "failed"), code


def _load_json(path: str) -> Any | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _check_effective_config(workspace: str, scope: list[int], abnormal: list[str]) -> None:
    path = os.path.join(workspace, "health_checks_effective.yaml")
    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        abnormal.append("no health_checks_effective.yaml materialized")
        return
    except Exception as exc:  # unreadable/corrupt
        abnormal.append(f"health_checks_effective.yaml unreadable: {exc}")
        return
    for gate in (raw or {}).get("health_gates", []):
        for chk in gate.get("checks", []):
            peeks = (chk.get("config") or {}).get("peek_file_indices")
            if sorted(peeks or []) != sorted(scope):
                abnormal.append(
                    f"effective config: gate {gate.get('id')} monitors {peeks}, "
                    f"expected the full scope {scope}"
                )


def _check_denoised_artifacts(workspace: str, scope: list[int], abnormal: list[str]) -> None:
    # Step 05c — both the match and the index parse come from the deliverable
    # naming authority. This auditor previously held its own regex, which was a
    # second restatement of the producer's template: a renamed deliverable
    # would have made it recognise nothing and report a clean workspace.
    naming = default_deliverable_naming()
    scope_set = set(scope)
    for path in glob.glob(os.path.join(workspace, "**", naming.any_glob()), recursive=True):
        file_index = naming.input_identity_of(os.path.basename(path))
        if file_index is not None and file_index not in scope_set:
            abnormal.append(f"OUT-OF-SCOPE denoised artifact on disk: {path}")


def summarize_workspace(workspace: str, exit_dir: str = "/tmp") -> dict[str, Any]:
    """Build one chain's summary dict from its on-disk artifacts."""
    run = os.path.basename(workspace.rstrip("/"))
    out: dict[str, Any] = {
        "workspace": workspace,
        "run": run,
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
        "exit_state": None,
        "exit_code": None,
        "abnormal": [],
    }
    abnormal = out["abnormal"]

    if not os.path.isdir(workspace):
        abnormal.append("workspace directory missing")
        return out

    # Exit marker — content, not existence.
    state, code = read_exit_marker(os.path.join(exit_dir, f"{run}.exit"))
    out["exit_state"], out["exit_code"] = state, code
    if state == "absent":
        abnormal.append("exit marker absent (still running or never launched)")
    elif state == "failed":
        abnormal.append(f"chain exit marker reports failure (EXIT={code})")
    elif state == "malformed":
        abnormal.append("exit marker malformed/unreadable")

    lock = _load_json(os.path.join(workspace, "run_invariants_lock.json"))
    if lock:
        out["resolved_data_scope"] = lock.get("resolved_data_scope")
        out["health_gate_enabled"] = lock.get("health_gate_enabled")
    else:
        abnormal.append("no readable run_invariants_lock.json")

    expected = expected_scope_from_name(run)
    if (
        expected is not None
        and out["resolved_data_scope"] is not None
        and sorted(out["resolved_data_scope"]) != expected
    ):
        abnormal.append(
            f"locked scope {out['resolved_data_scope']} != scope encoded in run name {expected}"
        )
    scope = out["resolved_data_scope"]

    if scope is not None:
        _check_effective_config(workspace, scope, abnormal)
        _check_denoised_artifacts(workspace, scope, abnormal)

    iter_dirs = sorted(
        d for d in glob.glob(os.path.join(workspace, "iter_[0-9][0-9][0-9]")) if os.path.isdir(d)
    )
    if not iter_dirs:
        abnormal.append("no iter_NNN directories found")

    scope_set = set(scope or [])
    for iter_dir in iter_dirs:
        manifest = _load_json(os.path.join(iter_dir, "manifest.json"))
        if manifest is None:
            abnormal.append(f"{os.path.basename(iter_dir)}: missing/unreadable manifest")
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
            abnormal.append(f"{entry['iter']}: manifest status=failed")
        elif status == "no_records":
            out["no_records_iters"] += 1

        m_scope = manifest.get("resolved_data_scope")
        if m_scope is not None and scope is not None and sorted(m_scope) != sorted(scope):
            abnormal.append(f"{entry['iter']}: manifest scope {m_scope} != lock {scope}")

        for key, field in (
            ("best_raw_score", "best_score"),
            ("best_valid_score", "best_valid_score"),
        ):
            v = manifest.get(field)
            if v is not None and (out[key] is None or v > out[key]):
                out[key] = v
                if key == "best_raw_score":
                    out["best_proposal"] = manifest.get("model_name")

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
                # Every gate-attempted file must be in scope.
                if scope_set:
                    for gres in rec.get("health_gate_results") or []:
                        agg = gres.get("aggregation") or {}
                        attempted = set(agg.get("files_requested") or []) | set(
                            agg.get("files_completed") or []
                        )
                        outside = sorted(attempted - scope_set)
                        if outside:
                            abnormal.append(
                                f"{entry['iter']}: gate {gres.get('gate_name')} "
                                f"attempted out-of-scope files {outside}"
                            )
    return out


def render(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# V18 wave checkpoint summary",
        "",
        "NOTE: aggregate scalars are comparable only WITHIN one scope;",
        "cross-scope review must use per-file vectors, never scalar ranking.",
        "",
    ]
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for s in summaries:
        key = str(s.get("resolved_data_scope") or "(unknown scope)")
        by_scope.setdefault(key, []).append(s)
    for scope_key, group in by_scope.items():
        lines.append(f"# Scope {scope_key} (scalars comparable within this group only)")
        for s in group:
            lines += [
                f"## {s['run']}",
                f"  exit marker       : {s['exit_state']} (code={s['exit_code']})",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspaces", nargs="+")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Final-checkpoint mode: exit 1 on ANY abnormal finding "
        "(incl. missing/nonzero/malformed exit markers).",
    )
    parser.add_argument(
        "--exit-dir",
        default="/tmp",
        help="Directory holding {run_name}.exit markers (default /tmp).",
    )
    args = parser.parse_args(argv)
    summaries = [summarize_workspace(ws, exit_dir=args.exit_dir) for ws in args.workspaces]
    print(render(summaries))
    total_abnormal = sum(len(s["abnormal"]) for s in summaries)
    if args.strict and total_abnormal:
        print(f"STRICT MODE: {total_abnormal} abnormal finding(s) — DO NOT approve the next wave.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
