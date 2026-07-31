"""Probe batch loader (C6b) — a few REAL segments for the bounded probe.

F-1a: callers resolve ``data_dir`` through the single source of truth
(``execute_tools.data_paths.TIDMAD_DATA_DIR``) before calling; this
helper only loads. A missing/empty dataset raises — never a synthetic
fallback (design contract F-1a: no silent static/synthetic degradation).
"""

from __future__ import annotations

import glob
import os


def load_probe_batch(*, data_dir: str, batch_size: int, segment_length: int):
    """Return an int64 tensor ``[batch_size, segment_length]`` of real ADC
    segments from the first available training file."""
    import torch

    from execute_tools.train_engine_sandbox import TIDMADDataset

    files = sorted(glob.glob(os.path.join(data_dir, "abra_training_*.h5")))
    if not files:
        raise RuntimeError(f"no abra_training_*.h5 files under {data_dir!r}")
    # sample_size=1: the probe reads SEQUENTIAL segments (the production
    # sampling stride of 20 exists to decorrelate training windows and
    # would demand 20x the data just to index one segment — a probe batch
    # needs real bytes, not decorrelation).
    dataset = TIDMADDataset(
        data_dir,
        [os.path.basename(files[0])],
        segmentation_size=segment_length,
        sample_size=1,
        max_segments=batch_size,
    )
    if len(dataset) < batch_size:
        raise RuntimeError(
            f"dataset too small for probe batch: {len(dataset)} segments < batch_size {batch_size}"
        )
    segments = [torch.as_tensor(dataset[i][0]) for i in range(batch_size)]
    return torch.stack(segments).long()
