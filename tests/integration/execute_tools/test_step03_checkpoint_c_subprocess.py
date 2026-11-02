"""Cardinality and dtype declarations cross a real CPU training subprocess.

Reuse the Step-02a synthetic HDF5 task, manifest, scope transport and child
launch harness. The scope adapter materializes the tiny dataset; the real
trainer owns contract resolution, model construction and checkpoint writing.
No provider, GPU or scientific dataset is used. Missing task binding remains
a production refusal. These tests require this checkout's frozen environment.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import torch

from .test_step02a_checkpoint_c_profile_boundary import (
    PYTHON,
    REPO_ROOT,
    _child_env,
    _run,
    _training_argv,
)
from .test_step02a_checkpoint_c_profile_boundary import boundary_workspace as workspace


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


def _train(ws, model_io: dict | None, exp_id: str) -> subprocess.CompletedProcess:
    argv = _training_argv(ws, str(ws["profile"]))
    argv[argv.index("--exp_id") + 1] = exp_id
    argv[argv.index("--run_name") + 1] = "step03_cpc"
    if model_io is not None:
        path = ws["cfg_dir"] / f"model_io_{exp_id}.json"
        path.write_text(json.dumps(model_io))
        argv += ["--model_io_json", str(path)]
    return _run(argv, cwd=ws["sandbox"])


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
        assert "UnsupportedModelInputDtypeError" in combined, combined[-3000:]

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
        argv = _training_argv(workspace, str(workspace["profile"]))
        argv += ["--model_io_json", str(path)]
        result = _run(argv, cwd=workspace["sandbox"])
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "not valid JSON" in combined or str(path) in combined, combined[-2000:]

    def test_the_child_imports_this_checkout(self, workspace):
        """Portability: without this, every assertion above could describe a
        different clone (the 02a lesson)."""
        assert "PYTHONPATH" not in _child_env()
        probe = subprocess.run(
            [PYTHON, "-c", "import execute_tools.model_input_dtype as m; print(m.__file__)"],
            cwd=workspace["sandbox"],
            env=_child_env(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip().startswith(str(REPO_ROOT)), probe.stdout
