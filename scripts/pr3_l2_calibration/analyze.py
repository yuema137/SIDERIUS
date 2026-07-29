# scripts/pr3_l2_calibration/analyze.py
"""Deterministic aggregation of calibration artifacts (protocol §8).

Pure post-processing — no LLM calls. Reads the per-sample artifact
bundles and the ledger; emits per-arm metric tables with EXPLICIT
eligibility denominators, operational metrics, and the delivery checks.
Rubric labels are merged from a separate adjudication file when present
(scorer facts and rubric labels never overwrite each other).

Usage:
    .venv/bin/python -m scripts.pr3_l2_calibration.analyze \
        reports/artifacts/pr3_l2p/<run_id>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def load_samples(run_dir: Path) -> list[dict]:
    samples = []
    for meta_path in sorted(run_dir.glob("*/sample_meta.json")):
        sample_dir = meta_path.parent
        meta = json.loads(meta_path.read_text())
        score_path = sample_dir / "deterministic_score.json"
        meta["score"] = json.loads(score_path.read_text()) if score_path.exists() else {}
        rubric_path = sample_dir / "rubric_adjudicated.json"
        meta["rubric"] = json.loads(rubric_path.read_text()) if rubric_path.exists() else {}
        calls_path = sample_dir / "calls.jsonl"
        rows = (
            [json.loads(line) for line in calls_path.read_text().splitlines() if line.strip()]
            if calls_path.exists()
            else []
        )
        meta["n_attempts"] = len(rows)
        meta["n_errors"] = sum(1 for r in rows if r.get("error"))
        meta["latency_total_s"] = round(sum(r.get("latency_s") or 0 for r in rows), 1)
        meta["input_tokens"] = sum(r.get("prompt_tokens") or 0 for r in rows if not r.get("error"))
        meta["cached_tokens"] = sum(r.get("cached_tokens") or 0 for r in rows if not r.get("error"))
        meta["output_tokens"] = sum(
            r.get("completion_tokens") or 0 for r in rows if not r.get("error")
        )
        samples.append(meta)
    return samples


def _rate(numer: int, denom: int) -> str:
    return f"{numer}/{denom}" + (f" = {numer / denom:.2f}" if denom else " (no eligible samples)")


def analyze(run_dir: Path) -> dict:
    samples = load_samples(run_dir)
    by_arm: dict[tuple, list[dict]] = defaultdict(list)
    for s in samples:
        by_arm[(s["scenario"], s["arm"])].append(s)

    report: dict = {"run_dir": str(run_dir), "n_samples": len(samples), "cells": {}}
    for (scenario, arm), group in sorted(by_arm.items()):
        valid = [s for s in group if s["score"].get("schema_valid")]
        cell = {
            "attempted": len(group),
            "valid": len(valid),
            "terminal_failures": [s["sample_id"] for s in group if s.get("terminal_error")],
            "pipeline_mode_all": all(s.get("production_pipeline_mode") for s in group),
            "treatment_isolation_ok_all": all(
                s["score"].get("treatment_isolation_ok") for s in group
            ),
            # Behavioral facts (denominator = valid samples in the cell).
            "repeat_prescreen_config_equals_failed": _rate(
                sum(1 for s in valid if s["score"].get("config_equals_failed")), len(valid)
            ),
            "deterministic_relevant_change": _rate(
                sum(1 for s in valid if s["score"].get("deterministic_relevant_change")),
                len(valid),
            ),
            "mentions_gate_name": _rate(
                sum(1 for s in valid if s["score"].get("mentions_gate_name")), len(valid)
            ),
            "mentions_fingerprint_string": _rate(
                sum(1 for s in valid if s["score"].get("mentions_fingerprint_string")),
                len(valid),
            ),
            "claims_feedback_use": _rate(
                sum(1 for s in valid if s["score"].get("claims_feedback_use")), len(valid)
            ),
            # Operational.
            "input_tokens": sum(s["input_tokens"] for s in group),
            "cached_tokens": sum(s["cached_tokens"] for s in group),
            "output_tokens": sum(s["output_tokens"] for s in group),
            "attempts": sum(s["n_attempts"] for s in group),
            "attempt_errors": sum(s["n_errors"] for s in group),
            "latency_total_s": round(sum(s["latency_total_s"] for s in group), 1),
        }
        if scenario == "S2":
            cell["healthy_mechanism_mentioned"] = _rate(
                sum(1 for s in valid if s["score"].get("healthy_mechanism_mentioned")),
                len(valid),
            )
            cell["cross_attribution_prescreen"] = _rate(
                sum(1 for s in valid if s["score"].get("cross_attribution_prescreen")),
                len(valid),
            )
        if any(s["rubric"] for s in group):
            labels: dict[str, int] = defaultdict(int)
            for s in valid:
                for label in s["rubric"].get("labels", []):
                    labels[label] += 1
            cell["rubric_labels"] = dict(labels)
        report["cells"][f"{scenario}_{arm}"] = cell

    summary_path = run_dir / "run_summary.json"
    if summary_path.exists():
        report["ledger"] = json.loads(summary_path.read_text())
    return report


if __name__ == "__main__":
    result = analyze(Path(sys.argv[1]))
    print(json.dumps(result, indent=2))
