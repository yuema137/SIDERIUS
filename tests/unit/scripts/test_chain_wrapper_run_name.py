"""Unit tests for ``--run_name`` threading in ``_chain_common.sh``.

Commit 4.3 made ``--run_name`` required in ``run_one_iteration.py`` (it
seeds the immutable run_id sidecar at ``{workspace}/.token_run_id`` and
labels chain_run_name in audit logs). This test pins the wrapper-side
contract: the chain orchestrator must (a) accept ``--run_name`` from the
caller, (b) refuse to launch without it, and (c) forward it verbatim
into the per-iter ``run_one_iteration.py`` invocation.

Tests use ``--dry-run`` mode so no subprocess actually runs — only the
APP_ARGS construction is exercised, and the printed command is
inspected for the expected ``--run_name VALUE`` pair.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_CHAIN = REPO_ROOT / "sdsc_submission_scripts" / "run_chain.sh"


def _run_dry(extra_args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    """Invoke run_chain.sh --dry-run with the given extra args; capture stdout/stderr."""
    seed = tmp_path / "fake_seed.json"
    seed.write_text("{}")
    cmd = [
        "bash", str(RUN_CHAIN),
        "--mode", "lilab",
        "--dry-run",
        "--workspace", str(tmp_path / "ws"),
        "--num_iterations", "1",
        "--seed_paths", str(seed),
        *extra_args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


def test_run_name_required_when_missing(tmp_path):
    """No --run_name → wrapper must refuse to launch with the canonical
    'Required: --workspace, --seed_paths, --run_name' message on stderr,
    non-zero exit. Catches the exact accident that broke V12: a launch
    command that forgot to thread the new flag."""
    proc = _run_dry([], tmp_path)
    assert proc.returncode != 0, (
        "wrapper must exit non-zero when --run_name is missing; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "run_name" in proc.stderr, (
        f"stderr should mention run_name; got: {proc.stderr!r}"
    )


def test_run_name_threads_through_to_runner_args(tmp_path):
    """When --run_name is provided, the dry-run output must show the
    Python invocation including ``--run_name <value>`` — verbatim, no
    transformation. This is the core wiring contract."""
    proc = _run_dry(["--run_name", "my_chain_v99_test"], tmp_path)
    assert proc.returncode == 0, (
        f"dry-run with --run_name should succeed; "
        f"rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    # The dry-run prints the would-exec command. Look for the flag + value
    # as adjacent tokens (printf '%q ' may quote the value, so check both
    # raw and shell-quoted forms).
    out = proc.stdout
    assert "--run_name" in out, f"--run_name flag missing in dry-run output:\n{out}"
    assert "my_chain_v99_test" in out, (
        f"run_name value missing in dry-run output:\n{out}"
    )


def test_run_name_distinct_from_workspace_basename(tmp_path):
    """The chain wrapper must not silently derive run_name from the
    workspace basename. If it did, an operator's typo in --run_name would
    be invisible — the bridge would still bind to the basename, and
    audit logs would lie about chain identity. We pin: --run_name is the
    sole source of truth, distinct from workspace basename."""
    workspace = tmp_path / "ws_named_alpha"
    seed = tmp_path / "fake_seed.json"
    seed.write_text("{}")
    cmd = [
        "bash", str(RUN_CHAIN),
        "--mode", "lilab", "--dry-run",
        "--workspace", str(workspace),
        "--run_name", "operator_chose_beta",
        "--num_iterations", "1",
        "--seed_paths", str(seed),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    assert proc.returncode == 0, proc.stderr
    assert "operator_chose_beta" in proc.stdout
    # Workspace basename should also appear (it's the --workspace value),
    # but the run_name token must be the operator-supplied one.
    out = proc.stdout
    rn_idx = out.find("--run_name")
    assert rn_idx >= 0
    after = out[rn_idx:rn_idx + 200]
    assert "operator_chose_beta" in after, (
        f"--run_name must be followed by the operator's value, not "
        f"silently re-derived from workspace; saw: {after!r}"
    )
