"""Real detached append continuation after abrupt shell death; API/GPU execution zero."""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import yaml

from tests.helpers.native_chain import write_native_chain_manifest
from tools.candidate_operations import (
    NativeChainOperation,
    NativeChainOperationRequest,
    NativeChainResumeOperation,
    NativeChainResumeRequest,
    OperationStoreConfig,
)
from tools.native_chain.models import NativeChainDeclaration, NativeChainRunBinding


def test_public_detached_resume_at_absent_boundary(tmp_path):
    root = Path(__file__).resolve().parents[3]
    inputs, data, envelope = (tmp_path / name for name in ("inputs", "data", "envelope"))
    for path in (inputs, data, envelope):
        path.mkdir()
    manifest = write_native_chain_manifest(root, inputs)
    # Test-only external composition code creates a deterministic interruption
    # after the first manifest commits, without editing captured argv or STOP.
    task = inputs / "interrupting_task.py"
    marker = envelope / "fixture-boundary.json"
    task.write_text(
        (root / "tests/fixtures/native_chain_task.py").read_text()
        + f"""

import atexit
import os
import signal
import sys
import time
import psutil

def _interrupt_fixture_chain():
    workspace = Path({str(envelope / "workspace")!r})
    manifest = workspace / "iter_001/manifest.json"
    if not manifest.exists() or json.loads(manifest.read_text()).get("status") != "completed":
        return
    parents = [p for p in psutil.Process().parents()
               if p.name() == "bash" and any(arg.endswith("/scripts/launch/run_chain.sh") for arg in p.cmdline())]
    Path({str(marker)!r}).write_text(json.dumps({{"shells": [p.pid for p in parents], "second_absent": not (workspace / "iter_002").exists()}}))
    for parent in parents:
        os.kill(parent.pid, signal.SIGKILL)
    time.sleep(120)  # Real outer cleanup must reap this remaining process.

if sys.argv[0].endswith("/native_chain/iteration.py") and "--iteration" in sys.argv and sys.argv[sys.argv.index("--iteration") + 1] == "1":
    atexit.register(_interrupt_fixture_chain)
"""
    )
    document = yaml.safe_load(manifest.read_text())
    document["task_data_path"]["file"] = str(task)
    manifest.write_text(yaml.safe_dump(document))
    declaration = NativeChainDeclaration(
        working_directory=root,
        run=NativeChainRunBinding(
            workspace=envelope / "workspace", run_name="resume_pseudo", final_iteration=2
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
    source.write_text(declaration.model_dump_json())
    capture_request = inputs / "review.json"
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
        return (
            json.loads(result.stdout) if module == "tools.candidate_operations" else result.stdout
        )

    command("tools.native_chain", "review", "--request", str(capture_request))
    capture = tmp_path / "review/capture.json"
    devices = tuple(
        str(p)
        for folder in (Path("/dev"), Path("/dev/nvidia-caps"))
        for p in folder.glob("nvidia*" if folder == Path("/dev") else "*")
        if p.is_char_device()
    )
    original = NativeChainOperation(
        request_id=uuid4(),
        request=NativeChainOperationRequest(
            capture_path=str(capture),
            capture_sha256=hashlib.sha256(capture.read_bytes()).hexdigest(),
            envelope=str(envelope),
            read_only=(str(inputs), str(data), "/sys"),
            network=False,
            devices=devices,
            environment_names=(),
            timeout_seconds=120,
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
    request_path.write_text(original.model_dump_json())
    base = ("--store-config", str(config_path))
    command("tools.candidate_operations", "submit", *base, "--request", str(request_path))

    def wait(operation_id):
        deadline = time.monotonic() + 160
        while True:
            status = command(
                "tools.candidate_operations", "status", *base, "--operation-id", str(operation_id)
            )
            if status["process"]["status"] == "exited":
                return status
            assert time.monotonic() < deadline, status
            time.sleep(0.5)

    first = wait(original.request_id)
    (tmp_path / "initial-status.json").write_text(json.dumps(first, indent=2))
    assert first["state"] == "completed", first
    proof = json.loads(marker.read_text())
    assert proof["shells"] and proof["second_absent"]
    workspace = envelope / "workspace"
    assert not (workspace / "iter_002").exists()
    assert not any(
        (workspace / name).exists() for name in ("STOP", "chain_stopped.json", ".chain_halted")
    )
    prior_path = Path(config.state_root) / "operations" / str(original.request_id)
    preserved = {
        path: path.read_bytes()
        for path in (
            prior_path / "completion.json",
            prior_path / "native-chain-terminal.json",
            envelope / ".native-chain-operation/binding.json",
            workspace / ".token_run_id",
            workspace / "iter_001/manifest.json",
        )
    }
    reviewed = command(
        "tools.candidate_operations",
        "review-resume",
        *base,
        "--operation-id",
        str(original.request_id),
    )
    assert reviewed["eligibility"] == "ready" and reviewed["admission"]["start_iteration"] == 2
    assert (
        command(
            "tools.candidate_operations",
            "review-resume",
            *base,
            "--operation-id",
            str(original.request_id),
        )["review_digest"]
        == reviewed["review_digest"]
    )
    successor = NativeChainResumeOperation(
        request_id=uuid4(),
        request=NativeChainResumeRequest(
            predecessor_operation_id=original.request_id,
            expected_review_digest=reviewed["review_digest"],
        ),
    )
    resume_path = tmp_path / "resume.json"
    resume_path.write_text(successor.model_dump_json())
    assert (
        command("tools.candidate_operations", "submit", *base, "--request", str(resume_path))[
            "observation"
        ]
        == "starting"
    )
    assert (
        command("tools.candidate_operations", "submit", *base, "--request", str(resume_path))[
            "observation"
        ]
        == "existing"
    )
    final = wait(successor.request_id)
    (tmp_path / "final-status.json").write_text(json.dumps(final, indent=2))
    assert final["state"] == "completed", final
    native = final["native_chain"]
    assert native["terminal"]["supervision"]["cleanup"]["final"]["status"] == "absent"
    assert native["terminal"]["supervision"]["execution"]["status"] == "completed"
    assert [row["native_status"] for row in native["evidence"]["checkpoints"]] == [
        "completed",
        "completed",
    ]
    assert all(row["artifact_verified"] for row in native["evidence"]["checkpoints"])
    interpreted = list((workspace / "iter_002").rglob("interpretation_iter_002.json"))
    assert len(interpreted) == 1 and json.loads(interpreted[0].read_text())["cold_start"] is False
    assert all(path.read_bytes() == raw for path, raw in preserved.items())
    old = command(
        "tools.candidate_operations", "status", *base, "--operation-id", str(original.request_id)
    )
    assert old["native_chain"]["terminal"] == first["native_chain"]["terminal"]
    assert old["native_chain"]["evidence"] == native["evidence"]
    assert old["native_chain"]["continuation"]["head_operation_id"] == str(successor.request_id)
    assert (
        command(
            "tools.candidate_operations",
            "review-resume",
            *base,
            "--operation-id",
            str(successor.request_id),
        )["eligibility"]
        == "not_needed"
    )
    source.unlink()
    capture.unlink()
    assert (
        command("tools.candidate_operations", "submit", *base, "--request", str(resume_path))[
            "observation"
        ]
        == "existing"
    )
    assert (
        command(
            "tools.candidate_operations",
            "status",
            *base,
            "--operation-id",
            str(original.request_id),
        )["native_chain"]["evidence"]
        == native["evidence"]
    )
