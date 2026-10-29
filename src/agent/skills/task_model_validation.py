"""Candidate checks and subprocess setup-failure transport for task-owned inputs."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.model_probe import ModelProbeContext, ModelProbeFailure, ModelProbeSetupError
from agent.skills.model_io_probe_skill import ProbeConstructionError, candidate_probe_extent
from agent.skills.task_model_probe import task_model_probe_cases
from core.local_code.failure import raise_if_code_package_failure

if TYPE_CHECKING:
    from agent.skills.generated_pytest import PytestLimit

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
            candidate_config=config,
        )
    except ProbeConstructionError as exc:
        return False, False, False, f"Candidate probe cannot be constructed: {exc}"
    assert contract is not None  # task_model_probe_cases rejects absent contracts
    for case in cases:
        try:
            with torch.set_grad_enabled(gradients):
                output = model(case.input)
        except Exception as exc:
            raise_if_code_package_failure(exc)
            return False, False, False, f"Forward pass failed: {exc}{case.description}"
        from agent.skills.model_output_geometry import validate_model_output

        try:
            validate_model_output(contract, output_type, case.input, output)
        except ProbeConstructionError as exc:
            return False, False, False, f"{exc}{case.description}"
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


def run_task_model_tests(
    test_file_path: str,
    *,
    limit: PytestLimit | None = None,
    seed_env: Mapping[str, str],
) -> tuple[bool, str]:
    """Preserve task setup failures across pytest without parsing its prose.

    ``limit`` is the caller's declared limit; ``None`` runs the
    group-supervised child without a deadline (see ``generated_pytest``).
    ``seed_env`` (``core.probe_seeds.probe_seed_env``) hands the probe's
    SeedContext to the generated test's ``run_bounded_probe``.
    """
    from agent.skills.generated_pytest import run_generated_pytest
    from core.subprocess_env import subprocess_env

    with tempfile.TemporaryDirectory(prefix="siderius-model-probe-") as directory:
        failure_path = Path(directory) / "setup-failure.json"
        env = subprocess_env()
        env[FAILURE_PATH_ENV] = str(failure_path)
        env.update(seed_env)
        passed, output = run_generated_pytest(test_file_path, env, limit=limit)
        raise_child_setup_failure(failure_path)
        return passed, output


def render_task_model_test(
    model_name: str,
    contract: ModelIOContract,
    context: ModelProbeContext,
) -> str:
    """Generated tests use the shared checker and explicit identity, never random data."""
    from agent.skills.task_model_probe_contract import task_probe_declaration

    if task_probe_declaration(context, contract) is not None:
        return f"""from pathlib import Path
from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.model_probe import ModelProbeContext, ModelProbeSetupError
from agent.skills.validator_probe_worker import run_bounded_probe
from agent.skills.task_model_validation import report_setup_failure

CONTRACT = ModelIOContract.model_validate_json({contract.model_dump_json()!r})
CONTEXT = ModelProbeContext.model_validate_json({context.model_dump_json()!r})


def test_task_owned_forward_and_gradient():
    model_path = Path(__file__).resolve().parent.parent / "models" / {f"{model_name}.py"!r}
    try:
        result = run_bounded_probe(str(model_path), CONTRACT, model_probe_context=CONTEXT)
    except ModelProbeSetupError as error:
        report_setup_failure(error)
        raise
    assert all(result[:3]), result[3]
"""
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
