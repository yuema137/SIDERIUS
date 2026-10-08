"""Task-authorized training preparation for explicit preprocessing or bound evidence."""

from __future__ import annotations

import time
from collections.abc import Sized
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec, TrainingDataCoverage
from core.target_standardization import TargetStandardizationReceipt

if TYPE_CHECKING:
    import torch

    from ml_models.models_format_sandbox import LossConfig, TrainConfig


class TrainingPreparationDeadline(TimeoutError):
    """The existing worker allowance expired while preparing its training data."""


def check_training_preparation_deadline(deadline_at: float | None) -> None:
    if deadline_at is not None and time.monotonic() >= deadline_at:
        raise TrainingPreparationDeadline(
            "training measurement deadline expired during preparation"
        )


@dataclass(frozen=True)
class PreparedTrainingBatch:
    model: Any
    model_input: Any
    loss_target: Any
    criterion: Any
    optimizer: Any
    coverage: TrainingDataCoverage | None
    standardization: TargetStandardizationReceipt | None


def prepare_task_training_components(
    spec: GpuMeasurementSpec,
    *,
    model: Any,
    train_cfg: TrainConfig,
    loss_cfg: LossConfig,
    input_dtype: torch.dtype,
    deadline_at: float | None,
) -> PreparedTrainingBatch:
    """Fit the authorized pool, then load one real batch while authorization lives."""
    import torch

    from execute_tools.target_standardization import (
        prepare_training_target_standardization,
        validate_target_standardization,
    )
    from execute_tools.task_probe_batch import _first_training_batch, task_training_probe_source
    from execute_tools.train_engine_sandbox import build_training_optimizer
    from ml_models.loss_models_sandbox import get_criterion, get_target_torch_dtype
    from ml_models.plugin_loader import get_output_type

    reference = spec.task_probe_data
    if reference is None or reference.sampling.epoch_seed is None:
        raise ValueError("training preprocessing requires an authorized scope and resolved seed")

    def check_deadline() -> None:
        check_training_preparation_deadline(deadline_at)

    enabled = train_cfg.target_standardization != "none"
    target_dtype = get_target_torch_dtype(loss_cfg)
    if enabled:
        validate_target_standardization(
            enabled=True,
            output_type=get_output_type(spec.request.model_type),
            target_dtype=lambda: target_dtype,
        )
    criterion = get_criterion(
        loss_cfg,
        class_weights=None,
        expected_contract_snapshot=spec.expected_custom_loss_snapshot,
    )
    optimizer = build_training_optimizer(model, train_cfg)
    check_deadline()
    with task_training_probe_source(reference) as source:
        check_deadline()
        fitting = source.sampling.model_copy(update={"train_portion": 1.0}) if enabled else None
        model, criterion, receipt = prepare_training_target_standardization(
            model,
            criterion,
            enabled=enabled,
            data_path=source.data_path,
            scope=source.scope,
            sampling=fitting or source.sampling,
            batch_size=train_cfg.batch_size,
            device=torch.device(spec.device),
            check_allocation=check_deadline,
        )
        check_deadline()
        dataset = source.data_path.training_dataset(source.scope, source.sampling)
        rows = len(dataset) if isinstance(dataset, Sized) else None
        if spec.training_binding is not None and (rows is None or rows < 1):
            raise ValueError("bound training requires a nonempty sized training dataset")
        raw_input, raw_target = _first_training_batch(
            dataset, train_cfg.batch_size, drop_last=train_cfg.drop_last
        )
        check_deadline()
        model_input = raw_input.to(device=spec.device, dtype=input_dtype)
        loss_target = raw_target.to(device=spec.device, dtype=target_dtype)
        coverage = None
        if spec.training_binding is not None:
            assert rows is not None
            coverage = TrainingDataCoverage(
                configured_batch_size=train_cfg.batch_size,
                materialized_dataset_rows=rows,
                observed_batch_rows=int(model_input.shape[0]),
                input_shape=tuple(model_input.shape),
                target_shape=tuple(loss_target.shape),
                storage_input_dtype=str(raw_input.dtype),
                model_input_dtype=str(model_input.dtype),
                target_dtype=str(loss_target.dtype),
                sampling=source.sampling,
                fitting_sampling=fitting,
                standardization=receipt,
            )
        check_deadline()
    return PreparedTrainingBatch(
        model, model_input, loss_target, criterion, optimizer, coverage, receipt
    )
