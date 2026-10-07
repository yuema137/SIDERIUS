"""Issue 431: a clean replay CLI must carry its task through a real worker.

These tests fail if task transport is dropped, inputs replace targets, the
child imports another checkout, or infrastructure errors become measurements.
No live providers, GPUs or downloaded data are used.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.runtime_control.probe_subprocess import ProbeWorkerSpec, run_worker
from execute_tools.task_data_path import (
    EpochSamplingParams,
    ScopeBuildRequest,
    TaskProbeDataSpec,
    resolve_task_scope_capability,
)
from workflows.task_composition import compose_run_task_bindings

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def replay_inputs(tmp_path):
    from examples.quickstart.plugins._quickstart_task import materialize_run_bundle

    bundle = materialize_run_bundle(ROOT / "examples/quickstart", tmp_path / "bundle")
    manifest = ROOT / "configs/task_composition/quickstart.yaml"
    composition = compose_run_task_bindings(str(manifest))
    task = resolve_task_scope_capability(composition.task_data_path)
    scope = task.build_training_scope(
        ScopeBuildRequest(
            round_kind="trial", selection_strategy="snapshot", portion=1.0, max_samples=4
        )
    )
    reference = TaskProbeDataSpec(
        manifest_path=str(manifest),
        semantic_fingerprint=composition.semantic_fingerprint,
        training_scope_payload=task.serialize_scope(scope),
        sampling=EpochSamplingParams(data_dir=bundle["data_dir"]),
        segmentation_applicability="not_applicable",
    )
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "proposal_iter_001.json").write_text(
        json.dumps({"model_name": "quickstart_reference_mlp"})
    )
    config = {
        "task_probe_data": reference.model_dump(mode="json"),
        "model_config_payload": {"hidden_dim": 4},
        "train_config": {"device": "cpu", "batch_size": 2, "epochs": 1},
        "device_vram_gb": 1.0,
        "caps": {
            "max_wall_seconds": 60.0,
            "n_warmup_steps": 0,
            "n_timed_train_steps": 1,
            "n_timed_inference_batches": 1,
        },
    }
    return snapshot, config


def _cli(tmp_path, *args):
    env = os.environ.copy()
    for name in ("PYTHONPATH", "SIDERIUS_PLUGIN_DIRS", "SIDERIUS_LOSS_DIRS"):
        env.pop(name, None)
    env.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    cwd = tmp_path / "unrelated-cwd"
    cwd.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "tools.runtime_replay", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def test_clean_cli_reaches_real_task_data_and_worker(replay_inputs, tmp_path):
    """Float [B,4] inputs and integer [B] labels make input-as-target fail."""
    snapshot, config = replay_inputs
    config_path = tmp_path / "probe.json"
    config_path.write_text(json.dumps(config))
    output = tmp_path / "caller-output"
    before = {p.relative_to(snapshot): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
    result = _cli(
        tmp_path,
        "executable",
        "--snapshot",
        str(snapshot),
        "--run",
        "--probe-config",
        str(config_path),
        "--output-dir",
        str(output),
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    workers = list(output.glob("probe-*/result.json"))
    assert len(workers) == 1, result.stdout
    measured = json.loads(workers[0].read_text())
    assert measured["status"] == "ok", measured
    assert measured["realized"]["parameter_count"] == 30  # Linear(4,4) + Linear(4,2)
    assert measured["train_ms_per_step"] > 0
    assert measured["inference_ms_per_batch"] > 0
    assert measured["peak_vram_gb"] is None
    transported = json.loads(workers[0].with_suffix(".spec.json").read_text())
    assert transported["task_probe_data"]["manifest_path"] == str(
        ROOT / "configs/task_composition/quickstart.yaml"
    )
    assert transported["loss_config"]["loss_type"] == "ce"
    assert '"mode": "executable"' in result.stdout
    assert before == {
        p.relative_to(snapshot): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "defect", ["missing", "fingerprint", "data-root", "objective", "cardinality"]
)
def test_actual_worker_refuses_bad_binding_as_infrastructure(
    replay_inputs, tmp_path, monkeypatch, defect
):
    """Exercise the real IPC decoder, not only the parent's pre-validation."""
    _snapshot, config = replay_inputs
    task = config["task_probe_data"]
    if defect == "fingerprint":
        task["semantic_fingerprint"] = "incorrect-parent-fingerprint"
    loss = {"loss_type": "focal" if defect == "objective" else "ce"}
    if defect == "cardinality":
        config["model_config_payload"]["num_classes"] = 3
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    spec = ProbeWorkerSpec(
        model_type="quickstart_reference_mlp",
        model_config_payload=config["model_config_payload"],
        train_config=config["train_config"],
        loss_config=loss,
        task_probe_data=None if defect == "missing" else TaskProbeDataSpec.model_validate(task),
        data_dir=str(tmp_path) if defect == "data-root" else None,
        device="cpu",
        device_vram_gb=1.0,
        result_path=str(tmp_path / f"{defect}.json"),
    )
    outcome = run_worker(spec, hard_cap_seconds=30, usage_sampler=None)
    assert outcome.classification == "infrastructure_failure", outcome
    assert outcome.result is not None and outcome.result.realized is None
    expected = {
        "missing": "require explicit task_probe_data",
        "fingerprint": "fingerprint mismatch",
        "data-root": "data_dir disagrees",
        "objective": "task-declared objective",
        "cardinality": "num_classes=3",
    }
    assert expected[defect] in outcome.detail


def test_replay_data_failure_never_becomes_a_measurement(replay_inputs, tmp_path):
    """A valid declaration with missing physical data must abort at the real loader."""
    snapshot, config = replay_inputs
    data = Path(config["task_probe_data"]["sampling"]["data_dir"])
    for shard in data.glob("*.csv"):
        shard.unlink()
    config_path = tmp_path / "probe.json"
    config_path.write_text(json.dumps(config))
    output = tmp_path / "failed-replay"
    result = _cli(
        tmp_path,
        "executable",
        "--snapshot",
        str(snapshot),
        "--run",
        "--probe-config",
        str(config_path),
        "--output-dir",
        str(output),
        "--json",
    )
    assert result.returncode != 0
    assert "ProbeInfrastructureFailure" in result.stderr
    assert '"empirical_measurement"' not in result.stdout
    workers = list(output.glob("probe-*/result.json"))
    assert len(workers) == 1
    failure = json.loads(workers[0].read_text())
    assert failure["status"] == "load_failure"
    assert failure["realized"] is None
    assert failure["train_ms_per_step"] is None


def test_metadata_and_plan_need_no_task_or_output(tmp_path):
    """Missing executable config must not retire the separate read-only modes."""
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "proposal_iter_001.json").write_text(json.dumps({"model_name": "unknown"}))
    for mode, extra in (("metadata", []), ("executable", ["--plan"])):
        result = _cli(tmp_path, mode, "--snapshot", str(snapshot), "--json", *extra)
        assert result.returncode == 0, result.stderr
        assert not list(tmp_path.rglob("*.spec.json"))
    missing = _cli(tmp_path, "executable", "--snapshot", str(snapshot), "--run")
    assert missing.returncode == 2
    assert "requires --probe-config and --output-dir" in missing.stderr


def test_task_probe_uses_production_dtype_authorities(replay_inputs, monkeypatch):
    """Storage float64/int16 must reach the model/loss as declared float32/int64.

    Deleting either production conversion fails in real Linear/CrossEntropy;
    the old Quickstart-only witness uses native dtypes and cannot catch this.
    """
    import torch

    import execute_tools.task_probe_batch as task_batches
    from core.runtime_control.probe_production import production_probe_executors
    from core.runtime_control.probe_task import bind_probe_task

    _, config = replay_inputs
    reference = TaskProbeDataSpec.model_validate(config["task_probe_data"])
    original_loader = task_batches.load_task_probe_batch

    def storage_batch(ref, batch_size):
        inputs, targets = original_loader(ref, batch_size)
        return inputs.to(torch.float64), targets.to(torch.int16)

    monkeypatch.setattr(task_batches, "load_task_probe_batch", storage_batch)
    with bind_probe_task(reference) as composition:
        executors = production_probe_executors(
            model_type="quickstart_reference_mlp",
            model_config=config["model_config_payload"],
            train_config=config["train_config"],
            loss_config=composition.objective.model_dump(mode="json"),
            task_probe_data=reference,
            device="cpu",
        )
        executors.setup()
        assert executors.train_step() > 0
        assert executors.inference_batch() > 0
