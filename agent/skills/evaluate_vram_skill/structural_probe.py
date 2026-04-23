"""Structural VRAM probe — dual-mechanism design (Phase 6.6 A.2).

Provides three deterministic probing primitives:

  1. `probe_forward_layers`  — torchinfo-based per-submodule report.
  2. `probe_autograd_tape`   — saved_tensors_hooks walk, dedup by storage.
  3. `probe_activation_footprint` — composer that dispatches based on mode.

Design rationale (see docs/phase66_deterministic_vram_and_hardening.md §3.2):
torchinfo hooks `nn.Module.forward` entry/exit, so it is blind to the bare
tensor ops inside a single forward (e.g. `FocalLoss1D`'s `targets_one_hot`,
`pt`, `alpha_t`). The autograd engine is not: every tensor it retains for
backward is registered through the saved-tensors machinery. We intercept that
machinery to get a byte-exact training activation footprint, and use
torchinfo only for the human-readable layer breakdown.
"""
from __future__ import annotations

from typing import Callable, Literal, Sequence

import torch
import torch.nn as nn
import torchinfo
from pydantic import BaseModel, ConfigDict, Field


# ── Pydantic contracts ──────────────────────────────────────────────────────

class LayerReport(BaseModel):
    """One entry from torchinfo's summary_list, normalised for our use."""
    model_config = ConfigDict(frozen=True)

    depth:        int
    var_name:     str
    class_name:   str
    input_shape:  list[int]
    output_shape: list[int]
    num_params:   int
    param_bytes:  int
    output_bytes: int
    is_leaf:      bool


class ForwardLayerReport(BaseModel):
    """Aggregated torchinfo view of one nn.Module (model or loss)."""
    model_config = ConfigDict(frozen=True)

    module_name:              str
    layers:                   list[LayerReport]
    total_param_bytes:        int = Field(description="Sum over leaves only.")
    forward_output_bytes_sum: int = Field(description="Sum over leaves only.")
    forward_output_bytes_max: int = Field(description="Max single-leaf output bytes.")


class AutogradTapeReport(BaseModel):
    """What the autograd engine retained for backward — byte-exact."""
    model_config = ConfigDict(frozen=True)

    unique_storage_count: int
    total_saved_bytes:    int


class ProbeResult(BaseModel):
    """Single object downstream consumers (wrapper, killer_report) read from."""
    model_config = ConfigDict(frozen=True)

    mode:          Literal["training", "inference"]
    model_forward: ForwardLayerReport
    loss_forward:  ForwardLayerReport | None = None
    autograd_tape: AutogradTapeReport | None = None
    input_bytes:   int
    output_bytes:  int


# ── Primitive 1: torchinfo wrapper ──────────────────────────────────────────

def _shape_to_list(shape) -> list[int]:
    """Normalise torchinfo's input_size / output_size to a flat list[int].

    torchinfo can return:
      - a flat `[B, C, T]` for single-tensor layers,
      - a nested `[[B, T], [B, T]]` for multi-input/output layers (e.g. a loss
        that takes logits + targets).

    For a leaf Module the first shape is the representative one we care about
    for byte accounting. We do not try to reconstruct the multi-tensor
    breakdown here — torchinfo's own `output_bytes` already sums correctly
    across outputs.
    """
    if not shape:
        return []
    if all(isinstance(d, int) for d in shape):
        return list(shape)
    # Nested list-of-shapes: return the first.
    first = shape[0]
    if isinstance(first, (list, tuple)) and all(isinstance(d, int) for d in first):
        return list(first)
    return []


def probe_forward_layers(
    module: nn.Module,
    input_data: torch.Tensor | Sequence[torch.Tensor],
    module_name: str | None = None,
) -> ForwardLayerReport:
    """Run torchinfo.summary on `module` with the given input, and normalise.

    Args:
        module: any nn.Module. Usually a model, but a loss Module works too.
        input_data: single Tensor or a sequence of Tensors passed as *args.
        module_name: override for the reported module name. Defaults to
                     `type(module).__name__`.

    Returns:
        ForwardLayerReport. `total_param_bytes` and the `forward_output_bytes_*`
        aggregates are computed over **leaf** layers only, to avoid
        double-counting nested containers.
    """
    if isinstance(input_data, torch.Tensor):
        info = torchinfo.summary(module, input_data=input_data, verbose=0, depth=10)
    else:
        info = torchinfo.summary(module, input_data=list(input_data), verbose=0, depth=10)

    layers: list[LayerReport] = []
    total_param_bytes = 0
    sum_out_bytes = 0
    max_out_bytes = 0

    for li in info.summary_list:
        report = LayerReport(
            depth=li.depth,
            var_name=li.var_name or "",
            class_name=li.class_name or "",
            input_shape=_shape_to_list(li.input_size),
            output_shape=_shape_to_list(li.output_size),
            num_params=int(li.num_params or 0),
            param_bytes=int(li.param_bytes or 0),
            output_bytes=int(li.output_bytes or 0),
            is_leaf=bool(li.is_leaf_layer),
        )
        layers.append(report)
        if report.is_leaf:
            total_param_bytes += report.param_bytes
            sum_out_bytes += report.output_bytes
            if report.output_bytes > max_out_bytes:
                max_out_bytes = report.output_bytes

    return ForwardLayerReport(
        module_name=module_name or type(module).__name__,
        layers=layers,
        total_param_bytes=total_param_bytes,
        forward_output_bytes_sum=sum_out_bytes,
        forward_output_bytes_max=max_out_bytes,
    )


# ── Primitive 2: autograd-tape walker via saved_tensors_hooks ──────────────

def probe_autograd_tape(forward_callable: Callable[[], torch.Tensor]) -> AutogradTapeReport:
    """Invoke `forward_callable()` under saved_tensors_hooks and count what
    autograd retained, deduped by underlying storage.

    This is the source of truth for training-mode activations. The returned
    bytes are the total PyTorch actually forced the allocator to keep live
    until backward() runs.

    Storage-pointer dedup is critical: a tensor and its view share a
    `data_ptr()`. save_for_backward fires once per view, but the physical
    allocation is a single buffer. Keying on `storage.data_ptr()` and using
    `storage.nbytes()` yields the physical cost, not the sum-of-views cost.

    The caller is responsible for building `forward_callable` in a way that
    keeps grad enabled (do not wrap in `torch.no_grad()`).
    """
    seen: dict[int, int] = {}

    def pack_hook(t: torch.Tensor) -> torch.Tensor:
        storage = t.untyped_storage()
        ptr = storage.data_ptr()
        if ptr and ptr not in seen:
            seen[ptr] = storage.nbytes()
        return t

    def unpack_hook(t: torch.Tensor) -> torch.Tensor:
        return t

    with torch.autograd.graph.saved_tensors_hooks(pack_hook, unpack_hook):
        _ = forward_callable()

    return AutogradTapeReport(
        unique_storage_count=len(seen),
        total_saved_bytes=sum(seen.values()),
    )


# ── Primitive 3: composer ───────────────────────────────────────────────────

def _tensor_bytes(t: torch.Tensor) -> int:
    return t.numel() * t.element_size()


def probe_activation_footprint(
    model: nn.Module,
    loss_module: nn.Module | None,
    input_sample: torch.Tensor,
    target_sample: torch.Tensor | None,
    mode: Literal["training", "inference"],
    device: torch.device | str = "cpu",
) -> ProbeResult:
    """Top-level probe. Dispatches to the primitives based on `mode`.

    Contract:
      * `mode="inference"`: `loss_module` and `target_sample` are ignored.
        Runs one `no_grad` forward through `model`. Returns a ProbeResult
        with `model_forward` populated, `loss_forward=None`,
        `autograd_tape=None`.

      * `mode="training"`: `loss_module` and `target_sample` must be provided.
        Runs one grad-enabled forward through model+loss under
        saved_tensors_hooks, captures the tape. Then runs torchinfo
        separately on model and loss for attribution.

    The probe mutates neither the model nor the loss module beyond moving
    them to `device` and flipping eval/train as appropriate for the mode.
    """
    device_t = torch.device(device) if not isinstance(device, torch.device) else device
    model = model.to(device_t)
    input_sample = input_sample.to(device_t)

    if mode == "inference":
        model.eval()
        model_layers = probe_forward_layers(
            model, input_sample, module_name=type(model).__name__
        )
        with torch.no_grad():
            out = model(input_sample)
        return ProbeResult(
            mode="inference",
            model_forward=model_layers,
            loss_forward=None,
            autograd_tape=None,
            input_bytes=_tensor_bytes(input_sample),
            output_bytes=_tensor_bytes(out),
        )

    # mode == "training"
    if loss_module is None or target_sample is None:
        raise ValueError(
            "training mode requires both loss_module and target_sample; "
            "these are the tensors the autograd tape will save during backward."
        )
    loss_module = loss_module.to(device_t)
    target_sample = target_sample.to(device_t)
    model.train()

    # Tape walk: one grad-enabled forward through the fused model+loss.
    def _fwd():
        logits = model(input_sample)
        return loss_module(logits, target_sample)

    tape_report = probe_autograd_tape(_fwd)

    # Separately run the model once more (no tape) to get its final output
    # shape for output_bytes, and to give torchinfo a clean forward.
    model_layers = probe_forward_layers(
        model, input_sample, module_name=type(model).__name__
    )
    with torch.no_grad():
        logits_for_shape = model(input_sample)
    # Probe the loss module with torchinfo for per-layer attribution.
    loss_layers = probe_forward_layers(
        loss_module,
        [logits_for_shape.detach(), target_sample],
        module_name=type(loss_module).__name__,
    )

    return ProbeResult(
        mode="training",
        model_forward=model_layers,
        loss_forward=loss_layers,
        autograd_tape=tape_report,
        input_bytes=_tensor_bytes(input_sample),
        output_bytes=_tensor_bytes(logits_for_shape),
    )
