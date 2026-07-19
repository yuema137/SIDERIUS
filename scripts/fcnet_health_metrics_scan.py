"""Reproduce report §2 with all per-file production HealthGate metrics.

The comparison is the official split-FCNet output versus the collapsed
paper-spec WaveNet baseline used by ``reports/health_metrics_scan.md``.
Metric formulas come from the production HealthCheck classes.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

from execute_tools.data_paths import TIDMAD_DATA_DIR
from execute_tools.health_checks._peek import peek_int8_at_channel
from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.output_diversity import OutputDiversityCheck
from execute_tools.health_checks.output_std import OutputStdCheck
from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
from execute_tools.health_checks.schemas import HealthCheckContext
from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck

NUM_FILES = 20
MV_PER_LSB = 40.0 / 128.0


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fcnet-dir",
        type=Path,
        default=Path("/home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/fcnet/full_20_files"),
    )
    parser.add_argument(
        "--collapsed-dir",
        type=Path,
        default=Path(
            "/home/klz/Data/SIDEREIS_DATA/wavenet/diagnostic_baseline_pre_v17_baseline_trial"
        ),
    )
    parser.add_argument("--target-dir", type=Path, default=Path(TIDMAD_DATA_DIR))
    return parser.parse_args()


def _paths(directory: Path, model: str, exp_id: str | None = None) -> dict[int, str]:
    if exp_id is None:
        pattern = f"abra_validation_denoised_{model}_{{index:04d}}.h5"
    else:
        pattern = (
            f"abra_validation_denoised_{model}_baseline_{model}_baseline_{model}_"
            f"{exp_id}_{{index:04d}}.h5"
        )
    paths = {i: str(directory / pattern.format(index=i)) for i in range(NUM_FILES)}
    missing = [path for path in paths.values() if not Path(path).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing {len(missing)} input file(s): {missing}")
    return paths


def _blocking_values(result: object) -> dict[int, float]:
    metrics = result.metrics  # type: ignore[attr-defined]
    return {int(row["file_index"]): float(row["metric_value"]) for row in metrics["per_file"]}


def _scan(paths: dict[int, str], target_dir: Path) -> dict[str, dict[int, float]]:
    ctx = HealthCheckContext(
        model_name="reference_scan",
        run_name="health_metrics_scan",
        round_index=0,
        denoised_paths=paths,
        target_path_fn=lambda i: str(target_dir / f"abra_validation_{i:04d}.h5"),
    )
    files = list(range(NUM_FILES))
    # Section 2 historically uses one million samples for every displayed
    # column. Production blocking gates use 100k; this report deliberately
    # keeps its original 1M comparison window while adding recording metrics.
    common = {"peek_samples": 1_000_000, "peek_file_indices": files, "aggregation": "any_pass"}
    diversity = OutputDiversityCheck().run(ctx, {**common, "min_unique_int8_values": 25})
    output_std = OutputStdCheck().run(ctx, {**common, "min_std_mv": 1.0})
    amplitude = AmplitudeCollapseCheck().run(ctx, {**common, "collapse_threshold": 0.95})
    pearson = PearsonDispersionCheck().run(ctx, {"peek_samples": 1_000_000})
    spectral = SpectralPeakRatioCheck().run(ctx, {"peek_samples": 1_000_000})
    return {
        "unique": _blocking_values(diversity),
        "std_mv": _blocking_values(output_std),
        "mode_fraction": _blocking_values(amplitude),
        "pearson": {int(k): float(v) for k, v in pearson.metrics["pearson_per_file"].items()},
        "spectral_peak_ratio": {
            int(k): float(v) for k, v in spectral.metrics["ratio_per_file"].items()
        },
    }


def _fmt(value: float) -> str:
    return f"{value:.4f}" if math.isfinite(value) else "invalid"


def render(fcnet_dir: Path, collapsed_dir: Path, target_dir: Path) -> str:
    """Return the existing §2 comparison table with spectral ratios added."""
    fcnet = _scan(_paths(fcnet_dir, "fcnet"), target_dir)
    collapsed = _scan(_paths(collapsed_dir, "wavenet", "1784177030"), target_dir)
    lines = [
        "| File | Target std (mV) | FCNet unique | FCNet std (mV) | FCNet mode % | FCNet Pearson | FCNet spectral ratio | Collapsed unique | Collapsed std (mV) | Collapsed mode % | Collapsed Pearson | Collapsed spectral ratio |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i in range(NUM_FILES):
        target = peek_int8_at_channel(
            str(target_dir / f"abra_validation_{i:04d}.h5"), "channel0002", 1_000_000
        )
        target_std = float(np.std(target.astype(np.float64)) * MV_PER_LSB)
        lines.append(
            f"| {i} | {target_std:.4f} | {int(fcnet['unique'][i])} | "
            f"{fcnet['std_mv'][i]:.4f} | {100 * fcnet['mode_fraction'][i]:.2f} | "
            f"{fcnet['pearson'][i]:+.4f} | {_fmt(fcnet['spectral_peak_ratio'][i])} | "
            f"{int(collapsed['unique'][i])} | {collapsed['std_mv'][i]:.4f} | "
            f"{100 * collapsed['mode_fraction'][i]:.2f} | {collapsed['pearson'][i]:+.4f} | "
            f"{_fmt(collapsed['spectral_peak_ratio'][i])} |"
        )
    return "\n".join(lines)


def main() -> None:
    args = _args()
    print(render(args.fcnet_dir, args.collapsed_dir, args.target_dir))


if __name__ == "__main__":
    main()
