"""The ONE bounded probe-batch builder for pre-phase GPU measurement.

Step 07 / PR 07c C2. Before this module there were TWO loaders producing
byte-identical batches from three hardcoded TIDMAD facts:

* the channel name pair ``channel0001`` / ``channel0002``;
* the class-index offset ``+128`` and its ``int8 -> int16`` cast chain;
* the filename family ``abra_training_*.h5``, globbed.

None of those is a property of *measurement*; every one is a property of the
DATASET, and every one is already declared on
:class:`~execute_tools.dataset_config.DatasetProfile`. This module derives
them from the resolved profile instead, so binding a different task moves the
bytes the measurement reads rather than silently measuring TIDMAD's.

**The bounded read is the property that must survive.** The predecessor
``load_probe_batch`` reached ``TIDMADDataset``, which materializes the whole
channel before ``max_segments`` is applied: for one 2,010,000,000-sample file
that is ~13 GiB live at once, and Gate 2 Lite-A case c1 was TERMed at
**24.10 GiB host RSS before the model was built** — to produce a batch
occupying 0.31 MiB on the GPU (V20 PR C2 / D-C2-12). This builder reads
exactly ``batch_size x segment_length`` samples by slicing, and there is no
``np.array(channel)`` anywhere in it.

**What it reproduces, exactly.** With ``sample_size=1`` the production path
reduces to contiguous slicing::

    num_segments  = len(channel) // (1 * seg_size)
    idict[f][i]  == alltrain[i*seg_size : (i+1)*seg_size]
    dataset[i][0] = idict[f][i].astype(compute_dtype) + value_offset

so segment ``i`` is the contiguous slice ``[i*seg : (i+1)*seg]`` of the
declared INPUT channel, widened and shifted by the declared encoding. The
target channel is never touched, because a probe batch is only the input.

**NO FALLBACK, and no implicit task.** The profile is a required argument:
callers resolve it from what they hold (the measurement spec's transport, or
the Regime-A seam in-process) and pass it down, exactly as
``resolve_dataset_profile``'s own contract asks subprocess entry points to.
A builder that reached for a default profile would reinstate by omission the
task assumption this module exists to remove. When bounded access is
impossible this raises; it must never quietly widen the read.
"""

from __future__ import annotations

import os
from typing import Any, cast

# `BoundedReadEvidence` / `BoundedProbeBatch` keep their home in
# `core.runtime_control.gpu_measurement_data`, which is where every consumer
# already imports them from. Importing them here (rather than moving them) is
# what makes this a delegation instead of a relocation, and the direction is
# the one `execute_tools` already uses elsewhere — `train_engine_sandbox` and
# `inference_single` both import `core.runtime_control` at module level.
from core.runtime_control.gpu_measurement_data import (
    BoundedProbeBatch,
    BoundedReadEvidence,
)
from execute_tools.dataset_config import (
    DatasetProfile,
    tidmad_topology,
)

__all__ = ["build_bounded_probe_batch", "resolve_declared_source_file"]

#: The HDF5 group structure the file format uses. NOT a task fact: it is the
#: container layout, identical for every profile that ships this format, and
#: `DatasetProfile` declares channel IDENTITY rather than container paths.
_TIMESERIES_GROUP = "timeseries"


def resolve_declared_source_file(profile: DatasetProfile, data_dir: str) -> str:
    """The first DECLARED training file that exists under ``data_dir``.

    Q-07c-2. The predecessor globbed ``abra_training_*.h5`` and took
    ``sorted(...)[0]``, which has two defects: the pattern was re-inlined
    rather than read from the profile, and any file matching the glob would be
    consumed even if the profile never declared it.

    So the declared indices ``0 .. num_files-1`` are enumerated in order and
    the first EXISTING one wins. On a healthy dataset that is index 0 —
    identical to the glob. On a gappy one it is the first present declared
    index — also identical to the glob. The behaviours diverge only where the
    glob was wrong: an UNDECLARED file sitting in the directory is never
    substituted for a declared one.

    Raises:
        RuntimeError: no declared training file is present.
    """
    declared = [
        tidmad_topology(profile).dataset.training_file_name(i)
        for i in range(profile.partition_count)
    ]
    for name in declared:
        candidate = os.path.join(data_dir, name)
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError(
        f"no declared training file exists under {data_dir!r}. The profile declares "
        f"{len(declared)} training file(s) ({declared[0]!r} … {declared[-1]!r}) and none "
        f"of them is present. A file found on disk that the profile does not declare is "
        f"never substituted — that would measure data the task did not claim."
    )


def build_bounded_probe_batch(
    *,
    profile: DatasetProfile,
    data_dir: str,
    batch_size: int,
    segment_length: int,
) -> BoundedProbeBatch:
    """``[batch_size, segment_length]`` int64 class indices, read by slicing.

    Args:
        profile: The resolved dataset declaration. Supplies the input channel,
            the storage/compute dtypes, the value offset and the training
            filename family. Required — see the module docstring.
        data_dir: Resolved dataset root.
        batch_size: Number of segments in the batch.
        segment_length: Samples per segment.

    Returns:
        The batch tensor and the evidence that producing it stayed bounded.

    Raises:
        RuntimeError: no declared file is present, the declared input channel
            is absent from the file, or the file holds fewer samples than the
            batch needs. Never a fallback to a wider read.
    """
    import h5py
    import torch

    source = resolve_declared_source_file(profile, data_dir)
    channel_name = tidmad_topology(profile).channels.input_channel
    encoding = tidmad_topology(profile).encoding
    needed = batch_size * segment_length

    with h5py.File(source, "r") as handle:
        try:
            # Type-only shim, mirroring `train_engine_sandbox._h5_dataset`:
            # h5py's stubs type `__getitem__` as `Group | Dataset | Datatype`,
            # so the chained subscript and the later `.shape` / slice /
            # `.astype` / `.nbytes` are all rejected under strict. Walking
            # through `Any` short-circuits the union and the cast records the
            # invariant every call site already relies on. The three
            # subscripts, their order, and the exceptions they raise are
            # unchanged.
            node: Any = handle[_TIMESERIES_GROUP]
            channel = cast("h5py.Dataset", node[channel_name][_TIMESERIES_GROUP])
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"bounded access is impossible: {source!r} has no "
                f"{_TIMESERIES_GROUP}/{channel_name}/{_TIMESERIES_GROUP} ({exc!r}), and "
                f"{channel_name!r} is the input channel this dataset profile declares. "
                "The measurement does not fall back to a full-file loader."
            ) from exc
        available = int(channel.shape[0])
        if available < needed:
            raise RuntimeError(
                f"dataset too small for a bounded probe batch: {available} samples "
                f"< {needed} required ({batch_size} x {segment_length})"
            )
        # THE bounded read: exactly the samples the batch needs, and no
        # `np.array(channel)` anywhere. h5py returns a fresh ndarray for the
        # slice, so nothing larger is ever materialised.
        raw = channel[0:needed]

    # The declared cast chain, in order: the samples are `storage_dtype` on
    # disk and the loader re-casts to it (a no-op for a matching source, kept
    # explicit so a wider source dtype truncates identically), then widens to
    # `compute_dtype` and adds the offset that moves a stored sample into
    # `[0, num_classes)`.
    segments = raw.astype(encoding.storage_dtype).astype(encoding.compute_dtype)
    segments = segments + encoding.value_offset
    tensor = torch.as_tensor(segments.reshape(batch_size, segment_length)).long()

    return BoundedProbeBatch(
        tensor=tensor,
        evidence=BoundedReadEvidence(
            source_file=os.path.basename(source),
            channel=channel_name,
            segment_count=batch_size,
            segment_length=segment_length,
            first_sample=0,
            last_sample=needed,
            bytes_read=int(raw.nbytes),
            file_sample_count=available,
        ),
    )
