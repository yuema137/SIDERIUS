"""Shared batch-boundary arithmetic and sample-weighted epoch loss."""

import numpy as np


def optimizer_steps_for_rows(rows: int, batch_size: int, *, drop_last: bool = True) -> int:
    if rows < 0 or batch_size <= 0:
        raise ValueError(
            "training batch geometry requires nonnegative rows and positive batch size"
        )
    return rows // batch_size if drop_last else (rows + batch_size - 1) // batch_size


def completed_epoch_loss(losses: list[float], batch_rows: list[int], *, drop_last: bool) -> float:
    if not losses or len(losses) != len(batch_rows) or any(n <= 0 for n in batch_rows):
        raise ValueError("epoch loss requires one positive sample count per completed batch")
    # Equal-batch legacy trajectory/bytes stay unchanged. A retained tail must
    # not receive the same weight as a larger batch in the reported objective.
    return float(np.mean(losses) if drop_last else np.average(losses, weights=batch_rows))
