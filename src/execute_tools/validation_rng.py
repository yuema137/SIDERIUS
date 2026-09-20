"""Typed RNG handoff for isolated validation calls, with no data or policy authority.

The native validation transaction interleaves model, objective and observable
calls in one global RNG stream. A remote executor must carry that stream between
calls in the same order; independently seeding workers is not equivalent.
This module transports state only. It does not create an execution boundary,
authorize validation access, or install a remote validation executor.
"""

from __future__ import annotations

import random
from typing import Annotated, Literal

import numpy as np
import torch
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt, model_validator

UInt32 = Annotated[StrictInt, Field(ge=0, le=2**32 - 1)]
StateBytes = Annotated[bytes, Field(min_length=1, max_length=1024 * 1024)]


class _State(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", ser_json_bytes="base64", val_json_bytes="base64"
    )


class PythonRngState(_State):
    version: Literal[3]
    keys: Annotated[tuple[UInt32, ...], Field(min_length=624, max_length=624)]
    position: Annotated[StrictInt, Field(ge=0, le=624)]
    gaussian: FiniteFloat | None


class NumpyRngState(_State):
    algorithm: Literal["MT19937"]
    keys: Annotated[tuple[UInt32, ...], Field(min_length=624, max_length=624)]
    position: Annotated[StrictInt, Field(ge=0, le=624)]
    has_gaussian: Annotated[StrictInt, Field(ge=0, le=1)]
    gaussian: FiniteFloat


class CudaRngState(_State):
    device: Annotated[StrictInt, Field(ge=0)]
    state: StateBytes


class ValidationRngState(_State):
    version: Literal[1] = 1
    python: PythonRngState
    numpy: NumpyRngState
    torch_cpu: StateBytes
    torch_cuda: tuple[CudaRngState, ...] = ()

    @model_validator(mode="after")
    def unique_devices(self) -> ValidationRngState:
        devices = [item.device for item in self.torch_cuda]
        if len(set(devices)) != len(devices):
            raise ValueError("duplicate CUDA RNG device")
        return self


def capture_validation_rng(*, cuda_devices: tuple[int, ...] = ()) -> ValidationRngState:
    """Capture only the explicit CUDA devices used by the validation transaction."""
    py_version, py_values, py_gaussian = random.getstate()
    np_algorithm, np_keys, np_position, np_has_gaussian, np_gaussian = np.random.get_state()
    return ValidationRngState(
        python=PythonRngState.model_validate(
            {
                "version": py_version,
                "keys": py_values[:-1],
                "position": py_values[-1],
                "gaussian": py_gaussian,
            }
        ),
        numpy=NumpyRngState.model_validate(
            {
                "algorithm": np_algorithm,
                "keys": tuple(int(key) for key in np_keys),
                "position": int(np_position),
                "has_gaussian": int(np_has_gaussian),
                "gaussian": float(np_gaussian),
            }
        ),
        torch_cpu=torch.get_rng_state().numpy().tobytes(),
        torch_cuda=tuple(
            CudaRngState(
                device=device, state=torch.cuda.get_rng_state(device).cpu().numpy().tobytes()
            )
            for device in cuda_devices
        ),
    )


def restore_validation_rng(snapshot: ValidationRngState) -> None:
    """Validate generator states on temporary generators before changing globals.

    The caller supplies a schema-validated snapshot from its own transaction.
    Workers must use matching Python/NumPy/Torch versions and CUDA device mapping.
    This is not a general cross-version or cross-device RNG conversion API.
    A requested CUDA device must exist; it is never silently dropped.
    """
    py_state = (
        snapshot.python.version,
        (*snapshot.python.keys, snapshot.python.position),
        snapshot.python.gaussian,
    )
    np_state = (
        snapshot.numpy.algorithm,
        np.asarray(snapshot.numpy.keys, dtype=np.uint32),
        snapshot.numpy.position,
        snapshot.numpy.has_gaussian,
        snapshot.numpy.gaussian,
    )
    cpu_state = torch.tensor(list(snapshot.torch_cpu), dtype=torch.uint8)
    # Construct private generators with fixed seeds: validating a message must
    # not consume the ambient Python, NumPy or Torch streams.
    random.Random(0).setstate(py_state)
    np.random.RandomState(0).set_state(np_state)
    torch.Generator(device="cpu").set_state(cpu_state)
    cuda_states = []
    for item in snapshot.torch_cuda:
        state = torch.tensor(list(item.state), dtype=torch.uint8)
        torch.Generator(device=f"cuda:{item.device}").set_state(state)
        cuda_states.append((item.device, state))
    random.setstate(py_state)
    np.random.set_state(np_state)
    torch.set_rng_state(cpu_state)
    for device, state in cuda_states:
        torch.cuda.set_rng_state(state, device=device)
