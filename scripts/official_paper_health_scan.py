"""Per-file HealthGate metrics for the official TIDMAD paper checkpoints.

Answers one question for any paper baseline: *does this model collapse, and
where?* The denoising score alone cannot say — a collapsed model can score
well by a PSD artifact (the class-127 phantom, `5.5763`), which is exactly
why the collapse-detection framework exists.

Metric formulas come from the production ``HealthCheck`` classes, so a number
here means the same thing it means inside a chain. The peek window is
1,000,000 samples to match the reference table in
``docs/design/paper_and_collapse_reference_baselines.md`` §3; production
blocking gates peek 100,000. Nothing is recomputed locally — the checks are
imported, not reimplemented.

Model-agnostic by construction: the model name, the denoised directory, and
the target directory are inputs. Missing per-file outputs are reported and
skipped rather than faked, because a partial scan that hides its gaps is
worse than no scan.

Usage::

    python scripts/official_paper_health_scan.py \\
        --model punet \\
        --denoised-dir /path/to/punet/full_20_files \\
        --json-out reference_data/official_paper_result/punet_health.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from execute_tools.data_paths import TIDMAD_DATA_DIR  # noqa: E402
from execute_tools.health_checks._peek import peek_int8_at_channel  # noqa: E402
from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck  # noqa: E402
from execute_tools.health_checks.output_diversity import OutputDiversityCheck  # noqa: E402
from execute_tools.health_checks.output_std import OutputStdCheck  # noqa: E402
from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck  # noqa: E402
from execute_tools.health_checks.schemas import HealthCheckContext  # noqa: E402
from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck  # noqa: E402

#: Reference-table peek window (§3). Production blocking gates use 100_000.
PEEK_SAMPLES = 1_000_000
MV_PER_LSB = 40.0 / 128.0
NUM_FILES = 20

#: Production thresholds, from ``configs/health_checks.yaml``. Reproduced as
#: literals so the scan reports pass/fail on the same line the chain uses;
#: they are recorded in the output so a later threshold change is visible.
MIN_UNIQUE_INT8 = 25
MIN_STD_MV = 1.0
COLLAPSE_THRESHOLD = 0.95

#: Band → checkpoint, from the paper's ``train.py::ifile_checkpoint``.
BANDS = {
    (0, 1, 2, 3): "0_4",
    (4, 5, 6, 7, 8, 9): "4_10",
    (10, 11, 12, 13, 14): "10_15",
    (15, 16, 17, 18, 19): "15_20",
}


def band_of(index: int) -> str:
    for files, checkpoint in BANDS.items():
        if index in files:
            return checkpoint
    return "?"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Model key, e.g. punet / rnn / transformer")
    parser.add_argument(
        "--denoised-dir",
        type=Path,
        required=True,
        help="Directory holding abra_validation_denoised_{model}_{i:04d}.h5 (machine-specific).",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path(TIDMAD_DATA_DIR),
        help="Directory holding abra_validation_{i:04d}.h5 ground-truth files.",
    )
    parser.add_argument(
        "--pattern",
        default="abra_validation_denoised_{model}_{index:04d}.h5",
        help="Denoised filename pattern; {model} and {index} are substituted.",
    )
    parser.add_argument("--peek-samples", type=int, default=PEEK_SAMPLES)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Scan the files that exist instead of failing when some are absent.",
    )
    return parser.parse_args()


def resolve_paths(
    directory: Path, model: str, pattern: str, allow_partial: bool
) -> tuple[dict[int, str], list[int]]:
    """Return ``({index: path}, missing_indices)``.

    Absence is data, not an error to paper over: a partially-inferred model
    must be reported as partial so no reader mistakes 18 files for 20.
    """
    candidates = {i: directory / pattern.format(model=model, index=i) for i in range(NUM_FILES)}
    present = {i: str(p) for i, p in candidates.items() if p.is_file()}
    missing = [i for i in range(NUM_FILES) if i not in present]
    if missing and not allow_partial:
        raise FileNotFoundError(
            f"{len(missing)} of {NUM_FILES} denoised files absent for '{model}' "
            f"(indices {missing}). Re-run inference or pass --allow-partial."
        )
    if not present:
        raise FileNotFoundError(f"No denoised files matched {pattern!r} under {directory}")
    return present, missing


def blocking_per_file(result: object) -> dict[int, float]:
    metrics = result.metrics  # type: ignore[attr-defined]
    return {int(row["file_index"]): float(row["metric_value"]) for row in metrics["per_file"]}


def scan(paths: dict[int, str], target_dir: Path, peek_samples: int) -> dict[str, dict[int, float]]:
    ctx = HealthCheckContext(
        model_name="official_paper_scan",
        run_name="official_paper_health_scan",
        round_index=0,
        denoised_paths=paths,
        target_path_fn=lambda i: str(target_dir / f"abra_validation_{i:04d}.h5"),
    )
    files = sorted(paths)
    common = {
        "peek_samples": peek_samples,
        "peek_file_indices": files,
        "aggregation": "any_pass",
    }
    diversity = OutputDiversityCheck().run(
        ctx, {**common, "min_unique_int8_values": MIN_UNIQUE_INT8}
    )
    output_std = OutputStdCheck().run(ctx, {**common, "min_std_mv": MIN_STD_MV})
    amplitude = AmplitudeCollapseCheck().run(
        ctx, {**common, "collapse_threshold": COLLAPSE_THRESHOLD}
    )
    pearson = PearsonDispersionCheck().run(ctx, {"peek_samples": peek_samples})
    spectral = SpectralPeakRatioCheck().run(ctx, {"peek_samples": peek_samples})
    return {
        "unique_int8": blocking_per_file(diversity),
        "std_mv": blocking_per_file(output_std),
        "mode_fraction": blocking_per_file(amplitude),
        "pearson": {int(k): float(v) for k, v in pearson.metrics["pearson_per_file"].items()},
        "spectral_peak_ratio": {
            int(k): float(v) for k, v in spectral.metrics["ratio_per_file"].items()
        },
    }


def target_std_mv(target_dir: Path, index: int, peek_samples: int) -> float:
    values = peek_int8_at_channel(
        str(target_dir / f"abra_validation_{index:04d}.h5"), "channel0002", peek_samples
    )
    return float(np.std(values.astype(np.float64)) * MV_PER_LSB)


def build_report(args: argparse.Namespace) -> dict:
    paths, missing = resolve_paths(args.denoised_dir, args.model, args.pattern, args.allow_partial)
    metrics = scan(paths, args.target_dir, args.peek_samples)

    per_file = []
    for i in sorted(paths):
        unique = metrics["unique_int8"][i]
        std = metrics["std_mv"][i]
        mode = metrics["mode_fraction"][i]
        per_file.append(
            {
                "file_index": i,
                "band_checkpoint": band_of(i),
                "target_std_mv": target_std_mv(args.target_dir, i, args.peek_samples),
                "unique_int8": int(unique),
                "std_mv": std,
                "mode_fraction": mode,
                "pearson": metrics["pearson"].get(i, float("nan")),
                "spectral_peak_ratio": metrics["spectral_peak_ratio"].get(i, float("nan")),
                "passes_diversity": bool(unique > MIN_UNIQUE_INT8),
                "passes_std": bool(std >= MIN_STD_MV),
                "passes_amplitude": bool(mode < COLLAPSE_THRESHOLD),
            }
        )

    scanned = len(per_file)
    verdicts = {
        "files_scanned": scanned,
        "files_missing": missing,
        "diversity_pass": sum(r["passes_diversity"] for r in per_file),
        "std_pass": sum(r["passes_std"] for r in per_file),
        "amplitude_pass": sum(r["passes_amplitude"] for r in per_file),
        "all_three_pass": sum(
            r["passes_diversity"] and r["passes_std"] and r["passes_amplitude"] for r in per_file
        ),
    }
    return {
        "model": args.model,
        "denoised_dir": str(args.denoised_dir),
        "target_dir": str(args.target_dir),
        "peek_samples": args.peek_samples,
        "thresholds": {
            "min_unique_int8_values": MIN_UNIQUE_INT8,
            "min_std_mv": MIN_STD_MV,
            "collapse_threshold": COLLAPSE_THRESHOLD,
        },
        "summary": verdicts,
        "per_file": per_file,
    }


def render_markdown(report: dict) -> str:
    s = report["summary"]
    n = s["files_scanned"]
    lines = [
        f"### HealthGate per-file metrics — {report['model']}",
        "",
        f"Peek window {report['peek_samples']:,} samples. Thresholds: "
        f"`unique_int8 > {MIN_UNIQUE_INT8}`, `std_mv >= {MIN_STD_MV}`, "
        f"`mode_fraction < {COLLAPSE_THRESHOLD}`.",
        "",
    ]
    if s["files_missing"]:
        lines += [
            f"> **Partial scan — {n} of {NUM_FILES} files.** Missing: "
            f"{', '.join(f'{i:04d}' for i in s['files_missing'])}. "
            "Absent outputs are not scored and not inferred.",
            "",
        ]
    lines += [
        f"| Pass count | diversity {s['diversity_pass']}/{n} | std {s['std_pass']}/{n} | "
        f"amplitude {s['amplitude_pass']}/{n} | **all three {s['all_three_pass']}/{n}** |",
        "|---|---|---|---|---|",
        "",
        "| file | ckpt | target std (mV) | unique_int8 | std (mV) | mode % | pearson | spectral | verdict |",
        "|---:|:---|---:|---:|---:|---:|---:|---:|:---|",
    ]
    for r in report["per_file"]:
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
            f"| {r['file_index']:04d} | `{r['band_checkpoint']}` | {r['target_std_mv']:.4f} | "
            f"{r['unique_int8']} | {r['std_mv']:.4f} | {100 * r['mode_fraction']:.2f} | "
            f"{pearson} | {spectral} | {'PASS' if ok else 'FAIL'} ({marks}) |"
        )
    lines += [
        "",
        "Verdict letters: upper case = passed that check (D diversity, S std, "
        "A amplitude), lower case = failed.",
    ]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    report = build_report(args)
    print(render_markdown(report))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"\nJSON written to {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
