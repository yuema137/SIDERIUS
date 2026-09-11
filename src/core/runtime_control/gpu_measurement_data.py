"""Bounded data access for the C2 pre-phase measurement worker.

V20 PR C2 / D-C2-12, operator decision 2026-08-03, after Gate 2 Lite-A c1
failed.

WHAT HAPPENED. `load_probe_batch` -> `TIDMADDataset.pull_event_from_dir`
read the WHOLE channel before `max_segments` was applied: for one
2,010,000,000-sample file that is ~13 GiB live at once. Under the worker's
24 GiB host cap the measurement was TERMed at **24.10 GiB RSS before the
model was built**: zero phases, zero forward passes. To produce a batch that
occupies **0.31 MiB** on the GPU.

WHERE EQUIVALENCE IS REQUIRED, AND WHERE IT IS NOT. C2 measures live GPU
capacity for the exact candidate, so the tensor delivered to the device, the
model, the optimizer, dtype, shape, channel order, the loss and the
forward/backward/step must all match production. Reproducing an *avoidable
host-side full-file copy* is not part of that: the same device tensor is
constructible from bounded reads, and the trainer's host cost is not the
GPU requirement.

WHAT THIS MODULE IS NOW (Step 07 / PR 07c C2). The batch-building work moved
to `execute_tools.probe_batch.build_bounded_probe_batch`, the ONE builder both
the worker and the in-process probe path go through, which derives the channel
identity, the value encoding and the training filename family from the
resolved `DatasetProfile` instead of from module constants. What stays here is
the evidence contract — `BoundedReadEvidence` / `BoundedProbeBatch`, the
schemas that make the bound auditable rather than claimed — and the worker's
entry point.

NO FALLBACK. When bounded access is impossible this raises. It must never
quietly widen the read: the whole point is that the unbounded path cannot run
under the cap, and silently taking it would restore the failure it exists to
remove. The unbounded loader no longer exists to fall back TO (Q-07c-1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from execute_tools.dataset_config import DatasetProfile


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
    *,
    data_dir: str,
    batch_size: int,
    segment_length: int,
    profile: DatasetProfile | None = None,
) -> BoundedProbeBatch:
    """`[batch_size, segment_length]` int64, read by slicing.

    The worker's seam onto the one builder. It exists as a separate name
    because the worker stubs THIS symbol in tests
    (`tests/unit/core/test_gpu_measurement_worker.py`), and because the
    Regime-A resolution below is a property of the CALL SITE, not of the
    builder — the builder itself requires an explicit profile so it can never
    assume a task by omission.

    Args:
        data_dir: Resolved dataset root.
        batch_size: Number of segments in the batch.
        segment_length: Samples per segment.
        profile: The resolved dataset declaration, transported by the caller.
            `None` resolves the Regime-A adapter, which keeps a spec
            serialized before the transport existed working unchanged — the
            same convention `TIDMADDataset` and `build_sample_set` use.

    Raises:
        RuntimeError: no declared file is present, the declared input channel
            is absent, or the file is smaller than the batch needs.
    """
    from execute_tools import probe_batch
    from execute_tools.dataset_config import resolve_dataset_profile

    return probe_batch.build_bounded_probe_batch(
        profile=profile or resolve_dataset_profile(),
        data_dir=data_dir,
        batch_size=batch_size,
        segment_length=segment_length,
    )
