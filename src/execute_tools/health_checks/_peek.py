# execute_tools/health_checks/_peek.py
"""
Shared HDF5-peek primitives for health checks that need int8 sample streams.

Both ``OutputDiversityCheck`` (unique-value count) and
``AmplitudeCollapseCheck`` (single-bin dominance) operate on a small peek
of the first denoised HDF5's INPUT channel. The peek walk is identical
(``timeseries/<channel>/timeseries[:peek_samples]``); this module owns
it so checks don't drift. The channel identity is supplied by the
caller from the Deliverable Contract (Step 08a C5), never spelled here.

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

from execute_tools.deliverable_spec import default_deliverable_storage
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
        channel: Channel-group key inside ``timeseries``. Supply it from
            the Deliverable Contract's ``input_channel_group`` (model
            output in denoised files, raw noisy readout in ground-truth
            files) or ``target_channel_group`` (the injected truth
            signal) — this module never names a channel itself.
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
    """Read up to ``peek_samples`` from the INPUT channel of an HDF5 file.

    Thin wrapper around ``peek_int8_at_channel`` preserving the pre-M8
    signature — all existing callers continue to work unchanged.

    **Deprecated (M9; kept for compatibility).** New code should call
    ``peek_int8_at_channel`` with a channel resolved from the Deliverable
    Contract, as the checks now do.

    Step 08a C5: the channel identity comes from the contract rather than
    from a literal here. The VALUE is unchanged — the contract derives
    ``input_channel_group`` from the same profile the pre-C5 literal
    transcribed — so every existing caller reads the same bytes.

    See ``peek_int8_at_channel`` for full docstring, args, and errors.
    """
    return peek_int8_at_channel(
        path, default_deliverable_storage().input_channel_group, peek_samples
    )
