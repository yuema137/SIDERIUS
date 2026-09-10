"""Step-00 DS-1 / DS-2 / TC-1 — dataset-config and trial-decision baselines.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.2, §15.1 (roadmap steps 02 / 05a / 07b A-surfaces).

DS-3's two additional selection digests live with the existing digest
suite in ``test_sample_set_builder.py`` (STR).
"""

from __future__ import annotations

from pathlib import Path

from core.runtime_control.registry_schemas import MeasurementIdentity
from tests.helpers.golden import assert_json_golden

GOLDENS = Path(__file__).parent / "goldens"


class TestMeasurementIdentityOrder:
    def test_measurement_identity_component_order(self):
        """DS-2: the ordered identity-key composition (stack LAST) — store
        keys and comparability groups depend on this exact order."""
        ident = MeasurementIdentity(
            measurement_kind="duration",
            task_identity="synthetic_regression",
            data_shape_class="vector3_mask2",
            model_family="wavenet",
            candidate_config_hash="cfg-hash-fixture",
            phase="training",
            hardware_uuid="GPU-fixture-uuid",
            runtime_stack_identity="stack-fixture",
        )
        assert ident.components() == (
            "duration",
            "synthetic_regression",
            "vector3_mask2",
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
