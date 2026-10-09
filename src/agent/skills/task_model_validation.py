"""Candidate checks and subprocess setup-failure transport for task-owned inputs."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.model_probe import ModelProbeContext, ModelProbeFailure, ModelProbeSetupError
from agent.skills.model_io_probe_skill import ProbeConstructionError, candidate_probe_extent
from agent.skills.task_model_probe import task_model_probe_cases
from core.local_code.failure import raise_if_code_package_failure

FAILURE_PATH_ENV = "SIDERIUS_MODEL_PROBE_FAILURE_PATH"


def check_task_model(
    model,
    config,
    contract: ModelIOContract | None,
    context: ModelProbeContext,
    output_type: str,
    *,
    gradients: bool,
) -> tuple[bool, bool, bool, str | None]:
    """Fixture failures raise; candidate failures return the validator's verdict."""
    import torch

    try:
        cases = task_model_probe_cases(
            context,
            contract,
            output_type,
            symbolic=candidate_probe_extent(config, contract),
        )
    except ProbeConstructionError as exc:
        return False, False, False, f"Candidate probe cannot be constructed: {exc}"
    for case in cases:
        try:
            with torch.set_grad_enabled(gradients):
                output = model(case.input)
        except Exception as exc:
            raise_if_code_package_failure(exc)
            return False, False, False, f"Forward pass failed: {exc}"
        if (
            not isinstance(output, torch.Tensor)
            or tuple(output.shape) != case.expected_output_shape
            or not torch.isfinite(output).all()
        ):
            return (
                False,
                False,
                False,
                (f"Forward must return a finite tensor with shape {case.expected_output_shape}"),
            )
        if gradients:
            try:
                model.zero_grad(set_to_none=True)
                output.sum().backward()
            except Exception as exc:
                raise_if_code_package_failure(exc)
                return True, False, True, f"Backward pass failed: {exc}"
    return True, True, True, None


def report_setup_failure(error: ModelProbeSetupError) -> None:
    """Publish a structured failure only to the parent-owned pytest channel."""
    path = os.environ.get(FAILURE_PATH_ENV)
    if path:
        with Path(path).open("x", encoding="utf-8") as stream:
            stream.write(ModelProbeFailure(message=str(error)).model_dump_json())


def raise_child_setup_failure(path: Path) -> None:
    if path.exists():
        failure = ModelProbeFailure.model_validate_json(path.read_bytes())
        raise ModelProbeSetupError(failure.message)


def run_task_model_tests(test_file_path: str) -> tuple[bool, str]:
    """Preserve task setup failures across pytest without parsing its prose."""
    from core.local_code.child import prepare_child
    from core.subprocess_env import subprocess_env

    with tempfile.TemporaryDirectory(prefix="siderius-model-probe-") as directory:
        failure_path = Path(directory) / "setup-failure.json"
        env = subprocess_env()
        env[FAILURE_PATH_ENV] = str(failure_path)
        invocation = prepare_child(
            [sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"],
            env,
        )
        try:
            result = subprocess.run(
                invocation.argv, capture_output=True, text=True, env=invocation.env
            )
        except Exception as exc:
            invocation.check(getattr(exc, "returncode", None))
            raise
        invocation.check(result.returncode)
        raise_child_setup_failure(failure_path)
        return result.returncode == 0, result.stdout + result.stderr


def render_task_model_test(
    model_name: str,
    contract: ModelIOContract,
    context: ModelProbeContext,
) -> str:
    """Generated tests use the shared checker and explicit identity, never random data."""
    return f"""import os
import sys

from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.model_probe import ModelProbeContext, ModelProbeSetupError
from agent.skills.model_io_probe_skill import probe_config_kwargs
from agent.skills.task_model_validation import check_task_model, report_setup_failure

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "models"))
from {model_name} import PLUGIN_CONFIG_CLASS, PLUGIN_MODEL_CLASS, PLUGIN_OUTPUT_TYPE

CONTRACT = ModelIOContract.model_validate_json({contract.model_dump_json()!r})
CONTEXT = ModelProbeContext.model_validate_json({context.model_dump_json()!r})


def test_task_owned_forward_and_gradient():
    config = PLUGIN_CONFIG_CLASS(**probe_config_kwargs(PLUGIN_CONFIG_CLASS, CONTRACT))
    model = PLUGIN_MODEL_CLASS(config)
    model.train()
    try:
        result = check_task_model(model, config, CONTRACT, CONTEXT, PLUGIN_OUTPUT_TYPE,
                                  gradients=True)
    except ModelProbeSetupError as error:
        report_setup_failure(error)
        raise
    assert all(result[:3]), result[3]
"""
