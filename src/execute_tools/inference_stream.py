"""Shared task-inference forward, output consumption and tensor lifetimes."""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from typing import Any

import torch

from execute_tools.inference_forward import forward_inference_batch
from execute_tools.inference_runtime import InferenceRuntimeEvidence


@dataclass
class InferenceProgress:
    """Counts observed while the caller consumes the prediction stream."""

    batches: int = 0
    samples: int = 0


def prediction_stream(
    batches: Iterable[Any],
    *,
    model: torch.nn.Module,
    device: torch.device,
    input_dtype: torch.dtype | None,
    progress: InferenceProgress,
    stage: str,
    runtime_evidence: InferenceRuntimeEvidence | None = None,
    observe_forward: Callable[[torch.Tensor, torch.Tensor], None] | None = None,
) -> Generator[torch.Tensor, None, None]:
    """Yield detached CPU predictions in the materialized dataset's order.

    This preserves the existing production loop's allocation lifetime: the
    previous predictions and final item view survive until their next
    assignments. Measurement must execute that same loop, not release them
    early and report a smaller workload. The optional observer sees the real
    input and resident output; it does not replace the forward or consumption.
    """
    iterator = iter(batches)
    while True:
        started = runtime_evidence.start_batch() if runtime_evidence is not None else 0.0
        try:
            batch = next(iterator)
        except StopIteration:
            break
        inputs = batch[0] if isinstance(batch, (list, tuple)) else batch
        predictions = forward_inference_batch(
            model, inputs, device=device, input_dtype=input_dtype, stage=stage
        )
        progress.batches += 1
        if observe_forward is not None:
            observe_forward(inputs, predictions)
        for prediction in predictions:
            progress.samples += 1
            yield prediction.detach().cpu()
        if runtime_evidence is not None:
            runtime_evidence.finish_batch(started, len(predictions))
