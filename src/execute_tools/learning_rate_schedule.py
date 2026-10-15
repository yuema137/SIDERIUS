"""Apply a validated epoch schedule without changing optimizer construction."""

from __future__ import annotations

from torch.optim import Optimizer

from ml_models.learning_rate_schedule import LearningRateSchedule, epoch_learning_rate


class EpochLearningRateController:
    def __init__(self, optimizer: Optimizer, schedule: LearningRateSchedule):
        self.optimizer = optimizer
        self.schedule = schedule
        self.base_rates = tuple(float(group["lr"]) for group in optimizer.param_groups)
        # Validate every group before any mutation, including cosine floors.
        for rate in self.base_rates:
            epoch_learning_rate(schedule, rate, 0)

    def start_epoch(self, epoch: int) -> list[float]:
        rates = [epoch_learning_rate(self.schedule, base, epoch) for base in self.base_rates]
        if len(rates) != len(self.optimizer.param_groups):
            raise ValueError("Optimizer parameter groups changed during epoch scheduling")
        for group, rate in zip(self.optimizer.param_groups, rates, strict=True):
            group["lr"] = rate
        return [float(group["lr"]) for group in self.optimizer.param_groups]


def build_epoch_lr_controller(
    optimizer: Optimizer, schedule: LearningRateSchedule | None
) -> EpochLearningRateController | None:
    """Disabled scheduling leaves all optimizer state and groups untouched."""
    return None if schedule is None else EpochLearningRateController(optimizer, schedule)
