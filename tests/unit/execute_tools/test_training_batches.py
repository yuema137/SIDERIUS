import torch
from torch.utils.data import TensorDataset

from execute_tools.task_data_path import bind_task_data_path
from execute_tools.training_batches import completed_epoch_loss, optimizer_steps_for_rows
from execute_tools.workload_resolvers import resolve_task_scope_training_workload


def test_whole_pool_step_count_includes_partial_tail_and_loss_uses_row_weights():
    assert optimizer_steps_for_rows(40_000, 128, drop_last=False) == 313
    assert optimizer_steps_for_rows(40_000, 128, drop_last=True) == 312
    assert completed_epoch_loss([1.0, 9.0], [3, 1], drop_last=False) == 3.0
    assert completed_epoch_loss([1.0, 9.0], [3, 3], drop_last=True) == 5.0


def test_task_scope_forecast_prices_the_same_tail_as_the_loader():
    class Data:
        def training_dataset(self, scope, params):
            assert scope == "opaque"
            return TensorDataset(torch.zeros(5, 1), torch.zeros(5, 1))

    with bind_task_data_path(Data()):
        workload = resolve_task_scope_training_workload(
            "opaque",
            data_dir="unused",
            batch_size=3,
            train_portion=1.0,
            epochs=4,
            drop_last=False,
        )
    assert workload.unit_count == 8
    assert workload.detail["steps_per_epoch"] == 2
