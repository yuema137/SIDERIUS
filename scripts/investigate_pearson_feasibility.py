"""
Empirical: can per-file Pearson correlation (and companion output-diversity metrics)
distinguish collapse from real learning?

Cases:
  1. Real-learning reference — best round of the hyperparameter tuning chain
     (exp_id agent_012, round 7, HG passed, score 1.0506). Files 12-19 only —
     rounds 1-11 in the file_vector are None (files 0-11 were not scored in
     this run's formal set).
  2. Paper-spec baseline (collapsed) — exp_id 1784177030. All 20 files.
     diagnostic_summary reports status=failed_mode_collapse, scalar=-2.973.
  3. Synthetic collapse K=0, rate=0.001 — fabricated per-file, all 20 files.
  4. Synthetic collapse K=-1, rate=0.001 — fabricated per-file, all 20 files.

Metrics per (case, file):
  - pearson(CH1_denoised, CH2_target)   — alignment-sensitive (see caveat below)
  - mse(CH1_denoised, CH2_target)       — alignment-sensitive
  - output_std                          — alignment-independent
  - output_unique_int8_count            — alignment-independent
  - target_std (for context)            — always from ground-truth CH2

Alignment caveat: agent round 012's denoised files have 200M samples (20 of 200
segments) — if those aren't the first 20 segments of the file, Pearson vs. the
first 200M samples of ground-truth CH2 will read ~0 even for genuine learning.
When this happens, output_std / unique_count still discriminate reliably.

Sample size: 1_000_000 samples per file = 100 ms at 10 MS/s. Enough for stable
Pearson + std statistics; keeps per-file read + FFT time bounded.

This is a DIAGNOSTIC script. Do not commit.
"""

from pathlib import Path
from typing import Any, cast

import h5py
import numpy as np

GROUND_TRUTH_DIR = Path("/home/klz/Data/TIDMAD")
BASELINE_TRIAL_DIR = Path(
    "/home/klz/Data/SIDEREIS_DATA/wavenet/diagnostic_baseline_pre_v17_baseline_trial"
)
AGENT_DIR = Path("/home/klz/Data/SIDEREIS_DATA/wavenet/diagnostic_baseline_pre_v17/agent")

BASELINE_EXP_ID = "1784177030"  # complete paper-spec baseline (0000..0019)
AGENT_BEST_EXP_ID = "012"  # round 7 winner, files 12-19 only
AGENT_BEST_FILES = list(range(12, 20))  # 12..19 inclusive

# Case 5: original-paper FCNet reproduction (real learning, trained per file-range)
FCNET_DIR = Path("/home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/fcnet/official_10_15/inference")
FCNET_FILES = [10, 11, 12, 13, 14]  # 15 missing in reproduction dir

N_FILES = 20
SAMPLE_SIZE = 1_000_000  # 100 ms at 10 MS/s
MV_PER_LSB = 40.0 / 128.0  # int8 -> mV conversion factor


def _read_channel(path: Path, channel: str, n_samples: int) -> np.ndarray:
    """Read the first n_samples int8 values from timeseries/<channel>/timeseries.

    Uses ``cast(h5py.Dataset, ...)`` after the group walk to narrow the type
    (mirrors ``execute_tools/health_checks/_peek.py::peek_int8_at_channel``).
    """
    with h5py.File(path, "r") as handle:
        node: Any = handle
        for k in ("timeseries", channel, "timeseries"):
            node = node[k]
        dset = cast(h5py.Dataset, node)
        return np.asarray(dset[:n_samples], dtype=np.int8)


def load_target_ch2(file_index: int, n_samples: int) -> np.ndarray:
    """Ground-truth CH2 (DM injection reference) from the raw validation file."""
    path = GROUND_TRUTH_DIR / f"abra_validation_{file_index:04d}.h5"
    return _read_channel(path, "channel0002", n_samples)


def load_denoised_ch1(path: Path, n_samples: int) -> np.ndarray:
    """CH1 of a denoised file = model output."""
    return _read_channel(path, "channel0001", n_samples)


def baseline_path(file_index: int) -> Path:
    return BASELINE_TRIAL_DIR / (
        f"abra_validation_denoised_wavenet_baseline_wavenet_baseline_wavenet_"
        f"{BASELINE_EXP_ID}_{file_index:04d}.h5"
    )


def agent_best_path(file_index: int) -> Path:
    return AGENT_DIR / (
        f"abra_validation_denoised_wavenet_diagnostic_baseline_pre_v17_agent_"
        f"wavenet_diagnostic_baseline_pre_v17_agent_"
        f"{AGENT_BEST_EXP_ID}_{file_index:04d}.h5"
    )


def fcnet_path(file_index: int) -> Path:
    return FCNET_DIR / f"abra_validation_denoised_fcnet_{file_index:04d}.h5"


def synthesize_collapse(K: int, perturbation_rate: float, n_samples: int, rng) -> np.ndarray:
    out = np.full(n_samples, K, dtype=np.int8)
    if perturbation_rate > 0:
        n_p = int(n_samples * perturbation_rate)
        if n_p > 0:
            idx = rng.choice(n_samples, size=n_p, replace=False)
            out[idx] = np.clip(
                K + rng.integers(-2, 3, size=n_p),
                -128,
                127,
            ).astype(np.int8)
    return out


def compute_metrics(denoised_int8: np.ndarray, target_int8: np.ndarray) -> dict:
    """All metrics + a couple of intermediates for context."""
    denoised_mv = denoised_int8.astype(np.float64) * MV_PER_LSB
    target_mv = target_int8.astype(np.float64) * MV_PER_LSB

    output_std = float(np.std(denoised_mv))
    target_std = float(np.std(target_mv))
    unique_count = len(np.unique(denoised_int8))

    # Pearson: undefined if either std is 0; report as NaN.
    if output_std < 1e-12 or target_std < 1e-12:
        pearson = float("nan")
    else:
        # ``np.corrcoef(a, b)[0, 1]`` is numerically identical to
        # ``scipy.stats.pearsonr(a, b)[0]`` and has cleaner numpy stub typing.
        r = float(np.corrcoef(denoised_mv, target_mv)[0, 1])
        pearson = float(r) if np.isfinite(r) else float("nan")

    mse = float(np.mean((denoised_mv - target_mv) ** 2))

    return {
        "pearson": pearson,
        "mse_mv2": mse,
        "output_std_mv": output_std,
        "target_std_mv": target_std,
        "output_unique_int8_count": unique_count,
    }


def _fmt(x):
    if isinstance(x, float):
        if x != x:  # NaN
            return "  nan  "
        return f"{x:8.4f}"
    return f"{x:8d}"


def _print_row(file_i, m):
    print(
        f"  {file_i:2d}  "
        f"pearson={_fmt(m['pearson'])}  "
        f"mse={m['mse_mv2']:.3e}  "
        f"out_std={m['output_std_mv']:.3e}  "
        f"tgt_std={m['target_std_mv']:.3e}  "
        f"uniq={m['output_unique_int8_count']:4d}"
    )


def _stats(values):
    v = [x for x in values if isinstance(x, (int, float)) and (x == x)]
    if not v:
        return "n/a (all NaN)"
    return (
        f"min={min(v):+.4f}  max={max(v):+.4f}  "
        f"mean={float(np.mean(v)):+.4f}  median={float(np.median(v)):+.4f}"
    )


def main():
    print("=" * 90)
    print("PEARSON FEASIBILITY EXPERIMENT")
    print(f"  ground-truth CH2 dir: {GROUND_TRUTH_DIR}")
    print(f"  paper-spec baseline dir: {BASELINE_TRIAL_DIR}")
    print(f"  agent tuning dir: {AGENT_DIR}")
    print(f"  SAMPLE_SIZE: {SAMPLE_SIZE} ({SAMPLE_SIZE / 1e7 * 1000:.1f} ms at 10 MS/s)")
    print("=" * 90)

    rng = np.random.default_rng(42)

    # ----- Load targets ------------------------------------------------------
    print("\n--- Loading target CH2 (ground-truth DM reference) ---")
    targets = {}
    for i in range(N_FILES):
        try:
            tgt = load_target_ch2(i, SAMPLE_SIZE)
            targets[i] = tgt
            print(
                f"  file {i:2d}: len={len(tgt)}  std_mv={float(np.std(tgt.astype(np.float64) * MV_PER_LSB)):.3e}  min={int(tgt.min())}  max={int(tgt.max())}"
            )
        except Exception as e:
            print(f"  file {i:2d}: FAILED — {e}")

    # ----- Case 1: Real learning (agent round 012) --------------------------
    print("\n--- Case 1: Real learning — agent round 012 (score=1.0506, HG passed) ---")
    print("    (files 12-19 only; 0-11 have no denoised output in this run)")
    case1 = {}
    for i in AGENT_BEST_FILES:
        if i not in targets:
            continue
        path = agent_best_path(i)
        if not path.exists():
            print(f"  {i:2d}  MISSING: {path}")
            continue
        try:
            denoised = load_denoised_ch1(path, SAMPLE_SIZE)
            m = compute_metrics(denoised, targets[i])
            case1[i] = m
            _print_row(i, m)
        except Exception as e:
            print(f"  {i:2d}  FAILED — {e}")

    # ----- Case 2: Paper-spec baseline (collapsed) --------------------------
    print("\n--- Case 2: Paper-spec baseline exp_id 1784177030 (collapsed, all 20 files) ---")
    case2 = {}
    for i in range(N_FILES):
        if i not in targets:
            continue
        path = baseline_path(i)
        if not path.exists():
            print(f"  {i:2d}  MISSING: {path}")
            continue
        try:
            denoised = load_denoised_ch1(path, SAMPLE_SIZE)
            m = compute_metrics(denoised, targets[i])
            case2[i] = m
            _print_row(i, m)
        except Exception as e:
            print(f"  {i:2d}  FAILED — {e}")

    # ----- Case 3: Synthetic collapse K=0 -----------------------------------
    print("\n--- Case 3: Synthetic collapse K=0, rate=0.001 (all 20 files) ---")
    case3 = {}
    for i in range(N_FILES):
        if i not in targets:
            continue
        denoised = synthesize_collapse(K=0, perturbation_rate=0.001, n_samples=SAMPLE_SIZE, rng=rng)
        m = compute_metrics(denoised, targets[i])
        case3[i] = m
        _print_row(i, m)

    # ----- Case 4: Synthetic collapse K=-1 ----------------------------------
    print("\n--- Case 4: Synthetic collapse K=-1, rate=0.001 (all 20 files) ---")
    case4 = {}
    for i in range(N_FILES):
        if i not in targets:
            continue
        denoised = synthesize_collapse(
            K=-1, perturbation_rate=0.001, n_samples=SAMPLE_SIZE, rng=rng
        )
        m = compute_metrics(denoised, targets[i])
        case4[i] = m
        _print_row(i, m)

    # ----- Case 5: Original-paper FCNet reproduction ------------------------
    print(
        "\n--- Case 5: Original-paper FCNet reproduction (files 10-14; trained per file-range) ---"
    )
    case5 = {}
    for i in FCNET_FILES:
        if i not in targets:
            continue
        path = fcnet_path(i)
        if not path.exists():
            print(f"  {i:2d}  MISSING: {path}")
            continue
        try:
            denoised = load_denoised_ch1(path, SAMPLE_SIZE)
            m = compute_metrics(denoised, targets[i])
            case5[i] = m
            _print_row(i, m)
        except Exception as e:
            print(f"  {i:2d}  FAILED — {e}")

    # ----- Summary ----------------------------------------------------------
    print("\n" + "=" * 90)
    print("SUMMARY ANALYSIS")
    print("=" * 90)

    def _summ(name, r, key):
        print(f"  {name:<45s} {key:<25s} : {_stats([m[key] for m in r.values()])}")

    print("\n[Pearson correlation]")
    _summ("Case 1 agent_012 tuning-best  (files 12-19)", case1, "pearson")
    _summ("Case 2 paper-spec baseline    (files 0-19) ", case2, "pearson")
    _summ("Case 3 synth K=0 rate=0.001   (files 0-19) ", case3, "pearson")
    _summ("Case 4 synth K=-1 rate=0.001  (files 0-19) ", case4, "pearson")
    _summ("Case 5 FCNet paper repro      (files 10-14)", case5, "pearson")

    print("\n[output_std_mv — alignment-independent]")
    _summ("Case 1 agent_012 tuning-best  (files 12-19)", case1, "output_std_mv")
    _summ("Case 2 paper-spec baseline    (files 0-19) ", case2, "output_std_mv")
    _summ("Case 3 synth K=0 rate=0.001   (files 0-19) ", case3, "output_std_mv")
    _summ("Case 4 synth K=-1 rate=0.001  (files 0-19) ", case4, "output_std_mv")
    _summ("Case 5 FCNet paper repro      (files 10-14)", case5, "output_std_mv")

    print("\n[output_unique_int8_count — alignment-independent]")
    _summ("Case 1 agent_012 tuning-best  (files 12-19)", case1, "output_unique_int8_count")
    _summ("Case 2 paper-spec baseline    (files 0-19) ", case2, "output_unique_int8_count")
    _summ("Case 3 synth K=0 rate=0.001   (files 0-19) ", case3, "output_unique_int8_count")
    _summ("Case 4 synth K=-1 rate=0.001  (files 0-19) ", case4, "output_unique_int8_count")
    _summ("Case 5 FCNet paper repro      (files 10-14)", case5, "output_unique_int8_count")

    # ----- Files 0-3 spotlight (user concern) ------------------------------
    print("\n--- Files 0-3 spotlight (low-frequency-signal / low-SNR files) ---")
    print(f"  {'file':<6}{'target_std':<15}{'baseline(Case2)':<40}{'synth K=0(Case3)':<40}")
    for i in range(4):
        if i in targets:
            tgt_std = f"{float(np.std(targets[i].astype(np.float64) * MV_PER_LSB)):.3e}"
            c2 = f"pearson={_fmt(case2.get(i, {}).get('pearson'))} std={case2.get(i, {}).get('output_std_mv', float('nan')):.3e}  uniq={case2.get(i, {}).get('output_unique_int8_count', 0):3d}"
            c3 = f"pearson={_fmt(case3.get(i, {}).get('pearson'))} std={case3.get(i, {}).get('output_std_mv', float('nan')):.3e}  uniq={case3.get(i, {}).get('output_unique_int8_count', 0):3d}"
            print(f"  {i:<6}{tgt_std:<15}{c2:<40}{c3:<40}")

    # ----- Files 12-19 spotlight (only ones where Case 1 is available) -----
    print("\n--- Files 12-19 spotlight (agent-scored + high-signal files) ---")
    print(
        f"  {'file':<6}{'target_std':<15}{'agent_012(Case1)':<42}{'baseline(Case2)':<42}{'synth K=0(Case3)':<42}"
    )
    for i in AGENT_BEST_FILES:
        if i in targets:
            tgt_std = f"{float(np.std(targets[i].astype(np.float64) * MV_PER_LSB)):.3e}"

            def fmtcell(c, ii=i):  # default-arg locks the loop variable (B023)
                if ii not in c:
                    return "n/a".ljust(42)
                m = c[ii]
                return f"pearson={_fmt(m['pearson'])} std={m['output_std_mv']:.3e}  uniq={m['output_unique_int8_count']:3d}"

            print(
                f"  {i:<6}{tgt_std:<15}{fmtcell(case1):<42}{fmtcell(case2):<42}{fmtcell(case3):<42}"
            )

    # ----- Files 10-14 spotlight (FCNet paper reference vs baseline vs synth) --
    print("\n--- Files 10-14 spotlight (FCNet paper reference cross-check) ---")
    print(
        f"  {'file':<6}{'target_std':<15}{'FCNet(Case5)':<42}{'baseline(Case2)':<42}{'synth K=0(Case3)':<42}"
    )
    for i in FCNET_FILES:
        if i in targets:
            tgt_std = f"{float(np.std(targets[i].astype(np.float64) * MV_PER_LSB)):.3e}"

            def fmtcell(c, ii=i):
                if ii not in c:
                    return "n/a".ljust(42)
                m = c[ii]
                return f"pearson={_fmt(m['pearson'])} std={m['output_std_mv']:.3e}  uniq={m['output_unique_int8_count']:3d}"

            print(
                f"  {i:<6}{tgt_std:<15}{fmtcell(case5):<42}{fmtcell(case2):<42}{fmtcell(case3):<42}"
            )


if __name__ == "__main__":
    main()
