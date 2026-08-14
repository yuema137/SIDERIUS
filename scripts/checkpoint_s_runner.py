#!/usr/bin/env python3
"""scripts/checkpoint_s_runner.py — Checkpoint S: 5× same-seed lit-review re-run.

After Commit F (last sub-commit of the 2026-06-12 search-quality train),
re-run the lit-review agent N times against the canonical seed
(interpretation_iter_014.json from exploration_explore_novel_v12_0504) and
verify the LLM behavioral effects of Fixes 1-6 + Commit F:

  1. Escalations succeed (non-noop) — Fix 3 working
  2. v=1 findings reach the proposer at confidence ≥ 0.60 — Fix 1 working
  3. Queries spread across ≥ 2 dimensions — Fix 5 working
  4. search_decisions audit trail populated — Fix 4 working
  5. Runs are reproducible enough that the LLM consistently picks the
     same ballpark of papers and dimensions

REAL API calls: DeepSeek (paper compression + search-decision +
synthesis) + Semantic Scholar (search + metadata + PDFs). Costs DeepSeek
quota + S2 rate. Estimated run time: ~5-10 min per run, ~25-50 min for
the default N=5.

Note: at the time this script was added, ``reference_data/root_papers_cache/``
held only its README — TIDMAD (arxiv:2406.04378) was NOT cached, so run 1
spends ~30s populating the cache before its dynamic loop starts. Runs 2-5
cache-hit the root paper instantly. The added latency only affects timing
on run 1, not the search-loop behavior under test.

Usage:
    .venv/bin/python scripts/checkpoint_s_runner.py [--n N] [--out-dir DIR]

Outputs:
    reference_data/lit_review_pilot_cache/post_6_5_audit_runs/run_{N}.json
    (one full LiteratureReviewOutput JSON per run, plus the node's
    auto-named ml_literature_review_run_{N}.json side-by-side)

Plus a stdout summary table at the end.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import yaml

# Make sure SIDERIUS root is on sys.path so `from agent.* / nodes.*` works
# when this script is invoked directly.
SIDERIUS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIDERIUS_ROOT))

from agent.schemas.interpretation import InterpretationOutput  # noqa: E402
from agent.schemas.literature_review import (  # noqa: E402
    LiteratureReviewInput,
    LiteratureReviewOutput,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig  # noqa: E402
from nodes.ml_literature_review import (  # noqa: E402
    MLLiteratureReviewAgent,
    _parse_dimension,
)
from workflows.task_config import get_task_description, load_task_config  # noqa: E402

# Canonical seed (operator-owned data, read-only)
SEED_PATH = Path(
    "/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v12_0504"
    "/iter_014/iteration_014/interpretation_iter_014.json"
)
# Default output directory (under reference_data/, the repo's writable scratch
# space; gitignored).
DEFAULT_OUT_DIR = SIDERIUS_ROOT / "reference_data/lit_review_pilot_cache/post_6_5_audit_runs"
# Canonical YAML
YAML_PATH = SIDERIUS_ROOT / "configs/lit_review_config.yaml"
# LLM routing — DeepSeek v4-pro for all three LLM call types (paper-extract,
# search-decision, synthesis). Matches the wiring test's _LLM_KWARGS.
LLM_KWARGS = {
    "llm_provider": "deepseek",
    "llm_model_id": "deepseek-v4-pro",
    "search_llm_provider": "deepseek",
    "search_llm_model_id": "deepseek-v4-pro",
}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_seed() -> InterpretationOutput:
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"Canonical seed file not found: {SEED_PATH}")
    return InterpretationOutput.model_validate_json(SEED_PATH.read_text(encoding="utf-8"))


def _load_yaml() -> dict:
    with YAML_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_input(
    interp: InterpretationOutput,
    cfg: dict,
    run_name: str,
    workspace: Path,
) -> LiteratureReviewInput:
    """Construct a LiteratureReviewInput from the seed + YAML for one run.

    Mirrors ``workflows.model_exploration._build_lit_review_input`` but
    inlined here so the script has no workflow dependency.

    Step 04b: the mirror follows production onto the canonical task profile.
    ``cfg`` no longer supplies ``task_description`` — the lit-review YAML
    stopped declaring one, so reading it here would have silently sent an
    empty task anchor to the LLM.
    """
    return LiteratureReviewInput.model_validate(
        {
            "experiment_history": interp,
            "root_papers": cfg.get("root_papers", []),
            "dynamic_search": cfg.get("dynamic_search", {}),
            "synthesis_config": cfg.get("synthesis", {}),
            "confidence_rubric": cfg.get("confidence_rubric", {}),
            "findings_verbosity": cfg.get("findings_verbosity", 1),
            "task_description": get_task_description(load_task_config()),
            "storage": StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(workspace), run_name=run_name),
            ),
            "run_name": run_name,
            **LLM_KWARGS,
        }
    )


# ---------------------------------------------------------------------------
# Per-run execution
# ---------------------------------------------------------------------------


def _run_one(
    n: int,
    interp: InterpretationOutput,
    cfg: dict,
    workspace: Path,
) -> LiteratureReviewOutput | None:
    """Run MLLiteratureReviewAgent.run() once.

    Returns the LiteratureReviewOutput on success, None on failure (the
    error is printed but the script continues to the next run so a
    transient failure doesn't lose the other 4 runs).
    """
    run_name = f"run_{n}"
    print(f"[run {n}] starting...")
    try:
        inp = _build_input(interp, cfg, run_name, workspace)
        agent = MLLiteratureReviewAgent()  # uses default root_cache_dir
        out = agent.run(inp)
        # Also write to the script-specified path (in addition to the
        # node's own auto-named file at
        # workspace/ml_literature_review_{run_name}.json).
        out_path = workspace / f"{run_name}.json"
        out_path.write_text(out.model_dump_json(indent=2), encoding="utf-8")
        max_rounds = cfg.get("dynamic_search", {}).get("max_rounds", "?")
        print(
            f"[run {n}] done — wrote {out_path.relative_to(SIDERIUS_ROOT)} "
            f"({len(out.findings)} findings, "
            f"{out.search_rounds_used}/{max_rounds} rounds)"
        )
        return out
    except Exception as e:
        print(f"[run {n}] FAILED: {e}")
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------


def _summarize(n: int, out: LiteratureReviewOutput) -> dict:
    """Compute per-run summary metrics."""
    # paper_id -> verbosity_achieved lookup
    verbosity_by_id = {rp.paper_id: rp.verbosity_achieved for rp in out.retrieved_papers}

    # Escalations: counted from the audit trail. "ok" outcome means
    # verbosity_achieved actually rose; "noop" / "error" / "budget_exceeded"
    # etc. are charged budget but did NOT add a v1 extract.
    escalations_total = sum(1 for d in out.search_decisions if d.action == "escalate")
    escalations_ok = sum(
        1 for d in out.search_decisions if d.action == "escalate" and d.outcome == "ok"
    )

    # v=1 findings: findings cited from a paper whose verbosity_achieved
    # reached 1 (or 2). Confidence >= 0.60 is implicit per the rubric
    # clamping logic, but we report raw counts so the audit can see if
    # the clamp was hit.
    v1_findings = sum(1 for f in out.findings if verbosity_by_id.get(f.source_ref, 0) >= 1)

    # Max confidence across findings.
    max_conf = max((f.confidence or 0.0) for f in out.findings) if out.findings else 0.0

    # Dimensions covered: scan each "search" decision's reasoning for the
    # first-occurring DIMENSION_LABELS token (case-insensitive). Trusted
    # LLM self-reporting — no parser-enforced contract.
    dims_seen: set[str] = set()
    for d in out.search_decisions:
        if d.action != "search":
            continue
        dim = _parse_dimension(d.reasoning or "")
        if dim is not None:
            dims_seen.add(dim)

    return {
        "run": n,
        "rounds_used": out.search_rounds_used,
        "search_decisions": len(out.search_decisions),
        "escalations_total": escalations_total,
        "escalations_ok": escalations_ok,
        "findings": len(out.findings),
        "v1_findings": v1_findings,
        "max_confidence": round(max_conf, 2),
        "dims_covered": len(dims_seen),
        "dim_labels": sorted(dims_seen),
    }


def _print_table(rows: list[dict]) -> None:
    """Print a fixed-width per-run summary plus aggregate row."""
    print()
    print("=" * 100)
    print("Checkpoint S — per-run summary (post 6.5a/b + Commit F)")
    print("=" * 100)
    print(
        f"{'run':>4} {'rnd':>4} {'sd':>4} "
        f"{'esc(ok/tot)':>13} {'find(v1/tot)':>14} "
        f"{'maxC':>6} {'dims':>5} labels"
    )
    print("-" * 100)
    for r in rows:
        print(
            f"{r['run']:>4} "
            f"{r['rounds_used']:>4} "
            f"{r['search_decisions']:>4} "
            f"{r['escalations_ok']:>4}/{r['escalations_total']:<8} "
            f"{r['v1_findings']:>4}/{r['findings']:<9} "
            f"{r['max_confidence']:>6.2f} "
            f"{r['dims_covered']:>5} "
            f"{','.join(r['dim_labels'])}"
        )
    print("-" * 100)
    # Aggregate across runs
    n_runs = len(rows)
    if n_runs == 0:
        print("(no successful runs to aggregate)")
        print("=" * 100)
        return
    avg_esc_ok = sum(r["escalations_ok"] for r in rows) / n_runs
    avg_v1 = sum(r["v1_findings"] for r in rows) / n_runs
    max_max_conf = max(r["max_confidence"] for r in rows)
    dim_union: set[str] = set()
    for r in rows:
        dim_union.update(r["dim_labels"])
    print(
        f"Across {n_runs} runs: "
        f"avg escalations_ok = {avg_esc_ok:.1f}, "
        f"avg v1 findings = {avg_v1:.1f}, "
        f"max max_confidence = {max_max_conf:.2f}, "
        f"dim union = {sorted(dim_union)}"
    )
    print("=" * 100)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Checkpoint S — 5× same-seed lit-review re-run")
    parser.add_argument("--n", type=int, default=5, help="Number of runs (default 5)")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory (default {DEFAULT_OUT_DIR.relative_to(SIDERIUS_ROOT)})",
    )
    args = parser.parse_args()

    workspace = args.out_dir
    workspace.mkdir(parents=True, exist_ok=True)

    print(f"Loading seed from {SEED_PATH}")
    interp = _load_seed()
    print(f"  bottlenecks ({len(interp.bottlenecks)}): {interp.bottlenecks}")
    print(f"  take_home: {interp.take_home_message!r}")
    print(f"  model_types explored: {interp.model_types}")

    print(f"\nLoading YAML config from {YAML_PATH.relative_to(SIDERIUS_ROOT)}")
    cfg = _load_yaml()
    task = get_task_description(load_task_config())
    print(
        f"  task_description (from configs/task_config.yaml): {task[:80]!r}{'...' if len(task) > 80 else ''}"
    )
    print(f"  dynamic_search.max_rounds = {cfg['dynamic_search']['max_rounds']}")
    print(f"  dynamic_search.escalation_allowed = {cfg['dynamic_search']['escalation_allowed']}")

    print(f"\nRunning {args.n} iterations to {workspace.relative_to(SIDERIUS_ROOT)}/")
    print("Each iteration ~5-10 min (real DeepSeek + S2 API calls)")
    print()

    rows: list[dict] = []
    for n in range(1, args.n + 1):
        out = _run_one(n, interp, cfg, workspace)
        if out is not None:
            rows.append(_summarize(n, out))

    _print_table(rows)


if __name__ == "__main__":
    main()
