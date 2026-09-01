"""PR-02a commit C2 — Dataset Profile declaration and in-process injection.

Design:
``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md``
§6.2 (this commit), §5c (Regime-A), OD-02a-1 (import-time consumers).

Three distinct failure classes, not one test per migrated module:

1. **Injection reachability** — a consumer keeps reading a module constant
   while the profile sits unused. This is §11.1's named failure class, "the
   beautiful profile consumed only by tests", and the ONE thing a
   parity-only suite cannot catch.
2. **Topology representability** — a changed partition count is rejected by a
   consumer, which would make an external task profile unusable.
3. **Declaration validation** — semantic relationships that field types alone
   cannot express remain enforced.

Class 2 is parametrized over the migrated consumers deliberately: it is ONE
concept ("this consumer follows the declaration"), and the per-module shape
cannot express it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.score_table import PerFileRow
from execute_tools import sample_set_builder, workload_resolvers
from execute_tools.dataset_config import (
    ChannelIdentity,
    DatasetConfig,
    DatasetProfile,
    ValueEncoding,
    bind_dataset_profile,
    resolve_dataset_profile,
)
from nodes import scoring_reference

BASE_DATASET = DatasetConfig(
    psd_segment_length=1_000,
    segments_per_file=13,
    num_files=7,
    sampling_frequency=50.0,
    training_file_pattern="training_{file_index:02d}.h5",
    validation_file_pattern="validation_{file_index:02d}.h5",
)
BASE_PROFILE = DatasetProfile(
    dataset=BASE_DATASET,
    channels=ChannelIdentity(input_channel="input", target_channel="target"),
    encoding=ValueEncoding(
        storage_dtype="uint8",
        compute_dtype="int16",
        value_offset=0,
        num_classes=256,
    ),
    anchor_selection_files=[0, 3, 6],
    health_peek_files=[1, 5],
)


def _profile(**dataset_overrides) -> DatasetProfile:
    """Return the neutral profile with only named geometry changed.

    Single-axis construction makes a stale consumer observable.
    """
    return BASE_PROFILE.model_copy(
        update={"dataset": BASE_DATASET.model_copy(update=dataset_overrides)}
    )


# ---------------------------------------------------------------------------
# Class 2 — injection reachability (the load-bearing one)
# ---------------------------------------------------------------------------


def _workload_ml_per_psd() -> int:
    """Geometry probe through the public training resolver.

    Step 05b made ``profile`` a required argument, so this probe now RESOLVES
    the currently bound declaration and passes it, instead of letting the
    resolver reach for it. The property under test is unchanged — a consumer
    that kept a module constant still returns the base-profile answer under a
    contrast binding — and the acquisition is now where 05b puts it: at the
    caller, once, explicitly.
    """
    resolved = workload_resolvers.resolve_training_workload(
        {"0": [0]},
        seg_size=10,
        batch_size=1,
        train_portion=None,
        epochs=1,
        profile=resolve_dataset_profile(),
    )
    return resolved.detail["ml_segments_per_psd"]


def _sample_set_builder_file_count() -> int:
    """File-count probe: a full-portion snapshot covers every declared file."""
    return len(
        sample_set_builder.build_sample_set(
            is_trial=True, trial_strategy="snapshot", trial_portion=1.0, seed=42
        )
    )


def _sample_set_builder_segments() -> int:
    """Segments-per-file probe through the normal-mode builder."""
    return len(sample_set_builder.build_sample_set(is_trial=False, file_index=0)[0])


def _scoring_reference_indices() -> int:
    return len(scoring_reference._fine_indices())


class TestInjectionReachability:
    """Each migrated consumer must FOLLOW a bound declaration.

    A consumer that kept its module-level constant returns the base-profile
    answer under a contrast profile, and only these assertions notice.
    """

    def test_geometry_consumer_follows_the_declared_psd_length(self):
        with bind_dataset_profile(BASE_PROFILE):
            assert _workload_ml_per_psd() == 100
        with bind_dataset_profile(_profile(psd_segment_length=2_000)):
            assert _workload_ml_per_psd() == 200

    @pytest.mark.parametrize(
        "probe",
        [_scoring_reference_indices, _sample_set_builder_file_count],
        ids=["scoring_reference", "sample_set_builder"],
    )
    def test_file_count_consumers_follow_the_declaration(self, probe):
        with bind_dataset_profile(BASE_PROFILE):
            assert probe() == 7
        with bind_dataset_profile(_profile(num_files=4)):
            assert probe() == 4

    def test_segment_count_consumer_follows_the_declaration(self):
        with bind_dataset_profile(BASE_PROFILE):
            assert _sample_set_builder_segments() == 13
        with bind_dataset_profile(_profile(segments_per_file=5)):
            assert _sample_set_builder_segments() == 5

    def test_binding_is_scoped_and_restores_on_exception(self):
        """A leaked contrast profile would surface as an unrelated failure in
        whatever test ran next — the reason binding is a ContextVar and not
        module state."""
        with bind_dataset_profile(BASE_PROFILE):
            with pytest.raises(RuntimeError):
                with bind_dataset_profile(_profile(num_files=3)):
                    assert resolve_dataset_profile().partition_count == 3
                    raise RuntimeError("boom")
            assert resolve_dataset_profile() is BASE_PROFILE

    def test_an_unbound_profile_refuses_instead_of_selecting_task_science(self):
        """A missing composition must not silently select task topology."""
        from execute_tools.dataset_config import DatasetProfileBindingError

        with pytest.raises(DatasetProfileBindingError, match="no dataset profile is bound"):
            resolve_dataset_profile()


# ---------------------------------------------------------------------------
# Class 4 — topology representability (what makes rung A1 possible)
# ---------------------------------------------------------------------------


class TestTopologyRepresentability:
    """OD-02a-1: the score-table bounds moved from import-time constraints to
    profile-resolved validators.

    ``test_score_table_adversarial.py`` covers the REJECTION direction. What
    is new here is the ACCEPTANCE direction under a different topology —
    previously impossible, and a precondition for Stage-B rung A1.
    """

    def test_a_file_index_legal_only_under_a_contrast_topology_is_accepted(self):
        with bind_dataset_profile(BASE_PROFILE):
            with pytest.raises(ValidationError, match="outside the declared topology"):
                PerFileRow(
                    file_index=25,
                    raw_baseline=None,
                    ground_truth=None,
                    model=None,
                    gain_vs_raw=None,
                    headroom_vs_gt=None,
                )
        with bind_dataset_profile(_profile(num_files=30)):
            row = PerFileRow(
                file_index=25,
                raw_baseline=None,
                ground_truth=None,
                model=None,
                gain_vs_raw=None,
                headroom_vs_gt=None,
            )
        assert row.file_index == 25


# ---------------------------------------------------------------------------
# Declaration validators — rules a Field constraint cannot express
# ---------------------------------------------------------------------------


class TestDeclarationValidators:
    def test_input_and_target_channel_must_differ(self):
        """An identical pair trains a model to predict its own input and
        scores it against itself — a plausible run with meaningless results
        and no error anywhere."""
        with pytest.raises(ValueError, match="must differ from the input channel"):
            ChannelIdentity(input_channel="ch", target_channel="ch")

    def test_alphabet_must_cover_the_shifted_dtype_range(self):
        """A too-small ``num_classes`` silently truncates the class
        histogram, which reweights the loss rather than raising."""
        with pytest.raises(ValueError, match=r"cannot hold int8 shifted by 128"):
            ValueEncoding(
                storage_dtype="int8",
                compute_dtype="int16",
                value_offset=128,
                num_classes=200,
            )

    def test_a_profile_is_constructible_for_a_wholly_different_dataset(self):
        """The declaration must not smuggle in a required task default;
        every field is supplied explicitly."""
        dataset = DatasetConfig(
            psd_segment_length=2_000,
            segments_per_file=4,
            num_files=3,
            sampling_frequency=25.0,
            training_file_pattern="run_{file_index:02d}.hdf5",
            validation_file_pattern="val_{file_index:02d}.hdf5",
        )
        other = DatasetProfile(
            dataset=dataset,
            channels=ChannelIdentity(input_channel="raw", target_channel="clean"),
            encoding=ValueEncoding(
                storage_dtype="uint8",
                compute_dtype="int16",
                value_offset=0,
                num_classes=256,
            ),
            # Step 02c: the two task-owned file sets are REQUIRED and carry
            # no default, for exactly the reason this test exists — a
            # task-shaped default would be smuggling. These indices are legal
            # against this dataset's three-partition domain.
            anchor_selection_files=[0, 2],
            health_peek_files=[1],
        )
        assert dataset.validation_file_name(2) == "val_02.hdf5"
        assert dataset.training_file_name(1) == "run_01.hdf5"
        # B2: the GENERIC identity is what the framework reads, and it
        # followed the declaration rather than a built-in partition count.
        assert other.partition_count == 3


# ---------------------------------------------------------------------------
# The validation-name seam gains its first production-shaped consumer
# ---------------------------------------------------------------------------


def test_validation_file_name_renders_from_the_declared_pattern():
    """``validation_file_pattern`` shipped with ZERO production consumers
    (roadmap §0.8). ``validation_file_name`` is its counterpart; C4 routes
    the scorer and inference read paths through it."""
    assert BASE_DATASET.validation_file_name(0) == "validation_00.h5"
    assert BASE_DATASET.validation_file_name(6) == "validation_06.h5"
    changed = BASE_DATASET.model_copy(
        update={"validation_file_pattern": "held_out_{file_index}.h5"}
    )
    assert changed.validation_file_name(3) == "held_out_3.h5"
