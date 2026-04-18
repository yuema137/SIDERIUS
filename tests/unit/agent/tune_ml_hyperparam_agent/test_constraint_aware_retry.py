"""
Phase D.4 — Constraint-aware retry.

Covers the three layers that make up the fix:

  1. ``_extract_schema_violations``: turns ``ValidationError`` into a
     serializable ``list[dict]`` the tuner can surface back to the planner.
     Distinguishes per-field bound errors (``multiple_of``,
     ``greater_than_equal`` …) from cross-field ``@model_validator(mode='after')``
     errors (``value_error``, ``loc='__root__'``).

  2. ``evaluate_vram_skill.run_skill``: when the plugin's
     ``PLUGIN_CONFIG_CLASS(**model_cfg)`` raises ``ValidationError``, the
     wrapper returns ``status='schema_violation'`` with the structured
     violation list and the offending config — instead of bubbling a generic
     "Loop Error" out of the tuner.

  3. ``HyperparamTuningAgent.run``: on ``schema_violation`` the tuner saves
     a ``skipped_schema_violation`` ``ExperimentRecord`` (mirroring the
     existing OOM / time-risk skip patterns), does NOT advance
     ``completed_rounds``, and does NOT raise. The planner picks the saved
     record up on the next attempt via ``sandbox.get_summary()``.

See ``docs/improving_validation_awareness.md`` §D.4.
"""
import tempfile
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field, ValidationError, model_validator

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.skills.evaluate_vram_skill.wrapper import (
    run_skill,
    _extract_schema_violations,
)
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent


# ---------------------------------------------------------------------------
# Mock config classes that exercise each error type the wrapper must handle
# ---------------------------------------------------------------------------

class _MockMonotoneCfg(BaseModel):
    """Mirrors ``dual_path_skip_fusion_cnn``'s ``@model_validator(mode='after')``
    cross-field invariant — the exact rule that blew up iter-1 of
    ``exploit_cnn_v1`` on 2026-04-17."""
    a: int = Field(default=1, ge=1)
    b: int = Field(default=2, ge=1)
    c: int = Field(default=3, ge=1)

    @model_validator(mode='after')
    def check_mono(self):
        if not (self.a <= self.b <= self.c):
            raise ValueError(
                f"values must be nondecreasing, got {self.a}, {self.b}, {self.c}"
            )
        return self


class _MockMultOfCfg(BaseModel):
    """Exercises per-field ``multiple_of`` and ``ge`` constraints — these are
    both representable in ``model_json_schema()`` (unlike ``@model_validator``)
    but the wrapper must handle them uniformly so the tuner's record
    machinery is format-agnostic."""
    channels: int = Field(default=8, ge=1, multiple_of=8)


class FakeSandbox:
    """Minimal stand-in — ``evaluate_vram_skill`` never calls sandbox methods."""
    pass


CPU_TRAIN = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
CE_LOSS = {"loss_type": "ce"}


# ===========================================================================
# _extract_schema_violations — extractor unit tests
# ===========================================================================

class TestExtractor:

    def test_model_validator_violation_loc_is_root(self):
        """``@model_validator(mode='after')`` errors carry an empty ``loc`` — the
        extractor normalizes that to ``'__root__'`` so the downstream prompt
        can distinguish cross-field rules from per-field ones at a glance."""
        with pytest.raises(ValidationError) as ei:
            _MockMonotoneCfg(a=5, b=3, c=3)
        violations = _extract_schema_violations(ei.value)
        assert len(violations) == 1
        v = violations[0]
        assert v["type"] == "value_error"
        assert v["loc"] == "__root__"
        assert "nondecreasing" in v["msg"]

    def test_multiple_of_loc_and_type_and_input(self):
        with pytest.raises(ValidationError) as ei:
            _MockMultOfCfg(channels=9)
        violations = _extract_schema_violations(ei.value)
        offending = [v for v in violations if v["type"] == "multiple_of"]
        assert offending, f"no multiple_of violation in {violations}"
        assert offending[0]["loc"] == "channels"
        assert offending[0]["input"] == 9

    def test_greater_than_equal_loc_and_type(self):
        with pytest.raises(ValidationError) as ei:
            _MockMultOfCfg(channels=0)
        violations = _extract_schema_violations(ei.value)
        assert any(
            v["type"] == "greater_than_equal" and v["loc"] == "channels"
            for v in violations
        ), f"expected ge violation, got {violations}"


# ===========================================================================
# run_skill — wrapper-level behavior
# ===========================================================================

class TestWrapperSchemaViolation:
    """``run_skill`` must return ``status='schema_violation'`` with structured
    violation info when the plugin config class rejects the ``model_cfg``."""

    def test_model_validator_violation_returns_schema_violation(self):
        cfg = {"a": 5, "b": 3, "c": 3}
        with patch(
            "agent.skills.evaluate_vram_skill.wrapper.get_config_class",
            return_value=_MockMonotoneCfg,
        ):
            result = run_skill(
                FakeSandbox(),
                model_type="mock",
                model_config=cfg,
                train_config=CPU_TRAIN,
                loss_config=CE_LOSS,
            )
        assert result["status"] == "schema_violation"
        assert result["offending_config"] == cfg
        assert len(result["violations"]) == 1
        v = result["violations"][0]
        assert v["type"] == "value_error"
        # The original message is preserved so the planner sees the RULE, not
        # just a generic "ValidationError".
        assert "nondecreasing" in v["msg"]
        # Suggestion + verdict propagate to the tuner's stdout + record.
        assert result.get("suggestion")
        assert result.get("verdict")

    def test_multiple_of_violation_returns_schema_violation(self):
        cfg = {"channels": 9}
        with patch(
            "agent.skills.evaluate_vram_skill.wrapper.get_config_class",
            return_value=_MockMultOfCfg,
        ):
            result = run_skill(
                FakeSandbox(),
                model_type="mock",
                model_config=cfg,
                train_config=CPU_TRAIN,
                loss_config=CE_LOSS,
            )
        assert result["status"] == "schema_violation"
        v = result["violations"][0]
        assert v["type"] == "multiple_of"
        assert v["loc"] == "channels"
        assert v["input"] == 9

    def test_ge_violation_returns_schema_violation(self):
        cfg = {"channels": 0}
        with patch(
            "agent.skills.evaluate_vram_skill.wrapper.get_config_class",
            return_value=_MockMultOfCfg,
        ):
            result = run_skill(
                FakeSandbox(),
                model_type="mock",
                model_config=cfg,
                train_config=CPU_TRAIN,
                loss_config=CE_LOSS,
            )
        assert result["status"] == "schema_violation"
        assert result["violations"][0]["type"] == "greater_than_equal"

    def test_happy_path_unchanged(self):
        """Valid config → unchanged ``status='success'`` path. Sanity-check
        that the new ``ValidationError`` branch does not intercept healthy
        configs. Uses the real ``rnn`` plugin so we exercise the actual
        ``get_config_class`` / ``MODEL_REGISTRY`` wiring rather than the
        patched mocks above."""
        result = run_skill(
            FakeSandbox(),
            model_type="rnn",
            model_config={
                "model_type": "rnn",
                "segmentation_size": 1000,
                "embedding_dim": 8,
                "hidden_dim": 8,
                "num_layers": 1,
            },
            train_config=CPU_TRAIN,
            loss_config=CE_LOSS,
        )
        assert result["status"] == "success"
        assert result["feasible"] is True


# ===========================================================================
# HyperparamTuningAgent.run — end-to-end tuner behavior on schema_violation
# ===========================================================================

FAKE_PLAN = {
    "model_type": "punet",
    "hypothesis": "Test hypothesis.",
    "reasoning": "Test reasoning.",
    "model_config": {"depth": 4, "segmentation_size": 40000, "batch_size": 1},
    "train_config": {"epochs": 5, "lr": 1e-4},
    "loss_config": {"loss_type": "ce"},
}

FAKE_REFLECT = {
    "conclusion": "n/a",
    "key_factor": "n/a",
    "discovery": "n/a",
    "memory_update": "n/a",
}

FAKE_CONFIG_MANUAL = {
    "status": "success",
    "data": {"punet": {"fields": ["depth"]}},
}

# Mirrors the shape ``evaluate_vram_skill.run_skill`` returns when
# ``PLUGIN_CONFIG_CLASS(**model_cfg)`` raises a ``ValidationError``. Kept as
# a dict (not an actual wrapper call) so the tuner test doesn't depend on
# the real plugin / MODEL_REGISTRY.
FAKE_SCHEMA_VIOLATION = {
    "status": "schema_violation",
    "violations": [
        {
            "loc": "__root__",
            "type": "value_error",
            "msg": "values must be nondecreasing, got 5, 3, 3",
            "input": None,
        },
    ],
    "offending_config": {"a": 5, "b": 3, "c": 3},
    "message": "Schema rejected config",
    "verdict": "Schema rejected config",
    "suggestion": "Propose a valid combination.",
}


def _make_input(tmp_path, max_rounds=1):
    return HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=max_rounds,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test_run"),
        ),
        progress_bar=False,
    )


class TestTunerSchemaViolationBehavior:
    """End-to-end: the tuner must treat ``schema_violation`` like OOM /
    time-risk skips — save a ``skipped_schema_violation`` record, continue,
    do NOT raise, do NOT advance ``completed_rounds``."""

    @pytest.fixture
    def agent_and_saved(self):
        with patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge, \
             patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox, \
             patch("nodes.ml_hyperparameter_tune_agent._run_skill") as mock_skill, \
             tempfile.TemporaryDirectory() as configs_dir:

            mock_brain = MockBridge.return_value
            mock_brain.plan.return_value = FAKE_PLAN
            mock_brain.reflect.return_value = FAKE_REFLECT

            saved = []
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.get_summary.side_effect = lambda: list(saved)
            mock_sandbox.save_record.side_effect = lambda r: saved.append(r)
            mock_sandbox.dirs = {"configs": configs_dir}

            def all_schema_violation(skill_folder, sandbox, **p):
                if skill_folder == "check_config_format_skill":
                    return FAKE_CONFIG_MANUAL
                return FAKE_SCHEMA_VIOLATION
            mock_skill.side_effect = all_schema_violation

            agent = HyperparamTuningAgent()
            yield agent, saved

    def test_does_not_raise_does_not_advance_rounds(self, agent_and_saved, tmp_path):
        """All 3 attempts return ``schema_violation`` — ``completed_rounds``
        stays at 0, status flips to ``partial``, no exception bubbles up."""
        agent, saved = agent_and_saved
        output = agent.run(_make_input(tmp_path, max_rounds=1))
        # max_rounds=1 → max_attempts = max_rounds * 3 = 3 (see agent loop cap).
        assert output.status == "partial"
        assert output.completed_rounds == 0
        assert output.total_attempts == 3

    def test_all_records_saved_as_skipped_schema_violation(self, agent_and_saved, tmp_path):
        agent, saved = agent_and_saved
        agent.run(_make_input(tmp_path, max_rounds=1))
        assert len(saved) == 3
        assert all(r["status"] == "skipped_schema_violation" for r in saved)

    def test_record_memory_carries_violation_details(self, agent_and_saved, tmp_path):
        """The next round's planner reads ``memory.conclusion`` and
        ``memory.memory_update`` — both must encode *what* was rejected and
        *why*, and the memory_update must carry the explicit
        'DO NOT repeat' marker so the planner's prompt picks it out."""
        agent, saved = agent_and_saved
        agent.run(_make_input(tmp_path, max_rounds=1))
        r = saved[0]
        # conclusion names the violating field AND the offending values
        assert "__root__" in r["memory"]["conclusion"]
        assert "{'a': 5, 'b': 3, 'c': 3}" in r["memory"]["conclusion"]
        # memory_update relays the pydantic message verbatim so the planner
        # can reason about the rule, not just the rejected values.
        assert "nondecreasing" in r["memory"]["memory_update"]
        assert "DO NOT" in r["memory"]["memory_update"].upper()
