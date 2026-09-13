"""Real workflow and runner halt boundaries; node calls are deterministic doubles."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core.local_code import LocalCodeError
from execute_tools.task_registration_scope import run_registration_scope
from tests.unit.workflows import test_model_exploration as harness
from tests.unit.workflows.test_model_exploration import workflow_env
from workflows import run_one_iteration as runner
from workflows.run_config import WorkflowLaunchConfig


@pytest.mark.parametrize("integrity", [True, False])
def test_proposal_failure_is_terminal_only_for_named_package_refusal(workflow_env, integrity):
    failure = LocalCodeError("undeclared helper") if integrity else RuntimeError("candidate error")
    proposer = workflow_env["propose"].return_value.run
    proposer.side_effect = [failure, harness._make_proposal_output()]
    launch = WorkflowLaunchConfig(
        data_dir=workflow_env["data_dir"],
        model_types=["punet"],
        source_run_name="v1",
        max_iterations=1,
    )
    if integrity:
        with pytest.raises(LocalCodeError) as raised:
            harness.run_workflow(
                launch=launch, workspace=workflow_env["workspace"], run_name="test"
            )
        assert raised.value is failure
        assert proposer.call_count == 1
        workflow_env["tune"].return_value.run.assert_not_called()
    else:
        result = harness.run_workflow(
            launch=launch, workspace=workflow_env["workspace"], run_name="test"
        )
        assert len(result) == 1 and proposer.call_count == 2


def test_tuner_refusal_stops_internal_workflow_before_promotion_or_next_iteration(
    workflow_env, monkeypatch
):
    from workflows import model_exploration

    promotions = []
    # Validated source promotion precedes tuning in the existing workflow.
    # No further promotion/result commit may happen after the refusal.
    monkeypatch.setattr(
        model_exploration, "_promote_loss_to_global", lambda *a, **kw: promotions.append(a)
    )
    refusal = LocalCodeError("declared helper no longer matches")
    promotions_before_tune = []

    def tune(_input):
        promotions_before_tune.extend(promotions)
        raise refusal

    workflow_env["tune"].return_value.run.side_effect = tune
    with pytest.raises(LocalCodeError) as raised:
        harness.run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=3,
            ),
            workspace=workflow_env["workspace"],
            run_name="test",
        )
    assert raised.value is refusal
    assert workflow_env["tune"].return_value.run.call_count == 1
    assert workflow_env["interp"].return_value.run.call_count == 1
    assert promotions == promotions_before_tune
    assert (Path(workflow_env["workspace"]) / "test/iteration_001").is_dir()
    assert not (Path(workflow_env["workspace"]) / "test/iteration_002").exists()


@pytest.mark.parametrize("wrapped", [True, False])
def test_real_entry_halts_on_composition_refusal_and_queued_entry_stays_halted(
    tmp_path, monkeypatch, capsys, wrapped
):
    refusal = LocalCodeError("declared package cannot be captured")
    failure = ValueError("composition constructor") if wrapped else refusal
    if wrapped:
        failure.__cause__ = refusal

    def compose(_path):
        raise failure

    monkeypatch.setattr(runner, "compose_run_task_bindings", compose)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--workspace",
            str(tmp_path),
            "--run_name",
            "terminal",
            "--start_iteration",
            "1",
            "--task_composition",
            "not-read.yaml",
            "--data_dir",
            str(tmp_path),
            "--healthgate_mode",
            "blocking",
            "--result_authority",
            "scientific",
        ],
    )
    with pytest.raises(SystemExit) as raised:
        runner.main()
    assert raised.value.code == 3
    marker = tmp_path / ".chain_halted"
    payload = json.loads(marker.read_text())
    assert payload["reason"] == "code_package_integrity"
    assert payload["detail"] == str(refusal)
    assert payload["iteration"] == 1
    original = marker.read_bytes()
    monkeypatch.setattr(runner, "compose_run_task_bindings", harness.compose_run_task_bindings)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--workspace",
            str(tmp_path),
            "--run_name",
            "terminal",
            "--start_iteration",
            "2",
            "--task_composition",
            str(harness.QUICKSTART),
            "--data_dir",
            str(tmp_path),
            "--healthgate_mode",
            "blocking",
            "--result_authority",
            "scientific",
        ],
    )
    with run_registration_scope(), pytest.raises(SystemExit) as queued:
        runner.main()
    assert queued.value.code == 3
    assert marker.read_bytes() == original
    assert "chain halt marker present" in capsys.readouterr().err


@pytest.mark.parametrize("integrity", [True, False])
def test_real_runner_workflow_catch_persists_crash_then_only_package_halts(tmp_path, integrity):
    from tests.unit.sdsc_submission_scripts.test_run_one_iteration import (
        TestNoRecordsExit,
        _run_main,
    )

    seed = TestNoRecordsExit()._seed_file(tmp_path)
    failure = (
        LocalCodeError("task helper refused") if integrity else RuntimeError("candidate error")
    )
    with (
        run_registration_scope(),
        patch("workflows.model_exploration.run_workflow", side_effect=failure),
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
    assert code == (3 if integrity else 1)
    manifest = json.loads((tmp_path / "iter_001/manifest.json").read_text())
    assert manifest["status"] == "failed" and manifest["output_path"] is None
    assert (tmp_path / ".chain_halted").exists() is integrity
