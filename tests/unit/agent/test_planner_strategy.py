"""Strategy discovery must never silently select a different experiment policy."""

import pytest

from agent import planner_strategy as strategies


def test_manual_provider_reaches_request_without_mutating_execution_schema(monkeypatch):
    """A bypassed renderer or a shared mutable input must fail at the bridge boundary."""
    from dataclasses import replace

    from agent import llm_bridge
    from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
    from tests.helpers.tuner_prompt_fixtures import planner_kwargs

    manual = {"properties": {"current_field": {"type": "integer"}}}

    def render(value):
        value.clear()
        return "Explicit experiment manual."

    selected = replace(
        strategies.resolve_planner_strategy("native-timing-v1"),
        config_manual_renderer=render,
    )
    monkeypatch.setattr(llm_bridge, "resolve_planner_strategy", lambda *a, **k: selected)
    bridge = BoundaryRecorderBridge()
    bridge.plan(**(planner_kwargs() | {"config_manual": manual}))
    assert "Explicit experiment manual." in bridge.captures[0][3]
    assert manual == {"properties": {"current_field": {"type": "integer"}}}
    selected = replace(selected, config_manual_renderer=None)
    bridge.plan(**(planner_kwargs() | {"config_manual": manual}))
    assert '"current_field"' in bridge.captures[1][3]
    assert "Explicit experiment manual." not in bridge.captures[1][3]


def test_absent_and_ambiguous_install_defaults_refuse(monkeypatch):
    for installed in ([], [object(), object()]):
        monkeypatch.setattr(
            strategies, "entry_points", lambda installed=installed, **kwargs: installed
        )
        with pytest.raises(ValueError, match="Expected one declared"):
            strategies.resolve_planner_strategy(None)


def test_explicit_selection_does_not_load_install_default(monkeypatch):
    calls = []

    def discover(**kwargs):
        calls.append(kwargs["group"])
        return []

    monkeypatch.setattr(strategies, "entry_points", discover)
    with pytest.raises(ValueError, match="missing-v3"):
        strategies.resolve_planner_strategy("missing-v3")
    assert calls == ["siderius.planner_strategies"]


def test_native_selection_is_explicit_and_never_loads_plugins(monkeypatch):
    def unexpected(**kwargs):
        pytest.fail("explicit native selection must not execute an installed plugin")

    monkeypatch.setattr(strategies, "entry_points", unexpected)
    selected = strategies.resolve_planner_strategy("native-timing-v1")
    assert selected.uses_timing_context
    assert selected.identity.name == "native-timing-v1"


def test_workspace_refuses_strategy_change_and_unverified_legacy_pin(tmp_path):
    """Missing pins must not be silently backfilled; changed providers cannot resume."""
    from core.run_invariants import RunInvariants, RunInvariantsViolation, ensure_run_invariants

    legacy = RunInvariants(
        resolved_data_scope=[0], health_gate_enabled=False, health_config_sha256=None
    )
    ensure_run_invariants(str(tmp_path), legacy)
    identity = strategies.resolve_planner_strategy("native-timing-v1").identity
    pinned = legacy.model_copy(update={"planner_strategy_identity": identity})
    original = (tmp_path / "run_invariants_lock.json").read_bytes()
    with pytest.raises(RunInvariantsViolation, match="planner_strategy_identity"):
        ensure_run_invariants(str(tmp_path), pinned)
    assert (tmp_path / "run_invariants_lock.json").read_bytes() == original
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    ensure_run_invariants(str(fresh), pinned)
    assert ensure_run_invariants(str(fresh), pinned) == "validated"
    changed = pinned.model_copy(
        update={
            "planner_strategy_identity": identity.model_copy(update={"content_sha256": "f" * 64})
        }
    )
    with pytest.raises(RunInvariantsViolation, match="planner_strategy_identity"):
        ensure_run_invariants(str(fresh), changed)


def test_changed_strategy_is_refused_before_provider_call():
    """Preflight identity must reach the bridge and gate its actual provider boundary."""
    from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
    from tests.helpers.tuner_prompt_fixtures import planner_kwargs

    identity = strategies.resolve_planner_strategy("native-timing-v1").identity
    bridge = BoundaryRecorderBridge()
    with pytest.raises(ValueError, match="changed after run preflight"):
        bridge.plan(
            **(
                planner_kwargs()
                | {
                    "planner_strategy": "native-timing-v1",
                    "expected_planner_strategy": identity.model_copy(
                        update={"content_sha256": "f" * 64}
                    ),
                }
            )
        )
    assert bridge.captures == []


def test_source_digest_covers_helpers_and_ignores_insertion_order():
    """A helper edit must change identity even if its top-level template is unchanged."""
    from core.planner_strategy_identity import source_fingerprint

    old = source_fingerprint({"template": b"prompt", "helper": b"old"})
    assert old == source_fingerprint({"helper": b"old", "template": b"prompt"})
    assert old != source_fingerprint({"template": b"prompt", "helper": b"new"})


def test_conditional_provider_system_text_reaches_final_request(monkeypatch):
    """Bypassing the provider hook must lose its task-dependent text and fail."""
    from dataclasses import replace

    from agent import llm_bridge
    from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
    from tests.helpers.tuner_prompt_fixtures import planner_kwargs

    def render(template, task):
        return template.replace("{STRATEGY}", "Recorded scope: " + task.score_field_noun)

    selected = replace(
        strategies.resolve_planner_strategy("native-timing-v1"),
        system_template="{STRATEGY}\n{TASK_DESCRIPTION}",
        system_renderer=render,
    )
    monkeypatch.setattr(llm_bridge, "resolve_planner_strategy", lambda *a, **k: selected)
    bridge = BoundaryRecorderBridge()
    arguments = planner_kwargs() | {"task_description": "Declared fixture task."}
    bridge.plan(**arguments)
    assert len(bridge.captures) == 1
    assert bridge.captures[0][2] == "Recorded scope: metric\nDeclared fixture task."

    selected = replace(selected, system_renderer=lambda template, task: None)
    with pytest.raises(TypeError, match="string system template"):
        bridge.plan(**arguments)
    assert len(bridge.captures) == 1


@pytest.mark.parametrize(
    "filename",
    [
        "certify_minimal.json",
        "deepseek_tiered_pro.json",
        "openai_tiered_pro.json",
        "openai_tiered_v1.json",
    ],
)
def test_shipped_routing_configs_work_without_experiment_plugins(monkeypatch, filename):
    """Removing the explicit selector from an example must fail in a clean install."""
    from pathlib import Path

    from workflows.llm_config import WorkflowLLMConfig

    monkeypatch.setattr(strategies, "entry_points", lambda **kwargs: [])
    path = Path(__file__).resolve().parents[3] / "configs" / "llm" / filename
    config = WorkflowLLMConfig.model_validate_json(path.read_text())
    assert config.tune is not None
    selected = strategies.resolve_planner_strategy(config.tune.planner_strategy)
    assert selected.identity.name == "native-timing-v1"
