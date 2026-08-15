"""Step 05c — CHECKPOINT C: the deliverable crosses a REAL subprocess.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` §6, §3.2a, §4.1, C7.

§6 is explicit that a config- or helper-only test is **insufficient** here:
the whole failure class lives at the subprocess boundary. Every other 05c
test runs in-process and proves the code reads the contract — none proves the
contract survives the trip from the parent that resolves it to the child that
writes the artifact.

So this module launches ``execute_tools/train_engine_sandbox.py`` and then
``execute_tools/inference_single.py`` with ``subprocess.run``, lets them read
real HDF5 off disk, and inspects the file the child actually wrote. No stub,
no monkeypatch, no in-process call. It reuses the fixture geometry and the
``PYTHONPATH`` pin of ``test_step03_checkpoint_c_subprocess.py`` deliberately
— §3.2a requires the EXISTING transport, and reusing the proven harness
demonstrates that rather than asserting it.

**What is proven, precisely.** Under §3.2a Option A the spec does not cross;
the child **reconstructs** it from ``--dataset_profile_json``, which already
crosses. So the claim is that the child reconstructs the **SHIPPED DEFAULT**
spec and writes, names and cleans through it. A *renamed* template is a frozen
compatibility literal, not a derivable fact, and 05c deliberately adds no
transport for it — the renamed-spec contrast is the in-process Stage-B rung,
and this module does **not** claim otherwise.

**Why it is cheap.** The declared ``psd_segment_length`` is 4,096 rather than
10,000,000, the model is a 1-block WaveNet, training is one epoch over two
segments, and everything runs on CPU. The production code path is identical;
the fixture is kilobytes.

**Not in CI.** ``tests/integration/`` is manual/local by design (CI is unit
plus static). Run deliberately; the result is recorded in the design ledger.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest

from execute_tools.deliverable_spec import default_deliverable_naming
from tests.unit.execute_tools.test_step05c_c0_deliverable_baseline import (
    canonical_h5_inspection,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = sys.executable

PSD_LEN = 4096
SEG_SIZE = 1024
N_PSD = 2
FILE_INDEX = 0
EXP_ID = "wavenet_step05c_cpc_001"
RUN_NAME = "step05c_cpc"
MODEL_TYPE = "wavenet"

# The profile deliberately keeps TIDMAD's CHANNEL IDENTITY and ENCODING and
# shrinks only the topology. That is what makes the reconstructed spec the
# SHIPPED DEFAULT one — naming is profile-independent, and storage derives
# from these two blocks.
PROFILE = {
    "dataset": {
        "psd_segment_length": PSD_LEN,
        "segments_per_file": N_PSD,
        "num_files": 2,
        "sampling_frequency": 1000.0,
        "training_file_pattern": "s5c_train_{file_index:03d}.h5",
        "validation_file_pattern": "s5c_valid_{file_index:03d}.h5",
    },
    "channels": {"input_channel": "channel0001", "target_channel": "channel0002"},
    "encoding": {
        "storage_dtype": "int8",
        "compute_dtype": "int16",
        "value_offset": 128,
        "num_classes": 256,
    },
    "anchor_selection_files": [FILE_INDEX],
    "health_peek_files": [FILE_INDEX],
}

# Deterministic fixture samples, including both int8 extremes so an offset
# drift that survived the boundary would wrap visibly rather than silently.
TARGET_SAMPLES = np.array(
    ([-128, -1, 0, 1, 127, 63, -64, 100] * ((PSD_LEN * N_PSD) // 8)), dtype=np.int8
)
INPUT_SAMPLES = np.array(
    ([12, -12, 34, -34, 56, -56, 78, -78] * ((PSD_LEN * N_PSD) // 8)), dtype=np.int8
)


def _child_env() -> dict[str, str]:
    """Pin the child onto THIS checkout (the 02a portability lesson).

    A plain ``python execute_tools/foo.py`` puts the SCRIPT's directory on
    ``sys.path[0]``, so an ``import execute_tools...`` can fall through to the
    venv's editable-install finder and import a DIFFERENT clone — which would
    let this test pass while exercising the wrong tree.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
    return env


def _write_h5(path: Path) -> None:
    with h5py.File(path, "w") as handle:
        group = handle.create_group("timeseries")
        for name, data in (
            (PROFILE["channels"]["input_channel"], INPUT_SAMPLES),
            (PROFILE["channels"]["target_channel"], TARGET_SAMPLES),
        ):
            channel = group.create_group(name)
            channel.create_dataset("timeseries", data=data)
            channel.attrs["sampling_frequency"] = PROFILE["dataset"]["sampling_frequency"]


@pytest.fixture
def workspace(tmp_path):
    data_dir, cfg_dir, sandbox = (tmp_path / n for n in ("data", "configs", "sandbox"))
    for directory in (data_dir, cfg_dir, sandbox):
        directory.mkdir()

    (cfg_dir / "dataset_profile.json").write_text(json.dumps(PROFILE))
    dataset = PROFILE["dataset"]
    _write_h5(data_dir / dataset["training_file_pattern"].format(file_index=FILE_INDEX))
    _write_h5(data_dir / dataset["validation_file_pattern"].format(file_index=FILE_INDEX))

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
            {"lr": 1e-4, "epochs": 1, "batch_size": 1, "optimizer_type": "adam", "device": "cpu"}
        )
    )
    (cfg_dir / "loss.json").write_text(json.dumps({}))
    (cfg_dir / "sample_set.json").write_text(json.dumps({str(FILE_INDEX): list(range(N_PSD))}))
    return {"data_dir": data_dir, "cfg_dir": cfg_dir, "sandbox": sandbox}


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=REPO_ROOT, env=_child_env(), capture_output=True, text=True, timeout=1800
    )


def _train(ws) -> subprocess.CompletedProcess:
    return _run(
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


def _infer(ws, checkpoint: Path, out_dir: Path) -> subprocess.CompletedProcess:
    return _run(
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
            str(checkpoint),
            "--exp_id",
            EXP_ID,
            "--run_name",
            RUN_NAME,
            "--data_dir",
            str(ws["data_dir"]),
            "--output_dir",
            str(out_dir),
            "--inference_batch_size",
            "1",
            "--file_index",
            str(FILE_INDEX),
            "--sample_set_json",
            str(ws["cfg_dir"] / "sample_set.json"),
        ]
    )


@pytest.fixture
def produced(workspace):
    """Run the REAL training and inference spawns; return what was written."""
    trained = _train(workspace)
    assert trained.returncode == 0, (trained.stdout + trained.stderr)[-4000:]

    checkpoints = sorted(workspace["sandbox"].rglob("*.pth"))
    assert checkpoints, f"no checkpoint written under {workspace['sandbox']}"

    out_dir = workspace["sandbox"]
    inferred = _infer(workspace, checkpoints[-1], out_dir)
    assert inferred.returncode == 0, (inferred.stdout + inferred.stderr)[-4000:]

    return {"workspace": workspace, "out_dir": out_dir, "stdout": inferred.stdout}


def test_the_child_names_the_deliverable_through_the_reconstructed_spec(produced):
    """The file the REAL child wrote carries the spec-resolved name.

    Not "a file appeared": the name is compared against
    ``default_deliverable_naming().name(...)`` for the identifiers passed on
    argv. That equality is the whole transport claim — the parent resolves the
    name one way and the child, which received no spec, reconstructs the same
    one from the profile that already crosses.
    """
    expected = default_deliverable_naming().name(
        model_type=MODEL_TYPE, run_name=RUN_NAME, exp_id=EXP_ID, file_index=FILE_INDEX
    )

    written = sorted(p.name for p in Path(produced["out_dir"]).glob("*.h5"))

    assert written == [expected]


def test_the_written_artifact_satisfies_logical_equality_with_the_contract(produced):
    """§4.1 over the file a real subprocess produced.

    Group paths, dataset names, dtypes and shapes come from the contract; the
    **injected/target channel's every sample value** is predictable and is
    asserted exactly. That last part is what proves the offset round-trip
    survived the boundary: the child adds the offset on read
    (``:217-218``) and subtracts the contract's offset on write, so the
    persisted truth channel must equal the fixture byte for byte. An offset
    that drifted by one would wrap ``-128`` to ``127`` here.

    The denoised channel's values are model output and are deliberately NOT
    pinned — asserting them would be pinning an untrained network's weights,
    not the contract.
    """
    written = next(Path(produced["out_dir"]).glob("*.h5"))
    inspection = canonical_h5_inspection(str(written))

    assert inspection["groups"] == [
        "timeseries",
        "timeseries/channel0001",
        "timeseries/channel0002",
    ]
    assert {d["dtype"] for d in inspection["datasets"].values()} == {"int8"}
    assert {d["shape"] for d in inspection["datasets"].values()} == {(PSD_LEN * N_PSD,)}
    assert inspection["attrs"]["timeseries/channel0001"] == {
        "file_first_sample_index": 100000000000000,
        "input_coupling": 0,
        "input_impedance_ohm": 50,
        "sampling_frequency": 10000000,
        "voltage_range_mV": 80,
    }
    assert (
        inspection["datasets"]["timeseries/channel0002/timeseries"]["values"]
        == TARGET_SAMPLES.tolist()
    )


def test_the_cleanup_authority_finds_exactly_what_the_child_wrote(produced):
    """The real artifact is matched by the real cleanup patterns.

    Producer and cleanup agreeing is failure class 1 stated positively, and it
    can only be checked against a file a real spawn produced: a glob written
    from the same literal as the producer would pass any in-process test.
    Both cleanup shapes are exercised, and the raw INPUT files must survive
    both — cleanup that reclaimed the dataset would be catastrophic and
    silent.
    """
    naming = default_deliverable_naming()
    out_dir = str(produced["out_dir"])

    attempt = glob.glob(
        os.path.join(
            out_dir,
            naming.attempt_glob(model_type=MODEL_TYPE, run_name=RUN_NAME, exp_id=EXP_ID),
        )
    )
    experiment = glob.glob(os.path.join(out_dir, naming.experiment_glob(exp_id=EXP_ID)))

    assert len(attempt) == 1
    assert sorted(attempt) == sorted(experiment)

    data_dir = str(produced["workspace"]["data_dir"])
    assert glob.glob(os.path.join(data_dir, naming.any_glob())) == []
    assert len(list(Path(data_dir).glob("*.h5"))) == 2


def test_the_child_reused_the_transported_profile_rather_than_resolving_its_own(produced):
    """The reconstruction consumed the profile it was GIVEN.

    The fixture's channel identity is TIDMAD's, so the group names alone
    cannot distinguish "reconstructed from the transport" from "resolved the
    shipped profile ambiently". The topology can: the artifact's length is
    ``PSD_LEN * N_PSD`` = 8,192, which only the transported profile declares —
    the shipped TIDMAD profile would have produced 10,000,000-sample segments.
    Same file, different question.
    """
    written = next(Path(produced["out_dir"]).glob("*.h5"))
    inspection = canonical_h5_inspection(str(written))

    assert {d["shape"] for d in inspection["datasets"].values()} == {(8192,)}
