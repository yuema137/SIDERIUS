"""Apply a :class:`~core.training_seeds.TrainingSeedPlan` to process RNGs and loaders.

Contract: ``docs/agent-reference/mechanisms/seeding.md``. Used inside the
training child, where torch and NumPy are already loaded; the torch-free plan
lives in ``core/training_seeds.py``.
"""

from __future__ import annotations

import random

import numpy as np
import torch

from core.training_seeds import ProcessSeedRecord, TrainingSeedPlan


def seed_process(plan: TrainingSeedPlan) -> ProcessSeedRecord:
    """Seed Python ``random``, legacy NumPy and torch (CPU and every CUDA device).

    Call before the first RNG consumer, i.e. before model construction.
    ``torch.manual_seed`` also seeds all CUDA devices (lazily when CUDA is
    not yet initialised).
    """
    record = plan.process_seeds()
    random.seed(record.python)
    np.random.seed(record.numpy)
    torch.manual_seed(record.torch)
    return record


def torch_generator(seed: int) -> torch.Generator:
    """A CPU generator for a ``DataLoader`` sampler, seeded with a derived seed."""
    generator = torch.Generator()
    generator.manual_seed(seed)
    return generator


def dataloader_worker_init(worker_id: int) -> None:
    """Seed a loader worker's Python and NumPy RNGs from its torch seed.

    In a worker, ``torch.initial_seed()`` is the loader generator's base seed
    plus ``worker_id``, so it is already derived and distinct per worker.
    """
    del worker_id
    seed = torch.initial_seed()
    np.random.seed(seed % 2**32)
    random.seed(seed)
