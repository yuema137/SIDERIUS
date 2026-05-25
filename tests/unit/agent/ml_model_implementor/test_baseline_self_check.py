"""Tests for Phase B.2a baseline-self-check in nodes/ml_model_implementor.py.

Covers the new ``_check_baseline_schema_compatibility`` helper and its wiring
into ``_validate_code``.

The helper instantiates the plugin's ``PLUGIN_CONFIG_CLASS`` with the proposer's
``baseline_config['model_config']`` (not just defaults) so implementor-invented
schema constraints can't silently reject the baseline until tuner-time.

See docs/improving_validation_awareness.md Phase B.2.
"""

import pytest
from pydantic import ValidationError

from agent.schemas.implementor import ImplementorInput
from nodes.ml_model_implementor import (
    MLModelImplementor,
    _check_baseline_schema_compatibility,
)

# ---- Minimal plugin source fixtures ----
# Each fixture is a complete, importable plugin file containing a
# PLUGIN_CONFIG_CLASS with some schema constraint. The helper only needs
# PLUGIN_CONFIG_CLASS to be defined — the rest of the plugin interface
# (PLUGIN_MODEL_CLASS etc.) is checked elsewhere.

_PLUGIN_MULTIPLE_OF_2 = """
from pydantic import BaseModel, Field

class TestConfig(BaseModel):
    channels: int = Field(default=32, ge=1)
    refiner_kernel_size: int = Field(default=4, ge=1, multiple_of=2)

PLUGIN_CONFIG_CLASS = TestConfig
"""

_PLUGIN_CHANNELS_MULTIPLE_OF_8 = """
from pydantic import BaseModel, Field

class TestConfig(BaseModel):
    channels: int = Field(default=32, multiple_of=8)

PLUGIN_CONFIG_CLASS = TestConfig
"""

_PLUGIN_NO_CONSTRAINTS = """
from pydantic import BaseModel, Field

class TestConfig(BaseModel):
    depth: int = Field(default=2, ge=1)

PLUGIN_CONFIG_CLASS = TestConfig
"""


# =====================================================================
# _check_baseline_schema_compatibility — direct unit tests
# =====================================================================


class TestBaselineCheckNoOp:
    def test_empty_baseline_config_returns_none(self):
        assert _check_baseline_schema_compatibility(_PLUGIN_NO_CONSTRAINTS, "m", {}) is None

    def test_missing_model_config_returns_none(self):
        # baseline_config has train_config but no model_config
        bc = {"train_config": {"lr": 1e-4}}
        assert _check_baseline_schema_compatibility(_PLUGIN_NO_CONSTRAINTS, "m", bc) is None

    def test_empty_model_config_returns_none(self):
        bc = {"model_config": {}}
        assert _check_baseline_schema_compatibility(_PLUGIN_NO_CONSTRAINTS, "m", bc) is None

    def test_none_baseline_config_returns_none(self):
        # Defensive: helper should tolerate None (even though schema normally
        # requires a dict)
        assert _check_baseline_schema_compatibility(_PLUGIN_NO_CONSTRAINTS, "m", None) is None


class TestBaselineCheckAccepts:
    def test_schema_accepts_baseline_values(self):
        bc = {"model_config": {"channels": 32, "refiner_kernel_size": 4}}
        assert _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc) is None

    def test_baseline_subset_passes(self):
        # Providing only a subset of fields — defaults fill the rest
        bc = {"model_config": {"channels": 64}}
        assert _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc) is None

    def test_extra_fields_silently_dropped_is_fine(self):
        # Pydantic ignores extra fields by default for BaseModel — baseline-check
        # must not over-flag. If the plugin's model_config has extra='allow' or
        # 'ignore', extra keys pass; if it has extra='forbid', they'd fail. The
        # helper just reflects whatever the schema chose.
        bc = {"model_config": {"channels": 32, "unused_extra_field": 99}}
        # The default TestConfig allows extras (default pydantic = 'ignore')
        assert _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc) is None


class TestBaselineCheckRejects:
    def test_multiple_of_constraint_violation(self):
        """The canonical explore_novel_v1 failure: kernel_size=5 vs multiple_of=2."""
        bc = {"model_config": {"refiner_kernel_size": 5}}
        err = _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc)
        assert err is not None
        assert "Baseline self-check failed" in err
        # The failing field name is surfaced via the pydantic error
        assert "refiner_kernel_size" in err
        # The error must route the LLM: relax schema OR adjust, not touch segmentation_size
        assert "RELAX" in err or "relax" in err
        assert "segmentation_size" in err  # boundary reminder

    def test_channels_multiple_of_8_rejection(self):
        bc = {"model_config": {"channels": 35}}  # not a multiple of 8
        err = _check_baseline_schema_compatibility(_PLUGIN_CHANNELS_MULTIPLE_OF_8, "m", bc)
        assert err is not None
        assert "channels" in err

    def test_error_includes_the_offending_model_config(self):
        """The LLM needs to see what values were rejected, not just the field name."""
        bc = {"model_config": {"refiner_kernel_size": 5}}
        err = _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc)
        assert err is not None
        # The offending dict is included verbatim
        assert "refiner_kernel_size" in err
        assert "5" in err

    def test_error_instructs_relaxation_not_mutation_of_segmentation_size(self):
        """Ownership boundary must be stated explicitly to the LLM per §2.1."""
        bc = {"model_config": {"refiner_kernel_size": 5}}
        err = _check_baseline_schema_compatibility(_PLUGIN_MULTIPLE_OF_2, "m", bc)
        assert err is not None
        assert "segmentation_size" in err
        # Ownership note mentions it cannot be changed by the implementor
        low = err.lower()
        assert (
            "not change" in low
            or "may not change" in low
            or "not touch" in low
            or "do not change" in low
        )


class TestBaselineCheckGraceful:
    """Unexpected plugin-source states should not raise — smoke/syntax checks
    are responsible for surfacing them. The baseline check returns None so it
    does not mask those errors."""

    def test_malformed_plugin_returns_none(self):
        """Unparseable Python → import fails → helper returns None (not an error)."""
        malformed = "this is not valid python ]]]"
        bc = {"model_config": {"channels": 32}}
        assert _check_baseline_schema_compatibility(malformed, "m", bc) is None

    def test_plugin_missing_plugin_config_class_returns_none(self):
        """Valid import but no PLUGIN_CONFIG_CLASS → helper returns None."""
        plugin_no_class = """
x = 1
"""
        bc = {"model_config": {"channels": 32}}
        assert _check_baseline_schema_compatibility(plugin_no_class, "m", bc) is None


# =====================================================================
# Integration with _validate_code — the check fires inside the existing gate
# =====================================================================


class TestValidateCodeIntegration:
    """B.2a: the baseline self-check is wired into _validate_code so the
    existing repair loop picks it up automatically — no new wiring needed
    in the retry machinery itself."""

    def _inp(self, baseline):
        return ImplementorInput(
            model_name="m",
            model_description="x",
            mathematical_definition="x",
            baseline_config=baseline,
        )

    def _build_valid_code(self):
        """Minimal `code` dict producing a plugin that passes all earlier checks.
        The config schema has `multiple_of=2` on refiner_kernel_size."""
        return {
            "extra_imports": "",
            "config_fields_code": (
                "    channels: int = Field(default=32, ge=1)\n"
                "    refiner_kernel_size: int = Field(default=4, ge=1, multiple_of=2)"
            ),
            "config_validators_code": "",
            "init_body": "        self.channels = config.channels",
            "forward_body": (
                "        x = x.long()\n"
                "        B, T = x.shape\n"
                "        return torch.zeros(B, 256, T, dtype=torch.float32)"
            ),
            "config_fields": {"channels": 32, "refiner_kernel_size": 4},
        }

    def test_accepting_baseline_passes_validate_code(self):
        inp = self._inp({"model_config": {"channels": 32, "refiner_kernel_size": 4}})
        result = MLModelImplementor._validate_code(self._build_valid_code(), inp)
        assert result is None

    def test_rejecting_baseline_fails_validate_code(self):
        """Baseline refiner_kernel_size=5 violates multiple_of=2 → error returned."""
        inp = self._inp({"model_config": {"refiner_kernel_size": 5}})
        result = MLModelImplementor._validate_code(self._build_valid_code(), inp)
        assert result is not None
        assert "Baseline self-check failed" in result
        assert "refiner_kernel_size" in result

    def test_earlier_checks_take_precedence(self):
        """Syntax error in config_fields_code → syntax check fires first, baseline
        check never runs. This verifies ordering: cheap checks before expensive."""
        bad_code = self._build_valid_code()
        bad_code["config_fields_code"] = "    this is = not valid python"
        inp = self._inp({"model_config": {"refiner_kernel_size": 5}})
        result = MLModelImplementor._validate_code(bad_code, inp)
        assert result is not None
        # Syntax or consistency check, not the baseline check
        assert "Baseline self-check" not in result

    def test_empty_baseline_does_not_add_error(self):
        """With no baseline values, the baseline check is a no-op."""
        inp = self._inp({})
        result = MLModelImplementor._validate_code(self._build_valid_code(), inp)
        assert result is None
