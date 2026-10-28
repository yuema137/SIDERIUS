"""
Unit tests for workflows/llm_config.py

Covers:
  - NodeLLMConfig: defaults, JSON round-trip
  - TunerLLMConfig: defaults (planner/reflector as nested NodeLLMConfig),
    independent provider+model per sub-call, JSON round-trip
  - WorkflowLLMConfig: per-slot typing, get() flattening for the tuner,
    uniform() with and without reflect overrides, partial JSON loading
"""

import argparse
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from workflows.llm_config import (
    NodeLLMConfig,
    TunerLLMConfig,
    WorkflowLLMConfig,
    parse_llm_config_bytes,
    resolve_standard_llm_config,
)

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
            "propose": {
                "comparison": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
                "reasoning": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
                "proposing": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
            },
            "implement": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
            "validate": {"provider": "gemini", "model_id": "gemini-3.1-flash-lite-preview"},
            "tune": {
                "planner": {"provider": "gemini", "model_id": "gemini-3.1-pro-preview"},
                "reflector": {"provider": "gemini", "model_id": "gemini-2.5-flash"},
            },
        }
        cfg = WorkflowLLMConfig.model_validate(data)
        assert cfg.propose.reasoning.model_id == "gemini-3.1-pro-preview"
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


# ---------------------------------------------------------------------------
# WorkflowLLMConfig.judge — bounded LLM-judge routes (B2-2)
# ---------------------------------------------------------------------------

# Bytes of a fixed uniform config WITHOUT `judge`, captured from origin/master
# (69a9d81a). Pins the serialized shape that run locks and launch expectations
# compare; a stray `"judge": null` would change it for every existing workflow.
# Issue #1034 deliberately set the legacy profile's planner to native-timing-v1.
UNIFORM_WITHOUT_JUDGE_JSON = (
    '{"interpret":{"provider":"openai","model_id":"gpt-4o-mini","reasoning_effort":null},'
    '"data_analysis":null,'
    '"propose":{"comparison":{"provider":"openai","model_id":"gpt-4o-mini","reasoning_effort":null},'
    '"reasoning":{"provider":"openai","model_id":"gpt-4o-mini","reasoning_effort":null},'
    '"proposing":{"provider":"openai","model_id":"gpt-4o-mini","reasoning_effort":null}},'
    '"implement":{"provider":"openai","model_id":"gpt-4o-mini","reasoning_effort":null},'
    '"validate":{"provider":"openai","model_id":"gpt-4o-mini","reasoning_effort":null},'
    '"tune":{"planner_strategy":"native-timing-v1",'
    '"planner":{"provider":"openai","model_id":"gpt-4o-mini","reasoning_effort":null},'
    '"reflector":{"provider":"openai","model_id":"gpt-4o","reasoning_effort":null}},'
    '"lit_review":{"main":{"provider":"openai","model_id":"gpt-4o-mini","reasoning_effort":null},'
    '"search":{"provider":"openai","model_id":"gpt-4o-mini","reasoning_effort":null}}}'
)


def _uniform_without_judge() -> WorkflowLLMConfig:
    return WorkflowLLMConfig.uniform(
        "openai", "gpt-4o-mini", reflect_provider="openai", reflect_model_id="gpt-4o"
    )


class TestWorkflowLLMConfigJudge:
    def test_config_without_judge_serializes_to_the_pinned_bytes(self):
        dumped = _uniform_without_judge().model_dump_json(by_alias=True)
        assert dumped == UNIFORM_WITHOUT_JUDGE_JSON
        assert "judge" not in json.loads(dumped)

    def test_judge_routes_round_trip_and_are_refused_through_get(self):
        config = WorkflowLLMConfig.model_validate(
            {
                "judge": {
                    "stop": {
                        "provider": "openai",
                        "model_id": "gpt-4o-mini",
                        "max_output_tokens": 800,
                        "max_retries": 3,
                    }
                }
            }
        )
        dumped = json.loads(config.model_dump_json())
        assert dumped["judge"]["stop"]["max_retries"] == 3
        assert WorkflowLLMConfig.model_validate(dumped) == config
        with pytest.raises(ValueError, match="not a node slot"):
            config.get("judge")

    def test_judge_route_requires_explicit_provider_and_model(self):
        """The judge's model is audited evidence: no central default may fill it in."""
        route = {"max_output_tokens": 800, "max_retries": 2}
        for explicit in ({"provider": "openai"}, {"model_id": "gpt-4o-mini"}):
            with pytest.raises(ValidationError):
                WorkflowLLMConfig.model_validate({"judge": {"stop": {**route, **explicit}}})
        with pytest.raises(ValidationError):
            WorkflowLLMConfig.model_validate(
                {"judge": {"stop": {**route, "provider": "openai", "model_id": ""}}}
            )

    def test_empty_judge_block_is_refused(self):
        with pytest.raises(ValidationError, match="at least one"):
            WorkflowLLMConfig.model_validate({"judge": {}})

    def test_unbounded_retries_remain_valid_for_other_slots_beside_judge(self):
        config = WorkflowLLMConfig.model_validate(
            {
                "interpret": {"provider": "openai", "model_id": "gpt-4o-mini"},
                "judge": {
                    "aggregate": {
                        "provider": "openai",
                        "model_id": "gpt-4o-mini",
                        "max_output_tokens": 400,
                        "max_retries": 2,
                    }
                },
            }
        )
        assert config.interpret is not None and config.interpret.max_retries is None
        assert config.get("interpret") == {"provider": "openai", "model_id": "gpt-4o-mini"}


class TestStrictExplicitProfileLoading:
    """Explicit ``--llm_config`` files go through the strict loader on the CLI path.

    ``resolve_standard_llm_config`` calls ``WorkflowLLMConfig.from_json``, which owns
    the refusal of undeclared keys. Native models remain lenient for Python construction.
    """

    @staticmethod
    def _cli_load(path):
        args = argparse.Namespace(
            llm_config=str(path),
            llm_model=None,
            reflect_provider=None,
            reflect_model_id=None,
        )
        return resolve_standard_llm_config(args)

    @staticmethod
    def _write(tmp_path, payload):
        path = tmp_path / "llm.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_misspelled_top_level_route_is_refused_on_cli_path(self, tmp_path):
        path = self._write(
            tmp_path, {"interpet": {"provider": "openai", "model_id": "gpt-4o-mini"}}
        )
        with pytest.raises(ValueError, match=r"llm_config: unknown configuration keys"):
            self._cli_load(path)

    def test_misspelled_nested_route_key_is_refused_on_cli_path(self, tmp_path):
        path = self._write(
            tmp_path,
            {
                "tune": {
                    "planner": {"provider": "openai", "model_id": "gpt-4o-mini"},
                    "reflecter": {"provider": "openai", "model_id": "gpt-4o-mini"},
                }
            },
        )
        with pytest.raises(ValueError, match=r"llm_config\.tune.*reflecter"):
            self._cli_load(path)

    def test_misspelled_leaf_field_is_refused_on_cli_path(self, tmp_path):
        path = self._write(
            tmp_path, {"interpret": {"provder": "openai", "model_id": "gpt-4o-mini"}}
        )
        with pytest.raises(ValueError, match=r"llm_config\.interpret.*provder"):
            self._cli_load(path)

    def test_inert_underscore_keys_are_accepted_and_discarded_at_every_level(self, tmp_path):
        path = self._write(
            tmp_path,
            {
                "_comment": "annotation",
                "interpret": {"_note": "leaf", "provider": "openai", "model_id": "gpt-4o-mini"},
                "tune": {
                    "_note": "tuner",
                    "planner": {
                        "_note": "planner",
                        "provider": "openai",
                        "model_id": "gpt-4o-mini",
                    },
                },
                "judge": {
                    "aggregate": {
                        "_note": "judge",
                        "provider": "openai",
                        "model_id": "gpt-4o-mini",
                        "max_output_tokens": 400,
                        "max_retries": 2,
                    }
                },
            },
        )
        config = self._cli_load(path)
        dumped = json.dumps(config.model_dump(mode="json", by_alias=True, exclude_none=True))
        assert "_note" not in dumped and "_comment" not in dumped
        assert config.get("interpret") == {"provider": "openai", "model_id": "gpt-4o-mini"}
        assert config.judge is not None and config.judge.aggregate is not None

    def test_shipped_certify_profile_comment_key_loads_on_cli_path(self):
        path = Path(__file__).resolve().parents[3] / "configs" / "llm" / "certify_minimal.json"
        assert "_comment" in json.loads(path.read_text(encoding="utf-8"))
        config = self._cli_load(path)
        assert config.get("interpret") == {"provider": "openai", "model_id": "gpt-4o-mini"}


def test_default_config_round_trips_through_its_serialized_form():
    dumped = WorkflowLLMConfig.default().model_dump(mode="json", by_alias=True, exclude_none=True)
    again = parse_llm_config_bytes(json.dumps(dumped).encode()).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert again == dumped


def test_malformed_profile_error_never_echoes_secret_bytes():
    content = b'{"interpret": {"api_key": "sk-test-SECRET123"\n,\n}}'
    with pytest.raises(ValueError, match="not valid JSON") as info:
        parse_llm_config_bytes(content)
    assert "SECRET123" not in str(info.value)
    assert "line" in str(info.value)


@pytest.mark.parametrize(
    "payload,location",
    [
        (
            {"interpret": {"provider": "openai", "model_id": ["sk-test-SECRET123"]}},
            "interpret.model_id",
        ),
        ({"interpret": {"provider": "sk-test-SECRET123"}}, "interpret.provider"),
    ],
)
def test_wrong_typed_secret_value_error_never_echoes_the_value(payload, location):
    with pytest.raises(ValueError, match=rf"{location}: ") as info:
        parse_llm_config_bytes(json.dumps(payload).encode())
    assert "SECRET123" not in str(info.value)


@pytest.mark.parametrize(
    "payload,reason",
    [
        (
            {
                "interpret": {
                    "provider": "anthropic",
                    "model_id": "sk-test-SECRET123",
                    "reasoning_effort": "low",
                }
            },
            "reasoning_effort requires provider='openai'",
        ),
        ({"judge": {}}, "judge must declare at least one of stop, aggregate, debate"),
    ],
)
def test_validator_reason_is_reported_without_input_values(payload, reason):
    with pytest.raises(ValueError) as info:
        parse_llm_config_bytes(json.dumps(payload).encode())
    assert reason in str(info.value)
    assert "SECRET123" not in str(info.value)
