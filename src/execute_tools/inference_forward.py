"""One model-input boundary for task-data-path inference and its preflight."""

from __future__ import annotations

import torch


class InferenceInputError(TypeError):
    """A forward call rejected the input prepared by the execution boundary."""


def forward_inference_batch(
    model: torch.nn.Module,
    inputs: torch.Tensor,
    *,
    device: torch.device,
    input_dtype: torch.dtype | None,
    stage: str,
) -> torch.Tensor:
    """Convert at the model boundary and report context without dumping data.

    ``input_dtype`` is required: callers must pass the resolved contract dtype
    or explicitly preserve dataset dtype with ``None``. Model evaluation mode
    is owned by the caller. OOM and other runtime exceptions keep their types.
    """
    source_dtype = inputs.dtype
    prepared = inputs.to(device=device, dtype=input_dtype or source_dtype)
    try:
        with torch.no_grad():
            return model(prepared)
    except TypeError as exc:
        raise InferenceInputError(
            f"{stage}: model={type(model).__name__}, storage_dtype={source_dtype}, "
            f"resolved_input_dtype={input_dtype}, actual_input_dtype={prepared.dtype}, "
            f"shape={tuple(prepared.shape)}, device={prepared.device}; "
            f"forward rejected the prepared input: {exc}. Check the model-I/O "
            "declaration and execution adapter before retrying training."
        ) from exc
