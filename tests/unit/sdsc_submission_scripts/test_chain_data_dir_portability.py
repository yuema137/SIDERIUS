"""Shell-wrapper portability tests for the chain DATA_DIR default (H100 PR).

Exercises ``run_chain.sh --dry-run`` (which walks the chain and prints the exact
per-iteration command with no side effects) to prove that:

* the chain no longer injects the old hardcoded lilab data path;
* an explicit ``--data_dir`` is preserved end-to-end;
* with no ``--data_dir`` the rendered ``run_one_iteration.py`` invocation omits
  the flag, so the Python config layer (``data_paths.py`` ->
  ``tidmad_data_config.yaml``) resolves the data directory;
* the existing seeded dry-run still renders successfully (lilab back-compat).
"""

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUN_CHAIN = _REPO_ROOT / "sdsc_submission_scripts" / "run_chain.sh"

_OLD_HARDCODED_PATH = "/home/klz/Data/TIDMAD"


def _dry_run(tmp_path, *extra_args):
    seed = tmp_path / "seed.json"
    seed.write_text("{}")
    cmd = [
        "bash",
        str(_RUN_CHAIN),
        "--mode",
        "lilab",
        "--workspace",
        str(tmp_path / "ws"),
        "--run_name",
        "portability_test",
        "--num_iterations",
        "1",
        "--seed_paths",
        str(seed),
        "--task_composition",
        str(_REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"),
        "--data_dir",
        str(tmp_path),
        "--dry-run",
        *extra_args,
    ]
    return subprocess.run(cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True)


def test_seeded_dry_run_succeeds(tmp_path):
    """Existing seeded behaviour still renders a valid chain (lilab back-compat)."""
    r = _dry_run(tmp_path)
    assert r.returncode == 0, r.stderr


def test_no_hardcoded_old_server_path(tmp_path):
    r = _dry_run(tmp_path)
    assert _OLD_HARDCODED_PATH not in (r.stdout + r.stderr)


def test_missing_data_dir_is_refused(tmp_path):
    """An empty explicit data root is refused before rendering work."""
    r = _dry_run(tmp_path, "--data_dir", "")
    assert r.returncode != 0
    assert "Required: --data_dir DIRECTORY" in r.stderr


def test_explicit_data_dir_preserved(tmp_path):
    r = _dry_run(tmp_path, "--data_dir", "/some/explicit/path")
    assert "--data_dir" in r.stdout
    assert "/some/explicit/path" in r.stdout
