"""Step 05c — Checkpoint 0: the deliverable baselines, captured BEFORE any
production edit.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` §4, §4.1, C0.

**Why this module exists.** PR 05c moves deliverable naming, channel-group
identity and the persisted storage representation out of seven inlined
production sites and behind one provisional ``DeliverableSpec``. A
write/cleanup refactor can only be proven inert against artifacts captured
*beforehand* — a golden taken after the edit proves nothing about the edit.
``create_abra_file`` has **no behavioural test at all** today (design §8), so
this is its first.

**What is captured here**

1. ``canonical_h5_inspection`` + the EXACT LOGICAL ARTIFACT golden (§4.1) for
   ``execute_tools/array2h5.py::create_abra_file`` — group paths, dataset
   names, dtypes, shapes, **every persisted sample value** and every attr
   key/value. Deliberately NOT raw HDF5 binary equality: HDF5 writes carry
   library-version, chunk-layout and allocation details that are not
   guaranteed byte-reproducible across environments, so a file hash would
   fail for reasons unrelated to this PR.
2. The producer FILENAME SET for a fixed identifier tuple — the three
   constructions at ``execute_tools/inference_single.py:620``, ``:897`` and
   ``:902``.

Every expectation is a **hardcoded literal**. Nothing here is re-derived by
calling the code under test.
"""

from __future__ import annotations

import os
from typing import Any

import h5py
import numpy as np

from execute_tools.array2h5 import create_abra_file

# ---------------------------------------------------------------------------
# The fixture array. Boundary values are deliberate: -128 and 127 are the int8
# extremes, so an offset or dtype drift introduced by C5 wraps here instead of
# passing silently on mid-range samples.
# ---------------------------------------------------------------------------
INPUT_SAMPLES: list[int] = [-128, -1, 0, 1, 127, -128, 63, -64]
TARGET_SAMPLES: list[int] = [127, 1, 0, -1, -128, 127, -64, 63]

# The 5 attrs create_abra_file writes on EACH channel group
# (array2h5.py:50-54 and :64-68). Frozen TIDMAD instrument metadata:
# OD-05c-2 leaves every one of them literal, so this golden is what "still
# literal" means mechanically.
FROZEN_CHANNEL_ATTRS: dict[str, int] = {
    "file_first_sample_index": 100000000000000,
    "input_coupling": 0,
    "input_impedance_ohm": 50,
    "sampling_frequency": 10000000,
    "voltage_range_mV": 80,
}


def canonical_h5_inspection(path: str) -> dict[str, Any]:
    """The canonical inspection representation §4.1 defines equality over.

    Returns a plain-Python structure covering group paths, dataset names,
    dtypes, shapes, every persisted sample value and every attr key/value.
    Reused by the C4 and C5 parity assertions, which is the point: one
    definition of "equal artifact" for the whole PR.
    """
    groups: list[str] = []
    datasets: dict[str, dict[str, Any]] = {}
    attrs: dict[str, dict[str, Any]] = {}

    with h5py.File(path, "r") as handle:

        def _visit(name: str, node: Any) -> None:
            if isinstance(node, h5py.Group):
                groups.append(name)
                if node.attrs:
                    attrs[name] = {k: node.attrs[k].item() for k in sorted(node.attrs)}
            elif isinstance(node, h5py.Dataset):
                datasets[name] = {
                    "dtype": str(node.dtype),
                    "shape": tuple(node.shape),
                    "values": np.asarray(node[...]).tolist(),
                }

        handle.visititems(_visit)

    return {
        "groups": sorted(groups),
        "datasets": datasets,
        "attrs": attrs,
    }


# ---------------------------------------------------------------------------
# 1. EXACT LOGICAL ARTIFACT golden (§4.1)
# ---------------------------------------------------------------------------


def test_c0_two_channel_artifact_golden(tmp_path):
    """The full logical artifact ``create_abra_file`` writes today, for the
    production call shape (``indexed=False``, two channels).

    Guards ``execute_tools/array2h5.py:25-75`` — the writer C4 gives a spec
    parameter and C5 routes the persisted encoding through. A single differing
    attr, dtype, shape or sample value is failure class 2 (design §7): the
    deliverable is scientific evidence, and a byte change is not a refactor.
    """
    out = str(tmp_path / "abra_validation_denoised_wavenet_run_exp_0000.h5")
    create_abra_file(
        out,
        np.asarray(INPUT_SAMPLES, dtype=np.int8),
        np.asarray(TARGET_SAMPLES, dtype=np.int8),
        indexed=False,
    )

    assert canonical_h5_inspection(out) == {
        "groups": [
            "timeseries",
            "timeseries/channel0001",
            "timeseries/channel0002",
        ],
        "datasets": {
            "timeseries/channel0001/timeseries": {
                "dtype": "int8",
                "shape": (8,),
                "values": [-128, -1, 0, 1, 127, -128, 63, -64],
            },
            "timeseries/channel0002/timeseries": {
                "dtype": "int8",
                "shape": (8,),
                "values": [127, 1, 0, -1, -128, 127, -64, 63],
            },
        },
        "attrs": {
            "timeseries/channel0001": {
                "file_first_sample_index": 100000000000000,
                "input_coupling": 0,
                "input_impedance_ohm": 50,
                "sampling_frequency": 10000000,
                "voltage_range_mV": 80,
            },
            "timeseries/channel0002": {
                "file_first_sample_index": 100000000000000,
                "input_coupling": 0,
                "input_impedance_ohm": 50,
                "sampling_frequency": 10000000,
                "voltage_range_mV": 80,
            },
        },
    }


def test_c0_single_channel_artifact_golden(tmp_path):
    """``array2=None`` — the science-data shape. C4 must leave it unchanged.

    Design C4 §6 names this edge explicitly: a profile declaring only an input
    channel must still write exactly one channel group, with no
    ``channel0002`` created and no target attrs.
    """
    out = str(tmp_path / "single.h5")
    create_abra_file(out, np.asarray(INPUT_SAMPLES, dtype=np.int8), None, indexed=False)

    inspection = canonical_h5_inspection(out)
    assert inspection["groups"] == ["timeseries", "timeseries/channel0001"]
    assert list(inspection["datasets"]) == ["timeseries/channel0001/timeseries"]
    assert inspection["datasets"]["timeseries/channel0001/timeseries"]["values"] == [
        -128,
        -1,
        0,
        1,
        127,
        -128,
        63,
        -64,
    ]
    assert inspection["attrs"]["timeseries/channel0001"] == FROZEN_CHANNEL_ATTRS


def test_c0_indexed_suffix_rule(tmp_path):
    """``indexed=True`` (the DEFAULT) appends ``_{i}``; production passes
    ``indexed=False`` and gets the bare name.

    OD-05c-2 leaves this suffix rule as writer mechanics — it is NOT a field
    of the provisional spec. Captured so a C4 signature change cannot move it
    unnoticed. ``array2h5.py:39-41``.
    """
    indexed_out = str(tmp_path / "indexed.h5")
    create_abra_file(indexed_out, np.asarray(INPUT_SAMPLES, dtype=np.int8), indexed=True)

    assert os.path.exists(str(tmp_path / "indexed_0.h5"))
    assert not os.path.exists(indexed_out)


def test_c0_invalid_filename_writes_nothing_and_returns_none(tmp_path):
    """A non-``.h5`` name prints and returns ``None`` without writing.

    ``array2h5.py:29-31``. Design §0.3 records this silent no-write as a
    DEFECT and explicitly does **not** fix it in 05c. Captured as-is so C4
    cannot change it while claiming to be a naming refactor — and so the debt
    is visible to whoever wins final ownership (§3).
    """
    bad = str(tmp_path / "not_an_h5_file.txt")
    assert create_abra_file(bad, np.asarray(INPUT_SAMPLES, dtype=np.int8)) is None
    assert os.listdir(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# 2. Producer FILENAME SET golden
# ---------------------------------------------------------------------------

# The identifier tuple every C1/C3 name assertion resolves against.
GOLDEN_MODEL_TYPE = "wavenet"
GOLDEN_RUN_NAME = "step05c_run"
GOLDEN_EXP_ID = "wavenet_step05c_run_003"
GOLDEN_FILE_INDEX = 7

# Hardcoded, NOT re-derived. Traceable to the production site each guards.
GOLDEN_SAMPLE_SET_NAME = (
    "abra_validation_denoised_wavenet_step05c_run_wavenet_step05c_run_003_0007.h5"
)
GOLDEN_FIX_MODE_NAME = "abra_validation_denoised_wavenet_0007.h5"
GOLDEN_SINGLE_FILE_NAME = (
    "abra_validation_denoised_wavenet_step05c_run_wavenet_step05c_run_003_0007.h5"
)


def test_c0_path_builder_agrees_with_the_producer_filename_golden():
    """The READER's name equals the PRODUCER's, exactly, for one tuple.

    This is the only executable oracle C0 can take over deliverable naming:
    the three producer constructions are inline f-strings inside
    ``inference_single.main()`` and cannot be called in isolation, but the
    reader side — ``_build_denoised_filename``
    (``ml_hyperparameter_tune_agent.py:1053``, template at ``:1088``) — is a
    module-level helper. Pinning it against the producer golden is what makes
    failure class 1 visible: a producer that writes one name while a reader
    globs for another leaves orphaned artifacts and a scorer that reads
    nothing.

    The four existing ``test_denoised_filename_helper.py`` tests assert
    *properties* of the returned path (absolute, under base_dir, contains each
    identifier, 4-digit padding). None asserts the **exact full name**, so
    none would catch a template that changed shape while keeping every
    identifier present. That is the defect only this test catches, and it
    stays valid through C2 (reader migration) and C3 (producer migration) —
    it is precisely the assertion that must keep holding when both move to
    the spec.

    Producer sites, current at ``226d4e9f`` and re-verified at the
    implementation base:

    * ``inference_single.py:620`` — the ``sample_set`` (multi-file) path
    * ``inference_single.py:897`` — ``mode == "fix"``; **omits run_name and
      exp_id**, a genuinely different name shape
    * ``inference_single.py:902`` — the single-file non-fix path
    """
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        _build_denoised_filename,
    )

    path = _build_denoised_filename(
        model_type=GOLDEN_MODEL_TYPE,
        run_name=GOLDEN_RUN_NAME,
        exp_id=GOLDEN_EXP_ID,
        file_index=GOLDEN_FILE_INDEX,
        base_dir="/step05c/workspace",
    )

    assert path == os.path.join("/step05c/workspace", GOLDEN_SAMPLE_SET_NAME)
