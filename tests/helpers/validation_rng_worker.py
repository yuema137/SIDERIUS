"""Synthetic stochastic roles; a process witness, not a private-data service."""

import json
import random
import sys

import numpy as np
import torch
from pydantic import BaseModel, ConfigDict

from execute_tools.validation_rng import (
    ValidationRngState,
    capture_validation_rng,
    restore_validation_rng,
)


class StochasticModel(torch.nn.Module):
    def forward(self, values):
        return values * (torch.rand_like(values) + random.random() + float(np.random.random()))


class StochasticObjective(torch.nn.Module):
    def forward(self, predictions, targets):
        multiplier = torch.rand(()) + random.gauss(0, 1) + float(np.random.normal())
        return (predictions - targets).square().mean() * multiplier


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rng: ValidationRngState
    values: list[list[float]]
    targets: list[list[float]] | None = None


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rng: ValidationRngState
    output: list[list[float]] | float


def main(role: str) -> None:
    torch.set_num_threads(1)
    module = StochasticModel().eval() if role == "model" else StochasticObjective()
    for line in sys.stdin:
        request = Call.model_validate_json(line)
        restore_validation_rng(request.rng)
        values = torch.tensor(request.values, dtype=torch.float32)
        with torch.no_grad():
            if role == "model":
                output = module(values)
            else:
                if request.targets is None:
                    raise ValueError("objective requires targets")
                output = module(values, torch.tensor(request.targets, dtype=torch.float32))
        reply = Reply(rng=capture_validation_rng(), output=output.tolist())
        print(json.dumps(reply.model_dump(mode="json")), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
