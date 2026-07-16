# execute_tools/health_checks/_peek.py
"""
Shared HDF5-peek primitives for health checks that need int8 sample streams.

Both ``OutputDiversityCheck`` (unique-value count) and
``AmplitudeCollapseCheck`` (single-bin dominance) operate on a small peek
of the first denoised HDF5's ``channel0001`` dataset. The peek walk is
identical (``timeseries/channel0001/timeseries[:peek_samples]``); this
module owns it so checks don't drift.

Design split:
    * ``choose_peek_file_index(ctx)`` — pick which file_index to peek at
      (AMB-4-5 → A: min explicit key, else 0).
    * ``peek_int8_at_path(path, peek_samples)`` — pure file I/O. Raises
      ``OSError`` / ``KeyError`` on error; the check catches these and
      builds a ``passed=False`` result with the path baked into the
      failure reason. This keeps the peek primitive dumb and lets each
      check own its "not applicable" vs "peek failed" policy.

Path contract (AMB-4-3 → A): the string returned by
``ctx.get_denoised_path(file_index)`` is used verbatim — must be either
an absolute path or CWD-relative. Callers of the health-check runner
(score_vector Phase 0/3, tuner integration in commit-5) join any base
directory themselves before building the context.
"""

from __future__ import annotations

from typing import Any, cast

import h5py
import numpy as np

from execute_tools.health_checks.schemas import HealthCheckContext


def choose_peek_file_index(ctx: HealthCheckContext) -> int:
    """Legacy single-file peek-target resolver.

    **Deprecated (M9)**: use ``peek_and_aggregate`` from
    ``execute_tools/health_checks/_multi_file_peek.py`` with an empty
    ``peek_file_indices`` (which triggers the same single-file fallback
    semantic). Retained for backward compatibility with callers not yet
    migrated. Do not use in new code.

    Uses the smallest explicit key in ``ctx.denoised_paths`` when the
    dict is non-empty; otherwise defaults to 0 so
    ``denoised_filename_fn(0)`` is called.
    """
    if ctx.denoised_paths:
        return min(ctx.denoised_paths)
    return 0


def peek_int8_at_channel(path: str, channel: str, peek_samples: int) -> np.ndarray:
    """Read up to ``peek_samples`` from a named channel of a TIDMAD HDF5 file.

    Generalises the CH1-only ``peek_int8_at_path``. Pure I/O — no
    context awareness, no error swallowing. The caller supplies a
    fully-resolved path and channel name and receives either the samples
    array or a raised exception it can classify.

    Args:
        path: Absolute or CWD-relative path to the HDF5 file.
        channel: Channel key inside ``timeseries`` — e.g. ``"channel0001"``
            (model output in denoised files, raw noisy readout in
            ground-truth files) or ``"channel0002"`` (target DM signal).
        peek_samples: Upper bound on how many leading samples to read.
            The returned array's shape reflects the actual read — reading
            fewer than requested is normal for tiny fixtures (numpy's
            slice does not extend past dataset end).

    Returns:
        A numpy array of the sample dtype (typically ``int8``).

    Raises:
        OSError: File missing, unreadable, or not a valid HDF5 file
            (includes ``FileNotFoundError`` as a subclass).
        KeyError: A step in the ``timeseries/<channel>/timeseries`` walk
            is absent from the file structure.
    """
    with h5py.File(path, "r") as h5f:
        # h5py's __getitem__ union type forces the Any-then-cast dance
        # (same pattern as scoring_utils._h5_dataset).
        node: Any = h5f
        for k in ("timeseries", channel, "timeseries"):
            node = node[k]
        dset = cast(h5py.Dataset, node)
        return np.asarray(dset[:peek_samples])


def peek_int8_at_path(path: str, peek_samples: int) -> np.ndarray:
    """Read up to ``peek_samples`` from ``channel0001`` of an HDF5 file.

    Thin wrapper around ``peek_int8_at_channel`` preserving the pre-M8
    signature — all existing callers continue to work unchanged.

    See ``peek_int8_at_channel`` for full docstring, args, and errors.
    """
    return peek_int8_at_channel(path, "channel0001", peek_samples)
