"""Step-00 DS-1 / DS-2 / TC-1 — dataset-config and trial-decision baselines.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.2, §15.1 (roadmap steps 02 / 05a / 07b A-surfaces).

DS-3's two additional selection digests live with the existing digest
suite in ``test_sample_set_builder.py`` (STR).
"""

from __future__ import annotations

from pathlib import Path

from core.runtime_control.registry_schemas import MeasurementIdentity
from execute_tools.dataset_config import (
    NUM_FILES,
    SEGMENT_LENGTH,
    SEGMENTS_PER_FILE,
    TIDMAD,
    DataScope,
)
from tests.helpers.golden import assert_json_golden

GOLDENS = Path(__file__).parent / "goldens"

# The exact divisor list of 2_000_000_000 total samples per file geometry:
# valid ML segmentation sizes in [100, 100_000] (audit B: 36 entries, only
# PROPERTIES were pinned before Step 00). Hardcoded expectation — never
# read back from the code under test.
_VALID_SEGMENTATION_SIZES_36 = [
    100,
    125,
    128,
    160,
    200,
    250,
    320,
    400,
    500,
    625,
    640,
    800,
    1000,
    1250,
    1600,
    2000,
    2500,
    3125,
    3200,
    4000,
    5000,
    6250,
    8000,
    10000,
    12500,
    15625,
    16000,
    20000,
    25000,
    31250,
    40000,
    50000,
    62500,
    78125,
    80000,
    100000,
]


class TestDS1TidmadDatasetConfig:
    def test_all_six_fields_deep_equal(self):
        """DS-1 (Type 2): every field of the TIDMAD singleton. Before
        Step 00, ``sampling_frequency`` and ``validation_file_pattern``
        were UNPINNED (the frozen raw-filename literal in the scorer is a
        separate MIGRATION PARITY pin, NUM-6)."""
        assert TIDMAD.model_dump() == {
            "psd_segment_length": 10_000_000,
            "segments_per_file": 200,
            "num_files": 20,
            "sampling_frequency": 10_000_000.0,
            "training_file_pattern": "abra_training_{file_index:04d}.h5",
            "validation_file_pattern": "abra_validation_{file_index:04d}.h5",
        }

    def test_module_constants_mirror_singleton(self):
        assert SEGMENT_LENGTH == 10_000_000
        assert SEGMENTS_PER_FILE == 200
        assert NUM_FILES == 20

    def test_valid_segmentation_sizes_exact_list(self):
        assert TIDMAD.valid_segmentation_sizes() == _VALID_SEGMENTATION_SIZES_36

    def test_filename_renders(self):
        assert TIDMAD.training_file_name(0) == "abra_training_0000.h5"
        assert TIDMAD.training_file_name(19) == "abra_training_0019.h5"
        assert TIDMAD.validation_file_pattern.format(file_index=7) == "abra_validation_0007.h5"

    def test_default_scope_resolves_full_range(self):
        assert DataScope.default().resolve(TIDMAD) == list(range(20))


class TestDS2ShapeClassAndIdentityOrder:
    def test_data_shape_class_exact_string(self):
        """DS-2: the shape-class string existed only as a fixture literal
        before Step 00. Produced through the REAL resolver with an
        explicit ``dataset_root`` (no machine data-dir coupling; steps
        02/07b depend on this key's stability)."""
        from execute_tools.data_paths import resolve_tidmad_measurement_capability

        cap = resolve_tidmad_measurement_capability(dataset_root="/nonexistent/step00-fixture")
        assert cap.data_shape_class == "psd10000000_seg200_files20"
        assert cap.task_identity == "tidmad_denoise"
        assert cap.dataset_adapter == "tidmad_hdf5"

    def test_measurement_identity_component_order(self):
        """DS-2: the ordered identity-key composition (stack LAST) — store
        keys and comparability groups depend on this exact order."""
        ident = MeasurementIdentity(
            measurement_kind="duration",
            task_identity="tidmad_denoise",
            data_shape_class="psd10000000_seg200_files20",
            model_family="wavenet",
            candidate_config_hash="cfg-hash-fixture",
            phase="training",
            hardware_uuid="GPU-fixture-uuid",
            runtime_stack_identity="stack-fixture",
        )
        assert ident.components() == (
            "duration",
            "tidmad_denoise",
            "psd10000000_seg200_files20",
            "wavenet",
            "cfg-hash-fixture",
            "training",
            "GPU-fixture-uuid",
            "stack-fixture",
        )
        assert ident.identity_key == "|".join(ident.components())


class TestTC1TrialConfigResolution:
    """TC-1 (Type 2): the resolved trial/formal ``TrialConfig`` under
    pinned decision inputs.

    Previous assumption: the tuner's trial-decision composition is a
    callable unit.
    Audit evidence: the composition is INLINE in the tuner's ``run()``
    (`ml_hyperparameter_tune_agent.py:4362`), not unit-invokable.
    Corrected understanding: the validated ``TrialConfig`` schema object
    is the declared single source of truth every in-run value passes
    through (CLAUDE.md Pydantic-validation rule).
    Implementation consequence: TC-1 pins the SCHEMA-resolution surface —
    ``model_validate`` on pinned planner-style inputs with defaults
    materialized by ``model_dump()``; the in-run stamps are pinned by
    REC-2 and selection determinism by DS-3.
    Validation consequence: a default/Literal/normalization change in
    ``TrialConfig`` fails these goldens.
    """

    def test_trial_mode_resolution(self):
        from agent.schemas.hyperparam_tuning import TrialConfig

        tc = TrialConfig.model_validate(
            {
                "is_trial": True,
                "mode": "trial",
                "trial_strategy": "snapshot",
                "trial_portion": 0.05,
                "train_portion": 1.0,
                "target_files": [],
                "eval_strategy": "snapshot",
                "eval_portion": 0.1,
                "train_validation_align": True,
                "file_index": None,
                "train_sampling_seed": 12345,
                "eval_sampling_seed": 12345,
                "train_base_seed": 67890,
                "resolved_order_strategy": "shuffle",
                "resolved_file_order": None,
            }
        )
        assert_json_golden(
            tc.model_dump(mode="json"),
            GOLDENS / "tc1_trial_mode_resolved.json",
            surface="TC-1 trial-mode TrialConfig",
        )

    def test_formal_mode_resolution_defaults_materialized(self):
        """Minimal formal-mode input: the three sampling seeds are REQUIRED
        (no defaults — itself a pinned fact); everything else materializes
        from schema defaults."""
        from agent.schemas.hyperparam_tuning import TrialConfig

        tc = TrialConfig.model_validate(
            {
                "is_trial": False,
                "mode": "formal",
                "train_sampling_seed": 12345,
                "eval_sampling_seed": 12345,
                "train_base_seed": 67890,
            }
        )
        assert_json_golden(
            tc.model_dump(mode="json"),
            GOLDENS / "tc1_formal_mode_resolved.json",
            surface="TC-1 formal-mode TrialConfig (defaults)",
        )
