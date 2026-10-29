"""Plan output must remain machine-readable when a stale split is dropped."""

import json
import subprocess
from pathlib import Path

import pytest

from tools.ci import __main__ as cli
from tools.ci.selection import Selection


def test_plan_stdout_is_json_with_a_stale_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """json.loads fails if the dropped-split diagnostic leaks onto stdout."""
    name = "tests/unit/test_example.py"
    monkeypatch.setattr(
        cli, "resolve_selection", lambda root, changed: Selection((name,), True, "fixture")
    )
    monkeypatch.setattr(cli, "load_weights", lambda: {name: 10.0})
    monkeypatch.setattr(cli, "load_splits", lambda: {name: {"test_removed": 10.0}})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{name}::test_current\n", stderr=""
        ),
    )

    assert cli.main(["plan", "--root", str(tmp_path)]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["files"] == 1
    assert "selection: fixture" in captured.err
    assert f"split for {name} DROPPED" in captured.err
