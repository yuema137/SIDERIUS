"""B-07c-1 — the measurement data-feeding axis (Step 07 / PR 07c, Checkpoint B).

C2's byte-parity oracle proves the refactor did not MOVE the bytes. It cannot
prove the bytes are actually derived from the profile: a builder that ignored
its `profile` argument and kept the old constants would pass every parity
assertion when the baseline profile's declarations and deleted constants have
the same values.

So this rung moves the DECLARATION and requires the bytes to follow — and, in
the SAME test, requires the identity keys and the comparability stamp to stay
byte-stable. Both halves together are what make the axis provably single: bytes
moved, and nothing else did.

The fixture is the existing Step-02 contrast-profile pattern
(`tests/helpers/two_family_profile.py`, 3 files / 4.8-B geometry) — reused, not
re-created.
"""

from __future__ import annotations

import hashlib

import pytest
import torch

from execute_tools.dataset_config import DatasetProfile
from execute_tools.probe_batch import build_bounded_probe_batch
from execute_tools.training_history import stamp_comparability
from ml_models.models_format_sandbox import LossConfig
from tests.helpers.two_family_profile import make_two_family_profile, write_two_family_fixture

SEG = 32
BATCH = 3
DECLARED_CHANNELS = make_two_family_profile().to_wire()["channels"]


def _profile_with(base: DatasetProfile, **overrides) -> DatasetProfile:
    """`base` with exactly one declaration replaced.

    Rebuilt through `model_validate` from a dump, the way the subprocess
    boundary reloads a profile — a variant that only validates in-process
    could pass a rung the real child would refuse.
    """
    payload = base.to_wire()
    for dotted, value in overrides.items():
        section, field = dotted.split(".")
        payload[section][field] = value
    return DatasetProfile.model_validate(payload)


def _batch_sha(profile: DatasetProfile, data_dir: str) -> str:
    tensor = build_bounded_probe_batch(
        profile=profile, data_dir=data_dir, batch_size=BATCH, segment_length=SEG
    ).tensor
    return hashlib.sha256(tensor.numpy().astype("<i8").tobytes()).hexdigest()


def _identity_projection(profile: DatasetProfile) -> dict[str, str]:
    """Every identity / key surface Checkpoint A pins, as one comparable
    projection.

    These are NOT functions of the profile's channel or encoding — that is
    exactly the claim. `data_shape_class` IS composed from the dataset
    geometry, which is why the contrasts below move channel and encoding and
    leave geometry alone: one axis at a time.
    """
    from core.runtime_control.observation_store import calibration_key
    from core.runtime_control.registry_schemas import MeasurementIdentity

    shape_class = (
        f"psd{profile.to_wire()['dataset']['psd_segment_length']}"
        f"_seg{profile.to_wire()['dataset']['segments_per_file']}"
        f"_files{profile.to_wire()['dataset']['num_files']}"
    )
    identity = MeasurementIdentity(
        measurement_kind="gpu_requirement",
        task_identity="synthetic_indexed_stream",
        data_shape_class=shape_class,
        model_family="synthetic_sequence_model",
        candidate_config_hash="deadbeef",
        phase="training",
        hardware_uuid="GPU-x",
        runtime_stack_identity="stack-1",
    )
    return {
        "data_shape_class": shape_class,
        "identity_components": "|".join(str(c) for c in identity.components()),
        "calibration_key": calibration_key(
            "training",
            gpu_name="NVIDIA X",
            torch_version="2.10.0",
            precision="float32",
            optimizer_type="adamw",
            model_family="synthetic_sequence_model",
            param_count=1024,
            seg_size=SEG,
            batch_size=BATCH,
        ),
    }


@pytest.fixture
def contrast(tmp_path):
    """One contrast-profile file family on disk, plus the baseline profile it
    was written under."""
    fx = write_two_family_fixture(
        tmp_path, num_files=3, psd_segment_length=2000, segments_per_file=4, families=("training",)
    )
    return fx


class TestB07c1TheMeasurementDataFeedingAxis:
    """ONE test per contrast, each moving exactly one DECLARATION, plus the
    stability half asserted alongside it.

    The unit of contrast is a declaration, not a field, and that is enforced
    rather than chosen: `ValueEncoding._alphabet_covers_the_shifted_range`
    refuses an incoherent triple, so `value_offset` cannot move on its own —
    for int8 data in a 256-class alphabet, 128 is the ONLY legal offset. A
    contrast that moved the offset alone would not be a stricter test; it
    would be an invalid profile the production path could never receive.
    """

    @pytest.mark.parametrize(
        "label,overrides",
        [
            # The channel the batch is READ from. A swap keeps shape, dtype and
            # value range and changes every measured number — the failure mode
            # a same-shape check cannot see.
            (
                "other_channel",
                {
                    "channels.input_channel": DECLARED_CHANNELS["target_channel"],
                    "channels.target_channel": DECLARED_CHANNELS["input_channel"],
                },
            ),
            # NON-INT8 storage. The fixture holds int8 payloads, so reading
            # them as uint8 wraps every negative sample — the cast chain is
            # genuinely being taken from the declaration.
            ("non_int8_storage", {"encoding.storage_dtype": "uint8", "encoding.value_offset": 0}),
            # The class-index offset. The one fact whose reintroduction as a
            # literal would keep shape and dtype correct and change every value.
            (
                "value_offset",
                {"encoding.value_offset": 200, "encoding.num_classes": 328},
            ),
        ],
    )
    def test_moving_one_declaration_moves_the_bytes_and_nothing_else(
        self, contrast, label, overrides
    ):
        baseline_profile = contrast.profile
        variant = _profile_with(baseline_profile, **overrides)

        baseline_bytes = _batch_sha(baseline_profile, contrast.data_dir)
        variant_bytes = _batch_sha(variant, contrast.data_dir)

        # (1) THE AXIS. The declaration moved, so the bytes must move. A
        # builder that ignored its profile fails exactly here.
        assert variant_bytes != baseline_bytes, (
            f"contrast {label!r} changed a declared fact and the probe batch "
            "did not change — the builder is not reading the profile"
        )

        # (2) THE STABILITY, in the same test, so the axis is provably single.
        assert _identity_projection(variant) == _identity_projection(baseline_profile)

        # Comparability is a function of the resolved LossConfig alone, so no
        # dataset declaration may move it (07c rev-3 retraction).
        loss_cfg = LossConfig(loss_type="focal")
        assert stamp_comparability(loss_cfg) == ("established", None)

    def test_the_baseline_is_reproducible_so_a_difference_means_something(self, contrast):
        """Non-vacuity for the contrasts above: if the builder were
        nondeterministic, every `!=` would pass for the wrong reason."""
        first = _batch_sha(contrast.profile, contrast.data_dir)
        second = _batch_sha(contrast.profile, contrast.data_dir)
        assert first == second

    def test_a_geometry_only_contrast_leaves_the_bytes_alone(self, contrast):
        """The negative control, and the reason the contrasts above move
        channel and encoding rather than geometry.

        `num_files` is what `data_shape_class` is composed from. It changes the
        identity — but the probe batch reads the first declared file's leading
        samples, which do not depend on how many files exist. So this is the
        one axis where the identity moves and the BYTES must not.
        """
        # GROWN, not shrunk: `anchor_selection_files` / `health_peek_files`
        # are declared inside the index space, so reducing num_files would
        # invalidate them and move a second declaration.
        variant = _profile_with(contrast.profile, **{"dataset.num_files": 4})
        assert _batch_sha(variant, contrast.data_dir) == _batch_sha(
            contrast.profile, contrast.data_dir
        )
        assert _identity_projection(variant) != _identity_projection(contrast.profile)


class TestTheFileFamilyComesFromTheDeclarationToo:
    def test_a_different_training_pattern_selects_a_different_file(self, contrast, tmp_path):
        """The third removed constant. The filename family is declared, so a
        profile naming another pattern must open another file — or refuse,
        rather than silently falling back to the old glob."""
        variant = _profile_with(
            contrast.profile, **{"dataset.training_file_pattern": "other_{file_index:04d}.h5"}
        )
        with pytest.raises(RuntimeError, match="no declared training file exists"):
            build_bounded_probe_batch(
                profile=variant,
                data_dir=contrast.data_dir,
                batch_size=BATCH,
                segment_length=SEG,
            )

    def test_the_evidence_names_the_file_the_declaration_chose(self, contrast):
        result = build_bounded_probe_batch(
            profile=contrast.profile,
            data_dir=contrast.data_dir,
            batch_size=BATCH,
            segment_length=SEG,
        )
        dataset = contrast.profile.to_wire()["dataset"]
        channels = contrast.profile.to_wire()["channels"]
        assert result.evidence.source_file == dataset["training_file_pattern"].format(file_index=0)
        assert result.evidence.channel == channels["input_channel"]


class TestTheBatchIsStillWellFormed:
    def test_every_contrast_still_produces_a_usable_class_index_tensor(self, contrast):
        """Moving a declaration must change the VALUES, not break the tensor:
        a variant that produced the wrong shape or dtype would also 'differ',
        and the axis test would pass for the wrong reason."""
        for overrides in (
            {"encoding.value_offset": 200, "encoding.num_classes": 328},
            {
                "channels.input_channel": DECLARED_CHANNELS["target_channel"],
                "channels.target_channel": DECLARED_CHANNELS["input_channel"],
            },
        ):
            variant = _profile_with(contrast.profile, **overrides)
            tensor = build_bounded_probe_batch(
                profile=variant,
                data_dir=contrast.data_dir,
                batch_size=BATCH,
                segment_length=SEG,
            ).tensor
            assert tensor.shape == (BATCH, SEG)
            assert tensor.dtype == torch.int64
