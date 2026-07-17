"""Completion/exit contract for ``scripts.run_comparison``."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.run_comparison import (
    PARTIAL_CAMPAIGN_EXIT_CODE,
    _read_tuner_completion,
    run_agent,
)


def _write_output(path, *, status, completed_rounds, termination_reason):
    path.write_text(
        json.dumps(
            {
                "status": status,
                "completed_rounds": completed_rounds,
                "termination_reason": termination_reason,
            }
        ),
        encoding="utf-8",
    )


def _run_agent(workspace, *, max_rounds=10):
    return run_agent(
        model_type="punet",
        agent_workspace=str(workspace),
        agent_run_name="campaign_agent",
        provider="openai",
        model_id="test-model",
        max_rounds=max_rounds,
    )


def test_completed_ten_of_ten_is_success(tmp_path):
    output = tmp_path / "run_output_campaign_agent.json"
    _write_output(
        output,
        status="completed",
        completed_rounds=10,
        termination_reason="completed",
    )
    with patch(
        "scripts.run_comparison.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ):
        _run_agent(tmp_path)

    complete, detail = _read_tuner_completion(str(output), requested_rounds=10)
    assert complete is True
    assert detail == "10/10 rounds completed"


def test_partial_three_of_ten_returns_stable_nonzero(tmp_path, capsys):
    output = tmp_path / "run_output_campaign_agent.json"
    _write_output(
        output,
        status="partial",
        completed_rounds=3,
        termination_reason="aborted_fail_rounds",
    )
    # The child is shell-clean; the persisted result remains authoritative.
    with patch(
        "scripts.run_comparison.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ), pytest.raises(SystemExit) as exc:
        _run_agent(tmp_path)

    assert exc.value.code == PARTIAL_CAMPAIGN_EXIT_CODE
    message = capsys.readouterr().out
    assert "Comparison run ended partial" in message
    assert "3/10 rounds completed" in message
    assert "termination_reason=aborted_fail_rounds" in message


def test_partial_exit_prevents_sequential_next_launch(tmp_path):
    output = tmp_path / "run_output_campaign_agent.json"
    _write_output(
        output,
        status="partial",
        completed_rounds=3,
        termination_reason="aborted_fail_rounds",
    )
    next_model_launched = False

    with patch(
        "scripts.run_comparison.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ):
        def launch_sequence():
            nonlocal next_model_launched
            _run_agent(tmp_path)
            next_model_launched = True

        with pytest.raises(SystemExit):
            launch_sequence()

    assert next_model_launched is False


@pytest.mark.parametrize(
    ("status", "rounds", "reason"),
    [
        ("partial", 3, "aborted_fail_rounds"),
        ("failed", 0, "unrecoverable_error"),
        ("completed", 9, "completed"),
    ],
)
def test_persisted_summary_and_completion_contract_agree(
    tmp_path, status, rounds, reason
):
    output = tmp_path / "run_output.json"
    _write_output(
        output,
        status=status,
        completed_rounds=rounds,
        termination_reason=reason,
    )
    complete, detail = _read_tuner_completion(str(output), requested_rounds=10)
    assert complete is False
    assert f"status={status}" in detail
    assert f"{rounds}/10" in detail
