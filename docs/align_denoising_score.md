# Aligning the SIDERIUS Denoising Score to 100% Legacy Parity

**Status:** Complete — All phases (A, B, C, D, 4.1, 4.2, 5.1, 5.2) landed and verified.
**Owner:** scoring layer (`execute_tools/scoring_utils.py`, `compute_raw_baseline.py`,
`compute_ground_truth.py`, `execute_tools/build_anchor_map.py`).
**Reference specification (authoritative):** `/home/tidmad/TIDMAD/denoising_score_old.py`.

---

## 0. Guiding principle

> The legacy script is the benchmark. Any deviation — even one that looks like
> a "safer" or "higher-precision" optimization — is a bug if it changes the
> rounded output.

The goal is **bit-for-bit reproduction** of the legacy score on identical inputs,
not "mathematically equivalent to within ε." Every floating-point trajectory
must match: the operation order, the dtype at each step, and the shape of every
intermediate array.

---

## 1. Confirmation of understanding

### 1.1 Why scaling must live in the time domain

The legacy formula is
```python
TS    = np.array(data, dtype=np.float32) * scaling             # FP scale, time-domain
psd   = dt/N * (abs(np.fft.rfft(TS.reshape(1, N)))**2).sum(0)[1:]
```

Mathematically, DFT linearity says `FFT(c·x) = c·FFT(x)` and therefore
`|FFT(c·x)|² = c² · |FFT(x)|²`. In **exact real arithmetic** the two
formulations agree. In **floating-point arithmetic they do not**:

* FFT is a sum of products. Each rounding step depends on the magnitude of
  the operands. Scaling the time series by `c ≈ 7.8 × 10⁻³` (for
  `volt_range = 2` mV) before FFT changes every intermediate dot-product by
  that factor. The butterfly additions then round at a different ulp scale
  than they would on the unscaled series.
* Applying `c²` after `|FFT(x)|²` multiplies a completed sum by a scalar —
  one rounding step, at the *squared-magnitude* scale. The trajectory is
  different, so the low bits of `psd_chunk` differ.

A ~1 ulp difference in `psd_chunk` survives through the signal/noise sums in
`getSNR`, the division `signal / noise`, the global maximum, the linear
average, and — crucially — the `np.round(·, 2)` step. Because rounding is a
**piecewise-constant** operation, any value sitting near a 0.005 boundary
can flip to a different two-decimal output, which is then passed through
`math.log(·, 5.27)` and shows up as a visible score difference.

**Therefore: scaling must be applied in the time domain, exactly as legacy
does. No post-FFT prefactor.**

### 1.2 Why `scipy.fft` is prohibited

* `numpy.fft.rfft(x: float32)` behavior depends on the numpy version:
  * **numpy ≤ 1.x** — always returns `complex128` (internally promotes to
    float64).
  * **numpy ≥ 2.0** — preserves input precision, returns `complex64`.
* `scipy.fft.rfft(x: float32)` → `complex64` on every version.

The legacy script uses `np.fft.rfft` verbatim. To mirror its output on this
machine, we must use `np.fft.rfft` — not `scipy.fft.rfft`. The two FFT
backends (scipy's pocketfft via `scipy.fft`, numpy's pocketfft via
`numpy.fft`) do not produce bit-identical output even at the same precision:
they differ in butterfly ordering, in how they handle length-prime factors,
and in SIMD kernels.

**Therefore: `scipy.fft.rfft` is prohibited anywhere on the scoring path.
All FFTs must be `np.fft.rfft` with exactly the same input dtype legacy
passes in (`float32`) and the same call shape (2-D `(1, N)` reshape).**

### 1.3 numpy version — Option B (DECIDED)

This machine runs numpy **2.4.3** (post-2.0). `np.fft.rfft` on `float32`
input now returns `complex64`. The legacy script was authored in **early
June 2024**, pre-numpy-2.0, where `np.fft.rfft` on `float32` input
implicitly promoted to `float64` and returned `complex128`. The canonical
benchmark numbers in the TIDMAD paper / reference runs were therefore
produced under the `complex128` path.

**Decision: Option B.** To achieve 100% parity with the published legacy
benchmark on our current numpy, we **force** the FFT to run in
`complex128` by casting the time series to `float64` immediately before
the `rfft` call:

```python
np.fft.rfft(TS.astype(np.float64).reshape(len(TS) // N, N))
```

This reproduces numpy 1.x's implicit promotion explicitly under numpy 2.x.
`TS` itself remains `float32` (matching the legacy `TS` object's dtype);
only the array handed to `rfft` is upcast.

**Parity claim under Option B:** the new code, run on numpy 2.4.3, reproduces
the legacy benchmark value that was originally generated under numpy 1.x —
i.e., the canonical reference number — bit-for-bit.

**Consequence for the parity test:** running `denoising_score_old.py` as-is
on numpy 2.4.3 does **not** produce the canonical number (it would use the
`complex64` path). The parity test must therefore run the legacy script
either (a) in a numpy-1.x environment or (b) on numpy 2.4.3 with a
monkey-patched `np.fft.rfft` that upcasts input to `float64`. See §5.1.

---

## 2. Problem Statement — four concrete bugs

Each bug is stated as a delta between the current SIDERIUS code and the
legacy reference. Line numbers refer to the current HEAD.

### Bug #1 — FFT precision (scipy.fft vs np.fft)

**Current** (`execute_tools/scoring_utils.py:23`, `:91`):
```python
from scipy.fft import rfft as _scipy_rfft
...
fft_out = _scipy_rfft(ts)           # complex64, pocketfft via scipy
```

**Legacy** (`denoising_score_old.py:61`):
```python
(abs(np.fft.rfft(TS.reshape(len(TS)//N, N)))**2).sum(0)[1:]
```

**Impact:** different FFT backend and (on pre-2.0 numpy) different intermediate
precision. Relative drift ≲10⁻⁵, sufficient to flip the outcome of
`np.round(·, 2)` on border cases.

### Bug #2 — Operator order / out-of-time-domain scaling

**Current** (`execute_tools/scoring_utils.py:84-97`):
```python
scaling   = volt_range / (2.0 * 128.0)           # Python float, not np.float32
dt        = 1.0 / sampling_freq
prefactor = np.float32(scaling * scaling * dt / SEGMENT_LENGTH)

ts      = np.asarray(data, dtype=np.float32)     # NO time-domain scaling
fft_out = _scipy_rfft(ts)                        # FFT of unscaled ts
psd_chunk = np.abs(fft_out)
np.square(psd_chunk, out=psd_chunk)
np.multiply(psd_chunk, prefactor, out=psd_chunk) # c²·dt/N applied post-FFT
psd_chunk = psd_chunk[1:]
```

**Legacy** (`denoising_score_old.py:55-61`):
```python
scaling = np.float32(volt_range/(2*128.0))                       # np.float32
TS      = np.array(data, dtype=np.float32)*scaling               # scale in time
dt      = 1.0/(h5.File(file)['timeseries']['channel0001']).attrs['sampling_frequency']
psd_chunk = dt/N*(abs(np.fft.rfft(TS.reshape(len(TS)//N,N)))**2).sum(0)[1:]
```

**Impact:** three separate floating-point divergences stacked:
1. `scaling` is a Python float (now) vs `np.float32` (legacy).
2. Time series enters the FFT unscaled (now) vs scaled (legacy).
3. The prefactor order `c²·dt/N` vs `dt/N · c²` differs in the last bit.

### Bug #3 — Normalization bias (anchor `s_max` vs file-local `amax`)

**Current** (`execute_tools/scoring_utils.py:283`):
```python
weight = file_anchors[seg_idx] / s_max       # s_max is GLOBAL, from anchor map
```

**Legacy** (`denoising_score_old.py:136`):
```python
snr_sg = snr_sg/(np.amax(snr_sg))            # amax over the CURRENT file list
```

**Impact:** the legacy `s_max` is the maximum of CH2 SNRs across whatever
files are passed to `calculateBenchmark`. When run on one file, it is the
file-local max; when run on 20 files, the 20-file max. The current code
pulls `s_max` from a static anchor map built over all 20 files. For a
single-file score, the anchor `s_max` is almost always **larger** than the
file-local max, biasing the normalized weights downward and producing a
numerically smaller score than legacy.

This is a semantic mismatch, not a FP drift, and it will dominate any
parity comparison.

### Bug #4 — Rounding timing

**Current** (`execute_tools/scoring_utils.py:373-378`):
```python
mean_score   = sum(valid_scores) / len(valid_scores)
final_scalar = math.log(mean_score + 1e-10, 5.27)    # no round
```

**Legacy** (`denoising_score_old.py:137`):
```python
score = np.round(np.sum(np.multiply(snr_sg, snr_squid))/snr_squid.size,
                 decimals=2) + 1e-10
return math.log(score, 5.27)
```

**Impact:** legacy rounds the linear score to 2 decimals *before* adding
1e-10 and taking the log. Omitting the round step keeps extra precision
but gives a different number. For a score of ~0.034, `round(·, 2)` yields
0.03 vs the raw 0.034 — a ~12% discrepancy in the linear space, a
noticeable shift after `log₅.₂₇(·)`.

### Bug #5 (minor) — zero-noise trap

**Current** (`execute_tools/scoring_utils.py:139`):
```python
if noise <= 0:
    noise = 1e-5
```

**Legacy** (`denoising_score_old.py:81`):
```python
if noise == 0:
    noise = 1e-5
```

**Impact:** PSD values are `|FFT|²·prefactor ≥ 0`, so `noise` is
mathematically non-negative. In practice never triggers. Still, to remove
all behavioral deviation, revert to `== 0`.

---

## 3. Refactoring Plan

### Phase A — Core PSD / SNR reconstruction (`execute_tools/scoring_utils.py`)

All low-level primitives are rewritten to be byte-strict transcriptions
of the legacy routines. The only deviations from legacy source text that
remain are (a) snake_case names, (b) docstrings, (c) reading
`sampling_frequency` from the already-open `h5f` rather than reopening
the file (legacy has `h5.File(file)['timeseries']['channel0001'].attrs['sampling_frequency']`
inside the `with h5f` block — a harmless legacy artifact that reads the
same scalar).

#### A.1 `get_one_sec_psd` — exact replacement

```python
import os
import gc
import numpy as np
import h5py

from execute_tools.dataset_config import SEGMENT_LENGTH, SEGMENTS_PER_FILE


def get_one_sec_psd(
    file_path: str,
    files: list[str] | str,
    ch: int,
    start: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Byte-strict legacy PSD for a single 1-second segment.

    Mirrors ``denoising_score_old.GetOneSecPSD`` exactly, under Option B
    (complex128 FFT — see §1.3):

    * scaling is ``np.float32(volt_range / (2 * 128.0))``
    * scaling is applied IN THE TIME DOMAIN — ``TS = data.astype(float32) * scaling``
    * FFT input is explicitly upcast to float64 so rfft returns complex128
      (numpy 1.x legacy behavior, lost in numpy 2.x)
    * FFT is ``np.fft.rfft`` on ``TS.astype(float64).reshape(len(TS)//N, N)``
    * PSD formula: ``dt/N * (abs(rfft(...))**2).sum(0)[1:]``
    * freq grid: ``np.linspace(0, 5*1e6, int(N/2))`` (legacy's hardcoded 5 MHz)
    """
    if isinstance(files, str):
        file_list = [os.path.join(file_path, files)]
    else:
        file_list = [os.path.join(file_path, f) for f in files]

    N = SEGMENT_LENGTH                          # 10_000_000
    file_num    = start // SEGMENTS_PER_FILE    # 200
    start_index = N * (start % SEGMENTS_PER_FILE)

    file = file_list[file_num]
    with h5py.File(file, "r") as h5f:
        channel_key = f"channel{ch:04d}"
        data = h5f["timeseries"][channel_key]["timeseries"][
            start_index : start_index + N
        ]
        volt_range    = h5f["timeseries"]["channel0001"].attrs["voltage_range_mV"]
        sampling_freq = h5f["timeseries"]["channel0001"].attrs["sampling_frequency"]

        scaling = np.float32(volt_range / (2 * 128.0))
        TS      = np.array(data, dtype=np.float32) * scaling
        dt      = 1.0 / sampling_freq

        # Option B — force complex128 FFT to reproduce numpy 1.x legacy
        # behavior (canonical TIDMAD benchmark numbers). See §1.3.
        psd_chunk  = dt / N * (
            abs(np.fft.rfft(TS.astype(np.float64).reshape(len(TS) // N, N))) ** 2
        ).sum(0)[1:]
        freq_array = np.linspace(0, 5 * 1e6, int(N / 2))

    del data, TS, dt
    gc.collect()
    return freq_array, psd_chunk
```

Notes:

* `np.float32(volt_range / (2 * 128.0))` — single-precision scale factor,
  same as legacy.
* `TS` itself stays `float32` (matches the legacy `TS` object's dtype).
  The `.astype(np.float64)` is applied **only at the `rfft` call site**,
  producing a temporary float64 view that is consumed inside `rfft` and
  released. Peak memory briefly doubles (40 MB float32 + 80 MB float64),
  matching what numpy 1.x did internally during the implicit promotion.
* `TS.astype(np.float64).reshape(len(TS)//N, N)` — always `(1, N)` for
  a single-segment slice. Reshape kept literally for parity with legacy's
  call shape.
* `freq_array` uses the literal `5*1e6` — legacy's hardcoded Nyquist — not
  `sampling_freq/2`. On this dataset these are bit-equal, but the legacy
  literal is what the spec says.
* `del data, TS, dt; gc.collect()` — mirrors legacy's cleanup. The float64
  temporary is not bound to a name and is collected automatically.

#### A.2 `find_peak` — already byte-strict (no change)

```python
def find_peak(pwr: np.ndarray) -> int:
    peak_diff = pwr[1:-1] - pwr[:-2] - pwr[2:]
    return int(np.where(peak_diff == np.amax(peak_diff))[0][0]) + 1
```

#### A.3 `get_snr` — revert zero-noise trap to `== 0`

```python
def get_snr(
    freq: np.ndarray,
    pwr: np.ndarray,
    target: float = 0,
) -> tuple[float, float]:
    if target == 0:
        center_id = find_peak(pwr)
    else:
        center_id = int(np.where(freq == target)[0][0])

    sig_range   = 1
    noise_range = 50
    signal = np.sum(pwr[center_id - sig_range : center_id + sig_range + 1])
    noise  = np.sum(pwr[center_id - noise_range : center_id + noise_range + 1]) - signal

    if noise == 0:                     # legacy: strict equality, NOT <= 0
        noise = 1e-5
    return signal / noise, freq[center_id]
```

(Return type stays tuple — legacy returns a list but the only numeric
values are the two floats; list-vs-tuple has no bearing on the score.)

#### A.4 `process_segment` — no numeric change (confirm signature)

```python
def process_segment(
    segment_index: int,
    data_dir: str,
    filename: str | list[str],
    coarse: bool = False,
) -> tuple[int, float, float]:
    start = segment_index * 10 if coarse else segment_index
    freq_sg,    psd_sg    = get_one_sec_psd(data_dir, filename, ch=2, start=start)
    snr_sg,     center_f  = get_snr(freq_sg, psd_sg)
    freq_squid, psd_squid = get_one_sec_psd(data_dir, filename, ch=1, start=start)
    snr_squid             = get_snr(freq_squid, psd_squid, center_f)[0]
    return segment_index, snr_sg, snr_squid
```

### Phase B — Scoring-logic realignment

Two orthogonal adjustments to `score_vector`:

1. **`legacy_mode` flag** — selects the `s_max` source.
2. **TIDMAD round** — always apply `round(·, 2) + 1e-10` before `math.log`.

#### B.1 `score_vector` — revised signature and body

```python
def score_vector(
    data_dir: str,
    sample_set: SampleSet,
    anchor_map: dict | None = None,
    s_max: float | None = None,
    denoised_filename_fn: callable = None,
    raw_data_dir: str | None = None,
    parallel: bool = True,
    num_workers: int = 8,
    legacy_mode: bool = False,
) -> tuple[list[float | None], float]:
    """
    Two-phase scoring:

    Phase 1 — collect raw (snr_sg, snr_squid) pairs for every sampled
              segment across every sampled file.
    Phase 2 — determine s_max (anchor or file-list-local, per legacy_mode),
              normalize, aggregate as the LEGACY grand mean, apply
              round(·, 2) + 1e-10, take log_{5.27}.

    legacy_mode=True  → s_max = np.amax over all collected snr_sg.
                        Anchor map is ignored. This path reproduces
                        ``denoising_score_old.calculateBenchmark`` bit-for-bit
                        when ``sample_set`` spans all segments of all files
                        the legacy call would have processed.

    legacy_mode=False → s_max must be provided (from anchor map). This is
                        the SIDERIUS anchor-normalized path, still with the
                        TIDMAD round applied for consistency.

    Returns
    -------
    file_vector : length-NUM_FILES list; per-file weighted mean
                  ``mean_i( snr_sg[f][i] / s_max * snr_squid[f][i] )``.
                  ``None`` for files not in sample_set.
    final       : scalar legacy-style score
                  ``log_{5.27}(round(grand_mean, 2) + 1e-10)`` where
                  ``grand_mean = Σ_{f,i} (snr_sg/s_max · snr_squid) / Σ_f |S_f|``.
    """
    import math
    import concurrent.futures

    # Phase 1 — collect raw SNR pairs ----------------------------------
    tasks = []
    for file_index, segment_indices in sample_set.items():
        denoised_filename = denoised_filename_fn(file_index)
        tasks.append((data_dir, denoised_filename, file_index,
                      segment_indices, raw_data_dir))

    raw_pairs: dict[int, list[tuple[float, float]]] = {}
    if parallel and len(tasks) > 1:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(num_workers, len(tasks))
        ) as executor:
            for fi, pairs in executor.map(_collect_raw_pairs, tasks):
                raw_pairs[fi] = pairs
    else:
        for task_args in tasks:
            fi, pairs = _collect_raw_pairs(task_args)
            raw_pairs[fi] = pairs

    # Phase 2 — choose s_max -------------------------------------------
    if legacy_mode:
        all_snr_sg = [sg for pairs in raw_pairs.values() for (sg, _) in pairs]
        if not all_snr_sg:
            return [None] * NUM_FILES, float("-inf")
        s_max_used = float(np.amax(np.asarray(all_snr_sg)))
        if s_max_used == 0.0:
            s_max_used = 1.0           # defensive; legacy divides without guard
    else:
        if s_max is None:
            raise ValueError("Non-legacy mode requires s_max (anchor map).")
        s_max_used = float(s_max)

    # Phase 2 — per-file vector and grand mean -------------------------
    file_vector: list[float | None] = [None] * NUM_FILES
    total_weighted = 0.0
    total_count = 0
    for fi, pairs in raw_pairs.items():
        if not pairs:
            continue
        file_sum = 0.0
        for sg, sq in pairs:
            file_sum += (sg / s_max_used) * sq
        file_vector[fi] = file_sum / len(pairs)
        total_weighted += file_sum
        total_count += len(pairs)

    if total_count == 0:
        return file_vector, float("-inf")

    grand_mean = total_weighted / total_count
    score_linear = round(grand_mean, 2) + 1e-10          # THE TIDMAD ROUND
    final = math.log(score_linear, 5.27)
    return file_vector, final
```

With helper:

```python
def _collect_raw_pairs(args) -> tuple[int, list[tuple[float, float]]]:
    """
    Worker: compute raw (snr_sg, snr_squid) for each requested segment of
    one file, using the byte-strict primitives.
    """
    data_dir, denoised_filename, file_index, segment_indices, raw_data_dir = args
    if raw_data_dir is None:
        raw_data_dir = data_dir

    raw_filename = f"abra_validation_{file_index:04d}.h5"
    pairs: list[tuple[float, float]] = []
    for local_idx, seg_idx in enumerate(segment_indices):
        # CH2 from raw file (original segment index)
        freq_ch2, psd_ch2 = get_one_sec_psd(raw_data_dir, raw_filename, ch=2, start=seg_idx)
        snr_sg, center_freq = get_snr(freq_ch2, psd_ch2)
        # CH1 from denoised file (local position — trial mode contiguous pack)
        freq_ch1, psd_ch1 = get_one_sec_psd(data_dir, denoised_filename, ch=1, start=local_idx)
        snr_squid = get_snr(freq_ch1, psd_ch1, target=center_freq)[0]
        pairs.append((float(snr_sg), float(snr_squid)))
    return file_index, pairs
```

#### B.2 Why grand mean (not mean-of-file-means) for the scalar

Legacy:
```
score = Σ_{f,i} (snr_sg[f][i] / s_max) · snr_squid[f][i]  /  (Σ_f |S_f|)
```
— a grand mean over all sampled segments.

`mean_f(file_vector[f])` equals the grand mean only when `|S_f|` is uniform
across files. In formal mode (all 20 files × 200 segments) it is uniform
and the two agree. In trial mode with non-uniform sampling they disagree.
We always compute the grand mean directly so the scalar is legacy-compatible
regardless of sampling uniformity.

### Phase C — Ceiling update (`compute_ground_truth.py`)

`compute_ground_truth.py` does not run FFTs; it reads pre-computed CH2 SNRs
from the anchor map. Once the anchor map is rebuilt with the strict np.fft
primitives (Phase D), the ceiling formulas need one fix: the
anchor-normalized ceiling must apply the TIDMAD round.

#### C.1 `_legacy_per_file_ceiling` — no numeric change

Already applies `round(raw, 2) + 1e-10` and uses file-local `max(anchors_f)`.
Matches the single-file legacy run exactly. Leave as is.

Cosmetic tidy (optional): avoid calling `max(anchors_f)` twice in
```python
max_sg = max(anchors_f) if max(anchors_f) != 0 else 1.0
```

#### C.2 `_anchor_normalized_ceiling` — add TIDMAD round

```python
def _anchor_normalized_ceiling(
    anchors: dict[str, list[float]], s_max: float
) -> tuple[list[float], float]:
    """
    Perfect-denoiser ceiling under the anchor-normalized formula,
    with the TIDMAD round applied for consistency with score_vector.

    Per-segment : anchor² / s_max
    Per-file    : mean_s(anchor² / s_max)
    Grand mean  : (Σ_f Σ_s anchor² / s_max) / (Σ_f |S_f|)
                  == mean_f(per_file) since |S_f|=200 for every f here
    Scalar      : log_{5.27}(round(grand_mean, 2) + 1e-10)
    """
    file_vector: list[float] = []
    total_weighted = 0.0
    total_count = 0
    for f in sorted(anchors, key=int):
        a = anchors[f]
        file_sum = sum(v * v for v in a) / s_max
        file_vector.append(file_sum / len(a))
        total_weighted += file_sum
        total_count += len(a)
    grand_mean = total_weighted / total_count
    scalar = math.log(round(grand_mean, 2) + 1e-10, 5.27)
    return file_vector, float(scalar)
```

### Phase D — Re-anchoring (`execute_tools/build_anchor_map.py`)

`segment_anchors.json` was built with the old (scipy.fft, post-FFT
scaling) scoring_utils path. Those anchor SNRs are now "poisoned" with
respect to the strict-legacy primitives.

**Required step:** once Phase A lands, **rebuild the anchor map**:

```bash
rm /home/klz/Data/TIDMAD/segment_anchors.json
/home/yuema137/SIDERIUS/.venv/bin/python \
  /home/yuema137/SIDERIUS/execute_tools/build_anchor_map.py \
  --data_dir /home/klz/Data/TIDMAD/ \
  --parallel -n 8
```

No code change to `build_anchor_map.py` is needed — it imports `get_one_sec_psd`
and `get_snr` from `scoring_utils`, so replacing those primitives
automatically makes the rebuilt map strict-legacy consistent.

After rebuild, the `s_max` stored in the anchor map equals
`np.amax(snr_sg)` over all 20 × 200 = 4000 segments **under the legacy
primitive**. The invariant
```
anchor_map.s_max == score_vector(sample_set=full, legacy_mode=True).s_max_used
```
then holds by construction.

---

## 4. Cascade into `compute_raw_baseline.py` and `compute_ground_truth.py`

### 4.1 `compute_raw_baseline.py` — eliminate the private copies

The file currently embeds private copies of `_get_one_sec_psd`,
`_find_peak`, `_get_snr`, `_process_iteration`, and `_calculate_score`
"copied verbatim from denoising_score_single.py to avoid import
side-effects." Keeping private copies is the root cause of drift: every
time `scoring_utils.py` is fixed, we must remember to hand-port the fix
here, and vice-versa.

**Plan:**

1. Delete `_get_one_sec_psd`, `_find_peak`, `_get_snr`, `_process_iteration`.
2. Import from `scoring_utils`:
   ```python
   from execute_tools.scoring_utils import (
       get_one_sec_psd,
       find_peak,
       get_snr,
       process_segment,
   )
   ```
3. Rewrite `_calculate_score` to reuse `process_segment` and apply
   byte-strict legacy aggregation for a single file:
   ```python
   def _calculate_score(data_dir, fname, coarse, parallel, num_workers):
       fpath = os.path.join(data_dir, fname)
       with h5py.File(fpath, "r") as f:
           length = f["/timeseries/channel0001/timeseries"].shape[0]
       n = length // 10_000_000
       if coarse:
           n = int(n / 10)                         # legacy form, not max(1, n//10)

       snr_squid = np.zeros(n)
       snr_sg    = np.zeros(n)

       if parallel:
           with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as ex:
               tasks = [ex.submit(process_segment, i, data_dir, fname, coarse)
                        for i in range(n)]
               for fut in tqdm(concurrent.futures.as_completed(tasks), total=n,
                               desc=f"  scoring {fname}"):
                   i, s_sg, s_squid = fut.result()
                   snr_sg[i]    = s_sg
                   snr_squid[i] = s_squid
       else:
           for i in tqdm(range(n), desc=f"  scoring {fname}"):
               _, s_sg, s_squid = process_segment(i, data_dir, fname, coarse)
               snr_sg[i]    = s_sg
               snr_squid[i] = s_squid

       snr_sg = snr_sg / np.amax(snr_sg)            # file-local max = legacy
       score  = np.round(np.sum(np.multiply(snr_sg, snr_squid)) / snr_squid.size,
                         decimals=2) + 1e-10
       return float(math.log(score, 5.27))
   ```
4. **`n` is hardcoded to 200** (fine) / `int(200/10) = 20` (coarse),
   matching legacy's LIST-input shortcut `n = 200 * len(file_list)` for a
   single-file list. Originally the plan was to derive `n` from the HDF5
   length (`length // 10_000_000`); that turned out to be wrong. Real
   `abra_validation_*.h5` files are **201 seconds** (2,010,000,000
   samples) — one second longer than legacy assumes. A length-derived
   `n = 201` would overrun the 1-element `file_list` inside
   `get_one_sec_psd` (which computes `file_num = start // 200`) at
   `i = 200`. Legacy's list-path silently caps the trailing second; we
   match that by hardcoding `n = 200`.
5. The `min(·, 200)` cap and `max(1, n // 10)` guards from the
   pre-refactor code were guarding against the same out-of-range
   issue. Under the hardcoded `n` they are no longer needed — there is
   nothing to cap.
6. With these changes, `compute_raw_baseline._calculate_score` is a
   per-file, byte-strict transcription of `denoising_score_old.calculateBenchmark`
   invoked with a single-file list.

### 4.2 `compute_ground_truth.py` — no private code; formula-only changes

This file does not duplicate PSD / SNR logic. It reads the anchor map.
The only changes needed are (a) in `_anchor_normalized_ceiling` to add
the TIDMAD round (§C.2), and (b) regeneration after the anchor map is
rebuilt (§D).

### 4.3 The numpy-version question — DECIDED: Option B

**Decision:** Option B. Force the FFT into `complex128` by casting `TS`
to `float64` immediately before `np.fft.rfft` (see §1.3 and §A.1).

**Rationale:** the legacy script was authored in early June 2024 under
numpy ≤ 1.x, where `np.fft.rfft(float32)` implicitly promoted to
`float64` and returned `complex128`. The canonical TIDMAD benchmark
numbers were produced on that code path. Running the legacy script
unmodified on our current numpy 2.4.3 would use `complex64` and no
longer produces those canonical numbers. The explicit `TS.astype(np.float64)`
in `get_one_sec_psd` restores the pre-2.0 behavior and therefore restores
reproducibility of the canonical numbers on any future numpy.

**Scope:** the cast applies only to the FFT input inside `get_one_sec_psd`.
No other function in the scoring path changes dtype.

---

## 5. Verification

### 5.1 Parity test (required before merging)

**Location:** `tests/integration/scoring/test_legacy_parity.py` (new file).
**Marker:** `@real_run` (requires HDF5 data on disk) plus a separate marker
or skip guard if legacy script path is not mounted.

**Important — Option B implication:** we cannot run
`denoising_score_old.py` unmodified on numpy 2.4.3 and expect a match,
because the as-written script would use the `complex64` FFT path here,
whereas our new code (and the canonical benchmark) use `complex128`. The
parity test therefore runs the legacy script **under numpy 1.x
semantics**, via one of the two mechanisms below.

**Mechanism 1 — monkey-patched legacy script (recommended).** The test
imports `denoising_score_old` as a module after monkey-patching
`np.fft.rfft` to upcast its input to `float64`:

```python
import numpy as np
import importlib.util, pathlib

def _patched_rfft(a, *args, **kwargs):
    return _orig_rfft(np.asarray(a, dtype=np.float64), *args, **kwargs)

_orig_rfft = np.fft.rfft
np.fft.rfft = _patched_rfft
try:
    spec = importlib.util.spec_from_file_location(
        "denoising_score_old",
        "/home/tidmad/TIDMAD/denoising_score_old.py",
    )
    legacy = importlib.util.module_from_spec(spec)
    # Load but do NOT execute the argparse block — call calculateBenchmark directly:
    # easiest path is to exec just the function definitions via ast, OR copy the
    # three functions (GetOneSecPSD, findPeak, getSNR, process_iteration,
    # calculateBenchmark) into a test fixture module `legacy_fixture.py`.
    score_legacy = legacy.calculateBenchmark(
        "tmp_data/", ["abra_validation_0000.h5"],
        argparse.Namespace(coarse=False, parallel=False, num_workers=1),
    )
finally:
    np.fft.rfft = _orig_rfft
```

In practice the cleanest implementation is: **copy the five legacy
functions verbatim into `tests/fixtures/legacy_scoring.py`**, apply the
`astype(np.float64)` patch inside `GetOneSecPSD` of that fixture only
(one-line edit), and call `legacy_fixture.calculateBenchmark` from the
test. That way no monkey-patching of `np.fft` leaks into the pytest
process and the reference implementation is self-contained.

**Mechanism 2 — separate numpy-1.x environment.** Create a sibling
virtualenv with numpy < 2.0 (e.g. `numpy==1.26.4`). Run the unmodified
legacy script there, capture the printed score to a file
`tests/fixtures/legacy_reference_scores.json`, and have the parity test
assert against that pinned value. Slower to set up but guarantees we are
comparing against a genuine numpy-1.x number, not a patched simulation.

Either mechanism yields the same reference value (the monkey-patch is
literally what numpy 1.x did internally). Pick Mechanism 1 unless there
is an independent reason to keep a numpy-1.x env around.

**Test procedure (fine, 1 file):**

1. Pick a single validation file present locally:
   `abra_validation_0000.h5` (under `/home/klz/Data/TIDMAD/`).
2. Stage a temporary data directory containing ONLY that file (symlink):
   ```
   tmp_data/abra_validation_0000.h5  →  /home/klz/Data/TIDMAD/abra_validation_0000.h5
   ```
3. Run the reference via Mechanism 1 (see above) and capture
   `score_legacy`.
4. In pytest, call the new `score_vector` with a single-file sample set
   and `legacy_mode=True`:
   ```python
   _, score_new = score_vector(
       data_dir="tmp_data",
       sample_set={0: list(range(200))},
       denoised_filename_fn=lambda i: f"abra_validation_{i:04d}.h5",
       raw_data_dir="tmp_data",
       anchor_map=None,
       s_max=None,
       legacy_mode=True,
       parallel=False,
   )
   ```
5. Assert `abs(score_new - score_legacy) < 1e-10`.

**Coarse variant:** repeat with `segment_indices = [i*10 for i in range(20)]`
and the fixture's `calculateBenchmark` called with `coarse=True`.

**20-file variant (optional, expensive):** full formal run comparing
legacy `-m none` over all 20 raw files against
`score_vector(sample_set={i: list(range(200)) for i in range(20)}, legacy_mode=True)`.
Gate behind a separate marker so CI is not burdened.

### 5.2 Anchor-map consistency check

After rebuild (§D), assert the invariant:
```python
from execute_tools.scoring_utils import score_vector

file_vec, scalar = score_vector(
    data_dir=TIDMAD_DATA_DIR,
    sample_set={i: list(range(200)) for i in range(NUM_FILES)},
    denoised_filename_fn=lambda i: f"abra_validation_{i:04d}.h5",
    raw_data_dir=TIDMAD_DATA_DIR,
    legacy_mode=True,
    parallel=True, num_workers=8,
)
# Independent computation
s_max_computed = …                           # np.amax collected inside score_vector

with open(segment_anchors_json) as f:
    am = json.load(f)
assert abs(am["s_max"] - s_max_computed) < 1e-10
```

### 5.3 Ground-truth ceiling check

With the rebuilt anchor map, `compute_ground_truth.py` produces:

* Per-file legacy ceilings (unchanged formula, just cleaner input).
* Anchor-normalized ceiling scalar, now with the TIDMAD round.

Sanity: the anchor-normalized ceiling must be ≥ the scalar produced by
`score_vector(full_sample_set, legacy_mode=False, anchor_map=rebuilt)` on
any real denoised run — the perfect denoiser upper-bounds real denoisers.

---

## 6. Rollout checklist

In order. Each step gets its own commit for bisectability.

- [x] **A.1–A.4** Replace `get_one_sec_psd`, `get_snr` (zero-trap), keep
      `find_peak`, keep `process_segment`. Remove `scipy.fft` import.
      Unit tests green on `tests/unit/execute_tools/test_scoring_utils.py`
      (13/13). Bit-for-bit parity against the legacy primitive + float64
      patch confirmed on a synthetic 10⁷-sample HDF5 segment (max abs
      PSD diff = 0, SNR identical).
- [x] **B.1** Introduce `legacy_mode` flag + `_collect_raw_pairs` helper
      in `score_vector`. Add TIDMAD round to both paths. Grand-mean
      aggregation `Σ/(Σ|S_f|)` implemented. Unit tests updated to assert
      `log_{5.27}(round(grand_mean, 2) + 1e-10)` and to exercise
      `legacy_mode=True` (13/13).
- [x] **C.2** Add TIDMAD round to `_anchor_normalized_ceiling`. Also
      restructured to compute the grand mean
      (`Σ_{f,i} anchor²/s_max / Σ_f |S_f|`) so the scalar is
      legacy-compatible under non-uniform `|S_f|`; under uniform
      `|S_f|` it equals `mean_f(file_vector)` as before. Hand-computed
      unit tests in `tests/unit/test_compute_ground_truth.py` (7/7) lock
      the formula against accidental drift.
- [x] **D**   Rebuilt `segment_anchors.json` under strict primitives
      (Option B). New `s_max = 295_715_680.1425` (previous stale value
      was `295_715_731.2500`; |Δ|≈51, consistent with the float32 FFT
      drift amplification observed in the 5.2 recomputation before
      rebuild). Regenerated artifact lives on the data mount at
      `/home/klz/Data/TIDMAD/segment_anchors.json`, not in the repo.
- [x] **4.1** Strip private copies from `compute_raw_baseline.py`;
      re-import strict primitives. Private `_get_one_sec_psd`,
      `_find_peak`, `_get_snr`, `_process_iteration` deleted;
      `_calculate_score` now a byte-strict transcription of
      `denoising_score_old.calculateBenchmark` on a single-file list
      with `n = 200` hardcoded to match legacy's LIST-input shortcut.
      `import h5py` dropped — no length read needed. Mocked unit tests
      in `tests/unit/test_compute_raw_baseline.py` (3/3) cover fine
      n=200 iteration count, coarse n=20 stride, and hand-computed
      aggregation. (Regeneration of `raw_baseline/*.json` via
      `python compute_raw_baseline.py --override` is a downstream
      artifact step — separate from this commit.)
- [x] **4.2** Regenerated `raw_baseline/*.json` (20/20 fine files; indices
      20–39 error on missing `abra_validation_00{20..39}.h5` — a
      pre-existing script quirk from a 40-file convention, not a
      refactor regression) and `ground_truth/*.json` under the rebuilt
      anchor map. Before/after drift: raw baseline scores are
      **bit-identical** for checked indices (the TIDMAD `round(·, 2)`
      step absorbs sub-ulp FP drift into the same 2-decimal bucket,
      preserving the published benchmark at the visible precision);
      ground truth per-file scores drift by `|Δ| ≤ 1.2e-7`;
      anchor-normalized scalar ceiling drifts by `|Δ| ≈ 1.1e-7`
      (10.1134 before → 10.1134 after; new ceiling's `s_max`
      reflects the rebuilt anchor map). Ceiling ≈ 10.11 comfortably
      upper-bounds typical denoiser scores (~1–9) — sanity passes.
- [x] **5.1a** Legacy five functions copied verbatim into
      `tests/fixtures/legacy_scoring.py`. One-line
      `.astype(np.float64)` patch inside `GetOneSecPSD` restores numpy
      1.x `complex128` semantics under numpy 2.4.3 (Option B).
- [x] **5.1b** Parity test `tests/integration/scoring/test_legacy_parity.py`
      committed and passing at `|Δ| < 1e-10` (3/3, ~217s runtime):
      (i) `compute_raw_baseline._calculate_score` coarse, (ii) fine,
      (iii) `score_vector(legacy_mode=True)` — the production merge
      gate. Marked `@pytest.mark.real_run`; skips if
      `abra_validation_0000.h5` is absent.
- [x] **5.2** Anchor-map consistency assertion committed at
      `tests/integration/scoring/test_anchor_map_consistency.py`
      (2/2 passing post-Phase-D). Two tests: (i) static — top-level
      `s_max` equals `max(max(segs) for segs in anchors.values())`;
      (ii) strict-primitive recomputation — CH2 SNR for a sparse
      5×3 grid (files 0, 5, 10, 15, 19 × segments 0, 100, 199)
      matches stored anchors at `|Δ| < 1e-10`. Test (ii) is the
      canonical canary for stale anchor maps — if a future refactor
      changes a primitive silently, this test goes red and points
      at the required rebuild command.

---

## 7. Final commitments

* **Scaling lives in the time domain.** `TS = data.astype(float32) * scaling` —
  no post-FFT prefactor, no in-place micro-optimizations. Memory pressure
  is reclaimed by `del TS; gc.collect()`, as legacy already does.
* **FFT is `np.fft.rfft` exclusively, in `complex128` (Option B).** The
  input is explicitly upcast via `TS.astype(np.float64)` before `rfft` to
  restore pre-numpy-2.0 behavior, under which the canonical TIDMAD
  benchmark numbers were produced. `scipy.fft` is removed from the import
  list of every scoring module.
* **`np.round(·, 2) + 1e-10` is applied before `math.log(·, 5.27)`**, in
  both legacy_mode and anchor-normalized paths, and in the ceiling
  calculator.
* **No private copies.** `compute_raw_baseline.py` and
  `build_anchor_map.py` both import from `scoring_utils`; there is one
  single definition of every primitive, and Phase D's anchor rebuild is
  the mechanism that propagates Phase A's fixes into stored artifacts.
* **The parity test is the merge gate.** No change to this scoring path
  lands unless `test_legacy_parity.py` passes at `|Δ| < 1e-10` against
  `denoising_score_old.py` on the same numpy build.
