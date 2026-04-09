"""
Regime aggregation for per-file denoising scores.

The TIDMAD validation set injects 309 sinusoidal signals into 20 files,
distributed sequentially in ascending frequency. Each file therefore covers
a contiguous frequency band, and the per-file denoising score is a direct
proxy for how well the model handles that band. See
``docs/tidmad_signal_frequencies.txt`` and
``tuner_advice/gated_fno_freq_band_aware_v1.json`` for the empirical map.

This module aggregates the per-file score vector (``file_vector``) into a
small dict of per-regime scores. The aggregation is fully deterministic
Python — no LLM calls — and the result is added to every experiment record
so the LLM gets a structured "gradient" instead of a 20-element raw array.

The dict shape is the deliberate extension point for the future Data
Analysis Agent (see ``docs/adaptive_new_model_proposer.md`` §2D): new
regime keys can be added without a schema migration.
"""
from __future__ import annotations

from typing import Dict, List, Optional


# Per-regime → list of file indices the regime aggregates over.
# Mirrors tuner_advice/gated_fno_freq_band_aware_v1.json:
#   files  0– 4 :  1.1 kHz –  9.0 kHz   (low kHz, dense sampling)
#   files  5–10 :  9.1 kHz – 94.0 kHz   (mid kHz, 10 kHz steps)
#   files 11–19 : 95.0 kHz – 4.9 MHz    (high kHz / MHz, sparse sampling)
#   global      : all files
#
# Adding a new regime is a one-line edit. Removing a regime is allowed but
# discouraged — downstream code that has come to rely on a regime key may
# break, so prefer to add new regimes alongside the existing ones.
REGIME_DEFINITIONS: Dict[str, List[int]] = {
    "low_freq_kHz":   [0, 1, 2, 3, 4],
    "mid_freq_10kHz": [5, 6, 7, 8, 9, 10],
    "high_freq_MHz":  [11, 12, 13, 14, 15, 16, 17, 18, 19],
    "global":         list(range(20)),
}


def aggregate_regime_scores(
    file_vector: Optional[List[Optional[float]]],
) -> Dict[str, float]:
    """Aggregate a per-file score vector into per-regime mean scores.

    Args:
        file_vector: A list of length 20 (one entry per validation file).
            Entries may be ``None`` for files that were not scored in this
            run (e.g. trial mode skipped them, or scoring failed). May also
            be ``None`` itself if the run had no scoring step.

    Returns:
        A dict with one entry per regime defined in ``REGIME_DEFINITIONS``.
        Each entry is the arithmetic mean of the non-None per-file scores
        within that regime. A regime whose files are all None gets ``0.0``
        (NOT ``None``) so downstream code never has to None-check the
        per-regime values. The full set of seed regime keys is always
        present in the output, even when the input is empty — this makes
        cross-experiment aggregation safe.

    Examples:
        >>> aggregate_regime_scores([1.0] * 20)
        {'low_freq_kHz': 1.0, 'mid_freq_10kHz': 1.0, 'high_freq_MHz': 1.0, 'global': 1.0}

        >>> aggregate_regime_scores(None)
        {'low_freq_kHz': 0.0, 'mid_freq_10kHz': 0.0, 'high_freq_MHz': 0.0, 'global': 0.0}

        >>> # Sparse: only files 0-4 scored, rest are None
        >>> v = [0.5, 0.5, 0.5, 0.5, 0.5] + [None] * 15
        >>> aggregate_regime_scores(v)
        {'low_freq_kHz': 0.5, 'mid_freq_10kHz': 0.0, 'high_freq_MHz': 0.0, 'global': 0.5}
    """
    if not file_vector:
        return {regime: 0.0 for regime in REGIME_DEFINITIONS}

    out: Dict[str, float] = {}
    for regime, file_indices in REGIME_DEFINITIONS.items():
        valid_scores = [
            file_vector[i]
            for i in file_indices
            if i < len(file_vector) and file_vector[i] is not None
        ]
        out[regime] = (
            float(sum(valid_scores) / len(valid_scores))
            if valid_scores
            else 0.0
        )
    return out
