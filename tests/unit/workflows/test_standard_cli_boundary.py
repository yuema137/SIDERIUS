"""Setup inspection must reuse launch defaults without importing the launcher."""

import os
import subprocess
import sys

import pytest

from workflows import advice, run_one_iteration, standard_cli


def test_cli_owner_import_does_not_load_dotenv_or_write_workspace(tmp_path):
    """Catches accidental import of the effectful runner from its new owner."""
    script = """
import os
import socket
import sys
from pathlib import Path
import dotenv

def forbidden(*args, **kwargs):
    raise AssertionError('configuration import attempted launch effects')

dotenv.load_dotenv = forbidden
socket.socket.connect = forbidden
socket.create_connection = forbidden
before = set(Path.cwd().iterdir())
from workflows.standard_cli import build_parser, normalize_args
assert 'workflows.run_one_iteration' not in sys.modules
args = normalize_args(build_parser().parse_args([
    '--workspace', str(Path.cwd() / 'runs'), '--run_name', 'new_user',
    '--start_iteration', '1', '--task_composition', 'task.yaml', '--data_dir', 'data',
]))
assert args.start_iteration == 1
assert set(Path.cwd().iterdir()) == before
"""
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_production_main_uses_the_same_parser_and_normalizer(monkeypatch, tmp_path):
    """Fails if execution bypasses the functions exposed to setup inspection."""
    assert run_one_iteration.build_parser is standard_cli.build_parser
    assert run_one_iteration.normalize_args is standard_cli.normalize_args
    assert run_one_iteration.load_advice_artifact is advice.load_advice_artifact

    class ReachedNormalization(Exception):
        pass

    def capture(args):
        normalized = standard_cli.normalize_args(args)
        assert normalized.start_iteration == 1
        assert normalized.max_rounds == 3
        assert normalized.run_name == "new_user"
        raise ReachedNormalization

    monkeypatch.setattr(run_one_iteration, "normalize_args", capture)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_one_iteration",
            "--workspace",
            str(tmp_path / "runs"),
            "--run_name",
            "new_user",
            "--start_iteration",
            "1",
            "--task_composition",
            "task.yaml",
            "--data_dir",
            "data",
        ],
    )
    with pytest.raises(ReachedNormalization):
        run_one_iteration.main()
    assert not (tmp_path / "runs").exists()
