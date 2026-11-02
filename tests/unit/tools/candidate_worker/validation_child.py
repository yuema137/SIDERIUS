"""Fresh CPU validation for fork-based lifecycle fixtures, with an offline provider."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

from agent.skills.generated_pytest import PytestLimit, run_generated_pytest
from tools.candidate_worker.unit_child import run_invocation_file

from .test_native import Provider


def install_fresh_validation_units(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Warm parent autograd and exec gradient-bearing units with explicit doubles."""
    import torch

    from core.runtime_control.observed_subprocess import supervise_subprocess
    from tools.candidate_worker import unit_runner
    from tools.candidate_worker.graph_evidence import read_graph_control
    from tools.candidate_worker.unit_models import NodeInvocation, ValidationUnit
    from tools.candidate_worker.unit_transport import decode_transport

    # Make the broad-run precondition explicit even in isolated lifecycle tests.
    # Real backward validation must still pass after the parent initialized autograd.
    torch.ones(8, requires_grad=True).square().sum().backward()
    in_process = unit_runner.spawn_unit

    def spawn_unit(invocation_path: str) -> None:
        invocation = decode_transport(NodeInvocation, read_graph_control(Path(invocation_path)))
        if not isinstance(invocation.unit, ValidationUnit):
            return in_process(invocation_path)
        supervise_subprocess(
            [
                sys.executable,
                "-c",
                "import os, runpy, sys; os.chdir(sys.argv.pop(1)); "
                "runpy.run_module('tests.unit.tools.candidate_worker.validation_child', "
                "run_name='__main__')",
                str(Path(__file__).resolve().parents[4]),
                invocation_path,
                str(tmp_path / "pytest_limits.jsonl"),
            ],
            env=dict(os.environ),
            preexec_fn=None,
            capture_stdout=False,
            label="offline validation unit",
        )

    monkeypatch.setattr(unit_runner, "spawn_unit", spawn_unit)


def validate(invocation_path: Path, pytest_record: Path) -> None:
    """Retain real gradient/pytest validation and record its transported budget."""
    validator = importlib.import_module("nodes.ml_code_validator_agent.ml_code_validator_agent")

    def recorded_pytest(
        test_file_path: str, env: dict[str, str], *, limit: PytestLimit | None = None
    ) -> tuple[bool, str]:
        with pytest_record.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "path": test_file_path,
                        "limit": None if limit is None else limit.model_dump(),
                    }
                )
                + "\n"
            )
        return run_generated_pytest(test_file_path, env, limit=limit)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(validator, "LLMBridge", Provider)
        patch.setattr(validator, "run_generated_pytest", recorded_pytest)
        run_invocation_file(invocation_path)


if __name__ == "__main__":
    validate(Path(sys.argv[1]), Path(sys.argv[2]))
