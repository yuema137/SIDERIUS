"""Observe registered model state without executing a forward or allocating a device.

The projection prices each unique Parameter object and each buffer slot in
unique module objects. It deliberately does not deduplicate host storage:
allocating device/dtype conversion can separate aliased tensors. Frozen state
is resident but does not receive gradient or optimizer-state pricing.
"""

from __future__ import annotations

import torch
from torch import nn

from core.preflight_observations import RegisteredStateInventory


def _projected_tensor_bytes(tensor: torch.Tensor) -> int:
    if torch.nn.parameter.is_lazy(tensor):
        raise ValueError("unmaterialized registered tensor")
    if tensor.is_meta:
        raise ValueError("meta registered tensor has no materialized allocation")
    if tensor.layout != torch.strided or tensor.is_quantized:
        raise ValueError(
            f"unsupported registered tensor layout/dtype: {tensor.layout}, {tensor.dtype}"
        )
    return tensor.numel() * tensor.element_size()


def inventory_registered_state(module: nn.Module) -> RegisteredStateInventory:
    """Return complete projected accounting or explicit unavailable evidence.

    Enumerating slots includes parent-owned, unused and nonpersistent state.
    None registrations are empty slots. Parameter aliases are deduplicated by
    object identity across the module tree; separate buffer slots remain
    separate because Module._apply transforms each registration independently.
    Unsupported state never becomes a zero-byte observation.
    """
    parameters: set[int] = set()
    parameter_bytes = trainable_bytes = buffer_bytes = buffer_count = 0
    try:
        for child in module.modules():
            for parameter in child._parameters.values():
                if parameter is None or id(parameter) in parameters:
                    continue
                parameters.add(id(parameter))
                size = _projected_tensor_bytes(parameter)
                parameter_bytes += size
                if parameter.requires_grad:
                    trainable_bytes += size
            for buffer in child._buffers.values():
                if buffer is not None:
                    buffer_bytes += _projected_tensor_bytes(buffer)
                    buffer_count += 1
    except (ValueError, RuntimeError, NotImplementedError) as exc:
        return RegisteredStateInventory(status="unavailable", reason=str(exc))
    return RegisteredStateInventory(
        status="available",
        parameter_bytes=parameter_bytes,
        trainable_parameter_bytes=trainable_bytes,
        buffer_bytes=buffer_bytes,
        parameter_count=len(parameters),
        buffer_count=buffer_count,
    )
