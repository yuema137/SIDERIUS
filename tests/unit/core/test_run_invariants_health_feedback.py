"""PR 3 lock policy: structured-health-feedback fields in RunInvariants.

CB5-a suite (``pr3_healthgate_feedback.md`` §3.9, §11-CB5). Covers the
operator resume matrix at the lock level plus the tuner pass-through
surface. NOTE (intentional intermediate state, recorded in the design
doc): at CB5-a only the TUNER call site passes the three values
explicitly — workflow and chain sites still rely on the builder
defaults until CB5-b/c; the all-three-sites regression lands in CB5-c.
"""

import json
import re
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    ensure_run_invariants,
    load_run_invariants,
)
from tests.helpers.tuner_source import tuner_node_source

REPO = Path(__file__).resolve().parents[3]
_TUNER = REPO / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"


def _invariants(**overrides) -> RunInvariants:
    base = dict(
        resolved_data_scope=list(range(20)),
        health_gate_enabled=False,
        health_config_sha256=None,
    )
    base.update(overrides)
    return RunInvariants(**base)


class TestResumeMatrix:
    def test_same_policy_accepted(self, tmp_path):
        on = _invariants(structured_health_feedback_enabled=True)
        assert ensure_run_invariants(str(tmp_path), on) == "created"
        assert ensure_run_invariants(str(tmp_path), on) == "validated"

    def test_changed_flag_rejected_naming_field_and_values(self, tmp_path):
        ensure_run_invariants(str(tmp_path), _invariants(structured_health_feedback_enabled=True))
        with pytest.raises(RunInvariantsViolation) as exc:
            ensure_run_invariants(
                str(tmp_path), _invariants(structured_health_feedback_enabled=False)
            )
        msg = str(exc.value)
        assert "structured_health_feedback_enabled" in msg
        assert "locked=True" in msg and "this run=False" in msg

    def test_changed_window_rejected(self, tmp_path):
        ensure_run_invariants(str(tmp_path), _invariants())
        with pytest.raises(RunInvariantsViolation, match="history_window_iterations"):
            ensure_run_invariants(
                str(tmp_path), _invariants(health_feedback_history_window_iterations=5)
            )

    def test_changed_max_entries_rejected(self, tmp_path):
        ensure_run_invariants(str(tmp_path), _invariants())
        with pytest.raises(RunInvariantsViolation, match="max_entries_per_model"):
            ensure_run_invariants(
                str(tmp_path), _invariants(health_feedback_history_max_entries_per_model=4)
            )

    def test_legacy_lock_resolves_off_3_8_and_validates(self, tmp_path):
        """A pre-PR3 lock file (none of the three keys) loads as the
        pre-feature state and a default-policy run resumes cleanly."""
        legacy = {
            "resolved_data_scope": list(range(20)),
            "health_gate_enabled": False,
            "health_config_sha256": None,
            "created_at": "2026-07-01T00:00:00+00:00",
        }
        (tmp_path / "run_invariants_lock.json").write_text(json.dumps(legacy))
        loaded = load_run_invariants(str(tmp_path))
        assert loaded.structured_health_feedback_enabled is False
        assert loaded.health_feedback_history_window_iterations == 3
        assert loaded.health_feedback_history_max_entries_per_model == 8
        assert ensure_run_invariants(str(tmp_path), _invariants()) == "validated"

    def test_enabling_on_over_legacy_lock_rejected(self, tmp_path):
        """Default-filling must never silently upgrade chain policy: a
        legacy workspace + a flag-ON run is a canonical mismatch."""
        legacy = {
            "resolved_data_scope": list(range(20)),
            "health_gate_enabled": False,
            "health_config_sha256": None,
        }
        (tmp_path / "run_invariants_lock.json").write_text(json.dumps(legacy))
        with pytest.raises(RunInvariantsViolation, match="structured_health_feedback_enabled"):
            ensure_run_invariants(
                str(tmp_path), _invariants(structured_health_feedback_enabled=True)
            )


class TestTunerPassThrough:
    """The tuner locks + stamps the three values it received (never
    consumes them). Source-surface assertions, the PR 2 override-surface
    pattern — the tuner is the only explicitly-wired site at CB5-a."""

    def test_input_schema_defaults(self):
        inp_fields = HyperparamTuningInput.model_fields
        assert inp_fields["enable_structured_health_feedback"].default is False
        assert inp_fields["health_feedback_history_window_iterations"].default == 3
        assert inp_fields["health_feedback_history_max_entries_per_model"].default == 8

    def test_tuner_lock_call_passes_all_three(self):
        src = tuner_node_source()
        call = re.search(r"build_run_invariants\((.*?)\n        \)", src, re.DOTALL).group(1)
        for kwarg in (
            "structured_health_feedback_enabled=",
            "health_feedback_history_window_iterations=",
            "health_feedback_history_max_entries_per_model=",
        ):
            assert kwarg in call, f"tuner lock call missing {kwarg}"
        assert "agent_input.enable_structured_health_feedback" in call

    def test_tuner_run_config_stamps_all_three(self):
        src = tuner_node_source()
        for key in (
            '"enable_structured_health_feedback"',
            '"health_feedback_history_window_iterations"',
            '"health_feedback_history_max_entries_per_model"',
        ):
            assert key in src, f"run_config stamp missing {key}"

    def test_builder_defaults_keep_pre_pr3_call_sites_unchanged(self, tmp_path):
        """A call site that omits the three params (workflow/chain until
        CB5-b/c) produces the OFF / 3 / 8 lock — identical to legacy."""
        inv = _invariants()
        assert inv.structured_health_feedback_enabled is False
        assert inv.health_feedback_history_window_iterations == 3
        assert inv.health_feedback_history_max_entries_per_model == 8
        assert set(RunInvariants._CANONICAL) >= {
            "structured_health_feedback_enabled",
            "health_feedback_history_window_iterations",
            "health_feedback_history_max_entries_per_model",
        }
