"""Keep a generated model's long temporal validation probe out of the chain process."""

from __future__ import annotations

import os
import resource
import subprocess
import sys
import tempfile
from pathlib import Path

import psutil
from pydantic import BaseModel, Field

from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.model_probe import ModelProbeContext, ModelProbeSetupError
from core.local_code.child import prepare_child
from core.subprocess_env import subprocess_env

ProbeResult = tuple[bool, bool, bool, str | None, int | None, int | None]


class ProbeRequest(BaseModel):
    model_probe_context: ModelProbeContext | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    model_file_path: str
    model_io_contract: ModelIOContract | None
    result_path: str


class ProbeResponse(BaseModel):
    setup_error: str | None = Field(default=None, exclude_if=lambda value: value is None)
    instantiation_ok: bool
    gradient_ok: bool
    output_type_ok: bool
    error: str | None
    total_parameters: int | None
    trainable_parameters: int | None

    def as_tuple(self) -> ProbeResult:
        if self.setup_error is not None:
            raise ModelProbeSetupError(self.setup_error)
        return (
            self.instantiation_ok,
            self.gradient_ok,
            self.output_type_ok,
            self.error,
            self.total_parameters,
            self.trainable_parameters,
        )


def _host_memory_budget_bytes() -> int:
    """Leave room for the parent, OS, and unrelated work on the same host."""
    total = psutil.virtual_memory().total
    cgroup_limit = Path("/sys/fs/cgroup/memory.max")
    if cgroup_limit.is_file():
        raw = cgroup_limit.read_text(encoding="ascii").strip()
        if raw.isdecimal():
            total = min(total, int(raw))
    return min(96 * 1024**3, max(256 * 1024**2, total // 2))


def _worker_address_space_limit() -> int:
    # Torch reserves address space that is not resident memory. Add the budget
    # to the worker's current virtual size after importing Torch, so that the
    # limit constrains new allocations without treating reservations as RSS.
    return psutil.Process().memory_info().vms + _host_memory_budget_bytes()


def run_bounded_probe(
    model_file_path: str,
    model_io_contract: ModelIOContract | None,
    *,
    model_probe_context: ModelProbeContext | None = None,
) -> ProbeResult:
    """Return a failed candidate verdict if its isolated check exceeds resources."""
    with tempfile.TemporaryDirectory(prefix="siderius-validator-") as directory:
        request = Path(directory) / "request.json"
        result = Path(directory) / "result.json"
        request.write_text(
            ProbeRequest(
                model_file_path=model_file_path,
                model_io_contract=model_io_contract,
                model_probe_context=model_probe_context,
                result_path=str(result),
            ).model_dump_json(),
            encoding="utf-8",
        )
        invocation = prepare_child(
            [sys.executable, "-m", "agent.skills.validator_probe_worker", str(request)],
            subprocess_env(plugin_dir=str(Path(model_file_path).parent)),
        )
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as output:
            try:
                completed = subprocess.run(
                    invocation.argv,
                    env=invocation.env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                    check=False,
                )
                invocation.check(completed.returncode)
            except subprocess.TimeoutExpired:
                return False, False, False, "Validation probe exceeded 300 seconds", None, None
            output.seek(0, os.SEEK_END)
            output.seek(max(0, output.tell() - 1000))
            output_tail = output.read()[-500:]
        if completed.returncode != 0 or not result.is_file():
            return (
                False,
                False,
                False,
                (
                    f"Isolated validation probe exited {completed.returncode} "
                    f"(budget {_host_memory_budget_bytes() // 1024**3} GiB): "
                    f"{output_tail}"
                ),
                None,
                None,
            )
        return ProbeResponse.model_validate_json(result.read_bytes()).as_tuple()


def main() -> None:
    request = ProbeRequest.model_validate_json(Path(sys.argv[1]).read_bytes())
    # Import Torch before setting the virtual-address ceiling. Torch reserves
    # virtual address space without consuming that amount of host memory.
    import torch  # noqa: F401

    # The child has not constructed the candidate. A single huge vectorized
    # allocation now fails here instead of taking down the chain process.
    limit = _worker_address_space_limit()
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    from nodes.ml_code_validator_agent.ml_code_validator_agent import (
        _check_instantiation_and_gradient,
    )

    options = (
        {"model_probe_context": request.model_probe_context}
        if request.model_probe_context is not None
        else {}
    )
    setup_error = None
    try:
        verdict = _check_instantiation_and_gradient(
            request.model_file_path,
            request.model_io_contract,
            _isolated_worker=True,
            **options,
        )
    except ModelProbeSetupError as error:
        setup_error = str(error)
        verdict = (False, False, False, None, None, None)
    Path(request.result_path).write_text(
        ProbeResponse(
            setup_error=setup_error,
            instantiation_ok=verdict[0],
            gradient_ok=verdict[1],
            output_type_ok=verdict[2],
            error=verdict[3],
            total_parameters=verdict[4],
            trainable_parameters=verdict[5],
        ).model_dump_json(),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
