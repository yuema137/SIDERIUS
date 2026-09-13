"""Real shell loop consumes a real runner's declaration-refusal halt exit."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


def test_actual_chain_does_not_submit_again_after_package_refusal(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    manifest = tmp_path / "task.yaml"
    config = yaml.safe_load((repo / "configs/task_composition/quickstart.yaml").read_text())
    config["code_package"] = {"root": ".", "files": ["missing.py"]}
    manifest.write_text(yaml.safe_dump(config))
    # The injected submitter is the documented backend seam. run_chain itself,
    # the Python entry, declaration capture, marker writer and exit are real.
    script = r"""
source "$1/scripts/launch/_chain_common.sh"
WORKSPACE="$2/workspace"
NUM_ITERATIONS=3
RUN_NAME=package_refusal
START_ITER=1
build_source_paths() { SOURCE_PATHS=(); }
build_app_args() { APP_ARGS=(); }
submit_iteration() {
    printf '%s\n' "$1" >> "$SUBMISSIONS"
    "$RUNNER_PYTHON" -m workflows.run_one_iteration --workspace "$WORKSPACE" \
        --run_name "$RUN_NAME" --start_iteration "$1" \
        --task_composition "$TASK_MANIFEST" --data_dir "$DATA_ROOT"
}
SUBMISSIONS="$2/submissions"
RUNNER_PYTHON="$3"
TASK_MANIFEST="$4"
DATA_ROOT="$2"
run_chain
"""
    result = subprocess.run(
        [
            "bash",
            "-c",
            script,
            "test-chain",
            str(repo),
            str(tmp_path),
            sys.executable,
            str(manifest),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert (tmp_path / "submissions").read_text().splitlines() == ["1"]
    marker = json.loads((tmp_path / "workspace/.chain_halted").read_text())
    assert marker["reason"] == "code_package_integrity"
    assert "missing.py" in marker["detail"]
