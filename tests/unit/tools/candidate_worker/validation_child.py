"""Fresh CPU validation for fork-based lifecycle fixtures, with an offline provider."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from agent.skills.generated_pytest import PytestLimit, run_generated_pytest
from tools.candidate_worker.unit_child import run_invocation_file
from tools.candidate_worker.unit_runner import spawn_unit as spawn_graph_unit

from .provider_usage import install_reporting
from .test_native import Provider


def install_fresh_validation_units(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Warm parent autograd and exec gradient-bearing units with explicit doubles."""
    import torch

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

        def command(path: str) -> list[str]:
            return [
                sys.executable,
                "-c",
                "import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); "
                "runpy.run_module('tests.unit.tools.candidate_worker.validation_child', "
                "run_name='__main__')",
                str(Path(__file__).resolve().parents[4]),
                path,
                str(tmp_path / "pytest_limits.jsonl"),
                str(tmp_path / "reported_calls.log"),
            ]

        # Keep production's environment, supervision and stderr handling together.
        # Only the command installs our explicitly trusted checkout's offline doubles.
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(unit_runner, "unit_command", command)
            spawn_graph_unit(invocation_path)

    monkeypatch.setattr(unit_runner, "spawn_unit", spawn_unit)


def validate(invocation_path: Path, pytest_record: Path, usage_record: Path) -> None:
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
        if usage_record.is_file():
            install_reporting(patch, Provider, usage_record)
        patch.setattr(validator, "LLMBridge", Provider)
        patch.setattr(validator, "run_generated_pytest", recorded_pytest)
        run_invocation_file(invocation_path)


if __name__ == "__main__":
    validate(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
