"""V21 PR F — report generation over schema-validated evidence.

The report NEVER classifies on its own: every verdict comes from
`classify.classify_point` (the single frozen implementation) and every
timing summary from `classify.summarize_exact`. Populations are grouped,
never pooled; `architecture_family` rides on every row; and no
cross-architecture pooled slope is computed anywhere (interpretation
boundary, operator rule).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.inspection_cost_study.classify import classify_point, summarize_exact
from scripts.inspection_cost_study.harness import read_measurements
from scripts.inspection_cost_study.schemas import Measurement, PointVerdict, SweepEntry

#: operation -> (budget_name, attribute on ProbeBudgets)
_BUDGET_FOR_OPERATION = {
    "candidate_probe": "single_candidate_seconds",
    "full_search": "batch_search_seconds",
    "training_probe": "single_probe_seconds",
}


def _points(
    measurements: list[Measurement],
) -> dict[tuple[str, str, int | None], list[Measurement]]:
    grouped: dict[tuple[str, str, int | None], list[Measurement]] = defaultdict(list)
    for m in measurements:
        grouped[(m.entry_id, m.operation, m.candidate_batch)].append(m)
    return dict(grouped)


def build_verdicts(
    measurements: list[Measurement],
    production_budgets: dict[str, float],
) -> list[PointVerdict]:
    """Every operation point, classified by THE frozen rule."""
    verdicts: list[PointVerdict] = []
    for (_entry, operation, _batch), group in sorted(
        _points(measurements).items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0)
    ):
        budget_name = _BUDGET_FOR_OPERATION[operation]
        verdicts.append(
            classify_point(
                group,
                budget_name=budget_name,
                budget_seconds=production_budgets[budget_name],
            )
        )
    return verdicts


def build_report(
    entries: list[SweepEntry],
    measurements_path: str | Path,
) -> dict[str, Any]:
    """Assemble the report payload from schema-validated evidence."""
    header, measurements, wall_expired = read_measurements(measurements_path)
    by_entry = {e.entry_id: e for e in entries}
    verdicts = build_verdicts(measurements, header.production_budgets)

    per_pop_op: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"CLEAR": 0, "WOULD_BE_CENSORED": 0, "INDETERMINATE": 0}
    )
    rows: list[dict[str, Any]] = []
    for v in verdicts:
        entry = by_entry.get(v.entry_id)
        population = entry.population if entry else "UNKNOWN_ENTRY"
        family = entry.architecture_family if entry else "UNKNOWN"
        per_pop_op[(population, v.operation)][v.verdict] += 1
        rows.append(
            {
                "entry_id": v.entry_id,
                "population": population,
                "architecture_family": family,
                "operation": v.operation,
                "candidate_batch": v.candidate_batch,
                "verdict": v.verdict,
                "budget_name": v.budget_name,
                "budget_seconds": v.budget_seconds,
                "n_under": v.n_under,
                "n_over_exact": v.n_over_exact,
                "n_over_censored": v.n_over_censored,
                "n_deadline": v.n_deadline,
                "reason": v.reason,
                "total_params": (entry.realized_total_parameter_count if entry else None),
                "trainable_params": (entry.realized_trainable_parameter_count if entry else None),
            }
        )

    disposition_counts: dict[str, int] = defaultdict(int)
    for m in measurements:
        disposition_counts[m.execution_outcome] += 1

    summaries: dict[str, dict[str, Any]] = {}
    per_op: dict[str, list[Measurement]] = defaultdict(list)
    for m in measurements:
        entry = by_entry.get(m.entry_id)
        pop = entry.population if entry else "UNKNOWN_ENTRY"
        per_op[f"{pop}::{m.operation}"].append(m)
    for key, group in sorted(per_op.items()):
        summaries[key] = summarize_exact(group)

    return {
        "manifest_hash": header.manifest_hash,
        "wall_expired": wall_expired,
        "production_budgets": header.production_budgets,
        "disposition_counts": dict(disposition_counts),
        "verdict_counts_per_population_operation": {
            f"{p}::{o}": c for (p, o), c in sorted(per_pop_op.items())
        },
        "rows": rows,
        "timing_summaries": summaries,
        "n_measurements": len(measurements),
    }
