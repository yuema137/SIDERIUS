"""Bounded data access for the C2 pre-phase measurement worker.

V20 PR C2 / D-C2-12, operator decision 2026-08-03, after Gate 2 Lite-A c1
failed.

WHAT HAPPENED. `load_probe_batch` -> `TIDMADDataset.pull_event_from_dir`
reads the WHOLE channel before `max_segments` is applied
(`train_engine_sandbox.py:110-132`): `np.array(channel0001).astype(np.int8)`,
`np.array(channel0002).astype(np.int16)`, two reshaped index copies and a
`bincount` temporary. For one 2,010,000,000-sample file that is ~13 GiB live
at once. `max_segments` truncates the EVENT LIST at line 131 -- after all of
it -- so it bounds nothing.

Under the worker's 24 GiB host cap the measurement was TERMed at **24.10 GiB
RSS before the model was built**: zero phases, zero forward passes. To
produce a batch that occupies **0.31 MiB** on the GPU.

WHERE EQUIVALENCE IS REQUIRED, AND WHERE IT IS NOT. C2 measures live GPU
capacity for the exact candidate, so the tensor delivered to the device, the
model, the optimizer, dtype, shape, channel order, the loss and the
forward/backward/step must all match production. Reproducing an *avoidable
host-side full-file copy* is not part of that: the same device tensor is
constructible from bounded reads, and the trainer's host cost is not the
GPU requirement.

WHAT THIS REPRODUCES, EXACTLY. With `sample_size=1` -- which is what
`load_probe_batch` passes -- the production path reduces to contiguous
slicing:

```text
num_segments  = len(channel) // (1 * seg_size)
random_offset = np.random.randint(0, 1)          # always 0
idict[f]      = alltrain[:num_segments*seg_size]
                  .reshape(num_segments, 1, seg_size)[:, 0, :]
idict[f][i]  == alltrain[i*seg_size : (i+1)*seg_size]
dataset[i][0] = idict[f][i].astype(np.int16) + 128
```

So segment `i` is the contiguous slice `[i*seg : (i+1)*seg]` of
`channel0001`, cast to int16 and shifted by +128 -- reproduced here by
reading exactly that slice from HDF5. `channel0002` is never touched,
because `load_probe_batch` returns only the input.

NO FALLBACK. When bounded access is impossible this raises. It must never
quietly reach for `load_probe_batch`: the whole point is that the
unbounded path cannot run under the cap, and silently taking it would
restore the failure it exists to remove.
"""

from __future__ import annotations

import glob
import os
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

#: The production dataset's channel roles. Named rather than positional so a
#: swap is a visible edit; `channel0001` is the input the trainer feeds the
#: model and `channel0002` is the clean target.
INPUT_CHANNEL = "channel0001"
TARGET_CHANNEL = "channel0002"

#: What `TIDMADDataset.__getitem__` adds after casting to int16. An int8
#: sample in [-128, 127] becomes a class index in [0, 255].
CLASS_INDEX_OFFSET = 128


class BoundedReadEvidence(BaseModel):
    """What was actually read, so the bound is auditable rather than claimed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_file: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    segment_count: int = Field(gt=0)
    segment_length: int = Field(gt=0)
    #: The half-open sample range actually requested from HDF5.
    first_sample: int = Field(ge=0)
    last_sample: int = Field(gt=0)
    bytes_read: int = Field(gt=0)
    #: Samples in the file. Recorded so the ratio between what exists and
    #: what was read is visible in the artifact.
    file_sample_count: int = Field(gt=0)

    @property
    def fraction_of_file_read(self) -> float:
        return self.bytes_read / max(1, self.file_sample_count)


class BoundedProbeBatch(BaseModel):
    """The batch, and the evidence that producing it stayed bounded."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    tensor: Any
    evidence: BoundedReadEvidence


def load_bounded_probe_batch(
    *, data_dir: str, batch_size: int, segment_length: int
) -> BoundedProbeBatch:
    """`[batch_size, segment_length]` int64, read by slicing.

    Byte-identical to `load_probe_batch` for the same file, indices and
    configuration -- proved against the production loader on a fixture in
    `tests/unit/core/test_gpu_measurement_data.py`, not asserted here.

    Raises rather than falling back. A dataset that cannot be sliced is an
    infrastructure condition the caller reports; reaching for the unbounded
    loader would reinstate the 24 GiB materialization this exists to avoid.
    """
    import h5py
    import numpy as np
    import torch

    files = sorted(glob.glob(os.path.join(data_dir, "abra_training_*.h5")))
    if not files:
        raise RuntimeError(f"no abra_training_*.h5 files under {data_dir!r}")
    source = files[0]
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
            node: Any = handle["timeseries"]
            channel = cast("h5py.Dataset", node[INPUT_CHANNEL]["timeseries"])
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"bounded access is impossible: {source!r} has no "
                f"timeseries/{INPUT_CHANNEL}/timeseries ({exc!r}). The C2 worker "
                "does not fall back to the full-file loader."
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

    # The production cast chain, in order: the whole channel is int8 on disk
    # and `pull_event_from_dir` casts it to int8 (a no-op here, kept explicit
    # so a wider source dtype would truncate identically), then
    # `__getitem__` casts to int16 and adds the class offset.
    segments = raw.astype(np.int8).astype(np.int16) + CLASS_INDEX_OFFSET
    tensor = torch.as_tensor(segments.reshape(batch_size, segment_length)).long()

    return BoundedProbeBatch(
        tensor=tensor,
        evidence=BoundedReadEvidence(
            source_file=os.path.basename(source),
            channel=INPUT_CHANNEL,
            segment_count=batch_size,
            segment_length=segment_length,
            first_sample=0,
            last_sample=needed,
            bytes_read=int(raw.nbytes),
            file_sample_count=available,
        ),
    )
