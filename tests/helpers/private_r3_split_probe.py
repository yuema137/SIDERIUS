"""Synthetic worker roles for R3 boundary qualification; not a runtime adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch


class SyntheticObjective(torch.nn.Module):
    def __init__(self, *, mutate: bool = False):
        super().__init__()
        self.register_buffer("scale", torch.tensor(1.75))
        self.register_buffer("calls", torch.tensor(0))
        self.mutate = mutate

    def forward(self, predictions, targets):
        if self.mutate:
            self.calls.add_(1)
        # Deliberately Python-only: no new TorchScript requirement on custom loss.
        scale = float(self.scale.detach().cpu().numpy())
        return (scale * (predictions - targets).square()).mean()


def run_role(role: str, inputs: Path, outputs: Path, hidden: Path) -> None:
    torch.set_num_threads(1)
    try:
        hidden.read_bytes()
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("operator-private target file was visible")
    if role == "research":
        for path in (
            hidden.parent.parent / "objective_input/targets.npy",
            hidden.parent.parent / "prediction_output/predictions.npz",
            hidden.parent.parent / "objective_output/losses.npy",
        ):
            try:
                path.read_bytes()
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("private evaluation intermediate was visible")
        receipt = json.loads((inputs / "receipt.json").read_text())
        assert set(receipt) == {"r3", "rows"}
        (outputs / "visibility.json").write_text('{"private_evaluation_files":"denied"}')
        return
    if role == "prediction":
        values = torch.from_numpy(np.load(inputs / "inputs.npy", allow_pickle=False))
        model = torch.jit.load(str(inputs / "model.pt"), map_location="cpu").eval()
        with torch.no_grad():
            predictions = {
                f"batch_{start}": model(values[start : start + 2]).numpy()
                for start in range(0, len(values), 2)
            }
        np.savez(outputs / "predictions.npz", **predictions)
        return
    if role == "objective":
        config = json.loads((inputs / "objective.json").read_text())
        criterion = SyntheticObjective(mutate=config["mutate"])
        criterion.load_state_dict(
            torch.load(inputs / "state.pt", map_location="cpu", weights_only=True)
        )
        before = {name: value.clone() for name, value in criterion.state_dict().items()}
        targets = torch.from_numpy(np.load(inputs / "targets.npy", allow_pickle=False))
        losses = []
        with np.load(inputs / "predictions.npz", allow_pickle=False) as predictions:
            with torch.no_grad():
                for start in range(0, len(targets), 2):
                    pred = torch.from_numpy(predictions[f"batch_{start}"])
                    target = targets[start : start + 2]
                    if pred.shape != target.shape:
                        raise ValueError("batch_shape_mismatch")
                    losses.append(float(criterion(pred, target).item()))
        if any(
            not torch.equal(value, criterion.state_dict()[name]) for name, value in before.items()
        ):
            (outputs / "status.json").write_text('{"status":"objective_state_mutation"}')
            return
        np.save(outputs / "losses.npy", np.asarray(losses, dtype=np.float64))
        (outputs / "status.json").write_text('{"status":"ok"}')
        return
    raise ValueError("unknown synthetic role")


if __name__ == "__main__":
    run_role(sys.argv[1], *(Path(p) for p in sys.argv[2:]))
