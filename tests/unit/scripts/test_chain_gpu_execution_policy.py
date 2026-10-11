"""The native chain must transport an explicit GPU policy without a custom loop."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FLAG = "--gpu_execution_policy_json"


def dry_chain(tmp_path: Path, mode: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/launch/run_chain.sh"),
            "--mode",
            mode,
            "--dry-run",
            "--no_auto_resume",
            "--workspace",
            str(tmp_path / "workspace"),
            "--run_name",
            "policy_transport",
            "--num_iterations",
            "3",
            "--task_composition",
            str(ROOT / "configs/task_composition/quickstart.yaml"),
            "--data_dir",
            str(tmp_path),
            *extra,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )


def commands(result: subprocess.CompletedProcess[str]) -> list[list[str]]:
    assert result.returncode == 0, result.stdout + result.stderr
    return [
        shlex.split(line)
        for line in result.stdout.splitlines()
        if line.startswith("    ") and "--start_iteration" in line
    ]


@pytest.mark.parametrize("mode", ["lilab", "sdsc"])
def test_policy_reaches_every_submission_without_changing_other_arguments(tmp_path, mode):
    """Fails if parsing, quoting, either submitter or any iteration drops the path."""
    # Dry-run transports paths; the Python runner, not Bash, validates the file.
    path = str(tmp_path / "GPU policy $(must-not-run); profile.json")
    original = commands(dry_chain(tmp_path, mode))
    selected = commands(dry_chain(tmp_path, mode, FLAG, path))
    assert len(original) == len(selected) == 3
    for iteration, (before, after) in enumerate(zip(original, selected, strict=True), 1):
        assert FLAG not in before
        assert after.count(FLAG) == 1
        index = after.index(FLAG)
        assert after[index + 1] == path
        assert after[after.index("--start_iteration") + 1] == str(iteration)
        assert after[:index] + after[index + 2 :] == before
    assert not (tmp_path / "workspace").exists()


@pytest.mark.parametrize("tail", [(), ("",), ("--max_rounds", "2")])
def test_missing_policy_value_refuses_before_any_submission(tmp_path, tail):
    """Fails if an empty or next-option value is silently accepted or loops forever."""
    result = dry_chain(tmp_path, "lilab", FLAG, *tail)
    assert result.returncode != 0
    assert "Required: --gpu_execution_policy_json FILE" in result.stderr
    assert "would exec" not in result.stdout
    assert not (tmp_path / "workspace").exists()
