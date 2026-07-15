"""
Shared low-level scoring utilities for TIDMAD denoising evaluation.

Two layers:

1. LOW-LEVEL (PSD / SNR): atomic building blocks that compute PSD and SNR
   at the 1-second segment level. Used by the anchor map builder, the
   segment-aware scorer, and (indirectly) the legacy scoring path.

2. ANCHOR-NORMALIZED SCORING: score_segments() and score_vector() use a
   pre-computed anchor map (from build_anchor_map.py) for normalization
   instead of file-local normalization. This makes scores from trial mode
   (sparse sampling) directly comparable to formal mode (all 20 files).

All functions operate on raw HDF5 data and are stateless.

LEGACY PARITY: every function here is a byte-strict transcription of the
reference implementation at ``/home/tidmad/TIDMAD/denoising_score_old.py``.
See ``docs/align_denoising_score.md`` for the full alignment contract. In
particular:

* scaling is applied in the time domain (``TS = data.astype(float32) * scaling``);
* the FFT is ``np.fft.rfft`` in ``complex128`` precision — enforced under
  numpy ≥ 2.0 by ``TS.astype(np.float64)`` immediately before ``rfft``, which
  restores the implicit float32→float64 promotion performed by numpy ≤ 1.x
  under which the canonical TIDMAD benchmark numbers were generated;
* the zero-noise trap in ``get_snr`` uses strict equality (``noise == 0``).

scipy.fft is prohibited here: it uses a different pocketfft backend with a
different butterfly ordering, and does not produce bit-identical output.
"""

import gc
import math
import os
from collections.abc import Callable
from typing import Any, cast

import h5py
import numpy as np

from execute_tools.dataset_config import NUM_FILES, SEGMENT_LENGTH, SEGMENTS_PER_FILE


def _h5_dataset(f: h5py.File, *path: str) -> h5py.Dataset:
    """Type-only helper: walk an HDF5 path and narrow the final node to Dataset.

    h5py stubs declare ``__getitem__`` as ``Group | Dataset | Datatype``,
    which makes pyright reject chained indexing even though every site here
    ends on a real Dataset. Pure type-system shim — identical runtime
    semantics to ``f[a][b][c]``.
    """
    node: Any = f
    for k in path:
        node = node[k]
    return cast(h5py.Dataset, node)


def _h5_group(f: h5py.File, *path: str) -> h5py.Group:
    """Type-only helper: walk an HDF5 path and narrow the final node to Group
    (used at sites that read ``.attrs[...]`` metadata). Pure type-system shim.
    """
    node: Any = f
    for k in path:
        node = node[k]
    return cast(h5py.Group, node)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def get_one_sec_psd(
    file_path: str,
    files: list[str] | str,
    ch: int,
    start: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute the Power Spectral Density for a single 1-second segment.

    Byte-strict transcription of ``denoising_score_old.GetOneSecPSD`` under
    Option B (complex128 FFT — see ``docs/align_denoising_score.md`` §1.3).

    * scaling is ``np.float32(volt_range / (2 * 128.0))``;
    * scaling is applied **in the time domain** — ``TS = data.astype(float32) * scaling``;
    * ``TS`` is explicitly upcast to float64 immediately before ``np.fft.rfft``
      so the FFT runs in complex128 (matches numpy 1.x implicit promotion
      under which the canonical TIDMAD benchmark numbers were generated);
    * the reshape ``TS.reshape(len(TS)//N, N)`` is kept literally to match
      the legacy call shape — for a single N-length slice it is a no-op;
    * the freq grid uses the literal legacy Nyquist ``5 * 1e6``, not
      ``sampling_freq / 2``, because the legacy spec hardcodes that value.

    Args:
        file_path: Directory containing the HDF5 files.
        files:     Filename or list of filenames (each 200 seconds).
        ch:        Channel number (1 = SQUID/denoised, 2 = ground truth).
        start:     Segment index (0-based). Segment ``start`` in file
                   ``start // SEGMENTS_PER_FILE`` at offset
                   ``(start % SEGMENTS_PER_FILE) * SEGMENT_LENGTH``.

    Returns:
        (freq_array, psd_chunk) — float64 frequency bins and float64 PSD
        values. Length is ``SEGMENT_LENGTH // 2`` (DC bin dropped).
    """
    if isinstance(files, str):
        file_list = [os.path.join(file_path, files)]
    else:
        file_list = [os.path.join(file_path, f) for f in files]

    N = SEGMENT_LENGTH
    file_num = start // SEGMENTS_PER_FILE
    start_index = N * (start % SEGMENTS_PER_FILE)

    file = file_list[file_num]
    with h5py.File(file, "r") as h5f:
        channel_key = f"channel{ch:04d}"
        data = _h5_dataset(h5f, "timeseries", channel_key, "timeseries")[
            start_index : start_index + N
        ]
        # h5py's ``attrs[...]`` stubs return ``Empty | ndarray | ...``, but
        # both attributes are scalar physics constants per the TIDMAD HDF5
        # convention. ``cast(float, ...)`` is a pure type-system narrow with
        # zero runtime cost — preserving the original numpy-scalar return
        # exactly — and matches the existing h5py boundary pattern used at
        # ``_h5_dataset`` / ``_h5_group`` (L56, L66) in this file.
        volt_range = cast(
            float, _h5_group(h5f, "timeseries", "channel0001").attrs["voltage_range_mV"]
        )
        sampling_freq = cast(
            float, _h5_group(h5f, "timeseries", "channel0001").attrs["sampling_frequency"]
        )

        scaling = np.float32(volt_range / (2 * 128.0))
        TS = np.array(data, dtype=np.float32) * scaling
        dt = 1.0 / sampling_freq

        # Option B — force complex128 FFT by upcasting TS to float64 at
        # the rfft call site. Under numpy ≥ 2.0, np.fft.rfft preserves
        # float32 precision (returns complex64); under numpy ≤ 1.x it
        # implicitly promoted to float64 (returned complex128). The
        # canonical TIDMAD benchmark numbers were produced under the
        # complex128 path, so we force it explicitly here.
        psd_chunk = (
            dt
            / N
            * (abs(np.fft.rfft(TS.astype(np.float64).reshape(len(TS) // N, N))) ** 2).sum(0)[1:]
        )
        freq_array = np.linspace(0, 5 * 1e6, int(N / 2))

    del data, TS, dt
    gc.collect()
    return freq_array, psd_chunk


def find_peak(pwr: np.ndarray) -> int:
    """Find the index of the dominant spectral peak."""
    peak_diff = pwr[1:-1] - pwr[:-2] - pwr[2:]
    return int(np.where(peak_diff == np.amax(peak_diff))[0][0]) + 1


def get_snr(
    freq: np.ndarray,
    pwr: np.ndarray,
    target: float = 0,
) -> tuple[float, float]:
    """
    Compute signal-to-noise ratio around a spectral peak.

    Transcribed from ``denoising_score_old.getSNR`` with one v17 change to
    the noise-floor guard. The legacy spec triggered a fallback of
    ``noise = 1e-5`` when ``noise == 0`` exactly. That fallback produced
    the class-127 mode-collapse artifact: constant int8 output → PSD is
    all floating-point subnormals → noise window sums to ~1e-40 → noise
    minus signal is a subnormal cancellation residue ~1e-45 → SNR ratio
    is deterministic 2^17 = 131072 → propagated all the way to a "score"
    of 5.5762667 that has zero information content. See
    ``docs/design/pluggable_health_checks.md`` §7.1 and the v16 forensic
    audit in ``reports/v16_20260630.md``.

    The v17 guard: return ``NaN`` when ``noise < 1e-10`` (subnormal
    territory). Downstream ``_collect_raw_pairs`` and ``score_vector``
    filter NaN pairs so the artifact never enters the aggregation.

    Args:
        freq:   Frequency array from ``get_one_sec_psd``.
        pwr:    PSD array from ``get_one_sec_psd``.
        target: Target frequency (Hz). 0 = auto-detect peak.

    Returns:
        ``(snr, center_freq)`` — SNR value and peak frequency. ``snr`` is
        ``NaN`` when the noise window collapsed to FP-precision noise
        (i.e. the model output was near-constant).
    """
    center_id = find_peak(pwr) if target == 0 else int(np.where(freq == target)[0][0])

    sig_range = 1
    noise_range = 50
    signal = np.sum(pwr[center_id - sig_range : center_id + sig_range + 1])
    noise = np.sum(pwr[center_id - noise_range : center_id + noise_range + 1]) - signal
    if noise < 1e-10:
        # Noise window is at floating-point-subnormal level — computing
        # signal/noise here would produce the class-127 mode-collapse
        # artifact. Return NaN so the caller filters this segment out.
        return float("nan"), freq[center_id]
    return signal / noise, freq[center_id]


def process_segment(
    segment_index: int,
    data_dir: str,
    filename: str | list[str],
    coarse: bool = False,
) -> tuple[int, float, float]:
    """
    Compute CH2 (ground truth) and CH1 (SQUID) SNR for a single segment.

    Args:
        segment_index: 0-based segment index within the file.
        data_dir:      Directory containing the HDF5 files.
        filename:      Filename or list of filenames.
        coarse:        If True, stride by 10 (coarse scan).

    Returns:
        (segment_index, snr_ground_truth, snr_squid)
    """
    start = segment_index * 10 if coarse else segment_index

    freq_sg, psd_sg = get_one_sec_psd(data_dir, filename, ch=2, start=start)
    snr_sg, center_freq = get_snr(freq_sg, psd_sg)

    freq_squid, psd_squid = get_one_sec_psd(data_dir, filename, ch=1, start=start)
    snr_squid = get_snr(freq_squid, psd_squid, center_freq)[0]

    return segment_index, snr_sg, snr_squid


# ---------------------------------------------------------------------------
# Anchor-normalized scoring (Phase 1)
# ---------------------------------------------------------------------------

SampleSet = dict[int, list[int]]
"""Mapping of file_index → list of segment indices to process."""


def validate_sample_set(sample_set: dict) -> SampleSet:
    """
    Lightweight validation for a SampleSet dict.

    Checks structure and types without a full Pydantic model. Normalizes
    JSON string keys to int. Raises ValueError on invalid input.

    Args:
        sample_set: Raw dict, possibly from JSON (string keys).

    Returns:
        Validated SampleSet with int keys and sorted int segment lists.
    """
    if not isinstance(sample_set, dict):
        raise ValueError(f"SampleSet must be a dict, got {type(sample_set).__name__}")
    if not sample_set:
        raise ValueError("SampleSet must not be empty.")

    validated: SampleSet = {}
    for key, segments in sample_set.items():
        try:
            file_index = int(key)
        except (ValueError, TypeError) as e:
            raise ValueError(f"SampleSet key must be an integer, got {key!r}") from e
        if not (0 <= file_index < NUM_FILES):
            raise ValueError(f"SampleSet file_index {file_index} out of range [0, {NUM_FILES}).")
        if not isinstance(segments, list) or not segments:
            raise ValueError(
                f"SampleSet[{file_index}] must be a non-empty list, got {type(segments).__name__}"
            )
        for seg in segments:
            if not isinstance(seg, int) or seg < 0 or seg >= SEGMENTS_PER_FILE:
                raise ValueError(
                    f"SampleSet[{file_index}] segment {seg!r} invalid — "
                    f"must be int in [0, {SEGMENTS_PER_FILE})."
                )
        validated[file_index] = segments

    return validated


def score_segments(
    data_dir: str,
    denoised_filename: str,
    file_index: int,
    segment_indices: list[int],
    anchor_map: dict,
    s_max: float,
    raw_data_dir: str | None = None,
) -> float:
    """
    Score specific segments of one denoised file using anchor-normalized weights.

    For each segment, computes ``snr_squid`` (CH1 denoised output) and
    multiplies by the pre-computed anchor weight ``anchor_snr / s_max``.
    Returns the mean of the weighted SNR values for this file.

    **Trial-mode layout**: the denoised file contains only the requested
    segments packed contiguously (original segment 185 may be stored at
    local position 1). This function uses the local position to read from
    the denoised file and the original segment index to read the raw file
    and look up anchor weights.

    Args:
        data_dir:           Directory containing the denoised HDF5 file.
        denoised_filename:  Filename of the denoised file (e.g.
                            ``"abra_validation_denoised_punet_0006.h5"``).
        file_index:         Which validation file (0-19) this corresponds to.
        segment_indices:    Which segments to score (0-based, original indices
                            within the full validation file). Order must match
                            the packing order used by inference_single.py.
        anchor_map:         The ``"anchors"`` dict from ``segment_anchors.json``.
                            Keys are file indices as strings, values are lists
                            of per-segment CH2 SNR values.
        s_max:              Global maximum CH2 SNR from the anchor map.
        raw_data_dir:       Directory containing the raw validation files
                            (``abra_validation_XXXX.h5``). Defaults to
                            ``data_dir`` when ``None``.

    Returns:
        The file-level score (weighted mean of denoised SNR for the sampled
        segments). Returns ``float('nan')`` if ``segment_indices`` is empty.
    """
    if not segment_indices:
        return float("nan")

    if raw_data_dir is None:
        raw_data_dir = data_dir

    file_anchors = anchor_map[str(file_index)]
    weighted_snrs = []

    for local_idx, seg_idx in enumerate(segment_indices):
        # CH2 center freq from raw validation file (use original segment index)
        raw_filename = f"abra_validation_{file_index:04d}.h5"
        freq_ch2, psd_ch2 = get_one_sec_psd(raw_data_dir, raw_filename, ch=2, start=seg_idx)
        _, center_freq = get_snr(freq_ch2, psd_ch2)

        # CH1 SNR from denoised file (use local position — trial mode
        # packs segments contiguously: original seg_idx → position local_idx)
        freq_ch1, psd_ch1 = get_one_sec_psd(data_dir, denoised_filename, ch=1, start=local_idx)
        snr_squid = get_snr(freq_ch1, psd_ch1, target=center_freq)[0]

        # Anchor weight: pre-computed CH2 SNR / global max
        weight = file_anchors[seg_idx] / s_max
        weighted_snrs.append(snr_squid * weight)

    return float(np.mean(weighted_snrs))


def _score_one_file(args: tuple) -> tuple[int, float]:
    """Worker for ``score_segments``-based anchor-only per-file scoring.

    Kept for backward compatibility with callers that used the pre-refactor
    ``score_vector``. The new ``score_vector`` goes through
    ``_collect_raw_pairs`` instead so it can operate in both anchor mode
    and ``legacy_mode``.
    """
    data_dir, denoised_filename, file_index, segment_indices, anchor_map, s_max, raw_data_dir = args
    score = score_segments(
        data_dir=data_dir,
        denoised_filename=denoised_filename,
        file_index=file_index,
        segment_indices=segment_indices,
        anchor_map=anchor_map,
        s_max=s_max,
        raw_data_dir=raw_data_dir,
    )
    return file_index, score


def _collect_raw_pairs(
    args: tuple,
) -> tuple[int, list[tuple[float, float]]]:
    """
    Worker — compute raw ``(snr_sg, snr_squid)`` for every requested segment
    of one file, using byte-strict legacy primitives.

    Returns ``(file_index, [(snr_sg, snr_squid), ...])`` preserving the order
    of ``segment_indices``. The caller decides how to normalize these pairs
    (anchor ``s_max`` vs legacy file-list-local ``np.amax``).

    Args tuple layout:
        (data_dir, denoised_filename, file_index, segment_indices, raw_data_dir)
    """
    data_dir, denoised_filename, file_index, segment_indices, raw_data_dir = args
    if raw_data_dir is None:
        raw_data_dir = data_dir

    raw_filename = f"abra_validation_{file_index:04d}.h5"
    pairs: list[tuple[float, float]] = []
    for local_idx, seg_idx in enumerate(segment_indices):
        # CH2 (ground truth) from the raw validation file — provides both
        # snr_sg and the center frequency for the matched-filter CH1 SNR.
        freq_ch2, psd_ch2 = get_one_sec_psd(raw_data_dir, raw_filename, ch=2, start=seg_idx)
        snr_sg, center_freq = get_snr(freq_ch2, psd_ch2)

        # CH1 (SQUID / denoised) from the denoised file. Trial-mode layouts
        # pack sampled segments contiguously, so read by ``local_idx`` not
        # ``seg_idx``. Formal mode has all 200 segments in place and
        # ``local_idx == seg_idx``.
        freq_ch1, psd_ch1 = get_one_sec_psd(data_dir, denoised_filename, ch=1, start=local_idx)
        snr_squid = get_snr(freq_ch1, psd_ch1, target=center_freq)[0]

        # v17 NaN filter — ``get_snr`` returns NaN when the noise window
        # collapsed to floating-point subnormals (mode-collapse signature).
        # Drop the segment so it does NOT contribute a phantom 2^17 ratio
        # to the file mean. If every segment of a file is dropped, the
        # caller sees an empty pair list and marks the file as None.
        if not math.isfinite(snr_sg) or not math.isfinite(snr_squid):
            continue
        pairs.append((float(snr_sg), float(snr_squid)))
    return file_index, pairs


def score_vector(
    data_dir: str,
    sample_set: SampleSet,
    anchor_map: dict | None = None,
    s_max: float | None = None,
    denoised_filename_fn: Callable[..., Any] | None = None,
    raw_data_dir: str | None = None,
    parallel: bool = True,
    num_workers: int = 8,
    legacy_mode: bool = False,
) -> tuple[list[float | None], float]:
    """
    Score multiple files and return the length-``NUM_FILES`` per-file vector
    plus a scalar score aligned with the legacy TIDMAD formula.

    Two-phase design (see ``docs/align_denoising_score.md`` §B):

    1. Collect raw ``(snr_sg, snr_squid)`` pairs for every sampled segment
       across every sampled file, via ``_collect_raw_pairs``.
    2. Choose ``s_max`` per ``legacy_mode``, normalize, aggregate as the
       **grand mean** across all sampled segments, then apply the TIDMAD
       ``round(·, 2) + 1e-10`` step before ``log_{5.27}``.

    Args:
        data_dir:              Directory containing the denoised HDF5 files.
        sample_set:            ``{file_index: [segment_indices]}`` — which
                               segments to score per file.
        anchor_map:            The ``"anchors"`` dict from
                               ``segment_anchors.json``. Only read in
                               ``legacy_mode=False``. Accepted but unused
                               in ``legacy_mode=True``.
        s_max:                 Global maximum CH2 SNR. Required when
                               ``legacy_mode=False``; ignored when
                               ``legacy_mode=True`` (computed from the
                               collected ``snr_sg`` values as
                               ``np.amax`` of the current file list).
        denoised_filename_fn:  Callable ``(file_index) → filename`` that
                               resolves the denoised HDF5 for each file
                               index. Must be provided — there is no
                               default.
        raw_data_dir:          Directory containing the raw validation
                               files (``abra_validation_XXXX.h5``).
                               Defaults to ``data_dir`` when ``None``.
        parallel:              Use multiprocessing to collect across files
                               in parallel.
        num_workers:           Max parallel workers.
        legacy_mode:           When True, reproduces
                               ``denoising_score_old.calculateBenchmark``
                               bit-for-bit on ``sample_set`` (provided the
                               underlying primitives match — see Phase A).
                               The ``s_max`` used for normalization is
                               ``np.amax`` over the CURRENTLY sampled
                               ``snr_sg`` values, mirroring legacy's
                               file-list-local maximum. No anchor map is
                               consulted.
    Returns:
        (file_vector, final_scalar):
        - ``file_vector``: length-``NUM_FILES`` list. Entry ``f`` is the
          per-file weighted mean
          ``mean_i( snr_sg[f][i] / s_max_used * snr_squid[f][i] )`` for
          files in ``sample_set``, ``None`` otherwise.
        - ``final_scalar``: the legacy-style score
          ``log_{5.27}(round(grand_mean, 2) + 1e-10)``
          where ``grand_mean = Σ_{f,i} (snr_sg/s_max_used · snr_squid)
          / Σ_f |S_f|``. For uniform ``|S_f|`` this equals the mean
          of ``file_vector`` entries; for non-uniform sampling the grand
          mean is the legacy-compatible aggregation.

    Health-check separation (commit-5a): ``score_vector`` is pure
    scoring — no health-check code. The previous embedded Phase 0
    pre-FFT short-circuit and Phase 3 post-scoring panel were removed
    entirely per Option A in
    ``docs/design/pluggable_health_checks.md`` §14. Health checks now
    run tuner-side via ``evaluate_gate`` at round boundaries; see the
    tuner's post-``sandbox.score_vector()`` block (landed in commit-5b).
    ``reference_file_vector`` and ``degeneracy_threshold_ratio`` were
    removed from this signature — both were only consumed by the
    deleted magnitude-ratio predicate.

    Raises:
        ValueError: If ``denoised_filename_fn`` is None, or if
                    ``legacy_mode=False`` and ``s_max`` is None.
    """
    import concurrent.futures
    import multiprocessing as mp

    if denoised_filename_fn is None:
        raise ValueError(
            "denoised_filename_fn is required — the scorer needs to know "
            "which denoised file to read for each file_index."
        )
    if not legacy_mode and s_max is None:
        raise ValueError(
            "Non-legacy mode requires s_max (from the anchor map). "
            "Pass legacy_mode=True to compute s_max from the current "
            "file list instead."
        )

    file_vector: list[float | None] = [None] * NUM_FILES

    # ------------------------------------------------------------------
    # Phase 1 — collect raw (snr_sg, snr_squid) pairs
    # ------------------------------------------------------------------
    tasks = []
    for file_index, segment_indices in sample_set.items():
        denoised_filename = denoised_filename_fn(file_index)
        tasks.append(
            (
                data_dir,
                denoised_filename,
                file_index,
                segment_indices,
                raw_data_dir,
            )
        )

    raw_pairs: dict[int, list[tuple[float, float]]] = {}
    if not tasks:
        return file_vector, float("-inf")

    if parallel and len(tasks) > 1:
        # Phase 6.8 §2 Layer A — force ``spawn`` start method so worker
        # processes do NOT copy-on-write the parent's ~8 GB heap. Default
        # ``fork`` on Linux caused a +15 GB transient on 2026-04-27 that
        # OOM-killed the v5 explore parent. ``_collect_raw_pairs`` is
        # module-level (picklable), so spawn is safe; cost is ~1-2 s of
        # worker import warmup on each call. See
        # docs/phase68_task1_memory_diagnostic_20260427.md §2 Commit 1.
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(num_workers, len(tasks)),
            mp_context=mp.get_context("spawn"),
        ) as executor:
            for fi, pairs in executor.map(_collect_raw_pairs, tasks):
                raw_pairs[fi] = pairs
    else:
        for task_args in tasks:
            fi, pairs = _collect_raw_pairs(task_args)
            raw_pairs[fi] = pairs

    # ------------------------------------------------------------------
    # Phase 2 — choose s_max, normalize, aggregate as legacy grand mean
    # ------------------------------------------------------------------
    if legacy_mode:
        all_snr_sg = [sg for pairs in raw_pairs.values() for (sg, _) in pairs]
        if not all_snr_sg:
            return file_vector, float("-inf")
        # Legacy uses ``np.amax(snr_sg)`` as the normalizer. We cast to
        # a float array and take ``np.amax`` to match the legacy call
        # shape exactly (same op as ``snr_sg/np.amax(snr_sg)``).
        s_max_used = float(np.amax(np.asarray(all_snr_sg, dtype=np.float64)))
        if s_max_used == 0.0:
            # Legacy divides without a guard; we refuse to divide by 0
            # but this branch cannot be reached on real physics data
            # (CH2 always has non-zero SNR at the peak).
            s_max_used = 1.0
    else:
        # Non-legacy mode requires the caller to supply ``s_max``. Surface the
        # contract explicitly instead of crashing inside ``float(None)``.
        if s_max is None:
            raise ValueError(
                "score_vector: s_max parameter is mandatory when legacy_mode=False "
                "(got None) — caller must supply the normalizer in non-legacy mode."
            )
        s_max_used = float(s_max)

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
    if grand_mean > 0 and math.isfinite(grand_mean):
        final_scalar = math.log(grand_mean, 5.27)
    else:
        final_scalar = float("-inf")

    return file_vector, final_scalar


# ---------------------------------------------------------------------------
# JSON-safety helper
# ---------------------------------------------------------------------------


def coerce_nonfinite_to_none(obj):
    """Recursively replace non-finite floats with ``None`` for JSON output.

    JSON RFC 8259 disallows ``Infinity``/``-Infinity``/``NaN``. ``json.dump``
    will silently emit those tokens when ``allow_nan=True`` (the default),
    which then breaks the dashboard's ``JSON.parse``. Apply this coercion
    immediately before ``json.dump`` at every storage boundary that may
    carry the ``float('-inf')`` "no-signal" sentinel produced by
    :func:`score_vector` and the grand-mean log helpers.

    Pydantic ``Optional[float]`` fields accept ``None`` on round-trip, so
    the on-disk representation is browser-safe and Python-safe.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: coerce_nonfinite_to_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [coerce_nonfinite_to_none(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(coerce_nonfinite_to_none(v) for v in obj)
    return obj
