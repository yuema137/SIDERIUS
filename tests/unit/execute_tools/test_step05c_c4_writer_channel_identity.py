"""Step 05c — C4: ``create_abra_file`` derives its channel-group identity.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` C4, §0.3, OD-05c-2.

This closes the write side of a gap Step 02 left half-open. The READ side
already resolves the pair from the profile
(``inference_single.py:661,664`` use ``profile_channels.input_channel`` /
``.target_channel``), while the WRITER contradicted it with two hardcoded
names — so "which channel holds the truth" was declared in one place and
re-decided in another.

C4 changes the **structure of the file's bytes**, which is a different risk
class from naming: the oracle is therefore EXACT LOGICAL ARTIFACT EQUALITY
(§4.1) against the C0 golden, not a spot check.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from execute_tools.array2h5 import create_abra_file
from execute_tools.dataset_config import ChannelIdentity, resolve_dataset_profile
from execute_tools.deliverable_spec import (
    DeliverableStorage,
    default_deliverable_storage,
    derive_tidmad_deliverable_spec,
)
from tests.unit.execute_tools.test_step05c_c0_deliverable_baseline import (
    FROZEN_CHANNEL_ATTRS,
    INPUT_SAMPLES,
    TARGET_SAMPLES,
    canonical_h5_inspection,
)

_ARRAY2H5_SOURCE = Path(__file__).resolve().parents[3] / "execute_tools" / "array2h5.py"


def _write(tmp_path, storage=None, array2=TARGET_SAMPLES):
    out = str(tmp_path / "deliverable.h5")
    create_abra_file(
        out,
        np.asarray(INPUT_SAMPLES, dtype=np.int8),
        None if array2 is None else np.asarray(array2, dtype=np.int8),
        indexed=False,
        **({} if storage is None else {"storage": storage}),
    )
    return out


# ---------------------------------------------------------------------------
# TIDMAD parity — the C0 golden, unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "storage",
    [None, "derived"],
    ids=["no_spec_supplied", "derived_from_profile"],
)
def test_tidmad_artifact_is_logically_identical_to_the_c0_golden(tmp_path, storage):
    """Both call shapes reproduce the pre-05c file EXACTLY.

    ``None`` is the backward-compat path every caller predating 05c takes;
    the derived storage is what production now supplies. A single differing
    attr, dtype, shape or sample value is failure class 2 — the deliverable is
    scientific evidence and a byte change is not a refactor — so this compares
    the whole canonical inspection, not a spot check.
    """
    resolved = (
        None
        if storage is None
        else derive_tidmad_deliverable_spec(resolve_dataset_profile()).storage
    )

    inspection = canonical_h5_inspection(_write(tmp_path, resolved))

    assert inspection == {
        "groups": ["timeseries", "timeseries/channel0001", "timeseries/channel0002"],
        "datasets": {
            "timeseries/channel0001/timeseries": {
                "dtype": "int8",
                "shape": (8,),
                "values": list(INPUT_SAMPLES),
            },
            "timeseries/channel0002/timeseries": {
                "dtype": "int8",
                "shape": (8,),
                "values": list(TARGET_SAMPLES),
            },
        },
        "attrs": {
            "timeseries/channel0001": dict(FROZEN_CHANNEL_ATTRS),
            "timeseries/channel0002": dict(FROZEN_CHANNEL_ATTRS),
        },
    }


def test_single_channel_write_is_unchanged(tmp_path):
    """``array2=None`` still writes exactly one group and no target attrs.

    Design C4 §6 names this edge: a profile declaring only an input channel
    must not gain an empty second group, and the target identity must simply
    go unused rather than resolve to something.
    """
    inspection = canonical_h5_inspection(_write(tmp_path, None, array2=None))

    assert inspection["groups"] == ["timeseries", "timeseries/channel0001"]
    assert list(inspection["datasets"]) == ["timeseries/channel0001/timeseries"]
    assert inspection["attrs"] == {"timeseries/channel0001": dict(FROZEN_CHANNEL_ATTRS)}


# ---------------------------------------------------------------------------
# The contrast — exactly the two group names move
# ---------------------------------------------------------------------------


def test_a_contrast_channel_identity_moves_the_group_names_and_nothing_else(tmp_path):
    """Under a different channel identity, ONLY the two group names change.

    Asserted by diffing the whole canonical inspection against the TIDMAD
    golden rather than by checking the new names exist: that is what proves
    the derivation touched the identity and not the dtypes, shapes, sample
    values or the frozen attrs. The attrs in particular must NOT follow the
    identity — OD-05c-2 leaves them literal, and a writer that started
    deriving them would have quietly made 05c own instrument metadata.
    """
    contrast = DeliverableStorage(
        input_channel_group="sensor_a",
        target_channel_group="sensor_b",
        storage_dtype="int8",
        value_offset=128,
    )

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    tidmad = canonical_h5_inspection(_write(tmp_path / "a", None))
    moved = canonical_h5_inspection(_write(tmp_path / "b", contrast))

    assert moved["groups"] == ["timeseries", "timeseries/sensor_a", "timeseries/sensor_b"]
    # Everything except the group PATHS is identical to the TIDMAD golden.
    assert [d["values"] for d in moved["datasets"].values()] == [
        d["values"] for d in tidmad["datasets"].values()
    ]
    assert [d["dtype"] for d in moved["datasets"].values()] == [
        d["dtype"] for d in tidmad["datasets"].values()
    ]
    assert [d["shape"] for d in moved["datasets"].values()] == [
        d["shape"] for d in tidmad["datasets"].values()
    ]
    assert list(moved["attrs"].values()) == list(tidmad["attrs"].values())


# ---------------------------------------------------------------------------
# What must NOT have moved
# ---------------------------------------------------------------------------


def test_writer_holds_no_channel_literal():
    """``array2h5.py`` contains no ``channel0001`` / ``channel0002`` literal.

    C4's frozen acceptance criterion, and the only check that catches a
    fallback quietly re-introducing the hardcoded pair — a fallback would make
    every TIDMAD assertion above pass while the derivation was dead.
    """
    source = _ARRAY2H5_SOURCE.read_text()

    assert '"channel0001"' not in source
    assert '"channel0002"' not in source


def test_the_deliberately_unowned_writer_facts_stay_literal():
    """The attrs, the ``N`` split and the suffix rule are still in the writer.

    OD-05c-2 draws this boundary on purpose: no production consumer reads the
    attrs, so deriving them would make 05c a format declaration rather than a
    contract extraction. Asserting it keeps a later commit from widening the
    spec by accident — the failure this catches is scope creep, which no
    behavioural test reports as a failure at all.
    """
    source = _ARRAY2H5_SOURCE.read_text()

    assert 'attrs["sampling_frequency"] = 10000000' in source
    assert "N = 2000000000" in source
    assert 'f"{os.path.splitext(file_name)[0]}_{i}.h5"' in source


def test_default_storage_equals_the_derived_tidmad_storage():
    """The no-argument path and the production path resolve the same value.

    If these ever diverged, a caller predating 05c would write a *different*
    file from the one production writes — the two-authorities defect this
    contract exists to remove, reappearing as a default.
    """
    assert (
        default_deliverable_storage()
        == derive_tidmad_deliverable_spec(resolve_dataset_profile()).storage
    )


def test_the_derivation_follows_a_bound_profile(tmp_path):
    """``default_deliverable_storage`` honours a bound profile, not a constant.

    It resolves through Step 02's ``resolve_dataset_profile`` seam, so a task
    that binds a profile gets ITS channel identity. A hardcoded TIDMAD fallback
    would pass every other test in this module and silently write the wrong
    groups for a bound task.
    """
    from execute_tools.dataset_config import bind_dataset_profile

    live = resolve_dataset_profile()
    bound = live.model_copy(
        update={"channels": ChannelIdentity(input_channel="bound_in", target_channel="bound_out")}
    )

    with bind_dataset_profile(bound):
        assert default_deliverable_storage().input_channel_group == "bound_in"
        assert canonical_h5_inspection(_write(tmp_path, None))["groups"] == [
            "timeseries",
            "timeseries/bound_in",
            "timeseries/bound_out",
        ]
