"""A deterministic metric conflict halts; ordinary candidate errors retain retries."""

import json
from unittest.mock import patch

import pytest

from execute_tools.evaluation_metric import MetricIdentityConflictError
from execute_tools.task_registration_scope import run_registration_scope
from nodes.result_interpretation_agent.evidence import InterpretationContractError
from tests.unit.sdsc_submission_scripts.test_run_one_iteration import (
    TestNoRecordsExit as _SeedFixture,
)
from tests.unit.sdsc_submission_scripts.test_run_one_iteration import (
    _run_main,
)


@pytest.mark.parametrize(
    "error,exit_code",
    [
        (InterpretationContractError("declaration conflict"), 3),
        (MetricIdentityConflictError("metric conflict"), 3),
        (RuntimeError("candidate failed"), 1),
    ],
)
def test_runner_preserves_failed_manifest_and_halts_only_contract_errors(
    tmp_path, error, exit_code
):
    seed = _SeedFixture()._seed_file(tmp_path)
    with (
        run_registration_scope(),
        patch("workflows.model_exploration.run_workflow", side_effect=error),
    ):
        code = _run_main(
            [
                "--workspace",
                str(tmp_path),
                "--start_iteration",
                "1",
                "--seed_paths",
                str(seed),
            ]
        )
    assert code == exit_code
    assert json.loads((tmp_path / "iter_001/manifest.json").read_text())["status"] == "failed"
    marker = tmp_path / ".chain_halted"
    assert marker.exists() == (exit_code == 3)
    if marker.exists():
        assert json.loads(marker.read_text())["reason"] == "run_contract_failure"
        with (
            run_registration_scope(),
            patch("workflows.model_exploration.run_workflow") as workflow,
        ):
            assert (
                _run_main(
                    [
                        "--workspace",
                        str(tmp_path),
                        "--start_iteration",
                        "2",
                        "--seed_paths",
                        str(seed),
                    ]
                )
                == 3
            )
        workflow.assert_not_called()
        assert not (tmp_path / "iter_002").exists()
