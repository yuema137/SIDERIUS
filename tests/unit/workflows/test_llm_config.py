"""
Unit tests for workflows/llm_config.py

Covers:
  - NodeLLMConfig: defaults, JSON round-trip
  - TunerLLMConfig: defaults (planner/reflector as nested NodeLLMConfig),
    independent provider+model per sub-call, JSON round-trip
  - WorkflowLLMConfig: per-slot typing, get() flattening for the tuner,
    uniform() with and without reflect overrides, partial JSON loading
"""
import json
import pytest
from pydantic import ValidationError

from workflows.llm_config import NodeLLMConfig, TunerLLMConfig, WorkflowLLMConfig


# ---------------------------------------------------------------------------
# NodeLLMConfig — leaf type
# ---------------------------------------------------------------------------

class TestNodeLLMConfig:

    def test_defaults(self):
        """No args → falls back to gemini / flash-lite-preview defaults."""
        c = NodeLLMConfig()
        assert c.provider == "gemini"
        assert c.model_id == "gemini-3.1-flash-lite-preview"

    def test_explicit_provider_and_model(self):
        c = NodeLLMConfig(provider="openai", model_id="gpt-4o-mini")
        assert c.provider == "openai"
        assert c.model_id == "gpt-4o-mini"

    def test_invalid_provider_raises(self):
        with pytest.raises(ValidationError):
            NodeLLMConfig(provider="anthropic", model_id="claude-3")

    def test_round_trip_through_json(self):
        c = NodeLLMConfig(provider="gemini", model_id="gemini-2-flash")
        loaded = NodeLLMConfig.model_validate_json(c.model_dump_json())
        assert loaded.provider == "gemini"
        assert loaded.model_id == "gemini-2-flash"


# ---------------------------------------------------------------------------
# TunerLLMConfig — nested per-sub-call NodeLLMConfig
# ---------------------------------------------------------------------------

class TestTunerLLMConfig:

    def test_defaults(self):
        """No args → planner = gemini-3.1-pro-preview, reflector = gemini-2-flash."""
        c = TunerLLMConfig()
        assert isinstance(c.planner, NodeLLMConfig)
        assert isinstance(c.reflector, NodeLLMConfig)
        assert c.planner.provider == "gemini"
        assert c.planner.model_id == "gemini-3.1-pro-preview"
        assert c.reflector.provider == "gemini"
        assert c.reflector.model_id == "gemini-2-flash"

    def test_planner_and_reflector_are_independent_objects(self):
        """The two slots must be distinct NodeLLMConfig instances so editing
        one doesn't accidentally affect the other."""
        c = TunerLLMConfig()
        assert c.planner is not c.reflector

    def test_explicit_same_provider_different_models(self):
        """The common case: same provider (gemini), two different models."""
        c = TunerLLMConfig(
            planner=NodeLLMConfig(provider="gemini", model_id="gemini-3.1-pro-preview"),
            reflector=NodeLLMConfig(provider="gemini", model_id="gemini-2-flash"),
        )
        assert c.planner.provider == c.reflector.provider == "gemini"
        assert c.planner.model_id != c.reflector.model_id

    def test_explicit_cross_provider(self):
        """The harder case: planner on gemini, reflector on openai."""
        c = TunerLLMConfig(
            planner=NodeLLMConfig(provider="gemini", model_id="gemini-3.1-pro-preview"),
            reflector=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
        )
        assert c.planner.provider == "gemini"
        assert c.reflector.provider == "openai"
        assert c.reflector.model_id == "gpt-4o-mini"

    def test_round_trip_through_json(self):
        """A full TunerLLMConfig with cross-provider routing must
        survive a model_dump_json → model_validate_json round-trip."""
        c = TunerLLMConfig(
            planner=NodeLLMConfig(provider="gemini", model_id="gemini-3.1-pro-preview"),
            reflector=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
        )
        dumped = c.model_dump_json()
        loaded = TunerLLMConfig.model_validate_json(dumped)
        assert loaded.planner.provider == "gemini"
        assert loaded.planner.model_id == "gemini-3.1-pro-preview"
        assert loaded.reflector.provider == "openai"
        assert loaded.reflector.model_id == "gpt-4o-mini"

    def test_partial_dict_loads_with_planner_default(self):
        """A dict that omits the planner field should load cleanly, with
        planner taking its default_factory value."""
        loaded = TunerLLMConfig.model_validate({
            "reflector": {"provider": "gemini", "model_id": "gemini-2-flash"},
        })
        assert loaded.planner.model_id == "gemini-3.1-pro-preview"  # default
        assert loaded.reflector.model_id == "gemini-2-flash"

    def test_empty_dict_loads_with_both_defaults(self):
        """An empty dict should load with both fields at default."""
        loaded = TunerLLMConfig.model_validate({})
        assert loaded.planner.model_id == "gemini-3.1-pro-preview"
        assert loaded.reflector.model_id == "gemini-2-flash"


# ---------------------------------------------------------------------------
# WorkflowLLMConfig — top-level per-agent config
# ---------------------------------------------------------------------------

class TestWorkflowLLMConfig:

    def test_default_all_slots_none(self):
        """Default WorkflowLLMConfig has all 5 slots set to None."""
        cfg = WorkflowLLMConfig()
        assert cfg.interpret is None
        assert cfg.propose is None
        assert cfg.implement is None
        assert cfg.validate_model is None
        assert cfg.tune is None

    def test_tune_slot_is_typed_TunerLLMConfig(self):
        """The tune slot must be typed as TunerLLMConfig (not the base
        NodeLLMConfig). Verified by trying to assign a NodeLLMConfig."""
        cfg = WorkflowLLMConfig(tune=TunerLLMConfig())
        assert isinstance(cfg.tune, TunerLLMConfig)

    def test_get_returns_empty_dict_for_unset_slot(self):
        cfg = WorkflowLLMConfig()
        assert cfg.get("interpret") == {}
        assert cfg.get("tune") == {}

    def test_get_returns_two_keys_for_single_call_agent(self):
        """For interpret/propose/implement/validate, get() returns just
        provider + model_id (no reflect_* keys)."""
        cfg = WorkflowLLMConfig(
            interpret=NodeLLMConfig(provider="gemini", model_id="gemini-2-flash"),
        )
        result = cfg.get("interpret")
        assert result == {"provider": "gemini", "model_id": "gemini-2-flash"}
        assert "reflect_provider" not in result
        assert "reflect_model_id" not in result

    def test_get_flattens_tune_into_4_keys(self):
        """For the tuner, get() flattens the nested TunerLLMConfig into
        the 4 flat keys expected by HyperparamTuningInput / LLMBridge."""
        cfg = WorkflowLLMConfig(
            tune=TunerLLMConfig(
                planner=NodeLLMConfig(provider="gemini", model_id="gemini-3.1-pro-preview"),
                reflector=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
            ),
        )
        result = cfg.get("tune")
        assert result == {
            "provider":         "gemini",
            "model_id":         "gemini-3.1-pro-preview",
            "reflect_provider": "openai",
            "reflect_model_id": "gpt-4o-mini",
        }

    def test_get_validate_alias(self):
        """The "validate" key must resolve to validate_model (the field
        name with the alias)."""
        cfg = WorkflowLLMConfig(
            validate=NodeLLMConfig(provider="gemini", model_id="gemini-2-flash"),
        )
        result = cfg.get("validate")
        assert result == {"provider": "gemini", "model_id": "gemini-2-flash"}


# ---------------------------------------------------------------------------
# WorkflowLLMConfig.uniform() — convenience constructor
# ---------------------------------------------------------------------------

class TestWorkflowLLMConfigUniform:

    def test_no_reflect_overrides_planner_equals_reflector(self):
        """Default behavior (legacy): planner and reflector use the same
        provider+model on every slot."""
        cfg = WorkflowLLMConfig.uniform("gemini", "gemini-3.1-pro-preview")
        assert cfg.tune.planner.provider == "gemini"
        assert cfg.tune.planner.model_id == "gemini-3.1-pro-preview"
        assert cfg.tune.reflector.provider == "gemini"
        assert cfg.tune.reflector.model_id == "gemini-3.1-pro-preview"
        # And the 4 single-call slots
        for slot in ("interpret", "propose", "implement", "validate_model"):
            cfg_slot = getattr(cfg, slot)
            assert cfg_slot.provider == "gemini"
            assert cfg_slot.model_id == "gemini-3.1-pro-preview"

    def test_reflect_model_id_only_same_provider(self):
        """Just override the reflector's model — same provider for both."""
        cfg = WorkflowLLMConfig.uniform(
            "gemini", "gemini-3.1-pro-preview",
            reflect_model_id="gemini-2-flash",
        )
        assert cfg.tune.planner.model_id == "gemini-3.1-pro-preview"
        assert cfg.tune.reflector.model_id == "gemini-2-flash"
        assert cfg.tune.planner.provider == "gemini"
        assert cfg.tune.reflector.provider == "gemini"

    def test_reflect_provider_and_model_cross_provider(self):
        """Override both provider and model for the reflector."""
        cfg = WorkflowLLMConfig.uniform(
            "gemini", "gemini-3.1-pro-preview",
            reflect_provider="openai",
            reflect_model_id="gpt-4o-mini",
        )
        assert cfg.tune.planner.provider == "gemini"
        assert cfg.tune.reflector.provider == "openai"
        assert cfg.tune.reflector.model_id == "gpt-4o-mini"
        # The 4 single-call slots stay on gemini
        for slot in ("interpret", "propose", "implement", "validate_model"):
            assert getattr(cfg, slot).provider == "gemini"

    def test_reflect_provider_only_no_model_override(self):
        """reflect_provider set but reflect_model_id unset → reflector
        uses the new provider with the main model name (which may or
        may not exist on that provider — uniform() doesn't validate)."""
        cfg = WorkflowLLMConfig.uniform(
            "gemini", "shared-model-name",
            reflect_provider="openai",
        )
        assert cfg.tune.reflector.provider == "openai"
        assert cfg.tune.reflector.model_id == "shared-model-name"

    def test_get_tune_after_uniform_with_overrides(self):
        """End-to-end: uniform() with overrides → get('tune') → flat dict
        with the right provider+model split."""
        cfg = WorkflowLLMConfig.uniform(
            "gemini", "gemini-3.1-pro-preview",
            reflect_provider="openai",
            reflect_model_id="gpt-4o-mini",
        )
        flat = cfg.get("tune")
        assert flat["provider"] == "gemini"
        assert flat["model_id"] == "gemini-3.1-pro-preview"
        assert flat["reflect_provider"] == "openai"
        assert flat["reflect_model_id"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# JSON config file loading (the user-facing nested format)
# ---------------------------------------------------------------------------

class TestWorkflowLLMConfigJSON:

    def test_full_nested_config_loads(self):
        """The user-facing JSON shape with nested planner/reflector slots
        must load cleanly."""
        data = {
            "interpret": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
            "propose":   {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
            "implement": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
            "validate":  {"provider": "gemini", "model_id": "gemini-3.1-flash-lite-preview"},
            "tune": {
                "planner":   {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
                "reflector": {"provider": "gemini", "model_id": "gemini-2-flash"},
            },
        }
        cfg = WorkflowLLMConfig.model_validate(data)
        assert cfg.interpret.provider == "gemini"
        assert cfg.tune.planner.model_id == "gemini-3.1-pro-preview"
        assert cfg.tune.reflector.model_id == "gemini-2-flash"
        # validate alias must resolve
        assert cfg.validate_model.model_id == "gemini-3.1-flash-lite-preview"

    def test_cross_provider_nested_config_loads(self):
        """A config that puts the reflector on a different provider."""
        data = {
            "tune": {
                "planner":   {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
                "reflector": {"provider": "openai", "model_id": "gpt-4o-mini"},
            },
        }
        cfg = WorkflowLLMConfig.model_validate(data)
        assert cfg.tune.planner.provider == "gemini"
        assert cfg.tune.reflector.provider == "openai"

    def test_partial_tune_only_reflector_loads_with_planner_default(self):
        """If the user writes only the reflector slot, the planner takes
        its default_factory value."""
        data = {
            "tune": {
                "reflector": {"provider": "gemini", "model_id": "gemini-2-flash"},
            },
        }
        cfg = WorkflowLLMConfig.model_validate(data)
        assert cfg.tune.planner.model_id == "gemini-3.1-pro-preview"  # default
        assert cfg.tune.reflector.model_id == "gemini-2-flash"

    def test_round_trip_via_model_dump_and_validate(self):
        cfg = WorkflowLLMConfig.uniform(
            "gemini", "gemini-3.1-pro-preview",
            reflect_model_id="gemini-2-flash",
        )
        dumped = json.loads(cfg.model_dump_json(by_alias=True))
        loaded = WorkflowLLMConfig.model_validate(dumped)
        assert loaded.tune.planner.model_id == "gemini-3.1-pro-preview"
        assert loaded.tune.reflector.model_id == "gemini-2-flash"
