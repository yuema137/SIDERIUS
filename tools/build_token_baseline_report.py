#!/usr/bin/env python
"""Token-usage baseline + top-3 bloat report builder.

Reads ``{workspace}/token_usage.jsonl`` and emits two markdown reports:

- ``reports/v12_token_baseline.md`` — full per-iter / per-label breakdown
  including USD cost, Happy-Path-Cost vs Recovery-Cost segmentation, and
  per-label linear growth slopes.
- ``reports/v12_top3_bloat.md`` — Top-3 proposer-component bloat per iter
  (per audit doc §1.9.1) + aggregate growth verdict.

See ``docs/audit_and_optimize_token_usage_and_growth.md`` §8 Commit 5
(Rev 6) for the full spec.

Pre-flight: the input JSONL is linted by ``validate_token_usage_jsonl.lint``
before any aggregation runs. A failed lint blocks publication and exits
nonzero — we never publish numbers from a corrupted log.

Two alerts are reported (informational, exit 0):
- ``[BLOAT_ALERT]`` when an iter's total USD exceeds the threshold (default
  $1.50/iter, the post-dehydration North Star — at V12 rates this fires
  on every iter by design).
- ``[CONTEXT_EXPLOSION]`` when any single call's ``tokens.prompt`` exceeds
  the threshold (default 50 K — past this, model recall degrades).

USD cost defaults to ``$10/1M prompt + $30/1M completion`` (placeholder
gpt-5.4 rates; configurable via ``--rate-prompt`` / ``--rate-completion``).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from agent.schemas.telemetry import TokenUsageRow
from core.layout import checkout_root, require_checkout
from tools.validate_token_usage_jsonl import lint as lint_jsonl

REPO_ROOT = checkout_root()

DEFAULT_RATE_PROMPT = 10.0  # USD per 1M prompt tokens (gpt-5.4 placeholder)
DEFAULT_RATE_COMPLETION = 30.0  # USD per 1M completion tokens
DEFAULT_BLOAT_USD_PER_ITER = 1.50  # post-dehydration North Star
DEFAULT_CONTEXT_EXPLOSION_PROMPT_TOK = 50_000

# Proposer's 10-key component schema (audit doc §1.5 / Commit 4.2).
PROPOSER_COMPONENT_KEYS: tuple[str, ...] = (
    "system_prompt",
    "candidates_markdown",
    "interpretation_json",
    "previous_failures",
    "vocab_block",
    "expert_context_block",
    "agent_cards_block",
    "prior_stage_outputs",
    "recent_gate_block",
    "template_and_scaffolding",
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CallStats:
    """Aggregated counts for one (iter, label) cell or one segmentation slice."""

    n_calls: int = 0
    prompt_tok: int = 0
    completion_tok: int = 0
    total_tok: int = 0  # provider-reported; sometimes ≠ prompt+completion
    chars_total: int = 0

    def add_row(self, row: TokenUsageRow) -> None:
        self.n_calls += 1
        self.prompt_tok += row.tokens.prompt or 0
        self.completion_tok += row.tokens.completion or 0
        self.total_tok += row.tokens.total or 0
        self.chars_total += row.chars.total

    def usd(self, rate_prompt: float, rate_completion: float) -> float:
        return (self.prompt_tok * rate_prompt + self.completion_tok * rate_completion) / 1_000_000


@dataclass
class IterAgg:
    """Per-iter totals + happy/recovery split + per-label breakdown."""

    iter: int
    happy: CallStats
    recovery: CallStats
    by_label: dict[str, CallStats]
    by_label_happy: dict[str, CallStats]
    by_label_recovery: dict[str, CallStats]
    proposer_components_chars: dict[str, int]  # summed across proposer rows

    @property
    def total(self) -> CallStats:
        merged = CallStats()
        merged.n_calls = self.happy.n_calls + self.recovery.n_calls
        merged.prompt_tok = self.happy.prompt_tok + self.recovery.prompt_tok
        merged.completion_tok = self.happy.completion_tok + self.recovery.completion_tok
        merged.total_tok = self.happy.total_tok + self.recovery.total_tok
        merged.chars_total = self.happy.chars_total + self.recovery.chars_total
        return merged


# ---------------------------------------------------------------------------
# Loading + segmentation
# ---------------------------------------------------------------------------


def load_rows(jsonl_path: Path) -> list[TokenUsageRow]:
    """Load + validate every row. Skips marker rows (label='_iter_flush')
    so they don't pollute aggregates."""
    rows: list[TokenUsageRow] = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            row = TokenUsageRow.model_validate(obj)
            if row.label == "_iter_flush":
                continue
            if row.iter is None:
                continue  # out-of-iter setup/teardown rows
            rows.append(row)
    return rows


def is_happy_path(row: TokenUsageRow) -> bool:
    """Happy-Path-Cost rule (audit doc §8 Commit 5):
    ``extra.attempt == 0 AND extra.status == "ok"``.
    Missing fields default to recovery (conservative)."""
    attempt = row.extra.get("attempt", -1)
    status = row.extra.get("status", "")
    return attempt == 0 and status == "ok"


def aggregate_by_iter(rows: list[TokenUsageRow]) -> dict[int, IterAgg]:
    """Build per-iter aggregates with happy/recovery + per-label split.

    Rows with ``iter is None`` are setup/teardown calls outside any
    iteration (see ``TokenUsageRow.iter`` docstring) — they're skipped
    because downstream consumers ``sorted(aggs)`` and arithmetic on
    iter indices would crash on a None key.
    """
    aggs: dict[int, IterAgg] = {}
    for row in rows:
        if row.iter is None:
            continue
        it = row.iter
        agg = aggs.get(it)
        if agg is None:
            agg = IterAgg(
                iter=it,
                happy=CallStats(),
                recovery=CallStats(),
                by_label=defaultdict(CallStats),
                by_label_happy=defaultdict(CallStats),
                by_label_recovery=defaultdict(CallStats),
                proposer_components_chars=defaultdict(int),
            )
            aggs[it] = agg
        agg.by_label[row.label].add_row(row)
        if is_happy_path(row):
            agg.happy.add_row(row)
            agg.by_label_happy[row.label].add_row(row)
        else:
            agg.recovery.add_row(row)
            agg.by_label_recovery[row.label].add_row(row)
        if row.label.startswith("proposer.") and row.components:
            for k, v in row.components.items():
                agg.proposer_components_chars[k] += int(v)
    # convert defaultdicts → plain dicts for stable rendering
    for agg in aggs.values():
        agg.by_label = dict(agg.by_label)
        agg.by_label_happy = dict(agg.by_label_happy)
        agg.by_label_recovery = dict(agg.by_label_recovery)
        agg.proposer_components_chars = dict(agg.proposer_components_chars)
    return aggs


# ---------------------------------------------------------------------------
# Growth slopes (numpy linear regression — robust to missing iters)
# ---------------------------------------------------------------------------


def linear_slope(iter_value_pairs: list[tuple[int, float]]) -> tuple[float, float]:
    """Least-squares linear fit y = slope*x + intercept.

    Robust to missing iterations (e.g., a crashed iter that never wrote to
    the JSONL): we fit on whatever points are present rather than indexing
    by position. Returns (slope, R²). If <2 points, returns (0.0, 0.0).

    Slope is in "value units per iter" — for prompt-token y, this is
    tokens/iter; for USD y, this is USD/iter."""
    if len(iter_value_pairs) < 2:
        return 0.0, 0.0
    xs = np.array([p[0] for p in iter_value_pairs], dtype=float)
    ys = np.array([p[1] for p in iter_value_pairs], dtype=float)
    if np.allclose(ys, ys[0]):  # flat — slope=0, R² undefined → 0
        return 0.0, 0.0
    slope, intercept = np.polyfit(xs, ys, 1)
    y_pred = slope * xs + intercept
    ss_res = float(np.sum((ys - y_pred) ** 2))
    ss_tot = float(np.sum((ys - ys.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(slope), r_squared


def per_label_slopes(
    aggs: dict[int, IterAgg],
    rate_prompt: float,
    rate_completion: float,
) -> dict[str, dict[str, float]]:
    """Per-label growth slopes for prompt tokens and USD cost.

    Returns ``{label: {"tok_slope", "tok_r2", "usd_slope", "usd_r2"}}``.
    """
    iters_sorted = sorted(aggs)
    label_set = sorted({lbl for it in iters_sorted for lbl in aggs[it].by_label})
    out: dict[str, dict[str, float]] = {}
    for lbl in label_set:
        tok_pts: list[tuple[int, float]] = []
        usd_pts: list[tuple[int, float]] = []
        for it in iters_sorted:
            cs = aggs[it].by_label.get(lbl)
            if cs is None or cs.n_calls == 0:
                continue  # missing point — handled by polyfit on whatever's left
            tok_pts.append((it, float(cs.prompt_tok + cs.completion_tok)))
            usd_pts.append((it, cs.usd(rate_prompt, rate_completion)))
        tok_slope, tok_r2 = linear_slope(tok_pts)
        usd_slope, usd_r2 = linear_slope(usd_pts)
        out[lbl] = {
            "tok_slope": tok_slope,
            "tok_r2": tok_r2,
            "usd_slope": usd_slope,
            "usd_r2": usd_r2,
            "n_points": float(len(tok_pts)),
        }
    return out


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@dataclass
class BloatAlert:
    iter: int
    usd: float


@dataclass
class ContextExplosionAlert:
    iter: int
    label: str
    prompt_tok: int
    attempt: int
    run_id: str


def detect_alerts(
    rows: list[TokenUsageRow],
    aggs: dict[int, IterAgg],
    rate_prompt: float,
    rate_completion: float,
    bloat_usd_threshold: float,
    context_prompt_threshold: int,
) -> tuple[list[BloatAlert], list[ContextExplosionAlert]]:
    bloats: list[BloatAlert] = []
    for it, agg in sorted(aggs.items()):
        usd = agg.total.usd(rate_prompt, rate_completion)
        if usd > bloat_usd_threshold:
            bloats.append(BloatAlert(iter=it, usd=usd))
    explosions: list[ContextExplosionAlert] = []
    for r in rows:
        if (r.tokens.prompt or 0) > context_prompt_threshold:
            explosions.append(
                ContextExplosionAlert(
                    iter=r.iter or -1,  # type: ignore[arg-type]
                    label=r.label,
                    prompt_tok=r.tokens.prompt or 0,
                    attempt=int(r.extra.get("attempt", -1)),
                    run_id=r.run_id,
                )
            )
    return bloats, explosions


# ---------------------------------------------------------------------------
# Top-3 bloat (audit doc §1.9.1) — proposer-component-keys view
# ---------------------------------------------------------------------------


def top3_bloat_per_iter(aggs: dict[int, IterAgg]) -> dict[int, list[tuple[str, int]]]:
    """For each iter, return up to 3 (component_key, chars) tuples sorted
    descending by chars across all proposer.* rows that iter."""
    out: dict[int, list[tuple[str, int]]] = {}
    for it, agg in aggs.items():
        sorted_keys = sorted(
            agg.proposer_components_chars.items(),
            key=lambda kv: -kv[1],
        )
        out[it] = sorted_keys[:3]
    return out


def aggregate_component_growth(
    aggs: dict[int, IterAgg],
) -> dict[str, dict[str, Any]]:
    """Per-component iter1→iterN growth for the 10 canonical proposer keys."""
    iters_sorted = sorted(aggs)
    if not iters_sorted:
        return {}
    first_iter = iters_sorted[0]
    last_iter = iters_sorted[-1]
    first = aggs[first_iter].proposer_components_chars
    last = aggs[last_iter].proposer_components_chars
    out: dict[str, dict[str, Any]] = {}
    for key in PROPOSER_COMPONENT_KEYS:
        c0 = first.get(key, 0)
        cn = last.get(key, 0)
        if c0 == 0 and cn == 0:
            continue
        if c0 == 0:
            growth_x = math.inf
            growth_pct = math.inf
        else:
            growth_x = cn / c0
            growth_pct = (cn - c0) / c0
        verdict = (
            "bloating" if growth_pct > 0.30 else ("shrinking" if growth_pct < -0.10 else "bounded")
        )
        out[key] = {
            "iter1_chars": c0,
            "iterN_chars": cn,
            "growth_x": growth_x,
            "growth_pct": growth_pct,
            "verdict": verdict,
        }
    return out


# ---------------------------------------------------------------------------
# Verdict (audit doc §1.9.2)
# ---------------------------------------------------------------------------


def compute_verdict(component_growth: dict[str, dict[str, Any]]) -> str:
    """One of:
    - 'Confirmed Proposer Hypothesis' if top growers are proposer-content keys
    - 'Pivot Required — Tuner' if tuner labels dominate (caller passes per_label growth)
    - 'Pivot Required — Other' otherwise
    - 'Sanity Floor' if total growth < 1.5× iter 1 (handled by caller).

    This function only returns proposer-vs-other; tuner pivot is detected by
    the caller using per_label slopes (tuner.* labels have no components dict)."""
    proposer_content_keys = {
        "interpretation_json",
        "candidates_markdown",
        "previous_failures",
        "prior_stage_outputs",
        "vocab_block",
    }
    bloating = [
        (k, v["growth_pct"]) for k, v in component_growth.items() if v["verdict"] == "bloating"
    ]
    bloating.sort(key=lambda kv: -kv[1])
    top3 = {k for k, _ in bloating[:3]}
    if top3 & proposer_content_keys:
        return "Confirmed Proposer Hypothesis"
    return "Pivot Required — Other"


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _fmt_int(n: float | int) -> str:
    return f"{int(n):,}"


def _fmt_usd(d: float) -> str:
    return f"${d:,.2f}"


def render_baseline_report(
    aggs: dict[int, IterAgg],
    label_slopes: dict[str, dict[str, float]],
    bloats: list[BloatAlert],
    explosions: list[ContextExplosionAlert],
    rate_prompt: float,
    rate_completion: float,
    bloat_usd_threshold: float,
    context_prompt_threshold: int,
    workspace: Path,
    run_id: str,
) -> str:
    iters_sorted = sorted(aggs)
    if not iters_sorted:
        return "# Token baseline\n\n_No data._\n"
    cum_usd = 0.0
    lines = [
        "# V12 Token Baseline Report",
        "",
        f"**Workspace**: `{workspace}`  ",
        f"**run_id**: `{run_id}`  ",
        f"**Iters captured**: {iters_sorted[0]}-{iters_sorted[-1]} ({len(iters_sorted)} total)  ",
        f"**USD rates**: ${rate_prompt:.2f}/1M prompt + ${rate_completion:.2f}/1M completion (placeholder gpt-5.4)  ",
        f"**[BLOAT_ALERT] threshold**: {_fmt_usd(bloat_usd_threshold)}/iter (post-dehydration North Star)  ",
        f"**[CONTEXT_EXPLOSION] threshold**: {_fmt_int(context_prompt_threshold)} prompt tokens/call  ",
        "",
        "---",
        "",
        "## 1. Per-iteration totals (Happy-Path vs Recovery + USD)",
        "",
        "| iter | calls | prompt | compl | total_tok | happy USD | recovery USD | total USD | cum USD | alerts |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    bloat_iters = {b.iter for b in bloats}
    explosion_iters = defaultdict(list)
    for e in explosions:
        explosion_iters[e.iter].append(e)
    for it in iters_sorted:
        agg = aggs[it]
        total = agg.total
        happy_usd = agg.happy.usd(rate_prompt, rate_completion)
        recov_usd = agg.recovery.usd(rate_prompt, rate_completion)
        tot_usd = happy_usd + recov_usd
        cum_usd += tot_usd
        flags = []
        if it in bloat_iters:
            flags.append("[BLOAT]")
        if it in explosion_iters:
            flags.append(f"[EXPLODE×{len(explosion_iters[it])}]")
        flag_str = " ".join(flags) if flags else "—"
        lines.append(
            f"| {it} | {total.n_calls} | {_fmt_int(total.prompt_tok)} | "
            f"{_fmt_int(total.completion_tok)} | {_fmt_int(total.total_tok or (total.prompt_tok + total.completion_tok))} | "
            f"{_fmt_usd(happy_usd)} | {_fmt_usd(recov_usd)} | "
            f"**{_fmt_usd(tot_usd)}** | {_fmt_usd(cum_usd)} | {flag_str} |"
        )
    lines += [
        "",
        f"**Cumulative USD across all observed iters**: {_fmt_usd(cum_usd)}",
        "",
        "---",
        "",
        "## 2. Per-label growth slopes (linear regression on observed iters)",
        "",
        "Slope is computed by least-squares linear fit on whatever iter points "
        "are present (so a crashed/missing iter does not break the calculation). "
        "Only labels with ≥2 observed iters are listed.",
        "",
        "| label | n_iters | tok slope (tok/iter) | tok R² | USD slope ($/iter) | USD R² |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for lbl in sorted(label_slopes, key=lambda k: -label_slopes[k]["tok_slope"]):
        s = label_slopes[lbl]
        if s["n_points"] < 2:
            continue
        lines.append(
            f"| `{lbl}` | {int(s['n_points'])} | "
            f"{s['tok_slope']:+,.0f} | {s['tok_r2']:.2f} | "
            f"{s['usd_slope']:+.4f} | {s['usd_r2']:.2f} |"
        )

    lines += ["", "---", "", "## 3. Alerts", ""]
    if bloats:
        lines.append(
            f"### [BLOAT_ALERT] — iters exceeding {_fmt_usd(bloat_usd_threshold)}/iter "
            f"({len(bloats)} of {len(iters_sorted)} iters)"
        )
        lines.append("")
        for b in bloats:
            mult = b.usd / bloat_usd_threshold
            lines.append(
                f"- iter **{b.iter}**: {_fmt_usd(b.usd)} ({mult:.1f}× the {_fmt_usd(bloat_usd_threshold)} ceiling)"
            )
        lines.append("")
    else:
        lines.append("### [BLOAT_ALERT]\n\n_None — no iter exceeded the threshold._\n")

    if explosions:
        lines.append(
            f"### [CONTEXT_EXPLOSION] — single calls exceeding {_fmt_int(context_prompt_threshold)} "
            f"prompt tokens ({len(explosions)} calls)"
        )
        lines.append("")
        lines.append("| iter | label | prompt tok | attempt |")
        lines.append("|---:|---|---:|---:|")
        for e in explosions:
            lines.append(f"| {e.iter} | `{e.label}` | {_fmt_int(e.prompt_tok)} | {e.attempt} |")
        lines.append("")
    else:
        lines.append(
            f"### [CONTEXT_EXPLOSION]\n\n_None — no single call exceeded {_fmt_int(context_prompt_threshold)} "
            f"prompt tokens._\n"
        )
    return "\n".join(lines) + "\n"


def render_top3_bloat_report(
    aggs: dict[int, IterAgg],
    component_growth: dict[str, dict[str, Any]],
    verdict: str,
    workspace: Path,
    run_id: str,
) -> str:
    iters_sorted = sorted(aggs)
    if not iters_sorted:
        return "# Top-3 Bloat\n\n_No data._\n"
    iter1 = iters_sorted[0]
    iter1_total_prompt = aggs[iter1].total.prompt_tok or 1
    lines = [
        "# V12 Top-3 Component Bloat Report",
        "",
        f"## Verdict: **{verdict}**",
        "",
        f"**Workspace**: `{workspace}`  ",
        f"**run_id**: `{run_id}`  ",
        f"**Iters analyzed**: {iter1}-{iters_sorted[-1]}  ",
        "",
        "---",
        "",
        "## 1. Top-3 component bloat per iter (proposer.* rows)",
        "",
        "Components are summed across all `proposer.*` rows in each iter. "
        "Only iters with proposer rows appear here.",
        "",
        "| iter | total prompt tok | top-1 component | top-2 component | top-3 component | top-3 share of total chars |",
        "|---:|---:|---|---|---|---:|",
    ]
    top3 = top3_bloat_per_iter(aggs)
    for it in iters_sorted:
        agg = aggs[it]
        if not agg.proposer_components_chars:
            continue
        total_proposer_chars = sum(agg.proposer_components_chars.values()) or 1
        cells: list[str] = []
        top3_chars_sum = 0
        for k, c in top3[it]:
            top3_chars_sum += c
            cells.append(f"`{k}`: {_fmt_int(c)}")
        while len(cells) < 3:
            cells.append("—")
        share = 100.0 * top3_chars_sum / total_proposer_chars
        lines.append(
            f"| {it} | {_fmt_int(agg.total.prompt_tok)} | "
            f"{cells[0]} | {cells[1]} | {cells[2]} | {share:.1f}% |"
        )

    lines += [
        "",
        "---",
        "",
        f"## 2. Aggregate component growth (iter {iter1} → iter {iters_sorted[-1]})",
        "",
        "| Component | iter1 chars | iterN chars | growth (×) | verdict |",
        "|---|---:|---:|---:|---|",
    ]
    for key in PROPOSER_COMPONENT_KEYS:
        if key not in component_growth:
            continue
        g = component_growth[key]
        x = g["growth_x"]
        x_str = "∞" if math.isinf(x) else f"{x:.2f}×"
        verdict_label = {
            "bloating": "**bloating**",
            "bounded": "bounded",
            "shrinking": "shrinking",
        }[g["verdict"]]
        lines.append(
            f"| `{key}` | {_fmt_int(g['iter1_chars'])} | "
            f"{_fmt_int(g['iterN_chars'])} | {x_str} | {verdict_label} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 3. Sanity floor check (audit doc §1.9.3)",
        "",
    ]
    iterN_total_prompt = aggs[iters_sorted[-1]].total.prompt_tok
    growth_ratio = iterN_total_prompt / max(iter1_total_prompt, 1)
    if growth_ratio < 1.5:
        lines.append(
            f"⚠️ **Sanity Floor tripped**: iter {iters_sorted[-1]} prompt-token total is "
            f"{growth_ratio:.2f}× iter {iter1} (< 1.5×). Per §1.9.3, even though the verdict "
            f"is '{verdict}', the absolute growth is small. Phase 2 may be deferred — "
            f"document the decision and revisit at iter 15."
        )
    else:
        lines.append(
            f"Growth ratio iter{iters_sorted[-1]} / iter{iter1} = **{growth_ratio:.2f}×** "
            f"≥ 1.5× sanity floor. Phase 2 is justified by raw cost growth."
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_CLI_DESCRIPTION = "Token-usage baseline + top-3 bloat report builder."


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    p.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Workspace directory containing token_usage.jsonl.",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write the two markdown reports.",
    )
    p.add_argument(
        "--baseline-name", default="v12_token_baseline.md", help="Filename for the baseline report."
    )
    p.add_argument(
        "--top3-name", default="v12_top3_bloat.md", help="Filename for the top-3 bloat report."
    )
    p.add_argument(
        "--rate-prompt",
        type=float,
        default=DEFAULT_RATE_PROMPT,
        help=f"USD per 1M prompt tokens (default {DEFAULT_RATE_PROMPT}).",
    )
    p.add_argument(
        "--rate-completion",
        type=float,
        default=DEFAULT_RATE_COMPLETION,
        help=f"USD per 1M completion tokens (default {DEFAULT_RATE_COMPLETION}).",
    )
    p.add_argument(
        "--bloat-usd-threshold",
        type=float,
        default=DEFAULT_BLOAT_USD_PER_ITER,
        help=f"USD/iter threshold for [BLOAT_ALERT] (default {DEFAULT_BLOAT_USD_PER_ITER}).",
    )
    p.add_argument(
        "--context-prompt-threshold",
        type=int,
        default=DEFAULT_CONTEXT_EXPLOSION_PROMPT_TOK,
        help=f"prompt-tokens/call threshold for [CONTEXT_EXPLOSION] "
        f"(default {DEFAULT_CONTEXT_EXPLOSION_PROMPT_TOK}).",
    )
    p.add_argument(
        "--skip-lint",
        action="store_true",
        help="Skip the JSONL pre-flight lint (use only for testing).",
    )
    args = p.parse_args(argv)
    if args.output_dir is None:
        args.output_dir = require_checkout(REPO_ROOT) / "reports"
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    jsonl = args.workspace / "token_usage.jsonl"
    if not jsonl.exists():
        print(f"[ERROR] token_usage.jsonl not found at {jsonl}", file=sys.stderr)
        return 1

    if not args.skip_lint:
        errors, warnings = lint_jsonl(jsonl)
        for w in warnings:
            print(w, file=sys.stderr)
        if errors:
            for e in errors:
                print(e, file=sys.stderr)
            print(
                f"[FAIL] AUDIT LOG CORRUPTION DETECTED in {jsonl}: "
                f"{len(errors)} error(s). Refusing to publish a report from a "
                f"corrupted log.",
                file=sys.stderr,
            )
            return 1

    rows = load_rows(jsonl)
    if not rows:
        print(f"[ERROR] no usable rows in {jsonl}", file=sys.stderr)
        return 1
    run_id = rows[0].run_id

    aggs = aggregate_by_iter(rows)
    label_slopes = per_label_slopes(aggs, args.rate_prompt, args.rate_completion)
    bloats, explosions = detect_alerts(
        rows,
        aggs,
        args.rate_prompt,
        args.rate_completion,
        args.bloat_usd_threshold,
        args.context_prompt_threshold,
    )
    component_growth = aggregate_component_growth(aggs)
    verdict = compute_verdict(component_growth)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = args.output_dir / args.baseline_name
    top3_path = args.output_dir / args.top3_name
    baseline_path.write_text(
        render_baseline_report(
            aggs,
            label_slopes,
            bloats,
            explosions,
            args.rate_prompt,
            args.rate_completion,
            args.bloat_usd_threshold,
            args.context_prompt_threshold,
            args.workspace,
            run_id,
        )
    )
    top3_path.write_text(
        render_top3_bloat_report(
            aggs,
            component_growth,
            verdict,
            args.workspace,
            run_id,
        )
    )
    print(f"[OK] wrote {baseline_path}")
    print(f"[OK] wrote {top3_path}")
    print(f"     verdict: {verdict}")
    print(f"     iters: {min(aggs)}-{max(aggs)} ({len(aggs)} total)")
    print(f"     [BLOAT_ALERT]: {len(bloats)} iter(s) over {_fmt_usd(args.bloat_usd_threshold)}")
    print(
        f"     [CONTEXT_EXPLOSION]: {len(explosions)} call(s) over "
        f"{_fmt_int(args.context_prompt_threshold)} tok"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
