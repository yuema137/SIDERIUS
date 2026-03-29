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
"""

import os
import gc
import numpy as np
import h5py


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEGMENT_LENGTH = 10_000_000  # 1-second PSD segment (10 MS/s sampling rate)
SEGMENTS_PER_FILE = 200      # usable segments per validation file
NUM_FILES = 20               # validation files 0–19


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

    Args:
        file_path: Directory containing the HDF5 files.
        files:     Filename or list of filenames (each 200 seconds).
        ch:        Channel number (1 = SQUID/denoised, 2 = ground truth).
        start:     Segment index (0-based). Segment ``start`` in file
                   ``start // 200`` at offset ``(start % 200) * SEGMENT_LENGTH``.

    Returns:
        (freq_array, psd_chunk) — frequency bins and PSD values.
    """
    if isinstance(files, str):
        file_list = [os.path.join(file_path, files)]
    else:
        file_list = [os.path.join(file_path, f) for f in files]

    file_num = start // SEGMENTS_PER_FILE
    start_index = SEGMENT_LENGTH * (start % SEGMENTS_PER_FILE)

    file = file_list[file_num]
    with h5py.File(file, "r") as h5f:
        channel_key = f"channel{ch:04d}"
        data = h5f["timeseries"][channel_key]["timeseries"][
            start_index : start_index + SEGMENT_LENGTH
        ]

        volt_range = h5f["timeseries"]["channel0001"].attrs["voltage_range_mV"]
        sampling_freq = h5f["timeseries"]["channel0001"].attrs["sampling_frequency"]

        scaling = np.float32(volt_range / (2 * 128.0))
        ts = np.array(data, dtype=np.float32) * scaling
        dt = 1.0 / sampling_freq

        psd_chunk = (
            dt / SEGMENT_LENGTH * (abs(np.fft.rfft(ts)) ** 2)
        )[1:]
        freq_array = np.linspace(0, sampling_freq / 2, SEGMENT_LENGTH // 2)

    del data, ts
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

    Args:
        freq:   Frequency array from ``get_one_sec_psd``.
        pwr:    PSD array from ``get_one_sec_psd``.
        target: Target frequency (Hz). 0 = auto-detect peak.

    Returns:
        (snr, center_freq) — the SNR value and the frequency of the peak.
    """
    if target == 0:
        center_id = find_peak(pwr)
    else:
        center_id = int(np.where(freq == target)[0][0])

    sig_range = 1
    noise_range = 50
    signal = np.sum(pwr[center_id - sig_range : center_id + sig_range + 1])
    noise = (
        np.sum(pwr[center_id - noise_range : center_id + noise_range + 1]) - signal
    )
    if noise <= 0:
        noise = 1e-5
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
        file_index:         Which validation file (0–19) this corresponds to.
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


def score_vector(
    data_dir: str,
    sample_set: SampleSet,
    anchor_map: dict,
    s_max: float,
    denoised_filename_fn: callable = None,
    raw_data_dir: str | None = None,
) -> tuple[list[float], float]:
    """
    Score multiple files and return the length-20 score vector + scalar.

    Args:
        data_dir:              Directory containing the denoised HDF5 files.
        sample_set:            ``{file_index: [segment_indices]}`` — which
                               segments to score per file.
        anchor_map:            The ``"anchors"`` dict from ``segment_anchors.json``.
        s_max:                 Global maximum CH2 SNR from the anchor map.
        denoised_filename_fn:  Optional callable ``(file_index) → filename``.
                               Defaults to ``"abra_validation_denoised_{model}_{idx}.h5"``
                               pattern — but since the model name varies, the caller
                               should provide this.
        raw_data_dir:          Directory containing the raw validation files
                               (``abra_validation_XXXX.h5``). Defaults to
                               ``data_dir`` when ``None``.

    Returns:
        (file_vector, final_scalar_score):
        - ``file_vector``: length-20 list. ``float('nan')`` for files not in
          the sample set.
        - ``final_scalar_score``: ``log_{5.27}(mean_of_non_nan + 1e-10)``.

    Raises:
        ValueError: If ``denoised_filename_fn`` is None and the caller hasn't
                    provided a way to resolve denoised filenames.
    """
    import math

    if denoised_filename_fn is None:
        raise ValueError(
            "denoised_filename_fn is required — the scorer needs to know "
            "which denoised file to read for each file_index."
        )

    file_vector = [float("nan")] * NUM_FILES

    for file_index, segment_indices in sample_set.items():
        denoised_filename = denoised_filename_fn(file_index)
        file_vector[file_index] = score_segments(
            data_dir=data_dir,
            denoised_filename=denoised_filename,
            file_index=file_index,
            segment_indices=segment_indices,
            anchor_map=anchor_map,
            s_max=s_max,
            raw_data_dir=raw_data_dir,
        )

    # Aggregate: mean of non-NaN entries
    valid_scores = [s for s in file_vector if not math.isnan(s)]
    if valid_scores:
        mean_score = sum(valid_scores) / len(valid_scores)
        final_scalar = math.log(mean_score + 1e-10, 5.27)
    else:
        final_scalar = float("-inf")

    return file_vector, final_scalar
