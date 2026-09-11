"""CHECKPOINT C boundary (iii) — the contract crosses a REAL subprocess.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§12 (iii), §16 (*"the contract reaches the subprocesses through the
established config-file/argv mechanism"*), **§4a.1 AMENDMENT A-1**.

§12 (iii) requires *"a real training + inference round [that] feeds a
contract-derived input dtype and cardinality through the actual
subprocess/runtime path"*, and §12 is explicit that entering by calling a
resolver directly does not satisfy it. Every other Step-03 test runs
in-process; that proves the code reads the contract, not that the contract
survives the trip from the parent that resolves it to the child that
consumes it.

So this module launches ``execute_tools/train_engine_sandbox.py`` with
``subprocess.run`` and lets it read real HDF5 off disk. No stub, no
monkeypatch, no in-process call. It mirrors PR-02a's
``test_step02a_checkpoint_c_profile_boundary.py`` deliberately — same
fixture geometry, same ``PYTHONPATH`` pin, same argv shape — because §16
requires the EXISTING transport, and reusing the proven harness is how
that is demonstrated rather than asserted.

**Why it is cheap.** The declared ``psd_segment_length`` is 4,096 rather
than 10,000,000, the model is a 1-block WaveNet, and training is one epoch
over a handful of segments. The production code path is identical; the
fixture is kilobytes.

**Not in CI.** ``tests/integration/`` is manual/local by design (CI is unit
plus static). Run deliberately, result recorded in the ledger.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest
import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = sys.executable

PSD_LEN = 4096
SEG_SIZE = 1024
N_PSD = 2
FILE_INDEX = 0

PROFILE = {
    "dataset": {
        "psd_segment_length": PSD_LEN,
        "segments_per_file": N_PSD,
        "num_files": 2,
        "sampling_frequency": 1000.0,
        "training_file_pattern": "s3_train_{file_index:03d}.h5",
        "validation_file_pattern": "s3_valid_{file_index:03d}.h5",
    },
    "channels": {"input_channel": "s3_in", "target_channel": "s3_truth"},
    "encoding": {
        "storage_dtype": "int8",
        "compute_dtype": "int16",
        "value_offset": 128,
        "num_classes": 256,
    },
    # Step 02c made these REQUIRED on DatasetProfile. Both index into this
    # fixture's 2-file topology, not TIDMAD's 20 — copying TIDMAD's
    # [0, 10, 19] / [3, 10, 17] would declare files that do not exist here.
    "anchor_selection_files": [FILE_INDEX],
    "health_peek_files": [FILE_INDEX],
}


def _profile(num_classes: int = 256) -> dict:
    """The dataset profile, with its class alphabet parameterized.

    Cardinality lives on BOTH authorities: the dataset declares what the
    data contains, the contract declares what the model emits, and rung
    3-E requires them to agree (§4b). A contrast that moved only the
    contract would be an inconsistency, not a contrast — which is exactly
    what the first cut of this module did, and what the engine now refuses.
    """
    profile = json.loads(json.dumps(PROFILE))
    profile["encoding"]["num_classes"] = num_classes
    return profile


def _model_io(*, classes: int, admissible: list[str]) -> dict:
    """A Model-I/O contract in the shape the parent writes to disk."""
    return {
        "input": {
            "axes": [
                {"role": "batch", "dimension": {"symbolic": "B"}},
                {"role": "temporal", "dimension": {"symbolic": "T"}},
            ],
            "dtype": {"admissible": admissible},
        },
        "output": {
            "axes": [
                {"role": "batch", "dimension": {"symbolic": "B"}},
                {"role": "class", "dimension": {"fixed": classes}},
                {"role": "temporal", "dimension": {"symbolic": "T"}},
            ],
            "dtype": {"admissible": ["float32"]},
        },
    }


def _write_h5(path: Path, n: int) -> None:
    rng = np.random.default_rng(0)
    with h5py.File(path, "w") as f:
        ts = f.create_group("timeseries")
        for name in (PROFILE["channels"]["input_channel"], PROFILE["channels"]["target_channel"]):
            grp = ts.create_group(name)
            grp.create_dataset("timeseries", data=rng.integers(-128, 127, size=n, dtype=np.int8))
            grp.attrs["voltage_range_mV"] = 80.0
            grp.attrs["sampling_frequency"] = PROFILE["dataset"]["sampling_frequency"]


@pytest.fixture
def workspace(tmp_path):
    return _workspace(tmp_path, 256)


def _workspace(tmp_path, dataset_classes: int):
    data_dir, cfg_dir, sandbox = (tmp_path / n for n in ("data", "configs", "sandbox"))
    for d in (data_dir, cfg_dir, sandbox):
        d.mkdir()

    (cfg_dir / "dataset_profile.json").write_text(json.dumps(_profile(dataset_classes)))
    dataset = PROFILE["dataset"]
    n_samples = PSD_LEN * N_PSD
    _write_h5(data_dir / dataset["training_file_pattern"].format(file_index=FILE_INDEX), n_samples)
    _write_h5(
        data_dir / dataset["validation_file_pattern"].format(file_index=FILE_INDEX), n_samples
    )

    (cfg_dir / "model.json").write_text(
        json.dumps(
            {
                "model_type": "wavenet",
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


def _child_env() -> dict[str, str]:
    """Pin the child onto THIS checkout (the 02a portability lesson).

    A plain ``python execute_tools/foo.py`` puts the SCRIPT's directory on
    ``sys.path[0]``, so an ``import execute_tools...`` can fall through to
    the venv's editable-install finder and import a DIFFERENT clone — which
    would let this test pass while exercising the wrong tree.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
    return env


def _train(ws, model_io: dict | None, exp_id: str) -> subprocess.CompletedProcess:
    argv = [
        PYTHON,
        "src/execute_tools/train_engine_sandbox.py",
        "--model_cfg",
        str(ws["cfg_dir"] / "model.json"),
        "--train_cfg",
        str(ws["cfg_dir"] / "train.json"),
        "--loss_cfg",
        str(ws["cfg_dir"] / "loss.json"),
        "--dataset_profile_json",
        str(ws["cfg_dir"] / "dataset_profile.json"),
        "--exp_id",
        exp_id,
        "--run_name",
        "step03_cpc",
        "--sandbox_dir",
        str(ws["sandbox"]),
        "--data_dir",
        str(ws["data_dir"]),
        "--file_index",
        str(FILE_INDEX),
        "--sample_set_json",
        str(ws["cfg_dir"] / "sample_set.json"),
    ]
    if model_io is not None:
        path = ws["cfg_dir"] / f"model_io_{exp_id}.json"
        path.write_text(json.dumps(model_io))
        argv += ["--model_io_json", str(path)]
    return subprocess.run(
        argv, cwd=REPO_ROOT, env=_child_env(), capture_output=True, text=True, timeout=900
    )


def _trained_class_count(sandbox: Path) -> int:
    """The output-layer width of the model the SUBPROCESS actually built.

    Read off the saved state_dict — the only observable that survives the
    process boundary, and the one that proves the cardinality was consumed
    at construction rather than merely transported.
    """
    checkpoints = sorted(sandbox.rglob("*.pth"))
    assert checkpoints, f"no checkpoint written under {sandbox}"
    state = torch.load(checkpoints[-1], map_location="cpu", weights_only=True)
    weight = state["output_conv2.weight"]  # WaveNet's final projection
    return int(weight.shape[0])


class TestCardinalityCrossesTheSubprocess:
    """§12(iii), cardinality half."""

    # A 16-class POSITIVE contrast is NOT expressible here, and the reason is
    # semantic rather than incidental. `ValueEncoding` validates that the
    # alphabet can hold the storage dtype's shifted range: int8 offset by 128
    # spans [0, 255], so an int8 dataset's num_classes is necessarily 256 and
    # numpy has no narrower integer type. The dataset-side class alphabet is
    # BOUNDED BY ITS STORAGE DTYPE (Step 02's authority), so varying it would
    # mean changing the encoding — Step-02 territory this PR does not own.
    #
    # The derivation contrast at 10 and 64 classes is therefore owned by the
    # in-process rung 3-C (test_step03_m6_cardinality_derivation.py), which
    # constructs models directly and is not bound by a real HDF5 fixture.
    # What THIS module owns is the transport claim, and the case below proves
    # it: the child could not refuse a contradiction it had not received.

    def test_a_contract_contradicting_the_dataset_fails_CLOSED_in_the_child(self, workspace):
        """Rung 3-E at the subprocess boundary — found BY this checkpoint.

        The child receives the profile and the contract as two separate
        argv files and cannot assume the parent paired them.

        Before the cross-check was added here, a contradictory pair built a
        16-wide model against 256-valued data and died with a torch
        embedding index error deep inside ``forward`` — a confusing crash
        where §21 requires a typed refusal. Now it fails closed, naming
        both numbers, before a single training step runs.
        """
        result = _train(workspace, _model_io(classes=16, admissible=["int64", "int32"]), "mismatch")
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "DatasetContradictionError" in combined, combined[-3000:]
        assert "16" in combined and "256" in combined

    def test_the_shipped_cardinality_still_produces_256(self, workspace):
        """Compatibility half: the same path with TIDMAD's declaration is
        unchanged, so the contrast above is attributable to the contract."""
        result = _train(workspace, _model_io(classes=256, admissible=["int64", "int32"]), "card256")
        assert result.returncode == 0, result.stderr[-3000:]
        assert _trained_class_count(workspace["sandbox"]) == 256

    def test_regime_a_without_the_flag_still_trains(self, workspace):
        """A caller that predates the flag is not broken, and gets 256."""
        result = _train(workspace, None, "regimea")
        assert result.returncode == 0, result.stderr[-3000:]
        assert _trained_class_count(workspace["sandbox"]) == 256


class TestDtypeCrossesTheSubprocess:
    """§12(iii), dtype half — proven by the case that must FAIL.

    A successful run cannot distinguish "the contract's dtype was consulted"
    from "the site's historical dtype was used anyway", because for TIDMAD
    both yield int32. A contract the runtime cannot satisfy CAN: it only
    fails if the declared admissibility actually reached the child and was
    intersected with runtime capability there.
    """

    def test_an_unsatisfiable_dtype_requirement_fails_the_subprocess(self, workspace):
        result = _train(workspace, _model_io(classes=256, admissible=["bfloat16"]), "badtype")
        assert result.returncode != 0, "the child accepted a dtype it cannot materialize"
        combined = result.stdout + result.stderr
        assert "UnsupportedModelInputDtypeError" in combined or "bfloat16" in combined, combined[
            -3000:
        ]

    def test_a_supported_narrowed_dtype_still_trains(self, workspace):
        """The positive control: narrowing to int64 alone — which is NOT the
        training site's historical int32 preference — must still succeed via
        the supported-alternative path (§24.9 Q7)."""
        result = _train(workspace, _model_io(classes=256, admissible=["int64"]), "int64only")
        assert result.returncode == 0, result.stderr[-3000:]
        assert _trained_class_count(workspace["sandbox"]) == 256


class TestTransportFailsClosed:
    """A supplied-but-broken contract must never fall back silently."""

    def test_a_broken_contract_file_fails_the_subprocess(self, workspace):
        path = workspace["cfg_dir"] / "broken.json"
        path.write_text("{ not json")
        argv = [
            PYTHON,
            "src/execute_tools/train_engine_sandbox.py",
            "--model_cfg",
            str(workspace["cfg_dir"] / "model.json"),
            "--train_cfg",
            str(workspace["cfg_dir"] / "train.json"),
            "--loss_cfg",
            str(workspace["cfg_dir"] / "loss.json"),
            "--dataset_profile_json",
            str(workspace["cfg_dir"] / "dataset_profile.json"),
            "--model_io_json",
            str(path),
            "--exp_id",
            "broken",
            "--run_name",
            "step03_cpc",
            "--sandbox_dir",
            str(workspace["sandbox"]),
            "--data_dir",
            str(workspace["data_dir"]),
            "--file_index",
            str(FILE_INDEX),
            "--sample_set_json",
            str(workspace["cfg_dir"] / "sample_set.json"),
        ]
        result = subprocess.run(
            argv, cwd=REPO_ROOT, env=_child_env(), capture_output=True, text=True, timeout=300
        )
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "not valid JSON" in combined or str(path) in combined, combined[-2000:]

    def test_the_child_imports_this_checkout(self, workspace):
        """Portability: without this, every assertion above could describe a
        different clone (the 02a lesson)."""
        probe = subprocess.run(
            [PYTHON, "-c", "import execute_tools.model_input_dtype as m; print(m.__file__)"],
            cwd=REPO_ROOT,
            env=_child_env(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip().startswith(str(REPO_ROOT)), probe.stdout
