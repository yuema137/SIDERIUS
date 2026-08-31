"""Regression coverage for workspace-owned execution state.

External consumers import SIDERIUS from a source checkout.  A synchronized
four-task qualification at framework ``3eb8fc67`` left five ignored ``.pyc``
files in that checkout even though every declared run artifact was correctly
workspace-owned.  These tests protect the two supported launch boundaries:
the chain wrapper before its source-authority probe, and the direct
one-iteration Python entry point before any framework import.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_CHAIN = REPO_ROOT / "sdsc_submission_scripts" / "run_chain.sh"
RUN_ONE = REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py"


def test_chain_exports_no_bytecode_policy_before_every_python_call(tmp_path: Path) -> None:
    """Catch the shell entry point invoking Python before checkout writes are disabled.

    A fake activated interpreter records the environment for the version and
    source-authority probes.  Removing or moving the export makes at least one
    recorded line differ from ``1``.
    """
    fake_venv = tmp_path / "venv"
    fake_python = fake_venv / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "${PYTHONDONTWRITEBYTECODE:-<unset>}" >> "$BYTECODE_ENV_LOG"\n'
        'case "$1" in\n'
        "  -c) exit 0 ;;\n"
        "  *) printf '%s\\n' '[source-authority] PASS (tree-only)'; exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    seed = tmp_path / "seed.json"
    seed.write_text("{}", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env_log = tmp_path / "bytecode-env.log"
    env = os.environ.copy()
    env.update(
        {
            "VIRTUAL_ENV": str(fake_venv),
            "BYTECODE_ENV_LOG": str(env_log),
        }
    )
    proc = subprocess.run(
        [
            "bash",
            str(RUN_CHAIN),
            "--mode",
            "lilab",
            "--workspace",
            str(tmp_path / "workspace"),
            "--run_name",
            "bytecode_boundary",
            "--task_composition",
            str(REPO_ROOT / "configs/task_composition/quickstart.yaml"),
            "--data_dir",
            str(data_dir),
            "--num_iterations",
            "1",
            "--seed_paths",
            str(seed),
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    observed = env_log.read_text(encoding="utf-8").splitlines()
    assert len(observed) >= 2, "version and source-authority probes must both execute"
    assert set(observed) == {"1"}


def test_direct_iteration_disables_bytecode_before_framework_imports() -> None:
    """Catch direct invocation importing SIDERIUS before setting its policy.

    ``run_one_iteration.py`` is a supported entry point independent of the
    shell chain.  The textual ordering assertion is intentional: importing
    the module to test the setting would execute the very framework imports
    whose order is under test.
    """
    source = RUN_ONE.read_text(encoding="utf-8")
    policy_env = source.index('os.environ["PYTHONDONTWRITEBYTECODE"] = "1"')
    policy_runtime = source.index("sys.dont_write_bytecode = True")
    first_framework_import = min(
        source.index("from agent."),
        source.index("from core."),
        source.index("from execute_tools."),
        source.index("from workflows."),
    )

    assert policy_env < first_framework_import
    assert policy_runtime < first_framework_import
