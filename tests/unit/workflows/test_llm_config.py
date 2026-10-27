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
    def test_openai_effort_is_explicit_and_other_providers_refuse_it(self):
        configured = NodeLLMConfig(
            provider="openai", model_id="gpt-5.6-sol", reasoning_effort="medium"
        )
        assert configured.reasoning_effort == "medium"
        with pytest.raises(ValidationError, match="requires provider='openai'"):
            NodeLLMConfig(provider="gemini", reasoning_effort="medium")


# ---------------------------------------------------------------------------
# TunerLLMConfig — nested per-sub-call NodeLLMConfig
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# WorkflowLLMConfig — top-level per-agent config
# ---------------------------------------------------------------------------


class TestWorkflowLLMConfig:
    def test_get_returns_empty_dict_for_unset_slot(self):
        cfg = WorkflowLLMConfig()
        assert cfg.get("interpret") == {}
        assert cfg.get("tune") == {}

    def test_get_returns_two_keys_for_single_call_agent(self):
        """For interpret/propose/implement/validate, get() returns just
        provider + model_id (no reflect_* keys)."""
        cfg = WorkflowLLMConfig(
            interpret=NodeLLMConfig(provider="gemini", model_id="gemini-2.5-flash"),
        )
        result = cfg.get("interpret")
        assert result == {"provider": "gemini", "model_id": "gemini-2.5-flash"}
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
            "provider": "gemini",
            "model_id": "gemini-3.1-pro-preview",
            "reflect_provider": "openai",
            "reflect_model_id": "gpt-4o-mini",
        }

    def test_get_validate_alias(self):
        """The "validate" key must resolve to validate_model (the field
        name with the alias)."""
        cfg = WorkflowLLMConfig(
            validate=NodeLLMConfig(provider="gemini", model_id="gemini-2.5-flash"),
        )
        result = cfg.get("validate")
        assert result == {"provider": "gemini", "model_id": "gemini-2.5-flash"}


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
        # Single-call slots
        for slot in ("interpret", "implement", "validate_model"):
            cfg_slot = getattr(cfg, slot)
            assert cfg_slot.provider == "gemini"
            assert cfg_slot.model_id == "gemini-3.1-pro-preview"
        # Proposal agent has nested per-stage configs
        for stage in (cfg.propose.comparison, cfg.propose.reasoning, cfg.propose.proposing):
            assert stage.provider == "gemini"
            assert stage.model_id == "gemini-3.1-pro-preview"

    def test_reflect_model_id_only_same_provider(self):
        """Just override the reflector's model — same provider for both."""
        cfg = WorkflowLLMConfig.uniform(
            "gemini",
            "gemini-3.1-pro-preview",
            reflect_model_id="gemini-2.5-flash",
        )
        assert cfg.tune.planner.model_id == "gemini-3.1-pro-preview"
        assert cfg.tune.reflector.model_id == "gemini-2.5-flash"
        assert cfg.tune.planner.provider == "gemini"
        assert cfg.tune.reflector.provider == "gemini"

    def test_reflect_provider_and_model_cross_provider(self):
        """Override both provider and model for the reflector."""
        cfg = WorkflowLLMConfig.uniform(
            "gemini",
            "gemini-3.1-pro-preview",
            reflect_provider="openai",
            reflect_model_id="gpt-4o-mini",
        )
        assert cfg.tune.planner.provider == "gemini"
        assert cfg.tune.reflector.provider == "openai"
        assert cfg.tune.reflector.model_id == "gpt-4o-mini"
        # The single-call slots stay on gemini
        for slot in ("interpret", "implement", "validate_model"):
            assert getattr(cfg, slot).provider == "gemini"
        # Proposal agent's nested stages stay on gemini
        for stage in (cfg.propose.comparison, cfg.propose.reasoning, cfg.propose.proposing):
            assert stage.provider == "gemini"

    def test_reflect_provider_only_no_model_override(self):
        """reflect_provider set but reflect_model_id unset → reflector
        uses the new provider with the main model name (which may or
        may not exist on that provider — uniform() doesn't validate)."""
        cfg = WorkflowLLMConfig.uniform(
            "gemini",
            "shared-model-name",
            reflect_provider="openai",
        )
        assert cfg.tune.reflector.provider == "openai"
        assert cfg.tune.reflector.model_id == "shared-model-name"

    def test_get_tune_after_uniform_with_overrides(self):
        """End-to-end: uniform() with overrides → get('tune') → flat dict
        with the right provider+model split."""
        cfg = WorkflowLLMConfig.uniform(
            "gemini",
            "gemini-3.1-pro-preview",
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
            "propose": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
            "implement": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
            "validate": {"provider": "gemini", "model_id": "gemini-3.1-flash-lite-preview"},
            "tune": {
                "planner": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
                "reflector": {"provider": "gemini", "model_id": "gemini-2.5-flash"},
            },
        }
        cfg = WorkflowLLMConfig.model_validate(data)
        assert cfg.interpret.provider == "gemini"
        assert cfg.tune.planner.model_id == "gemini-3.1-pro-preview"
        assert cfg.tune.reflector.model_id == "gemini-2.5-flash"
        # validate alias must resolve
        assert cfg.validate_model.model_id == "gemini-3.1-flash-lite-preview"

    def test_cross_provider_nested_config_loads(self):
        """A config that puts the reflector on a different provider."""
        data = {
            "tune": {
                "planner": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
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
                "reflector": {"provider": "gemini", "model_id": "gemini-2.5-flash"},
            },
        }
        cfg = WorkflowLLMConfig.model_validate(data)
        assert cfg.tune.planner.model_id == "gpt-5.6-luna"  # default
        assert cfg.tune.reflector.model_id == "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# LitReviewLLMConfig — nested per-bridge config (Commit 6, Design Decision 3)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# WorkflowLLMConfig.get("lit_review") — flatten + fallback semantics
# ---------------------------------------------------------------------------


class TestWorkflowLLMConfigLitReview:
    """Commit 6 Design Decision 3 (2026-06-11) — .get('lit_review')
    flattens the nested LitReviewLLMConfig into the 4-field shape
    LiteratureReviewInput consumes, and falls back to a translated
    interpret-slot dict when lit_review is None."""

    def test_get_lit_review_configured_returns_4_field_flatten(self):
        from workflows.llm_config import LitReviewLLMConfig

        cfg = WorkflowLLMConfig(
            lit_review=LitReviewLLMConfig(
                main=NodeLLMConfig(provider="openai", model_id="gpt-4o"),
                search=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
            )
        )
        assert cfg.get("lit_review") == {
            "llm_provider": "openai",
            "llm_model_id": "gpt-4o",
            "search_llm_provider": "openai",
            "search_llm_model_id": "gpt-4o-mini",
        }

    def test_get_lit_review_unconfigured_falls_back_to_translated_interpret(self):
        """When lit_review is None and interpret is set, .get('lit_review')
        translates interpret's provider/model_id → llm_provider/llm_model_id;
        search_llm_* fields stay absent so the lit-review node falls back to
        the main bridge for the search-decision call."""
        cfg = WorkflowLLMConfig(
            interpret=NodeLLMConfig(provider="openai", model_id="gpt-4o-mini"),
        )
        assert cfg.get("lit_review") == {
            "llm_provider": "openai",
            "llm_model_id": "gpt-4o-mini",
        }

    def test_get_lit_review_no_fallback_returns_empty_dict(self):
        """When neither lit_review nor interpret is configured, the
        fallback chain returns an empty dict — no LLM routing is asserted."""
        cfg = WorkflowLLMConfig()
        assert cfg.get("lit_review") == {}

    def test_uniform_populates_lit_review_with_both_subslots(self):
        cfg = WorkflowLLMConfig.uniform("openai", "gpt-4o-mini")
        assert cfg.lit_review is not None
        assert cfg.lit_review.main.provider == "openai"
        assert cfg.lit_review.main.model_id == "gpt-4o-mini"
        assert cfg.lit_review.search.provider == "openai"
        assert cfg.lit_review.search.model_id == "gpt-4o-mini"
        # End-to-end: .uniform() → .get('lit_review') → 4-field flatten.
        assert cfg.get("lit_review") == {
            "llm_provider": "openai",
            "llm_model_id": "gpt-4o-mini",
            "search_llm_provider": "openai",
            "search_llm_model_id": "gpt-4o-mini",
        }


# ---------------------------------------------------------------------------
# Regression — shipped workflow examples preserve literature route projection
# ---------------------------------------------------------------------------


class TestShippedJsonConfigsParse:
    """Regression guard against the Step-3 update being incomplete.
    Every workflow JSON config in configs/llm/ must (a) parse, (b) carry a
    lit_review block, (c) yield the required provider/model fields from
    .get('lit_review')."""

    def test_workflow_examples_parse_with_lit_review_block(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        paths = sorted((root / "configs" / "llm").glob("*.json"))
        assert paths, "Expected shipped workflow configurations"
        for path in paths:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            cfg = WorkflowLLMConfig.model_validate(data)
            assert cfg.lit_review is not None, f"{path.name}: lit_review block missing"
            got = cfg.get("lit_review")
            assert {
                "llm_provider",
                "llm_model_id",
                "search_llm_provider",
                "search_llm_model_id",
            } <= set(got), f"{path.name}: .get('lit_review') missing one or more keys"


def test_explicit_effort_reaches_every_configured_role():
    from workflows.llm_config import LitReviewLLMConfig, ProposalLLMConfig

    leaf = NodeLLMConfig(provider="openai", model_id="gpt-5.6-sol", reasoning_effort="medium")
    config = WorkflowLLMConfig(
        interpret=leaf,
        data_analysis=leaf,
        propose=ProposalLLMConfig(comparison=leaf, reasoning=leaf, proposing=leaf),
        implement=leaf,
        validate=leaf,
        tune=TunerLLMConfig(planner=leaf, reflector=leaf),
        lit_review=LitReviewLLMConfig(main=leaf, search=leaf),
    )
    for role in ("interpret", "data_analysis", "propose", "implement", "validate", "tune"):
        assert config.get(role)["reasoning_effort"] == "medium"
    assert config.get("tune")["reflect_reasoning_effort"] == "medium"
    assert config.get("lit_review")["llm_reasoning_effort"] == "medium"
    assert config.get("lit_review")["search_llm_reasoning_effort"] == "medium"


def test_proposer_transports_independent_stage_efforts():
    from workflows.llm_config import ProposalLLMConfig

    medium = NodeLLMConfig(provider="openai", model_id="gpt-5.6-sol", reasoning_effort="medium")
    high = NodeLLMConfig(provider="openai", model_id="gpt-5.6-sol", reasoning_effort="high")
    config = WorkflowLLMConfig(
        propose=ProposalLLMConfig(comparison=medium, reasoning=high, proposing=medium)
    )
    routed = config.get("propose")
    assert routed["comparison_reasoning_effort"] == "medium"
    assert routed["reasoning_reasoning_effort"] == "high"
    assert routed["proposing_reasoning_effort"] == "medium"
    assert routed["comparison_max_retries"] is None
