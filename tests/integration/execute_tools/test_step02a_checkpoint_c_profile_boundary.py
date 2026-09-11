"""PR-02a CHECKPOINT C — the profile crosses a REAL subprocess boundary.

Design:
``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md``
§5b (boundary FROZEN, command NOT frozen).

Every other test in this PR runs the loaders in-process. That proves the
code reads the profile; it does NOT prove the profile survives the trip
from the parent that resolves it to the child that consumes it. §5b is
explicit:

> A pseudo mode that replaces or bypasses ``train_engine_sandbox``,
> ``inference_single`` or ``denoising_score_single`` does NOT establish
> this property and does NOT satisfy Checkpoint C.

So this module launches the REAL entry points with ``subprocess.run`` and
lets them read real HDF5 off disk. No stub, no monkeypatch, no in-process
call.

**Why it is cheap.** The declared ``psd_segment_length`` is 4,096 rather
than 10,000,000. That is the whole point of the geometry being declared: the
production code path is identical, and the fixture is bytes instead of
gigabytes. No GPU, no LLM, no real model quality.

**Not in CI.** ``tests/integration/`` is manual/local by design; CI is unit
plus static. This is run deliberately and its result recorded in the
ledger.
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

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = sys.executable

# segmentation_size carries ge=1000 (models_format_sandbox.py:22), so the
# fixture cannot go below it. 4096 x 2 PSD segments is ~8 KB per file
# against TIDMAD's ~2 GB — the production code path is identical.
PSD_LEN = 4096
SEG_SIZE = 1024
ML_PER_PSD = PSD_LEN // SEG_SIZE
N_PSD = 2
FILE_INDEX = 0

# A declaration that is TIDMAD-shaped but tiny, with channels renamed so a
# child that ignored the transport and fell back to the singleton would fail
# to find its data rather than quietly succeed.
PROFILE = {
    "dataset": {
        "psd_segment_length": PSD_LEN,
        "segments_per_file": N_PSD,
        "num_files": 2,
        "sampling_frequency": 1000.0,
        "training_file_pattern": "cpc_train_{file_index:03d}.h5",
        "validation_file_pattern": "cpc_valid_{file_index:03d}.h5",
    },
    "channels": {"input_channel": "cpc_in", "target_channel": "cpc_truth"},
    "encoding": {
        "storage_dtype": "int8",
        "compute_dtype": "int16",
        "value_offset": 128,
        "num_classes": 256,
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
def boundary_workspace(tmp_path):
    """Profile config + declared data files + model/train/loss configs."""
    data_dir = tmp_path / "data"
    cfg_dir = tmp_path / "configs"
    sandbox = tmp_path / "sandbox"
    for d in (data_dir, cfg_dir, sandbox):
        d.mkdir()

    profile_path = cfg_dir / "dataset_profile_cpc.json"
    profile_path.write_text(json.dumps(PROFILE))

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

    return {
        "tmp": tmp_path,
        "data_dir": data_dir,
        "cfg_dir": cfg_dir,
        "sandbox": sandbox,
        "profile": profile_path,
    }


def _child_env() -> dict[str, str]:
    """Force the child onto THIS checkout.

    Found the hard way: a plain ``python execute_tools/foo.py`` puts the
    SCRIPT's directory on ``sys.path[0]``, not the repo root, so
    ``import execute_tools.dataset_config`` falls through to the venv's
    editable-install finder — which hardcodes absolute paths into the main
    checkout. Launched from a linked worktree, the child therefore imported
    a DIFFERENT clone.

    It failed loudly here only because the other clone lacks this PR's
    changes. Had the change already been there, this test would have passed
    while exercising the wrong tree — the exact failure CLAUDE.md's
    portability rule exists to prevent. ``PYTHONPATH`` pins the checkout
    under test, and ``test_the_child_imports_this_checkout`` proves it.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
    return env


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def test_the_child_imports_this_checkout():
    """Guard the guard: if the subprocess ever resolves the package to
    another clone again, every Checkpoint-C assertion below becomes
    meaningless, and it would do so SILENTLY once both clones carry the
    change."""
    probe = _run(
        [
            PYTHON,
            "-c",
            "import execute_tools.dataset_config as dc; print(dc.__file__)",
        ]
    )
    assert probe.returncode == 0, probe.stderr
    resolved = probe.stdout.strip()
    assert resolved.startswith(str(REPO_ROOT)), (
        f"the child imported a DIFFERENT checkout: {resolved} (expected under {REPO_ROOT})"
    )


def _training_argv(ws, profile_path: str | None) -> list[str]:
    argv = [
        PYTHON,
        "src/execute_tools/train_engine_sandbox.py",
        "--model_cfg",
        str(ws["cfg_dir"] / "model.json"),
        "--train_cfg",
        str(ws["cfg_dir"] / "train.json"),
        "--loss_cfg",
        str(ws["cfg_dir"] / "loss.json"),
        "--exp_id",
        "cpc",
        "--run_name",
        "checkpoint_c",
        "--sandbox_dir",
        str(ws["sandbox"]),
        "--data_dir",
        str(ws["data_dir"]),
        "--file_index",
        str(FILE_INDEX),
        "--sample_set_json",
        str(ws["cfg_dir"] / "sample_set.json"),
    ]
    if profile_path is not None:
        argv += ["--dataset_profile_json", profile_path]
    return argv


class TestTrainingSubprocessConsumesTheProfile:
    """The concentration point, across a real process."""

    def test_the_child_trains_on_data_only_the_declaration_can_find(self, boundary_workspace):
        """Load-bearing.

        The files on disk are named ``cpc_train_000.h5`` and their channels
        are ``cpc_in``/``cpc_truth``. NOTHING about that is discoverable from
        the TIDMAD singleton. If the transport were deleted, the flag
        ignored, or the loader still addressing ``channel0001``, the child
        could not read a single sample — so a green run here is positive
        evidence that the declaration crossed the boundary and was used.
        """
        ws = boundary_workspace
        result = _run(_training_argv(ws, str(ws["profile"])))

        assert result.returncode == 0, (
            f"training subprocess failed\nSTDOUT:\n{result.stdout[-3000:]}\n"
            f"STDERR:\n{result.stderr[-3000:]}"
        )
        # The engine warns-and-skips a file it cannot find; a silent fallback
        # to TIDMAD names would show up here rather than as a crash.
        assert "not found, skipping" not in result.stdout, result.stdout[-2000:]

        records = ws["sandbox"] / "records" / "checkpoint_c"
        written = list(records.glob("experiment_results_*.json"))
        assert written, f"no results JSON written; stdout:\n{result.stdout[-3000:]}"

        payload = json.loads(written[0].read_text())
        assert payload, "results JSON is empty"

    def test_a_supplied_but_broken_profile_fails_closed(self, boundary_workspace):
        """§5c's sharp half, across the real boundary: the child must die
        naming the path, not fall back to the singleton and train on
        whatever it can find."""
        ws = boundary_workspace
        broken = ws["cfg_dir"] / "broken_profile.json"
        broken.write_text("{ not json at all")

        result = _run(_training_argv(ws, str(broken)))

        assert result.returncode != 0, "a broken profile must not train"
        combined = result.stdout + result.stderr
        assert "broken_profile.json" in combined, "the diagnostic must name the path"
        assert "not valid JSON" in combined

    def test_a_missing_profile_path_fails_closed(self, boundary_workspace):
        ws = boundary_workspace
        result = _run(_training_argv(ws, str(ws["cfg_dir"] / "absent.json")))

        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "absent.json" in combined
        assert "fails closed" in combined

    def test_an_omitted_flag_keeps_regime_a(self, boundary_workspace):
        """The other half of §5c. With no flag the child resolves the shipped
        TIDMAD profile, so it looks for ``abra_training_0000.h5``, does not
        find it in this workspace, and warns-and-skips — today's behaviour,
        unchanged. It must NOT fail closed: that would break every legacy
        caller.
        """
        ws = boundary_workspace
        result = _run(_training_argv(ws, None))

        combined = result.stdout + result.stderr
        assert "abra_training_0000.h5" in combined, (
            "an omitted flag must resolve the shipped TIDMAD profile (Regime-A)"
        )
        assert "fails closed" not in combined


class TestAllThreeEntriesLoadTheSameProfileFile:
    """CP-A3's claim, verified across real process boundaries.

    Each entry point is launched with ``--dataset_profile_json`` pointing at
    the SAME file and asked to do the cheapest thing that requires having
    parsed it. ``--help`` is not enough — it never reads the file — so each
    is given a path that does not exist and must fail closed naming it.
    That is the smallest observable proof that the child actually loads what
    the parent wrote.
    """

    ENTRIES = (
        "src/execute_tools/train_engine_sandbox.py",
        "src/execute_tools/inference_single.py",
        "src/execute_tools/denoising_score_single.py",
    )

    @pytest.mark.parametrize("entry", ENTRIES)
    def test_each_entry_loads_the_file_and_fails_closed_on_a_bad_one(
        self, entry, boundary_workspace
    ):
        ws = boundary_workspace
        missing = str(ws["cfg_dir"] / "nope.json")
        argv = [PYTHON, entry, "--dataset_profile_json", missing]

        # Minimal required args per entry so argparse itself does not exit
        # before the profile is resolved.
        if entry.endswith("train_engine_sandbox.py"):
            argv = _training_argv(ws, missing)
        elif entry.endswith("inference_single.py"):
            argv += [
                "--mode",
                "agent",
                "-m",
                "wavenet",
                "--model_cfg",
                str(ws["cfg_dir"] / "model.json"),
                "--loss_cfg",
                str(ws["cfg_dir"] / "loss.json"),
                "--model_path",
                str(ws["sandbox"] / "absent_model.pth"),
                "--exp_id",
                "cpc",
                "--run_name",
                "checkpoint_c",
                "--data_dir",
                str(ws["data_dir"]),
                "--output_dir",
                str(ws["sandbox"]),
            ]
        else:
            argv += [
                "--mode",
                "agent",
                "-m",
                "wavenet",
                "--exp_id",
                "cpc",
                "--run_name",
                "checkpoint_c",
                "--data_dir",
                str(ws["data_dir"]),
                "--file_index",
                str(FILE_INDEX),
            ]

        result = _run(argv)
        combined = result.stdout + result.stderr
        assert result.returncode != 0, f"{entry} accepted a missing profile"
        assert "nope.json" in combined, (
            f"{entry} did not name the missing profile path:\n{combined[-2000:]}"
        )


def test_recorded_executable_head():
    """§5b requires the exact executable HEAD to be recorded with the
    evidence. Emitted here so the ledger entry cannot drift from the tree
    the run actually exercised."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    print(f"\nCHECKPOINT C executable HEAD: {head}")
    print(f"working tree: {'DIRTY -> ' + dirty if dirty else 'clean'}")
    assert len(head) == 40
    assert os.path.isdir(REPO_ROOT / ".git") or (REPO_ROOT / ".git").is_file()
