"""Actual operation CLI, bubblewrap, native two-iteration restoration; API/GPU execution zero."""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from tests.integration.workflows.test_captured_native_chain import _task_manifest
from tools.candidate_operations import (
    NativeChainOperation,
    NativeChainOperationRequest,
    OperationStoreConfig,
)
from tools.native_chain.models import NativeChainDeclaration, NativeChainRunBinding


def test_public_detached_native_chain(tmp_path):
    root = Path(__file__).resolve().parents[3]
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    envelope = tmp_path / "envelope"
    envelope.mkdir()
    manifest = _task_manifest(root, inputs)
    declaration = NativeChainDeclaration(
        working_directory=root,
        run=NativeChainRunBinding(
            workspace=envelope / "workspace", run_name="detached_pseudo", final_iteration=2
        ),
        chain_args=(
            "--task_composition",
            str(manifest),
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
            "--attempts_per_round",
            "1",
            "--attempts_per_formal_round",
            "1",
            "--max_proposal_attempts",
            "1",
            "--max_impl_attempts",
            "1",
            "--healthgate_mode",
            "observe_only",
            "--result_authority",
            "diagnostic",
            "--no-runtime_watchdog",
        ),
    )
    source = inputs / "declaration.json"
    source.write_text(declaration.model_dump_json() + " " * (4 * 1024 * 1024))
    capture_request = inputs / "review-request.json"
    capture_request.write_text(
        json.dumps(
            dict(
                source=str(source),
                output=str(tmp_path / "review"),
                read_only=[str(inputs)],
                task_check=dict(timeout_seconds=60),
                input_max_bytes=16777216,
            )
        )
    )

    def command(module, *arguments):
        result = subprocess.run(
            [sys.executable, "-m", module, *arguments],
            cwd=root,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    command("tools.native_chain", "review", "--request", str(capture_request))
    capture = tmp_path / "review/capture.json"
    assert 4 * 1024 * 1024 < capture.stat().st_size <= 16777216
    # Explicit read-only hardware observation; no scientific kernels are requested.
    devices = tuple(str(p) for p in Path("/dev").glob("nvidia*") if p.is_char_device())
    devices += tuple(str(p) for p in Path("/dev/nvidia-caps").glob("*") if p.is_char_device())
    request = NativeChainOperation(
        request_id=uuid4(),
        request=NativeChainOperationRequest(
            capture_path=str(capture),
            capture_sha256=hashlib.sha256(capture.read_bytes()).hexdigest(),
            envelope=str(envelope),
            read_only=(str(inputs), str(data), "/sys"),
            network=False,
            devices=devices,
            environment_names=(),
            timeout_seconds=240,
            input_max_bytes=16777216,
            max_iterations_observed=2,
            max_observation_bytes=1048576,
        ),
    )
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    config_path = tmp_path / "store.json"
    config_path.write_text(config.model_dump_json())
    request_path = tmp_path / "operation.json"
    request_path.write_text(request.model_dump_json())
    base = ["--store-config", str(config_path)]
    reviewed = json.loads(
        command(
            "tools.candidate_operations", "review", *base, "--request", str(request_path)
        ).stdout
    )
    assert reviewed["git_common_directory"] != str(root / ".git")  # actual linked-worktree metadata
    first = json.loads(
        command(
            "tools.candidate_operations", "submit", *base, "--request", str(request_path)
        ).stdout
    )
    assert first["observation"] == "starting"
    assert (
        json.loads(
            command(
                "tools.candidate_operations", "submit", *base, "--request", str(request_path)
            ).stdout
        )["observation"]
        == "existing"
    )
    status_args = [*base, "--operation-id", str(request.request_id)]
    deadline = time.monotonic() + 260
    while True:
        snapshot = json.loads(command("tools.candidate_operations", "status", *status_args).stdout)
        if snapshot["process"]["status"] == "exited" and snapshot["state"] != "active":
            break
        assert time.monotonic() < deadline, snapshot
        time.sleep(0.5)
    log = json.loads(
        command("tools.candidate_operations", "log", *status_args, "--kind", "operation").stdout
    )
    (tmp_path / "final-status.json").write_text(json.dumps(snapshot, indent=2))
    assert snapshot["state"] == "completed", (snapshot, log)
    native = snapshot["native_chain"]
    assert native["terminal"]["supervision"]["execution"]["status"] == "completed", (snapshot, log)
    assert native["terminal"]["supervision"]["cleanup"]["final"]["status"] == "absent"
    evidence = native["evidence"]
    assert evidence["availability"] == "available" and not evidence["anomalies"], evidence
    assert [r["native_status"] for r in evidence["checkpoints"]] == ["completed", "completed"]
    assert all(r["manifest_verified"] and r["artifact_verified"] for r in evidence["checkpoints"])
    assert evidence["token_run_id"] != str(request.request_id)
    workspace = envelope / "workspace"
    interpreted = list((workspace / "iter_002").rglob("interpretation_iter_002.json"))
    assert len(interpreted) == 1
    assert json.loads(interpreted[0].read_text())["cold_start"] is False
    assert log["text"]
    source.unlink()
    capture.unlink()
    assert (
        json.loads(
            command(
                "tools.candidate_operations", "submit", *base, "--request", str(request_path)
            ).stdout
        )["observation"]
        == "existing"
    )
    recovered = json.loads(command("tools.candidate_operations", "status", *status_args).stdout)
    assert recovered["native_chain"]["admission"] == native["admission"]
    assert recovered["state"] == "completed"
