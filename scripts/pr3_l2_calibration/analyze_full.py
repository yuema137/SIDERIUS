# scripts/pr3_l2_calibration/analyze_full.py
"""Deterministic analysis for the full descriptive Layer-2 campaign
(`pr3_l2_full_calibration_protocol.md`). Pure post-processing — no LLM.

Reports, per scenario cell (scenario × arm) and pooled where justified:
attempted / valid / terminal / incomplete counts, per-metric numerators
with EXACT eligible denominators, arm rates with Wilson 95% CIs,
absolute C−T differences with Newcombe hybrid 95% CIs, operational and
reliability metrics (incl. per-arm causal-correction rates — the §24.1
pre-registered mitigation), tokens, latency, cost.

Descriptive design: NO significance testing; a CI crossing zero is
NEVER reported as "no effect".

Usage:
    .venv/bin/python -m scripts.pr3_l2_calibration.analyze_full \
        reports/artifacts/pr3_l2_full/<run_id>
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

CORRECTION_MARKER = "## VALIDATION ERROR — CORRECT AND RESEND"

# Metric eligibility per scenario (frozen with the protocol; primary
# metrics marked P1/P2; safety S; secondary 2; exploratory X).
METRICS = {
    "S1": {
        "deterministic_relevant_change": "P2",
        "config_equals_failed": "P1-prescreen",
        "mentions_gate_name": "2",
        "mentions_fingerprint_string": "2",
        "claims_feedback_use": "2",
        "mentions_diversity_loss_mechanism": "X",
        "mentions_normalization_mechanism": "X",
        "mentions_activation_mechanism": "X",
    },
    "S2": {
        "deterministic_relevant_change": "P2",
        "healthy_mechanism_mentioned": "S",
        "cross_attribution_prescreen": "S",
        "config_equals_failed": "P1-prescreen",
        "mentions_gate_name": "2",
        "mentions_fingerprint_string": "2",
        "claims_feedback_use": "2",
    },
    "S3": {
        "healthy_mechanism_mentioned": "S",
        "stale_as_current_prescreen": "S",
        "historical_framing_present": "2",
        "mentions_fingerprint_string": "2",
        "mentions_gate_name": "2",
        "claims_feedback_use": "2",
        "deterministic_relevant_change": "X",
    },
    "S4": {
        "deterministic_relevant_change": "P2",
        "amplitude_or_scaling_change": "2",
        "mentions_conflict_or_marginal": "2",
        "retains_spectral_mechanism": "S",
        "mentions_std_gate_name": "2",
        "mentions_std_fingerprint_string": "2",
        "claims_feedback_use": "2",
    },
}


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float, float]:
    """Wilson 95% interval. Returns (rate, lo, hi); (nan,...) when n=0."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def newcombe_diff(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    """Newcombe hybrid 95% CI for p1 - p2 (arm1 minus arm2)."""
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan"), float("nan")
    p1, l1, u1 = wilson(k1, n1)
    p2, l2, u2 = wilson(k2, n2)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi


def load_samples(run_dir: Path) -> list[dict]:
    samples = []
    for meta_path in sorted(run_dir.glob("*/sample_meta.json")):
        d = meta_path.parent
        meta = json.loads(meta_path.read_text())
        sp = d / "deterministic_score.json"
        meta["score"] = json.loads(sp.read_text()) if sp.exists() else {}
        rp = d / "rubric_adjudicated.json"
        meta["rubric"] = json.loads(rp.read_text()) if rp.exists() else {}
        rows = [
            json.loads(line)
            for line in (d / "calls.jsonl").read_text().splitlines()
            if line.strip()
        ]
        meta["n_attempts"] = len(rows)
        meta["n_errors"] = sum(1 for r in rows if r.get("error"))
        meta["latency_total_s"] = round(sum(r.get("latency_s") or 0 for r in rows), 1)
        meta["input_tokens"] = sum(r.get("prompt_tokens") or 0 for r in rows if not r.get("error"))
        meta["cached_tokens"] = sum(r.get("cached_tokens") or 0 for r in rows if not r.get("error"))
        meta["output_tokens"] = sum(
            r.get("completion_tokens") or 0 for r in rows if not r.get("error")
        )
        corr = 0
        for r in rows:
            msgs = r.get("request_messages") or []
            user = next((m["content"] for m in msgs if m["role"] == "user"), "")
            if CORRECTION_MARKER in user:
                corr += 1
        meta["correction_calls"] = corr
        samples.append(meta)
    # Incomplete bundles (no sample_meta.json)
    for d in sorted(run_dir.glob("*/")):
        if (
            d.is_dir()
            and not (d / "sample_meta.json").exists()
            and ((d / "calls.jsonl").exists() or (d / "aborted_incomplete.json").exists())
        ):
            samples.append({"sample_id": d.name, "incomplete": True})
    return samples


def analyze(run_dir: Path) -> dict:
    samples = load_samples(run_dir)
    complete = [s for s in samples if not s.get("incomplete")]
    by_cell: dict[tuple, list[dict]] = defaultdict(list)
    for s in complete:
        by_cell[(s["scenario"], s["arm"])].append(s)

    report: dict = {
        "run_dir": str(run_dir),
        "n_samples_complete": len(complete),
        "n_incomplete": sum(1 for s in samples if s.get("incomplete")),
        "cells": {},
        "contrasts": {},
        "reliability": {},
    }

    scenarios = sorted({s["scenario"] for s in complete})
    for scenario in scenarios:
        for arm in ("C", "T"):
            group = by_cell.get((scenario, arm), [])
            valid = [s for s in group if s["score"].get("schema_valid")]
            cell: dict = {
                "attempted": len(group),
                "valid": len(valid),
                "terminal": sum(1 for s in group if s.get("terminal_error")),
                "pipeline_mode_all": all(s.get("production_pipeline_mode") for s in group),
                "isolation_ok_all": all(s["score"].get("treatment_isolation_ok") for s in group),
                "correction_calls": sum(s["correction_calls"] for s in group),
                "correction_rate_samples": wilson(
                    sum(1 for s in group if s["correction_calls"]), len(group)
                ),
                "input_tokens": sum(s["input_tokens"] for s in group),
                "cached_tokens": sum(s["cached_tokens"] for s in group),
                "output_tokens": sum(s["output_tokens"] for s in group),
                "latency_total_s": round(sum(s["latency_total_s"] for s in group), 1),
                "metrics": {},
            }
            for metric, tier in METRICS.get(scenario, {}).items():
                k = sum(1 for s in valid if s["score"].get(metric))
                n = len(valid)
                rate, lo, hi = wilson(k, n)
                cell["metrics"][metric] = {
                    "tier": tier,
                    "k": k,
                    "n": n,
                    "rate": None if math.isnan(rate) else round(rate, 3),
                    "wilson95": None if math.isnan(rate) else [round(lo, 3), round(hi, 3)],
                }
            report["cells"][f"{scenario}_{arm}"] = cell

        # C-vs-T contrasts (T minus C) per metric
        cv = [s for s in by_cell.get((scenario, "C"), []) if s["score"].get("schema_valid")]
        tv = [s for s in by_cell.get((scenario, "T"), []) if s["score"].get("schema_valid")]
        contrasts = {}
        for metric, tier in METRICS.get(scenario, {}).items():
            kc = sum(1 for s in cv if s["score"].get(metric))
            kt = sum(1 for s in tv if s["score"].get(metric))
            d, lo, hi = newcombe_diff(kt, len(tv), kc, len(cv))
            contrasts[metric] = {
                "tier": tier,
                "T": f"{kt}/{len(tv)}",
                "C": f"{kc}/{len(cv)}",
                "diff_T_minus_C": None if math.isnan(d) else round(d, 3),
                "newcombe95": None if math.isnan(d) else [round(lo, 3), round(hi, 3)],
            }
        report["contrasts"][scenario] = contrasts

    # Reliability + §24.1 correction-rate mitigation (pooled per arm)
    for arm in ("C", "T"):
        g = [s for s in complete if s["arm"] == arm]
        with_corr = sum(1 for s in g if s["correction_calls"])
        rate, lo, hi = wilson(with_corr, len(g))
        report["reliability"][arm] = {
            "samples": len(g),
            "terminal": sum(1 for s in g if s.get("terminal_error")),
            "samples_with_correction": with_corr,
            "correction_sample_rate": None if math.isnan(rate) else round(rate, 3),
            "wilson95": None if math.isnan(rate) else [round(lo, 3), round(hi, 3)],
        }
    rc = report["reliability"].get("C", {}).get("correction_sample_rate")
    rt = report["reliability"].get("T", {}).get("correction_sample_rate")
    if rc is not None and rt is not None:
        imb = abs(rt - rc)
        report["reliability"]["correction_imbalance_abs"] = round(imb, 3)
        report["reliability"]["imbalance_caveat_triggered"] = imb > 0.30

    sp = run_dir / "run_summary.json"
    if sp.exists():
        report["ledger"] = {k: v for k, v in json.loads(sp.read_text()).items() if k != "samples"}
    stp = run_dir / "run_status.json"
    if stp.exists():
        report["run_status"] = json.loads(stp.read_text())
    return report


if __name__ == "__main__":
    result = analyze(Path(sys.argv[1]))
    (Path(sys.argv[1]) / "analysis_full.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
