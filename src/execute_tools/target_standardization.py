"""Fit only an opaque, authorized training scope using streaming float64 moments."""

import math
import time
from collections.abc import Callable

import torch
from torch.utils.data import DataLoader

from core.target_standardization import TargetStandardizationReceipt
from execute_tools.task_data_path import EpochSamplingParams, TaskDataPath
from ml_models.target_standardization import StandardizedTargetLoss, StandardizedTargetModel


def validate_target_standardization(
    *, enabled: bool, output_type: str, target_dtype: Callable[[], torch.dtype]
) -> None:
    """Use the same eligibility rule in native training and its measurement."""
    if enabled and (
        output_type not in {"regressor", "hybrid"} or not target_dtype().is_floating_point
    ):
        raise ValueError(
            "target standardization requires a regressor with continuous floating targets"
        )


def prepare_training_target_standardization(
    model: torch.nn.Module,
    criterion: torch.nn.Module,
    *,
    enabled: bool,
    data_path: TaskDataPath,
    scope: object,
    sampling: EpochSamplingParams,
    batch_size: int,
    device: torch.device,
    check_allocation: Callable[[], None],
) -> tuple[torch.nn.Module, torch.nn.Module, TargetStandardizationReceipt | None]:
    """Bind one transform to training/validation and the exported model."""
    if not enabled:
        return model, criterion, None
    fitted = fit_training_target_standardization(
        data_path,
        scope,
        sampling=sampling,
        batch_size=batch_size,
        check_allocation=check_allocation,
    )
    return (
        StandardizedTargetModel(model, mean=fitted.mean, scale=fitted.scale).to(device),
        StandardizedTargetLoss(criterion, mean=fitted.mean, scale=fitted.scale).to(device),
        fitted,
    )


def fit_training_target_standardization(
    data_path: TaskDataPath,
    scope: object,
    *,
    sampling: EpochSamplingParams,
    batch_size: int,
    check_allocation: Callable[[], None],
) -> TargetStandardizationReceipt:
    """One global mean/population std over the selected pool, not evaluation.

    The caller supplies train_portion=1 so per-epoch subsampling does not fit a
    different transform each epoch. An explicit qualification row ceiling is
    retained. No assumption about task file names, label units or hardware.
    """
    started = time.perf_counter()
    check_allocation()
    dataset = data_path.training_dataset(scope, sampling)
    count = rows = 0
    mean = m2 = 0.0
    for inputs, targets in DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        drop_last=False,
        generator=torch.Generator().manual_seed(0),
    ):
        check_allocation()
        values = targets.detach().to(device="cpu", dtype=torch.float64).reshape(-1)
        if not values.numel() or not torch.isfinite(values).all():
            raise ValueError(
                "target standardization encountered empty or non-finite training targets"
            )
        n = values.numel()
        batch_mean = float(values.mean())
        batch_m2 = float(((values - batch_mean) ** 2).sum())
        delta = batch_mean - mean
        total = count + n
        m2 += batch_m2 + delta * delta * count * n / total
        mean += delta * n / total
        count = total
        rows += int(inputs.shape[0])
    if count < 2 or not math.isfinite(m2) or m2 <= 0:
        raise ValueError("target standardization requires nonconstant finite training targets")
    return TargetStandardizationReceipt(
        mean=mean,
        scale=math.sqrt(m2 / count),
        training_rows=rows,
        target_elements=count,
        fit_seconds=time.perf_counter() - started,
    )
