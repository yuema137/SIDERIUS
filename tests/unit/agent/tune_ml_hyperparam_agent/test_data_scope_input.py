"""
DataScope + HealthGate subsystem fields on HyperparamTuningInput (DS5a).

Asserts the schema/runtime validation split
(docs/design/enable_partial_file_list.md): schema validators cover only
dataset-independent internal consistency; everything requiring dataset
resolution (partial-scope rules) lives in validate_runtime_config and runs
at startup.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    validate_runtime_config,
)
from execute_tools.dataset_config import DataScope

PARTIAL = DataScope(file_indices=[4, 5, 6, 7, 8, 9])


def _inp(**kw) -> HyperparamTuningInput:
    return HyperparamTuningInput(model_type="punet", **kw)


# ---------------------------------------------------------------------------
# Schema-level: internal consistency only
# ---------------------------------------------------------------------------


class TestSchemaValidators:
    def test_defaults_are_full_scope_gates_enabled(self):
        inp = _inp()
        assert inp.data_scope == DataScope.default()
        assert inp.health_gate_enabled is True
        assert inp.health_gate_files is None

    def test_disabled_with_files_rejected(self):
        with pytest.raises(ValidationError, match="must be None when health_gate_enabled=False"):
            _inp(health_gate_enabled=False, health_gate_files=[4, 7])

    def test_empty_files_rejected(self):
        with pytest.raises(ValidationError, match="non-empty when provided"):
            _inp(health_gate_files=[])

    def test_partial_scope_with_formal_target_PASSES_schema(self):
        """The split: dataset-resolved rules do NOT live in the schema."""
        inp = _inp(data_scope=PARTIAL, formal_strategy="target", health_gate_files=[4, 7])
        assert inp.formal_strategy == "target"

    def test_disabled_without_files_valid(self):
        inp = _inp(health_gate_enabled=False)
        assert inp.health_gate_files is None


# ---------------------------------------------------------------------------
# Runtime-level: validate_runtime_config
# ---------------------------------------------------------------------------


class TestValidateRuntimeConfig:
    def test_full_scope_defaults_pass_and_resolve(self):
        assert validate_runtime_config(_inp()) == list(range(20))

    def test_partial_scope_resolves(self):
        inp = _inp(data_scope=PARTIAL, health_gate_files=[4, 7, 9], is_trial=True)
        assert validate_runtime_config(inp) == [4, 5, 6, 7, 8, 9]

    def test_partial_scope_formal_target_fails_at_runtime(self):
        inp = _inp(data_scope=PARTIAL, formal_strategy="target", health_gate_files=[4, 7])
        with pytest.raises(ValueError, match="formal_strategy='target' is not allowed"):
            validate_runtime_config(inp)

    def test_partial_scope_formal_anchors_fails_at_runtime(self):
        inp = _inp(data_scope=PARTIAL, formal_strategy="anchors", health_gate_files=[4, 7])
        with pytest.raises(ValueError, match="not allowed"):
            validate_runtime_config(inp)

    def test_partial_scope_enabled_without_files_fails(self):
        inp = _inp(data_scope=PARTIAL, is_trial=True)
        with pytest.raises(ValueError, match="requires an explicit --health_gate_files"):
            validate_runtime_config(inp)

    def test_partial_scope_disabled_without_files_passes(self):
        inp = _inp(data_scope=PARTIAL, health_gate_enabled=False, is_trial=True)
        assert validate_runtime_config(inp) == [4, 5, 6, 7, 8, 9]

    def test_single_file_mode_out_of_scope_fails(self):
        inp = _inp(data_scope=PARTIAL, health_gate_files=[4, 7], is_trial=False, file_index=2)
        with pytest.raises(ValueError, match=r"file_index=2 .*outside the DataScope"):
            validate_runtime_config(inp)

    def test_single_file_mode_in_scope_passes(self):
        inp = _inp(data_scope=PARTIAL, health_gate_files=[4, 7], is_trial=False, file_index=6)
        assert validate_runtime_config(inp) == [4, 5, 6, 7, 8, 9]

    def test_trial_mode_ignores_file_index(self):
        """file_index is documented as ignored under is_trial=True — the
        runtime check must not reject a stale default (6 ∈ scope here, but
        use a scope excluding 6 to prove the branch is trial-gated)."""
        inp = _inp(
            data_scope=DataScope(file_indices=[0, 1]),
            health_gate_files=[0, 1],
            is_trial=True,
            file_index=6,
        )
        assert validate_runtime_config(inp) == [0, 1]

    def test_out_of_range_scope_propagates_resolve_error(self):
        inp = _inp(data_scope=DataScope(file_indices=[4, 25]), health_gate_files=[4])
        with pytest.raises(ValueError, match=r"\[25\] out of range"):
            validate_runtime_config(inp)

    def test_old_serialized_inputs_without_new_fields_validate(self):
        """Pre-DS5 serialized inputs lack the three new fields — defaults
        apply and extras are ignored (no extra='forbid')."""
        inp = HyperparamTuningInput.model_validate({"model_type": "punet"})
        assert inp.data_scope == DataScope.default()
