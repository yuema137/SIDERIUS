"""Malformed optional pseudo ceiling uses the standard launch refusal."""

import sys
from pathlib import Path

import pytest

from workflows import run_one_iteration


def test_launch_refuses_malformed_override_before_iteration_setup(tmp_path, monkeypatch, capsys):
    """Removing launch-time resolution would reach the forbidden setup seam."""
    monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "invalid")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_one_iteration",
            "--workspace",
            str(tmp_path / "run"),
            "--run_name",
            "pseudo-envelope",
            "--start_iteration",
            "1",
            "--healthgate_mode",
            "blocking",
            "--result_authority",
            "scientific",
            "--task_composition",
            str(Path(__file__).resolve().parents[3] / "configs/task_composition/quickstart.yaml"),
            "--data_dir",
            str(data),
            "--is_pseudo_llm",
            "--is_pseudo_training",
        ],
    )

    def forbidden(*args, **kwargs):
        pytest.fail("malformed pseudo override reached iteration setup")

    monkeypatch.setattr(run_one_iteration, "prepare_iteration_dir", forbidden)
    with pytest.raises(SystemExit) as exc:
        run_one_iteration.main()
    assert exc.value.code == 2
    assert "LAUNCH REFUSED:" in capsys.readouterr().err
