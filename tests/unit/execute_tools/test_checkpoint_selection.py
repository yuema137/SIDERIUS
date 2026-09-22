import pytest
import torch

from execute_tools.checkpoint_selection import CheckpointSelector


def test_snapshot_copies_parameters_buffers_and_retains_first_tie():
    model = torch.nn.BatchNorm1d(2)
    selector = CheckpointSelector("best_validation_loss", has_validation=True)
    selector.observe(model, epoch=1, validation_loss=2.0)
    with torch.no_grad():
        model.weight.fill_(4)
        model.running_mean.fill_(7)
    selector.observe(model, epoch=2, validation_loss=2.0)
    receipt = selector.restore(model)
    assert receipt.epoch == 1
    torch.testing.assert_close(model.weight, torch.ones(2))
    torch.testing.assert_close(model.running_mean, torch.zeros(2))


def test_no_finite_validation_cannot_silently_export_last_weights():
    model = torch.nn.Linear(1, 1)
    selector = CheckpointSelector("best_validation_loss", has_validation=True)
    with pytest.raises(ValueError, match="non-finite"):
        selector.observe(model, epoch=1, validation_loss=float("nan"))
    with pytest.raises(ValueError, match="no completed validation"):
        selector.restore(model)
