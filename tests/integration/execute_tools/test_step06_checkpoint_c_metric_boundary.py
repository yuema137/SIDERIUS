"""Step 06 — CHECKPOINT C: the metric handle across the REAL scoring boundary.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§11 (Checkpoint C), §13 (what replaces the Gate), §19 C7.

Reuses the 05c Checkpoint-C harness (real ``train_engine_sandbox.py`` →
real ``inference_single.py`` spawns, PYTHONPATH pinned to THIS checkout) and
completes the chain Step 06 owns: the deliverable the REAL producer wrote is
scored by the REAL ``execute_scoring`` child THROUGH the metric handle, and the
result equals the in-process route bit-for-bit. Helper-only is insufficient
here (05c §6 discipline) — this is the seam being real, not the arithmetic
being right (that is the C0 oracle and the frozen numeric pins).

**Why full length.** The scorer's segment length is a module constant
(``scoring_utils.SEGMENT_LENGTH`` = 10,000,000), so unlike the 05c fixture the
profile here declares the REAL ``psd_segment_length`` with ``segments_per_file=1``;
training is one epoch over one 10 M-sample segment (batched), inference one
segment, CPU. Minutes, not hours; recorded in the ledger.

**What is proven, precisely.**
1. the producer-side representation (05c ``DeliverableSpec``, written by the
   real ``inference_single``) SATISFIES the evaluation-side acceptance
   contract (Step 06 ``TidmadScoreabilityContract``) — the two halves of the
   ownership split agree on a real artifact;
2. route (ii) — the real ``execute_scoring`` child, which reconstructs the
   metric from ``--dataset_profile_json`` — equals route (i) — the in-process
   handle — on that artifact, exactly;
3. the structured refusal crosses the real child (a wrong-dtype deliverable is
   refused before arithmetic; the parent classifies ``error``; no traceback).

Not in CI: ``tests/integration/`` is manual/local by design.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from core.sandbox_executor import TidmadSandbox
from execute_tools.array2h5 import create_abra_file
from execute_tools.build_anchor_map import default_anchor_map_path, load_anchor_map
from execute_tools.dataset_config import TIDMAD_PROFILE, bind_dataset_profile
from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec
from execute_tools.evaluation_metric import (
    TIDMAD_METRIC_ID,
    MetricResult,
    derive_tidmad_metric,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = sys.executable

SEGMENT_SAMPLES = 10_000_000  # the scorer's own constant, stated (see module docstring)
SEG_SIZE = 10_000  # must divide the 10 M-sample segment (train_engine_sandbox.py:398)
FILE_INDEX = 0
EXP_ID = "wavenet_step06_cpc_001"
RUN_NAME = "step06_cpc"
MODEL_TYPE = "wavenet"


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
    return env


def _signal(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(SEGMENT_SAMPLES)
    return np.clip(
        20.0 * np.sin(2 * np.pi * t / 64.0) + rng.normal(0, 3.0, SEGMENT_SAMPLES), -127, 127
    ).astype(np.int8)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("step06_cpc")
    data_dir, cfg_dir, sandbox_dir = root / "data", root / "configs", root / "sandbox"
    for d in (data_dir, cfg_dir, sandbox_dir):
        d.mkdir()
    train_pattern = str(data_dir / "s6_train_{file_index:04d}.h5")
    valid_pattern = str(data_dir / "s6_valid_{file_index:04d}.h5")
    profile = TIDMAD_PROFILE.model_copy(
        update={
            "dataset": TIDMAD_PROFILE.dataset.model_copy(
                update={
                    "segments_per_file": 1,
                    "num_files": 1,
                    "training_file_pattern": train_pattern,
                    "validation_file_pattern": valid_pattern,
                }
            ),
            "anchor_selection_files": [FILE_INDEX],
            "health_peek_files": [FILE_INDEX],
        }
    )
    (cfg_dir / "dataset_profile.json").write_text(json.dumps(profile.model_dump()))
    storage = derive_tidmad_deliverable_spec(profile).storage
    raw = _signal(10)
    for pattern in (train_pattern, valid_pattern):
        create_abra_file(
            pattern.format(file_index=FILE_INDEX), raw, raw, indexed=False, storage=storage
        )
    (cfg_dir / "model.json").write_text(
        json.dumps(
            {
                "model_type": MODEL_TYPE,
                "segmentation_size": SEG_SIZE,
                "input_channels": 4,
                "residual_channels": 8,
                "gate_channels": 8,
                "skip_channels": 8,
                "kernel_size": 2,
                "num_blocks": 1,
            }
        )
    )
    (cfg_dir / "train.json").write_text(
        json.dumps(
            {"lr": 1e-4, "epochs": 1, "batch_size": 64, "optimizer_type": "adam", "device": "cpu"}
        )
    )
    (cfg_dir / "loss.json").write_text(json.dumps({}))
    (cfg_dir / "sample_set.json").write_text(json.dumps({str(FILE_INDEX): [0]}))
    return {"profile": profile, "data_dir": data_dir, "cfg_dir": cfg_dir, "sandbox": sandbox_dir}


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=REPO_ROOT, env=_child_env(), capture_output=True, text=True, timeout=3600
    )


@pytest.fixture(scope="module")
def produced(workspace):
    """REAL training and REAL inference spawns; returns the deliverable path."""
    ws = workspace
    trained = _run(
        [
            PYTHON,
            "execute_tools/train_engine_sandbox.py",
            "--model_cfg",
            str(ws["cfg_dir"] / "model.json"),
            "--train_cfg",
            str(ws["cfg_dir"] / "train.json"),
            "--loss_cfg",
            str(ws["cfg_dir"] / "loss.json"),
            "--dataset_profile_json",
            str(ws["cfg_dir"] / "dataset_profile.json"),
            "--exp_id",
            EXP_ID,
            "--run_name",
            RUN_NAME,
            "--sandbox_dir",
            str(ws["sandbox"]),
            "--data_dir",
            str(ws["data_dir"]),
            "--file_index",
            str(FILE_INDEX),
            "--sample_set_json",
            str(ws["cfg_dir"] / "sample_set.json"),
        ]
    )
    assert trained.returncode == 0, (trained.stdout + trained.stderr)[-4000:]
    checkpoints = sorted(ws["sandbox"].rglob("*.pth"))
    assert checkpoints, "no checkpoint written"
    inferred = _run(
        [
            PYTHON,
            "execute_tools/inference_single.py",
            "--mode",
            "agent",
            "-m",
            MODEL_TYPE,
            "--dataset_profile_json",
            str(ws["cfg_dir"] / "dataset_profile.json"),
            "--model_cfg",
            str(ws["cfg_dir"] / "model.json"),
            "--loss_cfg",
            str(ws["cfg_dir"] / "loss.json"),
            "--model_path",
            str(checkpoints[-1]),
            "--exp_id",
            EXP_ID,
            "--run_name",
            RUN_NAME,
            "--data_dir",
            str(ws["data_dir"]),
            "--output_dir",
            str(ws["sandbox"]),
            "--inference_batch_size",
            "64",
            "--file_index",
            str(FILE_INDEX),
            "--sample_set_json",
            str(ws["cfg_dir"] / "sample_set.json"),
        ]
    )
    assert inferred.returncode == 0, (inferred.stdout + inferred.stderr)[-4000:]
    written = sorted(Path(ws["sandbox"]).glob("*.h5"))
    assert len(written) == 1, written
    return {"deliverable": written[0], "workspace": ws}


def _sandbox(ws) -> TidmadSandbox:
    # The sandbox's workspace IS where inference wrote the deliverable, so the
    # child's `--data_dir <workspace>` + reconstructed name resolves it exactly
    # as production does.
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(ws["sandbox"]), file_index=FILE_INDEX)


def test_the_real_producers_deliverable_satisfies_the_acceptance_contract(produced):
    ws = produced["workspace"]
    metric = derive_tidmad_metric(ws["profile"])
    verdict = metric.check_scoreability({FILE_INDEX: str(produced["deliverable"])})
    assert verdict.scoreable, verdict


def test_the_two_real_routes_agree_on_the_real_deliverable(produced, monkeypatch):
    ws = produced["workspace"]
    monkeypatch.chdir(REPO_ROOT)
    anchors = load_anchor_map(default_anchor_map_path())
    with bind_dataset_profile(ws["profile"]):
        sandbox = _sandbox(ws)
        run_metric = derive_tidmad_metric(ws["profile"])
        in_process = sandbox.evaluate_metric(
            run_metric,
            sample_set={FILE_INDEX: [0]},
            anchor_map=anchors["anchors"],
            s_max=float(anchors["s_max"]),
            denoised_filename_fn=lambda _fi: str(produced["deliverable"]),
        )
        child = sandbox.execute_scoring(EXP_ID, RUN_NAME, MODEL_TYPE, {}, {}, {})
    assert isinstance(in_process, MetricResult)
    assert (in_process.metric_id, in_process.direction) == (TIDMAD_METRIC_ID, "higher")
    assert child["status"] == "success", child
    assert child["results"]["denoising_score"] == in_process.scalar
    assert child["results"]["file_vector"] == in_process.per_sample
    assert in_process.scalar is not None and np.isfinite(in_process.scalar)


def test_the_structured_refusal_crosses_the_real_child(produced, monkeypatch):
    """Overwrite the deliverable with an int16 copy in a SEPARATE workspace and
    score through the real child: refused before arithmetic, parent 'error',
    no traceback, structured payload persisted."""
    ws = produced["workspace"]
    monkeypatch.chdir(REPO_ROOT)
    other = ws["sandbox"].parent / "refusal_ws"
    other.mkdir(exist_ok=True)
    spec = derive_tidmad_deliverable_spec(ws["profile"])
    name = spec.naming.name(
        model_type=MODEL_TYPE, run_name=RUN_NAME, exp_id=EXP_ID, file_index=FILE_INDEX
    )
    wide = np.arange(64, dtype=np.int16)
    create_abra_file(str(other / name), wide, wide, indexed=False, storage=spec.storage)
    with bind_dataset_profile(ws["profile"]):
        sandbox = TidmadSandbox(run_name=RUN_NAME, workspace=str(other), file_index=FILE_INDEX)
        result = sandbox.execute_scoring(EXP_ID, RUN_NAME, MODEL_TYPE, {}, {}, {})
    assert result["status"] == "error"
    assert "Deliverable not scoreable [tidmad_denoised_h5] required_dtype" in result["message"]
    assert "Traceback" not in result["message"]
    payload = json.loads(
        (other / "records" / RUN_NAME / f"score_results_{MODEL_TYPE}_{EXP_ID}.json").read_text()
    )
    assert payload["not_scoreable"]["verdict"]["failures"][0]["requirement"] == "required_dtype"
