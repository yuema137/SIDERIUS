"""Opt-in synthetic design qualification, NOT an installed R3 execution route.

The isolated objective worker intentionally receives evaluation target tensors;
its private files and raw output are never a research-facing surface. This is a
filesystem/process witness, not a claim of information-theoretic confidentiality
for arbitrary user-defined scalar objectives, or distinct host-UID qualification.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from torch.utils.data import TensorDataset

from agent.schemas.model_io_contract import ModelIOContract
from execute_tools.train_engine_sandbox import ObjectiveStateMutationError, _validation_pass
from ml_models.models_format_sandbox import LossConfig
from tests.helpers.private_r3_split_probe import SyntheticObjective

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_PRIVATE_R3_QUALIFICATION") != "1",
    reason="explicit local namespace qualification required",
)
ROOT = Path(__file__).resolve().parents[3]


def isolated_role(role, inputs, outputs, hidden):
    """No network, provider environment or operator-tree mount in either worker."""
    python_root = Path(sys.base_prefix)
    command = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
    for path in ("/usr", "/lib", "/lib64"):
        command.extend(("--ro-bind", path, path))
    command.extend(
        ("--symlink", "usr/bin", "/bin", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp")
    )
    roots = {ROOT: ROOT, python_root: python_root.resolve()}
    alias = Path(os.readlink(sys.executable))
    if alias.is_absolute():
        roots[alias.parent.parent] = alias.parent.parent.resolve()
    for target, source in roots.items():
        command.extend(("--ro-bind", str(source), str(target)))
    command.extend(
        (
            "--ro-bind",
            str(inputs),
            str(inputs),
            "--bind",
            str(outputs),
            str(outputs),
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--setenv",
            "OMP_NUM_THREADS",
            "1",
            "--chdir",
            str(outputs),
            sys.executable,
            "-I",
            "-B",
            str(ROOT / "tests/helpers/private_r3_split_probe.py"),
            role,
            str(inputs),
            str(outputs),
            str(hidden),
        )
    )
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=30, env={"PATH": "/usr/bin:/bin"}
    )
    assert result.returncode == 0, result.stderr


def contract():
    def tensor(width):
        return {
            "axes": [
                {"dimension": {"symbolic": "B"}, "role": "batch"},
                {"dimension": {"fixed": width}},
            ],
            "dtype": {"admissible": ["float32"]},
        }

    return ModelIOContract.model_validate({"input": tensor(4), "output": tensor(2)})


@pytest.mark.parametrize(
    "mutate", [False, True], ids=["custom-objective-parity", "objective-mutation-refused"]
)
def test_separate_prediction_and_custom_objective_workers(tmp_path, mutate):
    """An arbitrary Python criterion needs no TorchScript restriction in isolation."""
    inputs, prediction_out, objective_in, objective_out, private = [
        tmp_path / p
        for p in (
            "prediction_input",
            "prediction_output",
            "objective_input",
            "objective_output",
            "private",
        )
    ]
    for path in (inputs, prediction_out, objective_in, objective_out, private):
        path.mkdir()
    torch.manual_seed(17)
    x, y = torch.randn(5, 4), torch.randn(5, 2)
    model = torch.nn.Linear(4, 2).train()
    torch.jit.script(copy.deepcopy(model).eval()).save(str(inputs / "model.pt"))
    np.save(inputs / "inputs.npy", x.numpy())
    hidden = private / "operator_targets.npy"
    np.save(hidden, y.numpy())
    isolated_role("prediction", inputs, prediction_out, hidden)

    # Only the operator materializes targets into the isolated objective role.
    # The target owner never imports a candidate-supplied objective to compute it.
    shutil.copyfile(hidden, objective_in / "targets.npy")
    shutil.copyfile(prediction_out / "predictions.npz", objective_in / "predictions.npz")
    criterion = SyntheticObjective(mutate=mutate)
    # Check once: TorchScript caches failed compilation of this same class.
    if not mutate:
        with pytest.raises(RuntimeError, match="numpy"):
            torch.jit.script(criterion)
    torch.save(criterion.state_dict(), objective_in / "state.pt")
    (objective_in / "objective.json").write_text(json.dumps({"mutate": mutate}))
    isolated_role("objective", objective_in, objective_out, hidden)
    status = json.loads((objective_out / "status.json").read_text())["status"]

    # This trusted synthetic oracle compares the existing semantics; it is not
    # an example of importing untrusted candidate code into a deployed owner.
    kwargs = dict(
        model=model,
        criterion=criterion,
        model_cfg=SimpleNamespace(model_type="wavenet"),
        loss_cfg=LossConfig(loss_type="smooth_l1"),
        model_io=contract(),
        device=torch.device("cpu"),
        data_path=SimpleNamespace(validation_dataset=lambda *_: TensorDataset(x, y)),
        task_eval_scope=object(),
        data_dir=str(tmp_path),
        batch_size=2,
    )
    if mutate:
        with pytest.raises(ObjectiveStateMutationError):
            _validation_pass(**kwargs)
        assert status == "objective_state_mutation"
        assert not (objective_out / "losses.npy").exists()
    else:
        reference, count, _ = _validation_pass(**kwargs)
        losses = np.load(objective_out / "losses.npy", allow_pickle=False)
        assert losses.shape == (3,)
        reconstructed = sum(float(loss) * n for loss, n in zip(losses, (2, 2, 1), strict=True)) / 5
        assert status == "ok" and count == 5 and reconstructed == reference
        assert reconstructed != float(losses.mean()), "fixture must expose unequal-batch weighting"
    assert model.training
    if not mutate:
        research_in, research_out = tmp_path / "research_input", tmp_path / "research_output"
        research_in.mkdir()
        research_out.mkdir()
        (research_in / "receipt.json").write_text(json.dumps({"r3": reconstructed, "rows": count}))
        isolated_role("research", research_in, research_out, hidden)
        assert json.loads((research_out / "visibility.json").read_text()) == {
            "private_evaluation_files": "denied"
        }
