"""Actual public review + shell + two native pseudo children, without API/GPU work.

Run from a clean exact checkout with working bubblewrap namespaces. The local
integration environment must grant bubblewrap its normal namespace capability.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.native_chain.models import NativeChainDeclaration, NativeChainRunBinding


def test_public_capture_two_native_iterations(tmp_path):
    root = Path(__file__).resolve().parents[3]
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    workspace = tmp_path / "run"
    declaration = NativeChainDeclaration(
        working_directory=root,
        run=NativeChainRunBinding(
            workspace=workspace, run_name="capture_pseudo", final_iteration=2
        ),
        chain_args=(
            "--task_composition",
            "configs/task_composition/quickstart.yaml",
            "--data_dir",
            str(data),
            "--llm_config",
            "configs/llm/openai_tiered_pro.json",
            "--is_pseudo_llm",
            "--is_pseudo_training",
            "--max_rounds",
            "1",
            "--max_epochs",
            "1",
            "--healthgate_mode",
            "observe_only",
            "--result_authority",
            "diagnostic",
            "--no-runtime_watchdog",
        ),
    )
    source = inputs / "declaration.json"
    source.write_text(declaration.model_dump_json())
    output = tmp_path / "review"
    request = inputs / "request.json"
    request.write_text(
        json.dumps(
            dict(
                source=str(source),
                output=str(output),
                read_only=[],
                task_check=dict(timeout_seconds=60),
                input_max_bytes=16777216,
            )
        )
    )
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "PYTHONDONTWRITEBYTECODE": "1"}
    review = subprocess.run(
        [sys.executable, "-m", "tools.native_chain", "review", "--request", str(request)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (tmp_path / "review.log").write_text(review.stdout + review.stderr)
    assert review.returncode == 0, review.stdout + review.stderr
    assert not workspace.exists()
    capture = output / "capture.json"
    control = (
        "--expected_chain_capture",
        str(capture),
        "--expected_chain_capture_sha256",
        hashlib.sha256(capture.read_bytes()).hexdigest(),
        "--chain_capture_input_max_bytes",
        "16777216",
    )
    command = ["bash", "scripts/launch/run_chain.sh", *declaration.shell_arguments(), *control]
    dry = subprocess.run(
        [*command, "--dry-run"], cwd=root, env=env, capture_output=True, text=True, timeout=120
    )
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert not workspace.exists()
    execution = subprocess.run(
        command, cwd=root, env=env, capture_output=True, text=True, timeout=240
    )
    (tmp_path / "chain.log").write_text(execution.stdout + execution.stderr)
    assert execution.returncode == 0, execution.stdout + execution.stderr
    manifests = [
        json.loads((workspace / f"iter_{index:03d}" / "manifest.json").read_text())
        for index in (1, 2)
    ]
    assert [item["status"] for item in manifests] == ["completed", "completed"]
    assert "Restored" in execution.stdout or "restored" in execution.stdout
