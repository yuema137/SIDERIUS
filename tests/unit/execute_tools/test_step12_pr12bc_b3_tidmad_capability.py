"""Step 12 / PR-12bc — B3: TIDMAD's scope capability + the differential oracle.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §M / B3; ledger §Q.B3.

TIDMAD implements the optional capability by **CALLING** ``build_sample_set``
— one authority, a relocated call, never a copy. The claim this module owns is
that the relocation changed nothing:

* **the differential oracle** — for every cell of
  ``(round_kind, strategy, portion, seed, subset)``, covering **trial AND
  formal**, the capability-built scope DEEP-EQUALS what the legacy path builds
  from the same inputs;
* **materialization parity** — a scope that has been serialized and read back
  produces the IDENTICAL visited sample sequence and step count as B0's
  recorded baseline, not merely the same config values;
* **canonical serialization** — asserted BYTE-wise, because the framework
  digests these bytes and two equal scopes that serialize differently would
  report a difference that does not exist;
* **fail-closed deserialization** — a foreign, truncated, malformed or
  wrong-kind payload RAISES naming what was wrong, and is never partially
  accepted.

The oracle's expected side comes from ``build_sample_set`` — a DIFFERENT code
path that this PR does not touch — never from a second call to the capability.
That is the §25 non-self-reference rule: the two sides must be independently
derived or the test proves only that the function is deterministic.
"""

from __future__ import annotations

import hashlib
import json

import h5py
import numpy as np
import pytest

from execute_tools.dataset_config import (
    NUM_FILES,
    SEGMENTS_PER_FILE,
    DataScope,
    bind_dataset_profile,
)
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.task_data_path import (
    EpochSamplingParams,
    ScopeBuildRequest,
    declares_scope_capability,
    resolve_task_scope_capability,
)
from execute_tools.tidmad_data_path import TidmadScope, TidmadTaskDataPath
from tests.unit.core.test_step12_pr12bc_b0_baselines import (
    SMALL_DATASET,
    SMALL_PROFILE,
    SMALL_SEG_SIZE,
)

IMPL = TidmadTaskDataPath()
SEG_SIZE = 10_000


def _request(**kw) -> ScopeBuildRequest:
    base = {
        "round_kind": "trial",
        "selection_strategy": "snapshot",
        "portion": 0.01,
        "seed": 7,
        "task_parameters": {"seg_size": SEG_SIZE},
    }
    base.update(kw)
    return ScopeBuildRequest(**base)


# ======================================================================
# The capability is declared and resolvable
# ======================================================================


class TestTidmadDeclaresTheCapability:
    def test_it_resolves_through_the_b1_authority(self):
        assert declares_scope_capability(IMPL) is True
        assert resolve_task_scope_capability(IMPL) is IMPL

    def test_build_sample_set_remains_the_only_selection_authority(self):
        """Census: the capability RELOCATES the call, it does not copy the
        selection logic. A second implementation of "which segments" is what
        would make the oracle below start passing for the wrong reason.
        """
        import pathlib

        src = pathlib.Path(
            pathlib.Path(__file__).resolve().parents[3] / "execute_tools" / "tidmad_data_path.py"
        ).read_text(encoding="utf-8")
        assert "build_sample_set(" in src
        for copied in ("rng.sample(", "random.Random(", "anchor_selection_files"):
            assert (
                copied not in src.split("def _build_scope")[1].split("def build_training_scope")[0]
            ), (
                f"{copied!r} appears inside _build_scope — the selection logic was COPIED, not called"
            )


# ======================================================================
# THE DIFFERENTIAL ORACLE
# ======================================================================

#: `(round_kind, strategy, portion, seed, subset_ref, target_partitions)`.
#: Trial AND formal are both present: today they differ only in VALUES
#: (`policy.py:1164-1179`), and the oracle exists so that stays true rather
#: than being assumed.
ORACLE_MATRIX = [
    ("trial", "snapshot", 0.01, 7, None, ()),
    ("trial", "snapshot", 0.1, 1234, None, ()),
    ("trial", "snapshot", 1.0, 0, None, ()),
    ("formal", "snapshot", 1.0, 99, None, ()),
    ("formal", "snapshot", 0.1, 4321, None, ()),
    ("trial", "anchors", 0.05, 11, None, ()),
    ("formal", "anchors", 0.5, 12, None, ()),
    ("trial", "target", 0.25, 13, None, (2, 5, 9)),
    ("formal", "target", 1.0, 14, None, (0,)),
    ("trial", "snapshot", 0.5, 21, "4-9", ()),
    ("formal", "snapshot", 1.0, 22, "0,1,2", ()),
]

#: ``seed=None`` is NOT in the oracle matrix, deliberately. ``build_sample_set``
#: documents it as non-deterministic, so two independent draws legitimately
#: differ and an equality oracle over them would be asserting the opposite of
#: the contract. Its own property is asserted below instead.


@pytest.mark.parametrize(
    ("round_kind", "strategy", "portion", "seed", "subset", "targets"), ORACLE_MATRIX
)
class TestTheCompositionVsLegacyDifferentialOracle:
    def test_the_capability_builds_the_legacy_scope_exactly(
        self, round_kind, strategy, portion, seed, subset, targets
    ):
        """Expected side = ``build_sample_set``, an independent path."""
        built = IMPL.build_training_scope(
            _request(
                round_kind=round_kind,
                selection_strategy=strategy,
                portion=portion,
                seed=seed,
                subset_ref=subset,
                target_partitions=targets,
            )
        )
        legacy = build_sample_set(
            is_trial=True,
            trial_strategy=strategy,
            trial_portion=portion,
            target_files=list(targets) or None,
            seed=seed,
            scope=DataScope.from_cli(subset) if subset else None,
        )
        assert isinstance(built, TidmadScope)
        assert built.sample_set == legacy
        assert built.seg_size == SEG_SIZE

    def test_the_eval_leg_agrees_with_the_training_leg_for_identical_inputs(
        self, round_kind, strategy, portion, seed, subset, targets
    ):
        """The two legs differ by the VALUES the caller supplies, never by a
        different construction path — which is why they are two methods over
        one request rather than one method with a ``leg`` flag.
        """
        req = _request(
            round_kind=round_kind,
            selection_strategy=strategy,
            portion=portion,
            seed=seed,
            subset_ref=subset,
            target_partitions=targets,
        )
        assert IMPL.build_eval_scope(req) == IMPL.build_training_scope(req)

    def test_every_cell_round_trips_through_canonical_bytes(
        self, round_kind, strategy, portion, seed, subset, targets
    ):
        built = IMPL.build_training_scope(
            _request(
                round_kind=round_kind,
                selection_strategy=strategy,
                portion=portion,
                seed=seed,
                subset_ref=subset,
                target_partitions=targets,
            )
        )
        assert IMPL.deserialize_scope(IMPL.serialize_scope(built)) == built


class TestTheUnseededDrawKeepsItsContract:
    """``seed=None`` stays non-deterministic — and stays well-formed.

    Excluded from the oracle because equality is the wrong claim for it. What
    IS claimed: the capability does not quietly substitute a default seed
    (which would make every unseeded attempt identical and look like
    reproducibility), and the shape still obeys the declared topology.
    """

    def test_it_does_not_acquire_a_hidden_default_seed(self):
        draws = {
            json.dumps(
                IMPL.build_training_scope(_request(portion=0.05, seed=None)).sample_set,
                sort_keys=True,
            )
            for _ in range(8)
        }
        assert len(draws) > 1, (
            "eight unseeded draws were identical — the capability substituted a "
            "seed somewhere, which would make an unseeded attempt look "
            "reproducible when the contract says it is not"
        )

    def test_the_unseeded_draw_still_obeys_the_declared_topology(self):
        built = IMPL.build_training_scope(_request(portion=0.05, seed=None))
        assert sorted(built.sample_set) == list(range(NUM_FILES))
        assert all(len(v) == round(0.05 * SEGMENTS_PER_FILE) for v in built.sample_set.values())


# ======================================================================
# Canonical serialization
# ======================================================================


class TestSerializationIsCanonical:
    def test_the_bytes_are_stable_regardless_of_dict_ordering(self):
        """Two EQUAL scopes must produce identical bytes, or the digest chain
        reports a difference that does not exist. Built from dicts inserted in
        opposite orders so insertion order is genuinely different.
        """
        a = TidmadScope(sample_set={1: [0, 2], 5: [3]}, seg_size=SEG_SIZE)
        b = TidmadScope(sample_set={5: [3], 1: [0, 2]}, seg_size=SEG_SIZE)
        assert IMPL.serialize_scope(a) == IMPL.serialize_scope(b)

    def test_the_form_is_compact_and_key_sorted(self):
        """Pins the wire form itself, not merely site agreement: an ``indent=``
        added to a shared pattern would keep two sites equal while changing
        every byte the digest covers.
        """
        payload = IMPL.serialize_scope(TidmadScope(sample_set={2: [1]}, seg_size=64))
        assert payload == (
            '{"kind":"tidmad_scope_v1","profile":null,"sample_set":{"2":[1]},"seg_size":64}'
        )

    def test_sample_set_keys_survive_the_string_round_trip(self):
        """JSON has no integer keys, and ``tidmad_data_path.py:375`` already
        does ``int(k)``. Key-type drift would silently change what the loader
        visits, so the round trip is asserted on the INT form.
        """
        scope = TidmadScope(sample_set={0: [1], 13: [2, 3]}, seg_size=SEG_SIZE)
        back = IMPL.deserialize_scope(IMPL.serialize_scope(scope))
        assert back.sample_set == {0: [1], 13: [2, 3]}
        assert all(isinstance(k, int) for k in back.sample_set)

    def test_the_profile_identity_survives(self):
        """A scope that lost its profile would materialize against whatever
        was ambient — the exact defect the explicit-profile work removed.
        """
        scope = TidmadScope(sample_set={0: [0]}, seg_size=SMALL_SEG_SIZE, profile=SMALL_PROFILE)
        back = IMPL.deserialize_scope(IMPL.serialize_scope(scope))
        assert back.profile == SMALL_PROFILE
        assert back.profile.partition_count == SMALL_DATASET.num_files


# ======================================================================
# Fail-closed deserialization
# ======================================================================


class TestDeserializationFailsClosed:
    def test_a_foreign_scope_payload_is_refused_by_KIND(self):
        """Named by kind, not by whichever field happens to be missing
        first — a Pets payload and a truncated TIDMAD payload are different
        problems and must read differently.
        """
        foreign = json.dumps({"kind": "pets_scope_v1", "rows": [1, 2, 3]})
        with pytest.raises(ValueError, match="declares kind 'pets_scope_v1'"):
            IMPL.deserialize_scope(foreign)

    def test_an_untagged_payload_is_refused(self):
        with pytest.raises(ValueError, match="declares kind None"):
            IMPL.deserialize_scope(json.dumps({"sample_set": {"0": [0]}, "seg_size": 10}))

    @pytest.mark.parametrize("missing", ["sample_set", "seg_size"])
    def test_a_truncated_payload_names_what_is_missing(self, missing):
        payload = {"kind": "tidmad_scope_v1", "sample_set": {"0": [0]}, "seg_size": 10}
        del payload[missing]
        with pytest.raises(ValueError, match=f"missing \\['{missing}'\\]"):
            IMPL.deserialize_scope(json.dumps(payload))

    def test_non_json_is_refused(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            IMPL.deserialize_scope("{not json")

    def test_a_json_scalar_is_refused(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            IMPL.deserialize_scope("42")

    def test_a_malformed_field_is_refused_rather_than_coerced(self):
        payload = json.dumps(
            {"kind": "tidmad_scope_v1", "sample_set": {"nope": [0]}, "seg_size": 10}
        )
        with pytest.raises(ValueError, match="malformed"):
            IMPL.deserialize_scope(payload)

    def test_a_seg_size_of_zero_is_refused(self):
        """``TidmadScope`` declares ``ge=1``; a zero would divide by zero deep
        inside materialization instead.
        """
        payload = json.dumps({"kind": "tidmad_scope_v1", "sample_set": {"0": [0]}, "seg_size": 0})
        with pytest.raises(ValueError, match="malformed"):
            IMPL.deserialize_scope(payload)


class TestScopeConstructionFailsClosed:
    def test_a_missing_seg_size_is_refused_by_name(self):
        """The framework has no vocabulary for ``seg_size``, so it rides the
        opaque per-attempt payload — and its absence must be a named refusal,
        never a guessed default.
        """
        with pytest.raises(ValueError, match="requires a positive 'seg_size'"):
            IMPL.build_training_scope(
                ScopeBuildRequest(round_kind="trial", selection_strategy="snapshot", portion=0.1)
            )

    @pytest.mark.parametrize("bad", [0, -1, "10000", 1.5, None])
    def test_a_nonsense_seg_size_is_refused(self, bad):
        with pytest.raises(ValueError, match="requires a positive 'seg_size'"):
            IMPL.build_training_scope(_request(task_parameters={"seg_size": bad}))

    def test_a_partial_subset_still_refuses_a_non_snapshot_strategy(self):
        """The framework legality rule `build_sample_set` owns
        (``sample_set_builder.py:96-102``) reaches through the capability
        unchanged — the capability relocates the call, it does not soften it.
        """
        with pytest.raises(ValueError, match="not allowed under a partial DataScope"):
            IMPL.build_training_scope(_request(selection_strategy="anchors", subset_ref="4-9"))


# ======================================================================
# Materialization parity against B0's recorded baseline
# ======================================================================


@pytest.fixture
def small_data_dir(tmp_path):
    """The same synthetic topology B0 recorded its digests against."""
    root = tmp_path / "small_data"
    root.mkdir()
    n = SMALL_DATASET.segments_per_file * SMALL_DATASET.psd_segment_length
    for fi in range(SMALL_DATASET.num_files):
        idx = np.arange(n, dtype=np.int64)
        ch1 = ((fi * 1000 + idx) % 251 - 125).astype(np.int8)
        ch2 = ((fi * 1000 + idx * 7) % 251 - 125).astype(np.int8)
        with h5py.File(root / SMALL_DATASET.training_file_name(fi), "w") as f:
            f.create_dataset("timeseries/channel0001/timeseries", data=ch1)
            f.create_dataset("timeseries/channel0002/timeseries", data=ch2)
    return str(root)


class TestARoundTrippedScopeMaterializesIdentically:
    def test_it_reproduces_B0s_recorded_digests(self, small_data_dir):
        """Config-value equality is not enough. Key-type drift, a reordered
        file loop or a differently-derived seed all leave the config identical
        and change what the model sees, so the assertion is on the visited
        ROWS — the exact digests B0 recorded (design §Q.B0.2) before any of
        this existed.
        """
        with bind_dataset_profile(SMALL_PROFILE):
            built = IMPL.build_training_scope(
                _request(
                    selection_strategy="snapshot",
                    portion=0.4,
                    seed=1234,
                    task_parameters={"seg_size": SMALL_SEG_SIZE},
                )
            )
        assert built.sample_set == {0: [0, 3], 1: [0, 4], 2: [0, 4]}

        round_tripped = IMPL.deserialize_scope(IMPL.serialize_scope(built))
        ds = IMPL.training_dataset(
            round_tripped,
            EpochSamplingParams(data_dir=small_data_dir, epoch_seed=7, train_portion=1.0),
        )
        assert len(ds) == 24
        assert ds.psd_segments_read == 6
        assert {k: list(v) for k, v in ds.file_row_ranges.items()} == {
            0: [0, 8],
            1: [8, 16],
            2: [16, 24],
        }
        assert (
            hashlib.sha256(ds.inputs.tobytes()).hexdigest()
            == "6c08bbb24f4f5758000ae7150223aeca0c7a86394d5c55a2c75c2fbf32bbd83d"
        )
        assert (
            hashlib.sha256(ds.targets.tobytes()).hexdigest()
            == "6d79caf18802dd6467f97cc8add010546d02b19bd80d4127fc0726cf30fca76a"
        )
