"""Missing CPU pseudo envelope refuses before workflow or workspace setup."""

import sys
from pathlib import Path

import pytest

from core.pseudo_admission import PseudoEnvelopeRequired
from workflows import run_one_iteration


def test_launch_refuses_missing_envelope_before_iteration_setup(tmp_path, monkeypatch):
    """Removing launch-time resolution would reach the forbidden setup seam."""
    monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
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
        pytest.fail("missing pseudo envelope reached iteration setup")

    monkeypatch.setattr(run_one_iteration, "prepare_iteration_dir", forbidden)
    with pytest.raises(PseudoEnvelopeRequired, match="PSEUDO_ENVELOPE_REQUIRED"):
        run_one_iteration.main()
