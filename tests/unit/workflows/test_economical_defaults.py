"""Omission routes to Luna without overriding explicit or inherited choices."""

import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from agent import planner_strategy as strategies
from core.layout import checkout_root
from tools.setup_review.routes import standard_llm_routes
from workflows.llm_config import WorkflowLLMConfig, resolve_standard_llm_config


def resolve(**overrides):
    return resolve_standard_llm_config(
        Namespace(
            **{
                "llm_config": None,
                "llm_model": None,
                "reflect_provider": None,
                "reflect_model_id": None,
                **overrides,
            }
        )
    )


def test_default_all_eleven_actual_routes_and_export():
    config = resolve()
    routes = standard_llm_routes(
        config, literature_enabled=True, analysis_enabled=True, pseudo_llm=False
    )
    assert len(routes) == 11
    for route in routes:
        assert route.transport.provider == "openai"
        assert route.transport.model_id == "gpt-5.6-luna"
        assert route.transport.reasoning_effort == "medium"
        assert route.transport.max_retries == 1
    exported = json.loads((checkout_root() / "configs/llm/default.json").read_text())
    assert exported == config.model_dump(mode="json", by_alias=True, exclude_none=True)
    config.tune.planner.model_id = "explicit-change"
    assert config.tune.reflector.model_id == "gpt-5.6-luna"
    assert config.interpret.model_id == "gpt-5.6-luna"


@pytest.mark.parametrize(
    "profile",
    [
        "automatic",
        "legacy",
        *sorted(p.name for p in (checkout_root() / "configs/llm").glob("*.json")),
    ],
)
def test_shipped_profile_resolves_one_planner_on_clean_install(profile, monkeypatch):
    """Issue #1034: a framework-built or shipped profile omitting the planner refused.

    A clean install declares no ``siderius.planner_strategy_defaults`` entry point,
    so an omitted selection finds zero providers and the run refuses before planning.
    """

    def clean_install(**kwargs):
        return []

    monkeypatch.setattr(strategies, "entry_points", clean_install)
    if profile == "automatic":
        config = WorkflowLLMConfig.default()
    elif profile == "legacy":
        config = WorkflowLLMConfig.uniform("gemini", "legacy-model")
    else:
        config = WorkflowLLMConfig.from_json(str(checkout_root() / "configs/llm" / profile))
    assert config.tune is not None
    selected = strategies.resolve_planner_strategy(config.tune.planner_strategy)
    assert selected.identity.name == "native-timing-v1"


def test_explicit_file_precedes_legacy_and_preserves_inheritance(tmp_path):
    path = tmp_path / "custom.json"
    payload = {"interpret": {"provider": "gemini", "model_id": "explicit", "max_retries": None}}
    path.write_text(json.dumps(payload))
    cfg = resolve(llm_config=str(path), llm_model="ignored")
    assert cfg.get("data_analysis")["model_id"] == "explicit"
    assert cfg.get("lit_review")["llm_model_id"] == "explicit"
    assert cfg.get("interpret").get("reasoning_effort") is None
    assert cfg.get("tune") == {}


def test_explicit_legacy_gemini_and_reflector_override():
    cfg = resolve(llm_model="gemini-explicit")
    assert cfg.get("tune")["model_id"] == "gemini-explicit"
    assert cfg.get("tune")["reflect_model_id"] == "gemini-2.5-flash"
    cfg = resolve(reflect_provider="deepseek")
    assert cfg.get("tune")["model_id"] == "gpt-5.6-luna"
    assert cfg.get("tune")["reflect_model_id"] == "deepseek-v4-pro"


def test_shell_omits_model_until_explicitly_selected():
    source = checkout_root() / "scripts/launch/_chain_common.sh"
    script = (
        f'source "{source}"\nSOURCE_PATHS=()\nbuild_app_args 1\nprintf "%s\\n" "${{APP_ARGS[@]}}"'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert "--llm_model" not in result.stdout.splitlines()
    result = subprocess.run(
        ["bash", "-c", script.replace("build_app_args 1", "LLM_MODEL=chosen\nbuild_app_args 1")],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.splitlines()
    assert lines[lines.index("--llm_model") + 1] == "chosen"
