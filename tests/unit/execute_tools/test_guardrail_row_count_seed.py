"""Guardrail step pricing passes an explicit epoch seed when counting rows.

``resolve_task_scope_training_workload`` materializes the task's training
dataset only to count rows. Without an ``epoch_seed`` a task that refuses an
absent seed raised, and the tuner's best-effort guardrail turned that into
"[guardrails] ... failed (non-fatal)", so ``max_steps_per_attempt`` silently
stopped pricing the attempt.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from torch.utils.data import TensorDataset

from core.seeding import MissingRunSeed
from execute_tools.task_data_path import (
    EpochSamplingParams,
    ScopeBuildRequest,
    bind_task_data_path,
)
from execute_tools.task_registration_scope import run_registration_scope
from execute_tools.training_batches import optimizer_steps_for_rows
from execute_tools.workload_resolvers import resolve_task_scope_training_workload
from nodes.ml_hyperparameter_tune_agent.runtime import _resolve_task_scope_guardrail_steps
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
FULL = ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)


class SeedRequiringDataPath:
    """A fail-closed task: subsampling without the run's seed is refused."""

    task_data_path_id = "seed_requiring"

    def training_dataset(self, scope, params: EpochSamplingParams):
        rows = 40
        if params.train_portion is not None and params.train_portion < 1.0:
            if params.epoch_seed is None:
                raise MissingRunSeed("subsampling needs epoch_seed")
            rows = math.floor(rows * params.train_portion)
        if params.max_samples is not None:
            rows = min(rows, params.max_samples)
        return TensorDataset(torch.zeros(rows, 1), torch.zeros(rows))


def test_guardrail_prices_a_task_that_refuses_an_absent_epoch_seed(capsys) -> None:
    """Defect: the row count is requested without an epoch seed, the task
    refuses, and the guardrail swallows it and returns None. 40 rows at
    portion 0.5 -> 20 rows -> 5 steps of 4 per epoch, 3 epochs = 15."""
    with bind_task_data_path(SeedRequiringDataPath()):
        steps = _resolve_task_scope_guardrail_steps(
            task_scopes=SimpleNamespace(training="opaque"),
            data_dir="/unused",
            train_cfg={"batch_size": 4, "epochs": 3},
            train_portion=0.5,
            max_samples=None,
        )
    assert "failed (non-fatal)" not in capsys.readouterr().out
    assert steps is not None
    assert steps == optimizer_steps_for_rows(20, 4, drop_last=True) * _epochs({"epochs": 3})


def _epochs(train_cfg: dict) -> int:
    from agent.skills.training_skill.estimator import resolve_train_field

    return resolve_train_field(train_cfg, "epochs", safety_margin=1)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _quickstart_data(root: Path) -> str:
    module = _load(
        "guardrail_quickstart", REPO_ROOT / "examples/quickstart/plugins/_quickstart_task.py"
    )
    module.write_data_dir(root)
    return str(root)


def _masked_data(root: Path) -> str:
    module = _load(
        "guardrail_masked",
        REPO_ROOT / "examples/synthetic_masked_regression/plugins/_masked_task.py",
    )
    return module.materialize_run_bundle(root)["data_dir"]


@pytest.mark.parametrize(
    ("manifest", "write_data", "training_rows"),
    [
        ("quickstart.yaml", _quickstart_data, 128),
        ("synthetic_masked_regression.yaml", _masked_data, 48),
    ],
    ids=["quickstart", "synthetic_masked_regression"],
)
@pytest.mark.parametrize(("train_portion", "max_samples"), [(0.5, None), (1.0, 10), (None, None)])
def test_existing_examples_price_the_same_step_count(
    tmp_path: Path, manifest, write_data, training_rows, train_portion, max_samples
) -> None:
    """Defect: the explicit seed changes the count for a task whose count does
    not depend on it. The expected count is derived from the known training
    row counts, and also equals the count of a seedless materialization."""
    data_dir = write_data(tmp_path / "data")
    with run_registration_scope():
        composition = compose_run_task_bindings(
            str(REPO_ROOT / "configs/task_composition" / manifest)
        )
        with bind_run_task_composition(composition, physical_data_root=data_dir):
            path = composition.task_data_path
            scope = path.build_training_scope(FULL)
            workload = resolve_task_scope_training_workload(
                scope,
                data_dir=data_dir,
                batch_size=8,
                train_portion=train_portion,
                epochs=2,
                max_samples=max_samples,
            )
            seedless = len(
                path.training_dataset(
                    scope,
                    EpochSamplingParams(
                        data_dir=data_dir, train_portion=train_portion, max_samples=max_samples
                    ),
                )
            )
    rows = training_rows if train_portion is None else math.floor(training_rows * train_portion)
    rows = rows if max_samples is None else min(rows, max_samples)
    assert workload.detail["samples_per_epoch"] == rows == seedless
    assert workload.unit_count == optimizer_steps_for_rows(rows, 8, drop_last=True) * 2
