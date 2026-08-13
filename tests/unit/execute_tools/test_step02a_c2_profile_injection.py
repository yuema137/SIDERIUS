"""PR-02a commit C2 — Dataset Profile declaration and in-process injection.

Design:
``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md``
§6.2 (this commit), §5c (Regime-A), OD-02a-1 (import-time consumers).

Four distinct failure classes, not one test per migrated module:

1. **Declaration parity** — the shipped profile does not describe TIDMAD.
2. **Injection reachability** — a consumer keeps reading a module constant
   while the profile sits unused. This is §11.1's named failure class, "the
   beautiful profile consumed only by tests", and the ONE thing a
   parity-only suite cannot catch.
3. **Regime-A compatibility** — an existing caller that never heard of the
   profile stops resolving today's behaviour.
4. **Topology representability** — a declared file count other than 20 is
   rejected by a consumer, which would make Stage-B rung A1 impossible.

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
    TIDMAD,
    TIDMAD_PROFILE,
    ChannelIdentity,
    DatasetConfig,
    DatasetProfile,
    ValueEncoding,
    bind_dataset_profile,
    resolve_dataset_profile,
)
from nodes import scoring_reference


def _profile(**dataset_overrides) -> DatasetProfile:
    """TIDMAD with only the named dataset fields changed.

    Single-axis by construction, which is what the Stage-B rungs will need.
    """
    return TIDMAD_PROFILE.model_copy(
        update={"dataset": TIDMAD_PROFILE.dataset.model_copy(update=dataset_overrides)}
    )


# ---------------------------------------------------------------------------
# Class 1 — declaration parity
# ---------------------------------------------------------------------------


class TestDeclarationParity:
    def test_profile_carries_the_shipped_tidmad_dataset_unchanged(self):
        """The profile COMPOSES ``DatasetConfig`` rather than replacing it.

        If a future change inlined the fields into a new type instead, the
        Step-00 golden (``TIDMAD.model_dump()`` field by field) would be
        pinning an object the production path no longer reads.
        """
        assert TIDMAD_PROFILE.dataset is TIDMAD

    def test_declarations_match_the_literals_production_used(self):
        """Hardcoded expectations — the whole point is that these values
        used to live as literals at ~15 (channels) and ~8 (encoding)
        production sites with nothing tying them together."""
        assert TIDMAD_PROFILE.channels.input_channel == "channel0001"
        assert TIDMAD_PROFILE.channels.target_channel == "channel0002"
        assert TIDMAD_PROFILE.encoding.storage_dtype == "int8"
        assert TIDMAD_PROFILE.encoding.compute_dtype == "int16"
        assert TIDMAD_PROFILE.encoding.value_offset == 128
        assert TIDMAD_PROFILE.encoding.num_classes == 256


# ---------------------------------------------------------------------------
# Class 2 — injection reachability (the load-bearing one)
# ---------------------------------------------------------------------------


def _workload_ml_per_psd() -> int:
    """Geometry probe through the public training resolver."""
    resolved = workload_resolvers.resolve_training_workload(
        {"0": [0]}, seg_size=10, batch_size=1, train_portion=None, epochs=1
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

    A consumer that kept its module-level constant returns the TIDMAD-shaped
    answer under a contrast profile, and only these assertions notice.
    """

    def test_geometry_consumer_follows_the_declared_psd_length(self):
        # TIDMAD: 10,000,000 / 10 = 1,000,000 ML segments per PSD segment.
        assert _workload_ml_per_psd() == 1_000_000
        with bind_dataset_profile(_profile(psd_segment_length=1_000)):
            assert _workload_ml_per_psd() == 100

    @pytest.mark.parametrize(
        "probe",
        [_scoring_reference_indices, _sample_set_builder_file_count],
        ids=["scoring_reference", "sample_set_builder"],
    )
    def test_file_count_consumers_follow_the_declaration(self, probe):
        assert probe() == 20
        with bind_dataset_profile(_profile(num_files=7)):
            assert probe() == 7

    def test_segment_count_consumer_follows_the_declaration(self):
        assert _sample_set_builder_segments() == 200
        with bind_dataset_profile(_profile(segments_per_file=13)):
            assert _sample_set_builder_segments() == 13

    def test_binding_is_scoped_and_restores_on_exception(self):
        """A leaked contrast profile would surface as an unrelated failure in
        whatever test ran next — the reason binding is a ContextVar and not
        module state."""
        with pytest.raises(RuntimeError):
            with bind_dataset_profile(_profile(num_files=3)):
                assert resolve_dataset_profile().dataset.num_files == 3
                raise RuntimeError("boom")
        assert resolve_dataset_profile() is TIDMAD_PROFILE


# ---------------------------------------------------------------------------
# Class 3 — Regime-A compatibility
# ---------------------------------------------------------------------------


class TestRegimeACompatibility:
    def test_nothing_bound_resolves_the_shipped_tidmad_profile(self):
        """§5c: a caller that predates the transport must be unaffected.

        Distinct from "a supplied profile is broken", which fails closed —
        that rule arrives with the transport in C3.
        """
        assert resolve_dataset_profile() is TIDMAD_PROFILE

    def test_the_adapter_is_documented_as_an_adapter_at_the_code_site(self):
        """§6.2 acceptance: Regime-A semantics must be stated in code, not
        merely implied by a default value. A future reader who takes these
        for universal generic defaults is the failure this guards."""
        import inspect

        import execute_tools.dataset_config as dc

        source = inspect.getsource(dc)
        _, _, after = source.partition("TIDMAD_PROFILE = DatasetProfile(")
        preamble = source[: len(source) - len(after)]
        assert "REGIME-A COMPATIBILITY ADAPTER" in preamble
        assert "not a universal framework default" in preamble


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
        """The declaration must not smuggle TIDMAD in as a required default;
        every field is supplied here and none is TIDMAD's."""
        other = DatasetProfile(
            dataset=DatasetConfig(
                psd_segment_length=1_000,
                segments_per_file=4,
                num_files=3,
                sampling_frequency=50.0,
                training_file_pattern="run_{file_index:02d}.hdf5",
                validation_file_pattern="val_{file_index:02d}.hdf5",
            ),
            channels=ChannelIdentity(input_channel="raw", target_channel="clean"),
            encoding=ValueEncoding(
                storage_dtype="uint8",
                compute_dtype="int16",
                value_offset=0,
                num_classes=256,
            ),
            # Step 02c: the two task-owned file sets are REQUIRED and carry
            # no default, for exactly the reason this test exists — a
            # TIDMAD-shaped default would be smuggling. Note they are legal
            # against THIS dataset's num_files=3, not TIDMAD's 20.
            anchor_selection_files=[0, 2],
            health_peek_files=[1],
        )
        assert other.dataset.validation_file_name(2) == "val_02.hdf5"
        assert "abra" not in other.dataset.training_file_name(1)


# ---------------------------------------------------------------------------
# The validation-name seam gains its first production-shaped consumer
# ---------------------------------------------------------------------------


def test_validation_file_name_renders_from_the_declared_pattern():
    """``validation_file_pattern`` shipped with ZERO production consumers
    (roadmap §0.8). ``validation_file_name`` is its counterpart; C4 routes
    the scorer and inference read paths through it."""
    assert TIDMAD.validation_file_name(0) == "abra_validation_0000.h5"
    assert TIDMAD.validation_file_name(19) == "abra_validation_0019.h5"
    with bind_dataset_profile(_profile(validation_file_pattern="v_{file_index}.h5")):
        assert resolve_dataset_profile().dataset.validation_file_name(3) == "v_3.h5"


def test_selection_determinism_is_unchanged_by_the_migration():
    """SampleSet digests are a frozen parity surface.

    The builder now reads ``segments_per_file`` from the profile instead of a
    constant re-exported through ``scoring_utils``. Selection must be
    byte-identical; ``test_sample_set_builder.py``'s five sha16 digests are
    the authoritative oracle and run unmodified — this only guards the
    re-export collapse itself.
    """
    a = sample_set_builder.build_sample_set(
        is_trial=True, trial_strategy="snapshot", trial_portion=0.05, seed=42
    )
    b = sample_set_builder.build_sample_set(
        is_trial=True, trial_strategy="snapshot", trial_portion=0.05, seed=42
    )
    assert a == b
    assert len(a) == 20
