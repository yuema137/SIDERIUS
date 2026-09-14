"""Candidate construction-memory admission.

The measurement is deliberately independent of tasks and model families.  RSS
delta is split into storage owned by registered parameters, registered
buffers, and unexplained remainder; only the latter has the fixed default
ceiling.
"""

from __future__ import annotations

import gc
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psutil
import torch

CONSTRUCTION_REMAINDER_LIMIT_BYTES = 512 * 1024**2


@dataclass(frozen=True)
class ConstructionMemory:
    """Measured constructor RSS split by registered tensor ownership."""

    rss_delta_bytes: int
    parameter_bytes: int
    buffer_bytes: int
    unexplained_bytes: int


class CandidateAdmissionError(RuntimeError):
    """A typed candidate refusal that the bounded proposal loop may retry."""

    def __init__(
        self,
        message: str,
        *,
        model_name: str,
        measurement: ConstructionMemory | None = None,
    ) -> None:
        super().__init__(message)
        self.model_name = model_name
        self.measurement = measurement


def _storage_bytes(tensor: torch.Tensor) -> tuple[tuple[str, int | None, int], int]:
    """Return a stable identity and the complete backing-storage size."""
    storage = tensor.untyped_storage()
    # ``untyped_storage()`` may return a fresh Python wrapper for the same
    # allocation, so object identity is insufficient for tied/view tensors.
    device = tensor.device
    return ((device.type, device.index, int(storage.data_ptr())), int(storage.nbytes()))


def measure_construction(
    model_class: type,
    config_class: type,
    *,
    model_name: str,
    representative_T: int = 16000,
    rss_reader: Callable[[], int] | None = None,
) -> ConstructionMemory:
    """Construct once and account unique parameter/buffer backing storage."""
    rss = rss_reader or (lambda: int(psutil.Process().memory_info().rss))
    gc.collect()
    before = rss()
    model: torch.nn.Module | None = None
    try:
        fields = getattr(config_class, "model_fields", None) or {}
        kwargs: dict[str, Any] = (
            {"segmentation_size": representative_T} if "segmentation_size" in fields else {}
        )
        try:
            config = config_class(**kwargs)
        except Exception:
            config = config_class()
        if "loss_type" in inspect.signature(model_class.__init__).parameters:
            model = model_class(config, loss_type="focal")
        else:
            model = model_class(config)
        after = rss()
        rss_delta = max(0, after - before)
        seen: set[tuple[str, int | None, int]] = set()
        params = 0
        buffers = 0
        for tensor, category in [(t, "parameter") for t in model.parameters()] + [
            (t, "buffer") for t in model.buffers()
        ]:
            identity, size = _storage_bytes(tensor)
            if identity in seen:
                continue
            seen.add(identity)
            if category == "parameter":
                params += size
            else:
                buffers += size
        return ConstructionMemory(rss_delta, params, buffers, max(0, rss_delta - params - buffers))
    except CandidateAdmissionError:
        raise
    except Exception as exc:
        from core.local_code.failure import raise_if_code_package_failure

        raise_if_code_package_failure(exc)
        raise CandidateAdmissionError(
            f"Candidate {model_name!r} construction failed with {type(exc).__name__}: {exc}. "
            "Fix the constructor and propose again.",
            model_name=model_name,
        ) from exc
    finally:
        del model
        gc.collect()


def admit_construction(
    model_class: type,
    config_class: type,
    *,
    model_name: str,
    representative_T: int = 16000,
    rss_reader: Callable[[], int] | None = None,
) -> ConstructionMemory:
    """Measure and reject only excessive unexplained constructor memory."""
    try:
        result = measure_construction(
            model_class,
            config_class,
            model_name=model_name,
            representative_T=representative_T,
            rss_reader=rss_reader,
        )
    except CandidateAdmissionError:
        raise
    print(
        f"    [MemCheck] {model_name!r}: RSS {result.rss_delta_bytes / 1024**3:.3f} GiB; "
        f"parameters {result.parameter_bytes / 1024**3:.3f} GiB; "
        f"buffers {result.buffer_bytes / 1024**3:.3f} GiB; "
        f"unexplained {result.unexplained_bytes / 1024**3:.3f} GiB "
        f"(limit {CONSTRUCTION_REMAINDER_LIMIT_BYTES / 1024**3:.3f} GiB)",
        flush=True,
    )
    if result.unexplained_bytes > CONSTRUCTION_REMAINDER_LIMIT_BYTES:
        raise CandidateAdmissionError(
            f"Candidate construction used {result.rss_delta_bytes / 1024**3:.2f} GiB RSS: "
            f"{result.parameter_bytes / 1024**3:.2f} GiB parameters, "
            f"{result.buffer_bytes / 1024**3:.2f} GiB buffers, and "
            f"{result.unexplained_bytes / 1024**3:.2f} GiB unexplained remainder "
            f"(limit {CONSTRUCTION_REMAINDER_LIMIT_BYTES / 1024**3:.2f} GiB). "
            "Register tensor state as parameters/buffers or move the allocation to forward().",
            model_name=model_name,
            measurement=result,
        )
    return result
