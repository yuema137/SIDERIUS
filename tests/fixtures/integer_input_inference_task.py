"""Synthetic task whose storage representation differs from its model input."""

from typing import Any

import torch
from torch.utils.data import TensorDataset

from tests.fixtures.fcov8_declared_naming_task import (
    DeclaredNamingTaskDataPath,
)
from tests.fixtures.fcov8_declared_naming_task import (
    deliverable_name as deliverable_name,
)


class IntegerInputTaskDataPath(DeclaredNamingTaskDataPath):
    """Reuse scope/naming scaffolding while producing signed int16 samples."""

    task_data_path_id = "integer_input_inference_task"

    def validation_dataset(self, scope: Any, params: Any) -> TensorDataset:
        inputs = torch.arange(scope.rows * 4, dtype=torch.int16).reshape(scope.rows, 4) - 6
        return TensorDataset(inputs, torch.zeros(scope.rows, 1))
