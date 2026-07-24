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

DEFAULT_SUMMARY_DIR = Path("/workspace/DATA/SIDERIUS_DATA/tidmad_official_banded")
DEFAULT_OUT_DIR = Path("/workspace/REPO/SIDERIUS/reference_data/official_paper_result")

MODEL_ORDER = ["fcnet", "punet", "rnn", "transformer"]
LOG_BASE = 5.27
RAW_FLOOR = 1.0007
GT_CEILING = 10.1134


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--summary-dir", type=Path, default=DEFAULT_SUMMARY_DIR)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
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


def render_per_model(summary: dict, out_path: Path) -> None:
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
    lines.append(f"(log base {LOG_BASE}; raw-baseline floor = {RAW_FLOOR}, "
                 f"ground-truth ceiling = {GT_CEILING})")
    lines.append("")
    lines.append("Definition (from `execute_tools/scoring_utils.py` §3):")
    lines.append("")
    lines.append("```")
    lines.append(f"denoising_score = log_{LOG_BASE}( Σ_(f,i) per_segment[f,i] / Σ_f |S_f| )")
    lines.append("```")
    lines.append("")
    lines.append("Grand mean over every sampled segment across every sampled file, "
                 "then log. **Per-band or per-subset aggregates are NOT reported** — "
                 "they are not comparable to this scalar and averaging them is not a "
                 "valid substitute (see §3 for the three excluded patterns).")
    lines.append("")
    lines.append("## Run configuration")
    lines.append("")
    lines.append(f"- Full scope: **{summary['full_scope']}** (files {summary['file_indices']})")
    lines.append(f"- Segment size: {summary['seg_size']:,} samples")
    lines.append(f"- Batch size: {summary['batch_size']}")
    lines.append(f"- Device: `{summary['device']}`")
    lines.append(f"- s_max: {summary['s_max']:.6f} (canonical `segment_anchors.json`)")
    lines.append(f"- Inference wall time: {sum(inf_sec.values()) / 60.0:.1f} min "
                 f"({sum(inf_sec.values()):.0f} s)")
    lines.append(f"- Computed at: {summary['computed_at']}")
    lines.append("")
    lines.append("## Per-file breakdown")
    lines.append("")
    lines.append("`linear` = `file_vector_linear[f]` = `mean_i(per_segment[f,i])` "
                 "(200 segments/file). `log` = `log_5.27(linear)`. These are the atomic "
                 "diagnostic values — not aggregated in any way.")
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
    lines.append("Source summary JSON: "
                 f"`{Path(summary.get('data_dir', ''))}` (raw inputs), "
                 f"`tidmad_official_{key}_banded_score.json` (this run's outputs).")
    lines.append("")
    out_path.write_text("\n".join(lines))


def render_readme(summaries: dict[str, dict | None], out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# TIDMAD Official Paper-Model Denoising Scores")
    lines.append("")
    lines.append("Denoising scores for the official band-split TIDMAD paper "
                 "checkpoints, evaluated with the SIDERIUS `score_vector` pipeline "
                 "on the canonical anchor map.")
    lines.append("")
    lines.append("## Aggregation")
    lines.append("")
    lines.append("Every headline number below is the CANONICAL `denoising_score`:")
    lines.append("")
    lines.append("```")
    lines.append(f"denoising_score = log_{LOG_BASE}( Σ_(f,i) per_segment[f,i] / Σ_f |S_f| )")
    lines.append("```")
    lines.append("")
    lines.append("Grand mean over every sampled segment across every sampled file, "
                 "then log. See `execute_tools/scoring_utils.py` module docstring §3 "
                 "for the full contract and the three aggregation patterns that MUST "
                 "NOT be substituted.")
    lines.append("")
    lines.append("## Ruler")
    lines.append("")
    lines.append(f"- Raw baseline (no denoising): **{RAW_FLOOR}** — floor")
    lines.append(f"- Ground-truth ceiling (perfect denoiser): **{GT_CEILING}**")
    lines.append("")
    lines.append("All scores are on the same log_5.27 scale, using the global s_max "
                 "(295715680.14) from the committed `reference_data/segment_anchors.json`.")
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
    lines.append("*Wavenet is intentionally excluded* (per the request that spawned "
                 "this evaluation); the paper's official wavenet is a single generalist "
                 "checkpoint scored separately by `scripts/score_tidmad_official_wavenet.py`.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Model | denoising_score | vs raw floor | vs GT ceiling | Details |")
    lines.append("|:------|----------------:|-------------:|--------------:|:--------|")
    for key in MODEL_ORDER:
        s = summaries.get(key)
        if s is None:
            lines.append(f"| {key} | *pending* | — | — | *pending* |")
            continue
        sc = s.get("denoising_score")
        vs_raw = sc - RAW_FLOOR if sc is not None else None
        vs_gt = sc - GT_CEILING if sc is not None else None
        lines.append(
            f"| {key} | **{fmt(sc, 4)}** | "
            f"{fmt(vs_raw, 4)} | {fmt(vs_gt, 4)} | "
            f"[`{key}.md`]({key}.md) |"
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

    for key, s in summaries.items():
        if s is None:
            print(f"skip {key}: no summary JSON yet")
            continue
        out = args.out_dir / f"{key}.md"
        render_per_model(s, out)
        print(f"wrote {out}  (denoising_score={s.get('denoising_score')})")

    readme = args.out_dir / "README.md"
    render_readme(summaries, readme)
    print(f"wrote {readme}")


if __name__ == "__main__":
    main()
