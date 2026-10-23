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

import pytest
import yaml

from tools.native_chain.models import NativeChainDeclaration, NativeChainRunBinding


def _task_manifest(root, inputs):
    # The built-in pseudo bridge emits the existing token-model fixture. Give
    # it that declared I/O contract rather than Quickstart's float/tabular one.
    from tests.helpers.composed_manifest import write_complete_manifest

    manifest = write_complete_manifest(
        inputs,
        task_data_path={
            "file": str(root / "tests/fixtures/native_chain_task.py"),
            "symbol": "NativeChainTask",
            "id": "native_chain_tokens",
        },
        metric={
            "declaration": "../../examples/quickstart/declared/metric_accuracy.json",
            "implementation": {
                "file": str(root / "tests/fixtures/native_chain_task.py"),
                "symbol": "TokenAccuracy",
            },
        },
        model_plugins=None,
    )
    (inputs / "examples/quickstart/declared/dataset_profile.json").write_text(
        json.dumps(
            {
                "partition_count": 20,
                "anchor_selection_files": [4, 7, 9],
                "health_peek_files": [4, 7, 9],
                "topology": {
                    "modality": "token_sequence",
                    "class_cardinality": 256,
                    "sequence_length": 8,
                },
            }
        )
    )
    task_config = inputs / "examples/quickstart/declared/task_config.yaml"
    task_config.write_text(
        yaml.safe_dump(
            {
                "task_description": "Synthetic token-model pseudo lifecycle; no scientific data or training.",
                "forward_contract": {
                    "segmentation_applicability": "not_applicable",
                    "model_io": {
                        "input": {
                            "axes": [
                                {"role": "batch", "dimension": {"symbolic": "B"}},
                                {"dimension": {"fixed": 8}},
                            ],
                            "dtype": {"admissible": ["int64"]},
                        },
                        "output": {
                            "axes": [
                                {"role": "batch", "dimension": {"symbolic": "B"}},
                                {"role": "class", "dimension": {"fixed": 256}},
                                {"dimension": {"fixed": 8}},
                            ],
                            "dtype": {"admissible": ["float32"]},
                        },
                    },
                    "input_description": "eight integer tokens",
                    "output_description": "256 logits per token",
                    "task_type": "classification",
                    "output_head_note": "Unnormalized logits.",
                },
            }
        )
    )
    return manifest


def _admission_witnesses(capture_path, declaration, control, tmp_path):
    from tools.native_chain.check import admit, load_capture, verify_dispatch
    from tools.native_chain.models import NativeChainCaptureReference, NativeChainDispatch

    reference = NativeChainCaptureReference(
        path=capture_path, sha256=control[3], input_max_bytes=16777216
    )
    capture = load_capture(reference)
    shell = (*declaration.shell_arguments(), *control)
    with pytest.raises(ValueError, match="shell_arguments_changed"):
        admit(reference, (*shell, "--max_epochs", "2"))
    with pytest.raises(ValueError, match="iteration_out_of_range"):
        verify_dispatch(
            NativeChainDispatch(capture=reference, iteration=3, argv=capture.iteration_one_argv)
        )
    with pytest.raises(ValueError, match="dispatch_arguments_changed"):
        verify_dispatch(
            NativeChainDispatch(capture=reference, iteration=2, argv=capture.iteration_one_argv)
        )
    workspace = declaration.run.workspace
    workspace.mkdir()
    with pytest.raises(ValueError, match="workspace_not_fresh"):
        admit(reference, shell)
    workspace.rmdir()
    workspace.symlink_to(tmp_path / "missing-target")
    with pytest.raises(ValueError):
        admit(reference, shell)
    workspace.unlink()
    original = capture.source_path.read_bytes()
    capture.source_path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="source_changed"):
        load_capture(reference)
    capture.source_path.write_bytes(original)
    with pytest.raises(ValueError, match="capture_digest_changed"):
        load_capture(reference.model_copy(update={"sha256": "0" * 64}))
    with pytest.raises(ValueError, match="input_too_large"):
        load_capture(reference.model_copy(update={"input_max_bytes": 1}))
    malformed = tmp_path / "malformed.json"
    malformed.write_bytes(b"{broken")
    with pytest.raises(ValueError):
        load_capture(
            NativeChainCaptureReference(
                path=malformed,
                sha256=hashlib.sha256(malformed.read_bytes()).hexdigest(),
                input_max_bytes=16777216,
            )
        )


def test_public_capture_two_native_iterations(tmp_path):
    root = Path(__file__).resolve().parents[3]
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    manifest = _task_manifest(root, inputs)
    workspace = tmp_path / "run"
    declaration = NativeChainDeclaration(
        working_directory=root,
        run=NativeChainRunBinding(
            workspace=workspace, run_name="capture_pseudo", final_iteration=2
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
                read_only=[str(inputs)],
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
    _admission_witnesses(capture, declaration, control, tmp_path)
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
