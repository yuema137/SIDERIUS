"""Slow Dataset reads must be visible to the real validation timing call site."""

from types import SimpleNamespace

import pytest
import torch
from torch.utils.data import Dataset

import execute_tools.train_engine_sandbox as engine
from ml_models.models_format_sandbox import LossConfig


def test_validation_times_loader_and_preserves_unequal_tail(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(engine, "time", SimpleNamespace(perf_counter=lambda: clock[0]))

    class Rows(Dataset):
        def __len__(self):
            return 5

        def __getitem__(self, index):
            clock[0] += 0.1  # Simulated HDF5 read, no real sleep or GPU required.
            row = torch.tensor([index, index + 1], dtype=torch.float32)
            return row, row

    class Identity(torch.nn.Module):
        def forward(self, inputs):
            assert not self.training
            assert not torch.is_grad_enabled()
            return inputs.float()

    class Evidence:
        is_terminal = False

        def __init__(self):
            self.records = []

        def feed(self, unit_ms, *, elapsed_ms):
            self.records.append((unit_ms, elapsed_ms))

    evidence = Evidence()
    model = Identity().train()
    result, count, duration = engine._validation_pass(
        model=model,
        criterion=torch.nn.MSELoss(),
        model_cfg=SimpleNamespace(model_type="wavenet"),
        loss_cfg=LossConfig(loss_type="smooth_l1"),
        model_io=None,
        device=torch.device("cpu"),
        data_path=SimpleNamespace(validation_dataset=lambda *_: Rows()),
        task_eval_scope=object(),
        data_dir="unused",
        batch_size=2,
        verifier=evidence,
    )
    assert result == 0
    assert count == 5
    assert model.training
    assert duration == pytest.approx(0.5)
    assert [row[0] for row in evidence.records] == pytest.approx([100, 100, 100])
    assert [row[1] for row in evidence.records] == pytest.approx([200, 200, 100])
