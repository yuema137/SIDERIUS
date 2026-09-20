"""Native validation through two real stochastic workers, no private data/GPU.

The original validation loop remains the estimator, DataLoader and transaction
authority. RPC proxies exercise only RNG handoff; host UID, mounts, arbitrary
module transport, deadlines and installed adapter qualification are separate.
"""

import os
import random
import select
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from torch.utils.data import TensorDataset

from agent.schemas.model_io_contract import ModelIOContract
from execute_tools.train_engine_sandbox import _validation_pass
from execute_tools.validation_rng import capture_validation_rng, restore_validation_rng
from ml_models.models_format_sandbox import LossConfig
from tests.helpers.validation_rng_worker import Call, Reply, StochasticModel, StochasticObjective

ROOT = Path(__file__).resolve().parents[3]


class Worker:
    def __init__(self, role):
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-m", "tests.helpers.validation_rng_worker", role],
            cwd=ROOT,
            env={"PATH": os.defpath, "OMP_NUM_THREADS": "1"},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.calls = 0

    def close(self):
        self.process.terminate()
        try:
            self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate(timeout=5)

    def call(self, values, targets=None):
        request = Call(
            rng=capture_validation_rng(),
            values=values.tolist(),
            targets=None if targets is None else targets.tolist(),
        )
        self.process.stdin.write(request.model_dump_json() + "\n")
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], 15)
        assert ready, "synthetic RNG worker did not respond"
        response = self.process.stdout.readline()
        assert response, "synthetic RNG worker exited without a response"
        reply = Reply.model_validate_json(response)
        restore_validation_rng(reply.rng)
        self.calls += 1
        return torch.tensor(reply.output, dtype=values.dtype)


class Proxy(torch.nn.Module):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker

    def forward(self, *values):
        return self.worker.call(*values)


def test_stochastic_model_and_loss_interleave_like_native_validation():
    original = capture_validation_rng()
    try:
        random.seed(7)
        np.random.seed(11)
        torch.manual_seed(13)
        x, y = torch.randn(5, 4), torch.randn(5, 4)
        initial = capture_validation_rng()
        contract = ModelIOContract.model_validate(
            {
                name: {
                    "axes": [
                        {"dimension": {"symbolic": "B"}, "role": "batch"},
                        {"dimension": {"fixed": 4}},
                    ],
                    "dtype": {"admissible": ["float32"]},
                }
                for name in ("input", "output")
            }
        )
        kwargs = dict(
            model_cfg=SimpleNamespace(model_type="wavenet"),
            loss_cfg=LossConfig(loss_type="smooth_l1"),
            model_io=contract,
            device=torch.device("cpu"),
            data_path=SimpleNamespace(validation_dataset=lambda *_: TensorDataset(x, y)),
            task_eval_scope=object(),
            data_dir="synthetic-only",
            batch_size=2,
        )
        native_observations = []
        expected, rows, _ = _validation_pass(
            model=StochasticModel(),
            criterion=StochasticObjective(),
            observables=SimpleNamespace(
                observe=lambda output, target: native_observations.append(
                    float((output - target).abs().mean())
                )
            ),
            **kwargs,
        )
        assert capture_validation_rng() == initial
        with ExitStack() as stack:
            prediction = Worker("model")
            stack.callback(prediction.close)
            objective = Worker("objective")
            stack.callback(objective.close)
            assert prediction.process.pid != objective.process.pid
            proxy_model = Proxy(prediction).train()
            remote_observations, verified_at, allocation_at, measured = [], [], [], []

            def feed(unit_ms, *, elapsed_ms):
                measured.append((unit_ms, elapsed_ms))
                verifier.is_terminal = True

            verifier = SimpleNamespace(feed=feed, is_terminal=False)
            actual, actual_rows, _ = _validation_pass(
                model=proxy_model,
                criterion=Proxy(objective),
                observables=SimpleNamespace(
                    observe=lambda output, target: remote_observations.append(
                        float((output - target).abs().mean())
                    )
                ),
                verifier=verifier,
                on_verified=lambda: verified_at.append((prediction.calls, objective.calls)),
                check_allocation=lambda: allocation_at.append(prediction.calls),
                **kwargs,
            )
            assert actual == expected
            assert actual_rows == rows == 5
            assert prediction.calls == objective.calls == 3
            assert verified_at == [(1, 1)]  # Persist before the second batch runs.
            assert allocation_at == [0, 1, 2, 3]
            assert len(measured) == 1 and measured[0][0] * 2 == measured[0][1] > 0
            assert remote_observations == native_observations
            assert proxy_model.training
            assert capture_validation_rng() == initial
    finally:
        restore_validation_rng(original)
