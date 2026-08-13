"""PR-02a commit C6 — Stage-B atomic contrast rungs A1 / A2 / B / D.

Design:
``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md``
§6.6; parent §8 (the required ladder, atomicity binding).

Stage A proved TIDMAD parity. That is necessary and not sufficient: moving
strings into a config proves nothing on its own. These rungs prove the
abstraction actually VARIES with the declaration.

**What makes these distinct from the C2-C4 tests.** Those proved
per-consumer reachability — this module's consumer read the profile. A rung
is a different claim: ONE axis changes, everything else is held at TIDMAD,
and the whole resolved path follows together. A failing rung therefore
names which abstraction failed, which is the entire point of an atomic
ladder.

**Atomicity is machine-checked, not asserted in prose.** ``_assert_atomic``
diffs the rung's ``model_dump()`` against TIDMAD's and requires the changed
keys to be exactly the declared axis. Parent §8 makes atomicity binding and
specifically forbids A1 or A2 from touching geometry, encoding or channels;
a comment promising that would not survive a careless edit, and this does.
"""

from __future__ import annotations

import h5py
import numpy as np
import pytest

import execute_tools.scoring_utils as su
import execute_tools.train_engine_sandbox as tes
from execute_tools.dataset_config import (
    TIDMAD_PROFILE,
    ChannelIdentity,
    DatasetProfile,
)

SEG_SIZE = 8


# ---------------------------------------------------------------------------
# Atomicity machinery
# ---------------------------------------------------------------------------


def _flatten(dump: dict, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in dump.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{path}."))
        else:
            out[path] = value
    return out


def _changed_axes(profile: DatasetProfile) -> set[str]:
    base = _flatten(TIDMAD_PROFILE.model_dump())
    other = _flatten(profile.model_dump())
    assert base.keys() == other.keys(), "a rung must not add or drop declaration fields"
    return {k for k in base if base[k] != other[k]}


def _assert_atomic(profile: DatasetProfile, expected: set[str]) -> None:
    """The rung differs from TIDMAD in EXACTLY the named fields."""
    actual = _changed_axes(profile)
    assert actual == expected, (
        f"rung is not atomic: expected to vary {sorted(expected)}, actually varies {sorted(actual)}"
    )


def _vary_dataset(**fields) -> DatasetProfile:
    return TIDMAD_PROFILE.model_copy(
        update={"dataset": TIDMAD_PROFILE.dataset.model_copy(update=fields)}
    )


# ---------------------------------------------------------------------------
# Shared fixture: a file written to whatever the rung declares
# ---------------------------------------------------------------------------


def _write(tmp_path, profile: DatasetProfile, file_index: int):
    """Write one training file exactly as the DECLARATION describes it."""
    dataset, channels, enc = profile.dataset, profile.channels, profile.encoding
    n = dataset.psd_segment_length
    payload_in = (np.arange(n, dtype=np.int64) % 251 - 125).astype(enc.storage_dtype)
    payload_tg = ((np.arange(n, dtype=np.int64) * 7) % 251 - 125).astype(enc.storage_dtype)
    with h5py.File(tmp_path / dataset.training_file_name(file_index), "w") as f:
        ts = f.create_group("timeseries")
        ts.create_group(channels.input_channel).create_dataset("timeseries", data=payload_in)
        ts.create_group(channels.target_channel).create_dataset("timeseries", data=payload_tg)
    return payload_in, payload_tg


@pytest.fixture
def captured_raw_name(monkeypatch):
    """The raw validation filename the REAL scorer resolves."""
    seen: list[str] = []

    def fake_psd(file_path, files, ch, start=0):
        if ch == 2:
            seen.append(files)
        return np.zeros(4), np.zeros(4)

    monkeypatch.setattr(su, "get_one_sec_psd", fake_psd)
    monkeypatch.setattr(su, "get_snr", lambda freq, pwr, target=None: (1.0, 1.0))
    return seen


def _score_one(profile: DatasetProfile, file_index: int):
    su.score_vector(
        data_dir=".",
        sample_set={file_index: [0]},
        anchor_map={str(file_index): [1.0]},
        s_max=1.0,
        denoised_filename_fn=lambda fi: "denoised.h5",
        raw_data_dir=".",
        parallel=False,
        profile=profile,
    )


# ---------------------------------------------------------------------------
# RUNG A1 — file count / index space ONLY
# ---------------------------------------------------------------------------


class TestRungA1FileCount:
    """``num_files`` != 20. Family structure and geometry UNCHANGED.

    Isolating count from family shape is what lets a failure name one cause;
    revision 1's combined 4.8-A could not.
    """

    PROFILE = _vary_dataset(num_files=3)

    def test_the_rung_is_atomic(self):
        _assert_atomic(self.PROFILE, {"dataset.num_files"})

    def test_the_index_space_follows_the_declaration(self):
        from execute_tools.dataset_config import DataScope

        assert DataScope.default().resolve(self.PROFILE.dataset) == [0, 1, 2]

    def test_an_index_outside_the_declared_count_is_rejected(self):
        from execute_tools.dataset_config import DataScope

        with pytest.raises(ValueError, match="out of range"):
            DataScope(file_indices=[5]).resolve(self.PROFILE.dataset)

    def test_a_count_dependent_consumer_follows(self):
        """The score table's row rule is the consumer OD-02a-1 unblocked:
        with the old import-time bound this topology was unrepresentable."""
        from agent.schemas.score_table import PerFileRow
        from execute_tools.dataset_config import bind_dataset_profile

        with bind_dataset_profile(self.PROFILE):
            PerFileRow(
                file_index=2,
                raw_baseline=None,
                ground_truth=None,
                model=None,
                gain_vs_raw=None,
                headroom_vs_gt=None,
            )
            with pytest.raises(Exception, match="outside the declared topology"):
                PerFileRow(
                    file_index=3,
                    raw_baseline=None,
                    ground_truth=None,
                    model=None,
                    gain_vs_raw=None,
                    headroom_vs_gt=None,
                )


# ---------------------------------------------------------------------------
# RUNG A2 — file-family topology ONLY
# ---------------------------------------------------------------------------


class TestRungA2FamilyTopology:
    """Family STRUCTURE varies; count and geometry held at A1's baseline.

    TIDMAD has two parallel families — ``abra_training_*`` and
    ``abra_validation_*`` — one index space across both. This rung declares a
    single-family dataset where one physical family serves both roles, which
    is the shape a task with no separate validation corpus would have.

    Permitted to build on A1's proven baseline (parent §8, "a later rung may
    build on a proven earlier rung"), so it varies family structure ALONE
    relative to A1 — hence the atomicity assertion names A1's count too.
    """

    PROFILE = _vary_dataset(
        num_files=3,
        training_file_pattern="corpus_{file_index:02d}.h5",
        validation_file_pattern="corpus_{file_index:02d}.h5",
    )

    def test_the_rung_is_atomic_relative_to_a1(self):
        _assert_atomic(
            self.PROFILE,
            {
                "dataset.num_files",  # A1's established baseline
                "dataset.training_file_pattern",
                "dataset.validation_file_pattern",
            },
        )

    def test_geometry_encoding_and_channels_are_untouched(self):
        """Parent §8 forbids A1/A2 from touching these. Stated as an
        assertion because the prohibition is binding."""
        assert self.PROFILE.dataset.psd_segment_length == 10_000_000
        assert self.PROFILE.dataset.segments_per_file == 200
        assert self.PROFILE.channels == TIDMAD_PROFILE.channels
        assert self.PROFILE.encoding == TIDMAD_PROFILE.encoding

    def test_a_single_family_resolves_both_roles_to_one_file(self):
        """The load-bearing claim: nothing assumes two distinct families."""
        dataset = self.PROFILE.dataset
        assert dataset.training_file_name(1) == "corpus_01.h5"
        assert dataset.validation_file_name(1) == "corpus_01.h5"

    def test_the_training_loader_resolves_the_declared_family(self, tmp_path, capsys):
        tes.TIDMADDataset(
            str(tmp_path),
            [],
            segmentation_size=SEG_SIZE,
            sample_set={"1": [0]},
            profile=self.PROFILE,
        )
        out = capsys.readouterr().out
        assert "corpus_01.h5" in out
        assert "abra_" not in out

    def test_the_scorer_resolves_the_declared_family(self, captured_raw_name):
        _score_one(self.PROFILE, file_index=1)
        assert captured_raw_name == ["corpus_01.h5"]


# ---------------------------------------------------------------------------
# RUNG B — sample decomposition geometry ONLY
# ---------------------------------------------------------------------------


class TestRungBGeometry:
    """``psd_segment_length`` != 10,000,000, every other axis fixed.

    §8 promoted this from deferred to REQUIRED, and the reason is exactly
    what this rung tests: Step 00 froze the 36-divisor list under TIDMAD's
    10M, which proves the helper still behaves — and proves NOTHING about
    whether consumers stop assuming 10M when the profile says otherwise.
    """

    PSD = 2048
    PROFILE = _vary_dataset(psd_segment_length=PSD)

    def test_the_rung_is_atomic(self):
        _assert_atomic(self.PROFILE, {"dataset.psd_segment_length"})

    def test_the_legality_rule_follows_the_declared_geometry(self):
        """The divisors of 2048 in [100, 100_000] are not the divisors of
        10,000,000 — a consumer holding the frozen 36-entry list would be
        offering illegal sizes."""
        legal = self.PROFILE.dataset.valid_segmentation_sizes()
        assert legal == [128, 256, 512, 1024, 2048]
        assert legal != TIDMAD_PROFILE.dataset.valid_segmentation_sizes()
        for size in legal:
            assert self.PSD % size == 0

    def test_the_training_loader_decomposes_by_the_declaration(self, tmp_path):
        """A loader still assuming 10,000,000 cannot reshape this file."""
        _write(tmp_path, self.PROFILE, 4)
        dataset = tes.TIDMADDataset(
            str(tmp_path),
            [],
            segmentation_size=256,
            sample_set={"4": [0]},
            profile=self.PROFILE,
        )
        assert len(dataset) == self.PSD // 256

    def test_the_workload_resolver_follows_the_declaration(self):
        from execute_tools import workload_resolvers

        resolved = workload_resolvers.resolve_training_workload(
            {"0": [0]},
            seg_size=256,
            batch_size=1,
            train_portion=None,
            epochs=1,
            profile=self.PROFILE,
        )
        assert resolved.detail["ml_segments_per_psd"] == self.PSD // 256

    def test_no_ten_million_literal_survives_in_the_migrated_consumers(self):
        """Mutation-equivalent guard: a consumer that re-hardcoded 10,000,000
        would pass every parity test and fail only here."""
        assert self.PROFILE.dataset.psd_segment_length != 10_000_000
        assert 10_000_000 not in set(self.PROFILE.dataset.valid_segmentation_sizes())


# ---------------------------------------------------------------------------
# RUNG D — channel identity ONLY
# ---------------------------------------------------------------------------


class TestRungDChannelIdentity:
    """TIDMAD shape, channels renamed.

    §1.6's correction in fixture form: which channel is input and which is
    truth was addressed by a hardcoded HDF5 path at ~15 production sites, so
    it looked like a model fact. It is a dataset fact, and this is the rung
    that proves the loaders now read the declaration.
    """

    PROFILE = TIDMAD_PROFILE.model_copy(
        update={
            "dataset": TIDMAD_PROFILE.dataset.model_copy(update={"psd_segment_length": 16}),
            "channels": ChannelIdentity(input_channel="adc_raw", target_channel="adc_truth"),
        }
    )

    def test_the_rung_varies_channels_plus_only_the_fixture_scale(self):
        """Geometry is shrunk purely so the fixture is 16 samples rather than
        10 million; it is declared here so atomicity stays machine-checked
        rather than quietly assumed."""
        _assert_atomic(
            self.PROFILE,
            {
                "dataset.psd_segment_length",
                "channels.input_channel",
                "channels.target_channel",
            },
        )
        assert self.PROFILE.encoding == TIDMAD_PROFILE.encoding

    def test_the_loader_reads_the_declared_channels(self, tmp_path):
        payload_in, payload_tg = _write(tmp_path, self.PROFILE, 4)
        dataset = tes.TIDMADDataset(
            str(tmp_path),
            [],
            segmentation_size=SEG_SIZE,
            sample_set={"4": [0]},
            profile=self.PROFILE,
        )
        fname = self.PROFILE.dataset.training_file_name(4)
        expected_in = payload_in.reshape(-1, SEG_SIZE)
        expected_tg = payload_tg.reshape(-1, SEG_SIZE)
        np.testing.assert_array_equal(dataset.idict[fname], expected_in)
        np.testing.assert_array_equal(dataset.tdict[fname], expected_tg)

    def test_a_loader_still_hardcoding_channel0001_would_fail(self, tmp_path):
        """The rung is only as strong as its ability to catch the old code.

        The fixture contains NO ``channel0001``/``channel0002`` group, so a
        loader that still addressed them raises KeyError rather than quietly
        passing — which is what makes this rung real evidence.
        """
        _write(tmp_path, self.PROFILE, 4)
        path = tmp_path / self.PROFILE.dataset.training_file_name(4)
        with h5py.File(path, "r") as handle:
            assert "channel0001" not in handle["timeseries"]
            assert "channel0002" not in handle["timeseries"]
            assert "adc_raw" in handle["timeseries"]

    def test_the_declaration_refuses_a_degenerate_channel_pair(self):
        """Renaming must not open the door to input == target."""
        with pytest.raises(ValueError, match="must differ from the input channel"):
            ChannelIdentity(input_channel="adc_raw", target_channel="adc_raw")
