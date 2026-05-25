"""Tests for ConfigAdjustment + ImplementorOutput.baseline_config_adjustments.

Covers Phase B.1 of docs/improving_validation_awareness.md.

Validates:
  ConfigAdjustment (single-entry policy):
    - numeric within ±20% passes
    - numeric at exactly 20% boundary passes (inclusive)
    - numeric beyond 20% raises with a policy-violation message
    - bool values rejected (categorical — must relax schema)
    - string / list / dict rejected (non-numeric)
    - zero original requires zero adjusted (relative delta undefined)
    - reason must be non-empty

  ImplementorOutput.baseline_config_adjustments (ownership check):
    - defaults to empty dict (backward compat with existing tests)
    - valid model-internal adjustment accepted
    - 'segmentation_size' key rejected (proposer owns it)
    - mixed dict with one forbidden key raises on that key
"""

import pytest
from pydantic import ValidationError

from agent.schemas.implementor import (
    _FORBIDDEN_ADJUSTMENT_FIELDS,
    _MAX_ADJUSTMENT_DELTA,
    ConfigAdjustment,
    ImplementorOutput,
)

# ---- minimal valid ImplementorOutput kwargs (used across tests) ----

_BASE_OUTPUT_KW = {
    "model_type": "attn_unet",
    "description_file_path": "/tmp/attn_unet/description.md",
    "model_file_path": "/tmp/attn_unet.py",
    "test_file_path": "/tmp/test_attn_unet.py",
    "config_fields": {"depth": 2},
    "model_description": "x",
    "mathematical_definition": "x",
}


# =====================================================================
# ConfigAdjustment — single-entry policy
# =====================================================================


class TestConfigAdjustmentNumeric:
    def test_within_20pct_passes(self):
        # 100 -> 110 is 10% — well within
        adj = ConfigAdjustment(
            original_value=100,
            adjusted_value=110,
            reason="snap to multiple_of=10",
        )
        assert adj.adjusted_value == 110

    def test_at_exactly_20pct_passes(self):
        # Boundary is inclusive: 100 -> 120 is exactly 20%
        adj = ConfigAdjustment(
            original_value=100,
            adjusted_value=120,
            reason="boundary case",
        )
        assert adj.adjusted_value == 120

    def test_negative_delta_at_boundary_passes(self):
        # 5 -> 4 is exactly 20% down (the canonical kernel-size example)
        adj = ConfigAdjustment(
            original_value=5,
            adjusted_value=4,
            reason="5 -> 4 to satisfy multiple_of=2 on refiner_kernel_size",
        )
        assert adj.adjusted_value == 4

    def test_beyond_20pct_rejected(self):
        # 100 -> 80 is 20% but 100 -> 75 is 25% — over the line
        with pytest.raises(ValidationError) as exc:
            ConfigAdjustment(
                original_value=100,
                adjusted_value=75,
                reason="too aggressive",
            )
        msg = str(exc.value)
        assert "exceeding" in msg or "deviates" in msg
        assert "20" in msg  # ±20% is surfaced

    def test_mixed_int_float_within_range(self):
        # 10 -> 10.5 is 5% — fine
        adj = ConfigAdjustment(
            original_value=10,
            adjusted_value=10.5,
            reason="float snap",
        )
        assert adj.adjusted_value == 10.5


class TestConfigAdjustmentCategorical:
    def test_bool_original_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ConfigAdjustment(
                original_value=True,
                adjusted_value=False,
                reason="flip flag",
            )
        assert "bool" in str(exc.value).lower()

    def test_bool_adjusted_rejected(self):
        # int -> bool is still categorical — bool subclasses int so check both sides
        with pytest.raises(ValidationError) as exc:
            ConfigAdjustment(
                original_value=1,
                adjusted_value=True,
                reason="weird coerce",
            )
        assert "bool" in str(exc.value).lower()

    def test_string_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ConfigAdjustment(
                original_value="relu",
                adjusted_value="gelu",
                reason="change activation",
            )
        assert "numeric" in str(exc.value).lower()

    def test_list_rejected(self):
        with pytest.raises(ValidationError):
            ConfigAdjustment(
                original_value=[1, 2, 3],
                adjusted_value=[1, 2],
                reason="shrink list",
            )

    def test_dict_rejected(self):
        with pytest.raises(ValidationError):
            ConfigAdjustment(
                original_value={"a": 1},
                adjusted_value={"a": 2},
                reason="nested change",
            )


class TestConfigAdjustmentEdgeCases:
    def test_zero_original_requires_zero_adjusted(self):
        # 0 -> 5 is an undefined relative delta
        with pytest.raises(ValidationError) as exc:
            ConfigAdjustment(
                original_value=0,
                adjusted_value=5,
                reason="out of thin air",
            )
        assert "undefined" in str(exc.value).lower() or "zero" in str(exc.value).lower()

    def test_zero_original_zero_adjusted_passes(self):
        # 0 -> 0 is a no-op but technically a recorded adjustment (LLM may do this)
        adj = ConfigAdjustment(
            original_value=0,
            adjusted_value=0,
            reason="no-op for documentation",
        )
        assert adj.original_value == 0

    def test_reason_required_non_empty(self):
        with pytest.raises(ValidationError) as exc:
            ConfigAdjustment(
                original_value=100,
                adjusted_value=110,
                reason="",
            )
        # Pydantic reports min_length violation
        assert "reason" in str(exc.value).lower()

    def test_reason_missing_rejected(self):
        with pytest.raises(ValidationError):
            ConfigAdjustment(
                original_value=100,
                adjusted_value=110,
            )


# =====================================================================
# ImplementorOutput.baseline_config_adjustments — ownership check
# =====================================================================


class TestImplementorOutputAdjustments:
    def test_defaults_to_empty_dict(self):
        """Existing tests construct ImplementorOutput without this field — must stay valid."""
        out = ImplementorOutput(**_BASE_OUTPUT_KW)
        assert out.baseline_config_adjustments == {}

    def test_valid_model_internal_adjustment_accepted(self):
        out = ImplementorOutput(
            **_BASE_OUTPUT_KW,
            baseline_config_adjustments={
                "refiner_kernel_size": ConfigAdjustment(
                    original_value=5,
                    adjusted_value=4,
                    reason="multiple_of=2",
                ),
            },
        )
        assert "refiner_kernel_size" in out.baseline_config_adjustments
        assert out.baseline_config_adjustments["refiner_kernel_size"].adjusted_value == 4

    def test_forbidden_segmentation_size_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ImplementorOutput(
                **_BASE_OUTPUT_KW,
                baseline_config_adjustments={
                    "segmentation_size": ConfigAdjustment(
                        original_value=16384,
                        adjusted_value=16000,
                        reason="try to fix here",
                    ),
                },
            )
        msg = str(exc.value)
        assert "segmentation_size" in msg
        assert "proposer" in msg.lower()  # error routes the retry upstream

    def test_mixed_adjustments_reject_on_forbidden(self):
        """A valid model-internal adjustment plus a forbidden one still rejects."""
        with pytest.raises(ValidationError) as exc:
            ImplementorOutput(
                **_BASE_OUTPUT_KW,
                baseline_config_adjustments={
                    "refiner_kernel_size": ConfigAdjustment(
                        original_value=5,
                        adjusted_value=4,
                        reason="ok",
                    ),
                    "segmentation_size": ConfigAdjustment(
                        original_value=16384,
                        adjusted_value=16000,
                        reason="not ok",
                    ),
                },
            )
        assert "segmentation_size" in str(exc.value)

    def test_multiple_valid_adjustments_accepted(self):
        out = ImplementorOutput(
            **_BASE_OUTPUT_KW,
            baseline_config_adjustments={
                "channels": ConfigAdjustment(
                    original_value=64,
                    adjusted_value=72,
                    reason="multiple_of=8",
                ),
                "hidden_dim": ConfigAdjustment(
                    original_value=128,
                    adjusted_value=144,
                    reason="multiple_of=16",
                ),
            },
        )
        assert len(out.baseline_config_adjustments) == 2


class TestModuleConstants:
    """Lightweight sanity checks on the module-level policy constants."""

    def test_forbidden_set_contains_segmentation_size(self):
        # This is the only dataset-level field we guard today (docs §5.1).
        assert "segmentation_size" in _FORBIDDEN_ADJUSTMENT_FIELDS

    def test_forbidden_set_is_frozen(self):
        # Guard against accidental mutation at runtime.
        assert isinstance(_FORBIDDEN_ADJUSTMENT_FIELDS, frozenset)

    def test_delta_threshold_matches_locked_decision(self):
        # docs §5.2 locked in ±20%.
        assert _MAX_ADJUSTMENT_DELTA == 0.20
