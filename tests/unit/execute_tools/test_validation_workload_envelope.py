"""The envelope shrinks the epoch itself, before any step runs.

The distinction this module exists to prove is not cosmetic. A bound
enforced during execution — a deadline kill, a mid-loop stop — spends
the whole cost of the run and yields no evidence: Step 03 lost a Gate
attempt to a round that trained for 33m53s under a "5 minute" budget.
A bound enforced where the epoch is BUILT costs nothing to apply: fewer
segments are read, fewer batches exist, and the run that follows is a
small, complete, real training execution.

So these tests assert on the built dataset and on the executed run, not
on a log line saying a limit was configured.
"""

from __future__ import annotations

import os

import h5py
import numpy as np
import pytest

import execute_tools.train_engine_sandbox as tes
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from execute_tools.dataset_config import TIDMAD_PROFILE, bind_dataset_profile
from execute_tools.workload_resolvers import resolve_training_workload
from ml_models.models_format_sandbox import LossConfig, TrainConfig, WaveNetConfig

SEG_SIZE = 1000
#: 2 files x 5 PSD segments x (10_000 // 1_000) = 100 ML segments total.
N_PSD_PER_FILE = 5
N_FILES = 2
ML_PER_PSD = 10
TOTAL_SEGMENTS = N_FILES * N_PSD_PER_FILE * ML_PER_PSD


@pytest.fixture
def tiny_dataset(tmp_path):
    """Two synthetic files, so the ceiling can cut across a file boundary."""
    n_samples = N_PSD_PER_FILE * SEG_SIZE * ML_PER_PSD
    rng = np.random.default_rng(13)
    for index in range(N_FILES):
        with h5py.File(tmp_path / f"abra_training_{index:04d}.h5", "w") as f:
            ts = f.create_group("timeseries")
            ts.create_group("channel0001").create_dataset(
                "timeseries", data=rng.integers(-128, 127, size=n_samples, dtype=np.int8)
            )
            ts.create_group("channel0002").create_dataset(
                "timeseries", data=rng.integers(-128, 127, size=n_samples, dtype=np.int16)
            )

    profile = TIDMAD_PROFILE.model_copy(
        update={
            "dataset": TIDMAD_PROFILE.dataset.model_copy(
                update={"psd_segment_length": SEG_SIZE * ML_PER_PSD}
            )
        }
    )
    with bind_dataset_profile(profile):
        yield {
            "data_dir": str(tmp_path),
            "sample_set": {str(i): list(range(N_PSD_PER_FILE)) for i in range(N_FILES)},
            "profile": profile,
        }


def _dataset(tiny, *, max_samples=None):
    return tes.TIDMADEpochDataset(
        data_dir=tiny["data_dir"],
        sample_set=tiny["sample_set"],
        seg_size=SEG_SIZE,
        train_portion=1.0,
        profile=tiny["profile"],
        max_samples=max_samples,
    )


# ---------------------------------------------------------------------
# The epoch is smaller, not merely stopped early
# ---------------------------------------------------------------------


def test_the_unbounded_epoch_loads_the_whole_scope(tiny_dataset):
    """The baseline every bounded assertion below is measured against.

    Without it, a ceiling test could pass because the fixture never held
    that much data, and the ceiling would be credited with a cut nothing
    caused.
    """
    assert len(_dataset(tiny_dataset)) == TOTAL_SEGMENTS


def test_the_ceiling_cuts_the_epoch_to_exactly_its_value(tiny_dataset):
    """THE property, at ML-segment granularity.

    Exactness matters: the Gate predicts its own step count from this
    number before launch, so a ceiling that only cut to the nearest PSD
    segment would leave the prediction wrong by up to
    ``psd_segment_length // seg_size`` segments — 10,000 of them at the
    seg_size the planner chose during Step 03.

    Fails when: the final slice is dropped and the cut lands on a PSD
    boundary instead.
    """
    assert len(_dataset(tiny_dataset, max_samples=13)) == 13


def test_the_ceiling_stops_data_being_read_at_all(tiny_dataset, monkeypatch):
    """The cost has to be AVOIDED, not discarded.

    A ceiling applied only to the finished arrays would still pay every
    HDF5 read and every byte of RAM — on a real scope that is minutes and
    gigabytes, which is most of what makes an unbounded Gate expensive.

    So this counts actual ``h5py.File`` opens. An earlier version of this
    test asserted on ``file_row_ranges`` instead and PASSED with the
    read-budget deleted: the post-hoc range clip hid the extra read
    entirely. Counting the reads is the only thing that distinguishes
    "loaded less" from "loaded everything and threw some away".

    Fails when: the per-file budget or the early break is removed.
    """
    opened: list[str] = []
    real_open = tes.h5py.File

    def counting_open(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(tes.h5py, "File", counting_open)

    unbounded = _dataset(tiny_dataset)
    bounded = _dataset(tiny_dataset, max_samples=ML_PER_PSD)

    assert len(bounded) == ML_PER_PSD
    # Cross-file: the second file is never opened.
    assert len(opened) == N_FILES + 1, f"opens: {opened}"
    # Within the first file: one PSD segment read, not all five. The row
    # count cannot show this — the post-hoc cut leaves ML_PER_PSD rows
    # either way — which is why the counter exists.
    assert unbounded.psd_segments_read == N_FILES * N_PSD_PER_FILE
    assert bounded.psd_segments_read == 1


def test_row_ranges_never_address_rows_that_were_cut_away(tiny_dataset):
    """Sequential ordering indexes rows THROUGH these ranges.

    A range extending past the cut would build a sampler pointing at rows
    that no longer exist — an IndexError deep inside the first epoch of a
    Gate run, i.e. exactly the "bounded run produced no evidence" failure
    in a new costume.

    Fails when: the ranges are left unclipped after the slice.
    """
    bounded = _dataset(tiny_dataset, max_samples=13)

    assert bounded.file_row_ranges
    for start, end in bounded.file_row_ranges.values():
        assert end <= len(bounded)
        assert start < end


def test_a_generous_ceiling_changes_nothing(tiny_dataset):
    """A maximum, never a target.

    Fails when: an off-by-one or inverted comparison starts truncating
    ordinary campaigns — the failure that would silently shorten real
    science if this ever escaped validation posture.
    """
    assert len(_dataset(tiny_dataset, max_samples=TOTAL_SEGMENTS * 10)) == TOTAL_SEGMENTS


def test_the_resolver_predicts_the_built_epoch_exactly(tiny_dataset):
    """The resolver's contract is to MIRROR production, not approximate it.

    A Gate decides before launch whether its workload is small enough,
    using ``resolve_training_workload``. If that diverges from what the
    trainer builds, the pre-launch check is fiction.

    Fails when: either side's ceiling arithmetic changes without the
    other's.
    """
    for ceiling in (7, 13, ML_PER_PSD, TOTAL_SEGMENTS * 10, None):
        built = len(_dataset(tiny_dataset, max_samples=ceiling))
        predicted = resolve_training_workload(
            tiny_dataset["sample_set"],
            seg_size=SEG_SIZE,
            profile=tiny_dataset["profile"],
            batch_size=1,
            train_portion=1.0,
            epochs=1,
            max_samples=ceiling,
        )
        assert predicted.detail["samples_per_epoch"] == built, f"ceiling={ceiling}"


# ---------------------------------------------------------------------
# End to end: a bounded run is still a real training run
# ---------------------------------------------------------------------


def test_a_bounded_run_still_trains_and_leaves_a_usable_checkpoint(tiny_dataset, tmp_path):
    """Gate 2's whole value is that inference and scoring run on a model
    training actually produced.

    An envelope that skipped the checkpoint, or left a NaN loss, would
    make the Gate an expensive no-op that still reported success.

    Fails when: the ceiling empties the epoch, breaks the end-of-epoch
    path, or the policy field stops reaching the dataset.
    """
    sandbox_dirs = {
        "models": str(tmp_path / "cached_models"),
        "results": str(tmp_path / "records"),
    }
    os.makedirs(sandbox_dirs["models"], exist_ok=True)
    session = RuntimeVerificationSession(
        str(tmp_path / "rv.json"),
        policy=RuntimeControlPolicy(validation_max_train_samples=8),
        attempt_id="exp_envelope",
    )

    summary = tes.run_experiment_streaming(
        WaveNetConfig(
            segmentation_size=SEG_SIZE,
            input_channels=4,
            residual_channels=8,
            gate_channels=8,
            skip_channels=8,
            kernel_size=2,
            num_blocks=1,
        ),
        TrainConfig(lr=1e-4, epochs=1, batch_size=2, optimizer_type="adam", device="cpu"),
        LossConfig(),
        sample_set=tiny_dataset["sample_set"],
        data_dir=tiny_dataset["data_dir"],
        sandbox_dirs=sandbox_dirs,
        exp_id="exp_envelope",
        runtime_session=session,
    )

    assert summary is not None
    assert np.isfinite(summary["final_loss"])
    assert os.path.exists(os.path.join(sandbox_dirs["models"], "_OK_exp_envelope"))


def test_the_policy_default_leaves_production_untouched():
    """Every production campaign must resolve to None.

    Fails when: a default is ever given to this field, which would put a
    workload ceiling on real science.
    """
    assert RuntimeControlPolicy().validation_max_train_samples is None


def test_the_policy_rejects_an_empty_envelope():
    """Zero samples is not a bounded training run, it is no training run.

    Fails when: the ge=1 bound is dropped and a Gate can be configured to
    execute nothing while still reporting that training ran.
    """
    with pytest.raises(ValueError):
        RuntimeControlPolicy(validation_max_train_samples=0)
