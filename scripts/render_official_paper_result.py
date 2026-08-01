#!/usr/bin/env python
"""Render the official band-split TIDMAD paper-model results as Markdown.

Reads the per-model summary JSONs produced by
``scripts/score_tidmad_official_banded.py`` and writes:

    reference_data/official_paper_result/README.md   — overview + summary table
    reference_data/official_paper_result/{model}.md  — per-model per-file table

The headline number per model is the CANONICAL denoising_score defined in
``execute_tools/scoring_utils.py`` module docstring §3 — the linear grand
mean over every sampled segment, then log_5.27. Per-file rows show the
atomic ``file_vector_linear`` and its log_5.27; per-band aggregates are NOT
reported (see the aggregation-standard memory / scoring_utils §3 for why).

Reference anchors on the same global-s_max ruler:
  * raw baseline (no denoising)      = 1.0007
  * ground-truth ceiling             = 10.1134

Idempotent: re-run whenever a new summary JSON lands to rebuild the report.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# Both locations are server-specific and deliberately have NO defaults —
# pass them explicitly (portability audit 2026-07-24). Typical out-dir is
# the repo's reference_data/official_paper_result/.
MODEL_ORDER = ["fcnet", "punet", "rnn", "transformer"]
LOG_BASE = 5.27
RAW_FLOOR = 1.0007
GT_CEILING = 10.1134


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(__doc__ or "Render official paper results").splitlines()[0]
    )
    p.add_argument(
        "--summary-dir",
        type=Path,
        required=True,
        help="Directory with the banded-scoring summary JSONs (server-specific, required).",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Output directory for the rendered Markdown (server-specific, required).",
    )
    return p.parse_args()


def fmt(v: float | None, digits: int = 6, sci: bool = False) -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
        return "—"
    return f"{v:.{digits}e}" if sci else f"{v:.{digits}f}"


def load_summary(summary_dir: Path, model_key: str) -> dict | None:
    p = summary_dir / f"tidmad_official_{model_key}_banded_score.json"
    if not p.is_file():
        return None
    with p.open("r") as f:
        return json.load(f)


def load_health(out_dir: Path, model_key: str) -> dict | None:
    """Per-file HealthGate metrics from ``scripts/official_paper_health_scan.py``.

    Optional by design: a model may have a score before anyone has asked
    whether it collapsed, and the score page must still render.
    """
    p = out_dir / f"{model_key}_health.json"
    if not p.is_file():
        return None
    with p.open("r") as f:
        return json.load(f)


def health_headline(health: dict | None) -> str:
    """One cell for the README table — collapse is not visible in the score."""
    if health is None:
        return "*not scanned*"
    s = health["summary"]
    n = s["files_scanned"]
    partial = f", {len(s['files_missing'])} missing" if s["files_missing"] else ""
    return f"{s['all_three_pass']}/{n} healthy{partial}"


def render_health_section(health: dict) -> list[str]:
    """Per-file collapse metrics.

    Reported beside the score because the two can disagree: a collapsed
    model can score well through a PSD artifact, which is the whole reason
    the HealthGate framework exists.
    """
    s = health["summary"]
    t = health["thresholds"]
    n = s["files_scanned"]
    lines = [
        "",
        "## HealthGate per-file metrics",
        "",
        f"Peek window {health['peek_samples']:,} samples (the reference-table "
        "window; production blocking gates peek 100,000). Metric formulas are "
        "the production `HealthCheck` classes, imported rather than "
        "reimplemented, so a number here means what it means inside a chain.",
        "",
        f"Thresholds: `unique_int8 > {t['min_unique_int8_values']}`, "
        f"`std_mv >= {t['min_std_mv']}`, "
        f"`mode_fraction < {t['collapse_threshold']}`.",
        "",
        f"**Healthy on {s['all_three_pass']} of {n} files** "
        f"(diversity {s['diversity_pass']}/{n}, std {s['std_pass']}/{n}, "
        f"amplitude {s['amplitude_pass']}/{n}).",
        "",
    ]
    if s["files_missing"]:
        lines += [
            f"> **Partial scan — {n} of 20 files.** Missing denoised outputs: "
            + ", ".join(f"`{i:04d}`" for i in s["files_missing"])
            + ". Absent files are neither scored nor inferred.",
            "",
        ]
    lines += [
        "| file | ckpt | target std (mV) | unique_int8 | std (mV) | mode % | pearson | spectral | verdict |",
        "|---:|:---|---:|---:|---:|---:|---:|---:|:---|",
    ]
    for r in health["per_file"]:
        ok = r["passes_diversity"] and r["passes_std"] and r["passes_amplitude"]
        marks = "".join(
            [
                "D" if r["passes_diversity"] else "d",
                "S" if r["passes_std"] else "s",
                "A" if r["passes_amplitude"] else "a",
            ]
        )
        spectral = (
            f"{r['spectral_peak_ratio']:.4f}" if math.isfinite(r["spectral_peak_ratio"]) else "—"
        )
        pearson = f"{r['pearson']:+.4f}" if math.isfinite(r["pearson"]) else "—"
        lines.append(
            f"| {r['file_index']:04d} | `{r['band_checkpoint']}` | "
            f"{r['target_std_mv']:.4f} | {r['unique_int8']} | {r['std_mv']:.4f} | "
            f"{100 * r['mode_fraction']:.2f} | {pearson} | {spectral} | "
            f"{'PASS' if ok else 'FAIL'} ({marks}) |"
        )
    lines += [
        "",
        "Verdict letters: upper case passed that check (D diversity, S std, "
        "A amplitude), lower case failed.",
        "",
        "Regenerate:",
        "",
        "```bash",
        f"python scripts/official_paper_health_scan.py --model {health['model']} \\",
        f"  --denoised-dir {health['denoised_dir']} \\",
        f"  --json-out reference_data/official_paper_result/{health['model']}_health.json",
        "```",
    ]
    return lines


def render_health_only(health: dict, out_path: Path) -> None:
    """A model whose collapse metrics exist before its score does."""
    key = health["model"]
    lines = [
        f"# TIDMAD official band-split {key}",
        "",
        "## Headline",
        "",
        "**Canonical `denoising_score` = _pending_** — the banded scoring run "
        "has not produced a summary JSON for this model yet. The HealthGate "
        "metrics below stand on their own: they describe the denoised outputs "
        "that do exist, and they do not depend on the score.",
    ]
    lines += render_health_section(health)
    out_path.write_text("\n".join(lines))


def render_per_model(summary: dict, out_path: Path, health: dict | None = None) -> None:
    key = summary["model_key"]
    fv = summary["file_vector_linear"]
    fv_log = summary["file_vector_log"]
    ckpt_by_file = summary["checkpoint_by_file"]
    inf_sec = summary["inference_seconds"]
    score = summary.get("denoising_score")

    lines: list[str] = []
    lines.append(f"# {summary['model']}")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"**Canonical `denoising_score` = {fmt(score)}**  ")
    lines.append(
        f"(log base {LOG_BASE}; raw-baseline floor = {RAW_FLOOR}, "
        f"ground-truth ceiling = {GT_CEILING})"
    )
    lines.append("")
    lines.append("Definition (from `execute_tools/scoring_utils.py` §3):")
    lines.append("")
    lines.append("```")
    lines.append(f"denoising_score = log_{LOG_BASE}( Σ_(f,i) per_segment[f,i] / Σ_f |S_f| )")
    lines.append("```")
    lines.append("")
    lines.append(
        "Grand mean over every sampled segment across every sampled file, "
        "then log. **Per-band or per-subset aggregates are NOT reported** — "
        "they are not comparable to this scalar and averaging them is not a "
        "valid substitute (see §3 for the three excluded patterns)."
    )
    lines.append("")
    lines.append("## Run configuration")
    lines.append("")
    lines.append(f"- Full scope: **{summary['full_scope']}** (files {summary['file_indices']})")
    lines.append(f"- Segment size: {summary['seg_size']:,} samples")
    lines.append(f"- Batch size: {summary['batch_size']}")
    lines.append(f"- Device: `{summary['device']}`")
    lines.append(f"- s_max: {summary['s_max']:.6f} (canonical `segment_anchors.json`)")
    lines.append(
        f"- Inference wall time: {sum(inf_sec.values()) / 60.0:.1f} min "
        f"({sum(inf_sec.values()):.0f} s)"
    )
    lines.append(f"- Computed at: {summary['computed_at']}")
    lines.append("")
    lines.append("## Per-file breakdown")
    lines.append("")
    lines.append(
        "`linear` = `file_vector_linear[f]` = `mean_i(per_segment[f,i])` "
        "(200 segments/file). `log` = `log_5.27(linear)`. These are the atomic "
        "diagnostic values — not aggregated in any way."
    )
    lines.append("")
    lines.append("| file | checkpoint | inference (s) | linear | log_5.27 |")
    lines.append("|-----:|:-----------|--------------:|-------:|---------:|")
    for i in range(len(fv)):
        ckpt = ckpt_by_file.get(str(i), "—")
        secs = inf_sec.get(str(i), None)
        lines.append(
            f"| {i:04d} | `{ckpt}` | "
            f"{fmt(secs, 1) if secs is not None else '—'} | "
            f"{fmt(fv[i], 4, sci=True)} | "
            f"{fmt(fv_log[i], 4)} |"
        )
    lines.append("")
    lines.append("## Reproducibility")
    lines.append("")
    lines.append("```bash")
    lines.append(f"scripts/score_tidmad_official_banded.py --models {key} \\")
    lines.append("  --data-dir /workspace/DATA/TIDMAD_DATA \\")
    lines.append("  --work-dir /workspace/DATA/SIDERIUS_DATA/tidmad_official_banded")
    lines.append("```")
    lines.append("")
    lines.append(
        "Source summary JSON: "
        f"`{Path(summary.get('data_dir', ''))}` (raw inputs), "
        f"`tidmad_official_{key}_banded_score.json` (this run's outputs)."
    )
    lines.append("")
    if health is not None:
        lines.extend(render_health_section(health))
        lines.append("")
    out_path.write_text("\n".join(lines))


def render_readme(
    summaries: dict[str, dict | None],
    out_path: Path,
    healths: dict[str, dict | None] | None = None,
) -> None:
    healths = healths or {}
    lines: list[str] = []
    lines.append("# TIDMAD Official Paper-Model Denoising Scores")
    lines.append("")
    lines.append(
        "Denoising scores for the official band-split TIDMAD paper "
        "checkpoints, evaluated with the SIDERIUS `score_vector` pipeline "
        "on the canonical anchor map."
    )
    lines.append("")
    lines.append("## Aggregation")
    lines.append("")
    lines.append("Every headline number below is the CANONICAL `denoising_score`:")
    lines.append("")
    lines.append("```")
    lines.append(f"denoising_score = log_{LOG_BASE}( Σ_(f,i) per_segment[f,i] / Σ_f |S_f| )")
    lines.append("```")
    lines.append("")
    lines.append(
        "Grand mean over every sampled segment across every sampled file, "
        "then log. See `execute_tools/scoring_utils.py` module docstring §3 "
        "for the full contract and the three aggregation patterns that MUST "
        "NOT be substituted."
    )
    lines.append("")
    lines.append("## Ruler")
    lines.append("")
    lines.append(f"- Raw baseline (no denoising): **{RAW_FLOOR}** — floor")
    lines.append(f"- Ground-truth ceiling (perfect denoiser): **{GT_CEILING}**")
    lines.append("")
    lines.append(
        "All scores are on the same log_5.27 scale, using the global s_max "
        "(295715680.14) from the committed `reference_data/segment_anchors.json`."
    )
    lines.append("")
    lines.append("## Band-checkpoint mapping (from `train.py::ifile_checkpoint`)")
    lines.append("")
    lines.append("| Band | Frequency range | Validation files | Checkpoint |")
    lines.append("|:-----|:----------------|:-----------------|:-----------|")
    lines.append("| 0-3   | low          | 0, 1, 2, 3         | `{Model}_0_4.pth`   |")
    lines.append("| 4-9   | mid          | 4, 5, 6, 7, 8, 9   | `{Model}_4_10.pth`  |")
    lines.append("| 10-14 | mid-high     | 10, 11, 12, 13, 14 | `{Model}_10_15.pth` |")
    lines.append("| 15-19 | high         | 15, 16, 17, 18, 19 | `{Model}_15_20.pth` |")
    lines.append("")
    lines.append(
        "*Wavenet is intentionally excluded* (per the request that spawned "
        "this evaluation); the paper's official wavenet is a single generalist "
        "checkpoint scored separately by `scripts/score_tidmad_official_wavenet.py`."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Model | denoising_score | vs raw floor | vs GT ceiling | HealthGate | Details |"
    )
    lines.append(
        "|:------|----------------:|-------------:|--------------:|:-----------|:--------|"
    )
    for key in MODEL_ORDER:
        s = summaries.get(key)
        h = healths.get(key)
        health_cell = health_headline(h)
        details = f"[`{key}.md`]({key}.md)" if (s is not None or h is not None) else "*pending*"
        if s is None:
            lines.append(f"| {key} | *pending* | — | — | {health_cell} | {details} |")
            continue
        sc = s.get("denoising_score")
        vs_raw = sc - RAW_FLOOR if sc is not None else None
        vs_gt = sc - GT_CEILING if sc is not None else None
        lines.append(
            f"| {key} | **{fmt(sc, 4)}** | "
            f"{fmt(vs_raw, 4)} | {fmt(vs_gt, 4)} | {health_cell} | {details} |"
        )
    lines.append("")
    lines.append(
        "The HealthGate column counts files passing all three blocking checks "
        "(diversity, std, amplitude). It is reported beside the score because "
        "the two can disagree: a collapsed model can score well through a PSD "
        "artifact. A high score with a low health count is a warning, not a result."
    )
    lines.append("")
    lines.append("## Reproducibility")
    lines.append("")
    lines.append("Rebuild this whole directory (idempotent, reads the summary JSONs):")
    lines.append("")
    lines.append("```bash")
    lines.append("scripts/render_official_paper_result.py")
    lines.append("```")
    lines.append("")
    out_path.write_text("\n".join(lines))


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    summaries = {key: load_summary(args.summary_dir, key) for key in MODEL_ORDER}
    healths = {key: load_health(args.out_dir, key) for key in MODEL_ORDER}

    for key, s in summaries.items():
        h = healths.get(key)
        out = args.out_dir / f"{key}.md"
        if s is None:
            # Collapse metrics can precede the score; a model that has been
            # scanned but not scored still deserves a page, because "did it
            # collapse" is answerable without knowing how well it scored.
            #
            # Narrowed here rather than in a combined `s is None and h is
            # None` guard above: the combined form left `h` typed as
            # `dict | None` at the render call, which pyright rejects and a
            # reader has to re-derive.
            if h is None:
                print(f"skip {key}: no summary JSON and no health JSON yet")
                continue
            #
            # But never downgrade: the summary JSONs are server-specific, so
            # running this on a machine that lacks them must not overwrite a
            # page that already carries a real score with a health-only stub.
            if out.is_file() and "denoising_score` = _pending_" not in out.read_text():
                print(
                    f"skip {key}: {out.name} already holds a scored page and no "
                    "summary JSON is present here — refusing to overwrite it "
                    "with a health-only page. Run where the summary JSONs live."
                )
                continue
            render_health_only(h, out)
            print(f"wrote {out}  (health-only, {h['summary']['all_three_pass']} healthy files)")
            continue
        render_per_model(s, out, h)
        health_note = "" if h is None else f", health {h['summary']['all_three_pass']} healthy"
        print(f"wrote {out}  (denoising_score={s.get('denoising_score')}{health_note})")

    readme = args.out_dir / "README.md"
    if all(s is None for s in summaries.values()) and readme.is_file():
        # Same non-downgrade rule as the per-model pages: an environment with
        # no summary JSONs would rewrite every score as "pending".
        print(
            f"skip {readme.name}: no summary JSON for any model here — "
            "refusing to rewrite a populated summary table as all-pending."
        )
        return
    render_readme(summaries, readme, healths)
    print(f"wrote {readme}")


if __name__ == "__main__":
    main()
