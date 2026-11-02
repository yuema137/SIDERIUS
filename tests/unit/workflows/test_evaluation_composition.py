"""Evaluation opt-in must bind semantics and refuse unimplemented launches (#1292)."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
import yaml

from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    validate_run_invariants,
    write_run_invariants,
)
from execute_tools.evaluation_registry import (
    ComponentKindRegistration,
    ComponentRenderContext,
    EvaluationLoadContext,
    ResolvedComponent,
    builtin_registry,
)
from execute_tools.evaluation_spec import ComponentSpec, EvaluationSpec
from execute_tools.task_registration_scope import run_registration_scope
from workflows.evaluation_composition import _identity, compose_evaluation
from workflows.task_composition import (
    TaskCompositionError,
    bind_run_task_composition,
    compose_run_task_bindings,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/step10_p1/fourth_task"


@pytest.fixture(autouse=True)
def isolated_registration():
    with run_registration_scope():
        yield


@pytest.fixture
def task(tmp_path):
    path = tmp_path / "task"
    shutil.copytree(FIXTURE, path)
    return path


def declaration(task):
    manifest = yaml.safe_load((task / "composition.yaml").read_text())
    metric = json.loads((task / manifest["metric"]["declaration"]).read_text())["id"]
    return {
        "components": [
            {
                "kind": "metric",
                "id": "quality",
                "metric": metric,
                "meaning": "Coverage of the evaluation bands.",
            }
        ],
        "selection": {"kind": "primary"},
    }


def compose(task, evaluation):
    path = task / "composition.yaml"
    manifest = yaml.safe_load(path.read_text())
    if evaluation is None:
        manifest.pop("evaluation", None)
    else:
        manifest["evaluation"] = evaluation
    path.write_text(yaml.safe_dump(manifest))
    return compose_run_task_bindings(str(path))


@pytest.mark.parametrize("field", ["meaning", "units", "guidance", "components", "constraints"])
def test_oversized_author_fields_refuse_composition_before_component_loading(
    task, monkeypatch, field
):
    """Public composition errors retain field names and never reach plugin loaders."""
    raw = declaration(task)
    if field in ("meaning", "units"):
        raw["components"][0][field] = "x" * (1001 if field == "meaning" else 129)
    elif field == "guidance":
        raw["selection"] = {
            "kind": "rubric_balance",
            "rubric": {"id": "unused", "version": "1"},
            "guidance": "x" * 1001,
            "deterministic_ranking": {"kind": "primary"},
        }
    elif field == "components":
        raw["components"] = [dict(raw["components"][0], id=f"quality_{i}") for i in range(33)]
    else:
        raw["constraints"] = [{"component": "quality", "op": ">", "threshold": 0.0}] * 65
    registry = builtin_registry()
    loaded = []
    original = registry["metric"].load

    def load(component, context):
        loaded.append(component.id)
        return original(component, context)

    registry["metric"] = replace(registry["metric"], load=load)
    monkeypatch.setattr("workflows.evaluation_composition.builtin_registry", lambda: registry)
    with pytest.raises(TaskCompositionError, match=field):
        compose(task, raw)
    assert not loaded


def formula(evaluation):
    evaluation["selection"] = {
        "kind": "formula",
        "formula": {
            "family": "weighted_sum",
            "params": {
                "terms": [
                    {
                        "component": "quality",
                        "weight": 2.0,
                        "lower": 0.0,
                        "upper": 10.0,
                        "out_of_range": "refuse",
                    }
                ]
            },
        },
    }
    return evaluation


def test_composes_but_launch_names_every_missing_capability(task, tmp_path):
    """The real binding boundary must not silently execute a primary-only fallback."""
    plain = compose(task, None)
    with bind_run_task_composition(plain, physical_data_root=str(tmp_path)):
        pass
    spec = formula(declaration(task))
    spec["constraints"] = [{"component": "quality", "op": ">=", "threshold": 1.0}]
    composed = compose(task, spec)
    assert composed.evaluation is not None
    assert composed.metric.spec == plain.metric.spec
    with pytest.raises(TaskCompositionError) as error:
        with bind_run_task_composition(composed, physical_data_root=str(tmp_path)):
            pytest.fail("unimplemented evaluation launched")
    for name in (
        "composition succeeded",
        "feasibility constraints",
    ):
        assert name in str(error.value)


@pytest.mark.parametrize("mutation", ["meaning", "constraint", "weight", "remove"])
def test_evaluation_only_change_refuses_real_resume(task, tmp_path, mutation):
    """Metric identity can stay fixed while scientific evaluation changes."""
    spec = formula(declaration(task))
    before = compose(task, spec)
    lock = RunInvariants(
        resolved_data_scope=[0],
        health_gate_enabled=False,
        health_config_sha256=None,
        task_composition_fingerprint=before.semantic_fingerprint,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_run_invariants(str(workspace), lock)
    if mutation == "meaning":
        spec["components"][0]["meaning"] = "A different scientific interpretation."
    elif mutation == "constraint":
        spec["constraints"] = [{"component": "quality", "op": ">", "threshold": 1.0}]
    elif mutation == "weight":
        spec["selection"]["formula"]["params"]["terms"][0]["weight"] = 3.0
    else:
        spec = None
    after = compose(task, spec)
    assert before.metric.spec == after.metric.spec
    with pytest.raises(RunInvariantsViolation, match="task_composition_fingerprint"):
        validate_run_invariants(
            str(workspace),
            lock.model_copy(update={"task_composition_fingerprint": after.semantic_fingerprint}),
        )


@pytest.mark.parametrize("reference", ["metric", "formula", "constraint"])
def test_cross_declaration_references_refuse(task, reference):
    """Pydantic accepts these strings; the composer must resolve their targets."""
    spec = formula(declaration(task))
    if reference == "metric":
        spec["components"][0]["metric"] = "missing"
    elif reference == "formula":
        spec["selection"]["formula"]["params"]["terms"][0]["component"] = "missing"
    else:
        spec["constraints"] = [{"component": "missing", "op": ">=", "threshold": 0.0}]
    with pytest.raises(TaskCompositionError, match="undeclared"):
        compose(task, spec)


def test_inspection_distinguishes_descriptive_range_from_normalization(task):
    """A component range must not silently replace term bounds or reverse constraints."""
    spec = formula(declaration(task))
    spec["components"][0]["range"] = {"lower": -100.0, "upper": 100.0}
    spec["constraints"] = [{"component": "quality", "op": ">=", "threshold": 1.0}]
    composed = compose(task, spec)
    assert composed.evaluation is not None
    view = composed.evaluation.inspect()
    assert view["marginal_rates"][0]["utility_per_raw_unit_exact"] == "-1/10"
    assert "opposes" in view["warnings"][0]
    spec["constraints"].append({"component": "quality", "op": "<", "threshold": 1.0})
    with pytest.raises(TaskCompositionError, match="no feasible value"):
        compose(task, spec)


PLUGIN = """from typing import Literal
from execute_tools.evaluation_spec import ComponentSpec
from execute_tools.evaluation_registry import ComponentKindRegistration, ResolvedComponent
class Energy(ComponentSpec):
    kind: Literal["energy"]
    scale: float = 1.0
def load(component, context):
    return ResolvedComponent(direction="lower", identity={"protocol": "energy-v1"})
def fingerprint(component, resolved):
    return dict(resolved.identity)
def render(component, context):
    return "Energy: " + component.meaning
KIND = ComponentKindRegistration("energy", "1", Energy, load, fingerprint, render,
                                 "quantitative", frozenset({"measurements"}))
"""


def plugin_spec(task):
    (task / "kind.py").write_text(PLUGIN)
    spec = declaration(task)
    spec["component_kinds"] = {"energy": {"file": "kind.py", "symbol": "KIND"}}
    spec["components"].append(
        {"kind": "energy", "id": "energy", "meaning": "Joules per inference."}
    )
    return spec


def test_user_kind_hooks_identity_and_isolation(task, tmp_path):
    """One registration extends validation/render dispatch and carries actual code pins."""
    spec = plugin_spec(task)
    before = compose(task, spec)
    evaluation = before.evaluation
    assert evaluation is not None
    component = evaluation.spec.components[1]
    assert evaluation.registry["energy"].render(component, ComponentRenderContext()) == (
        "Energy: Joules per inference."
    )
    assert "measurements" in evaluation.required_capabilities
    relocated = tmp_path / "relocated"
    shutil.copytree(task, relocated)
    moved = compose_evaluation(
        {"evaluation": spec}, str(relocated), {before.metric.spec.id: before.metric.spec}, None
    )
    assert moved is not None
    assert moved.canonical_identity == evaluation.canonical_identity
    (task / "kind.py").write_text(PLUGIN.replace("energy-v1", "energy-v2"))
    changed = compose(task, spec)
    assert changed.semantic_fingerprint != before.semantic_fingerprint
    del spec["component_kinds"]
    with pytest.raises(TaskCompositionError, match="energy"):
        compose(task, spec)


@pytest.mark.parametrize("bad", ["path", "schema"])
def test_plugin_registration_and_contribution_cannot_weaken_contract(task, bad):
    spec = plugin_spec(task)
    source = PLUGIN
    if bad == "path":
        source = source.replace('"energy-v1"', '"/host/private/energy"')
        message = "absolute host paths"
    else:
        source = source.replace("    scale: float = 1.0", '    model_config = {"extra": "allow"}')
        message = "extra=forbid"
    (task / "kind.py").write_text(source)
    with pytest.raises(TaskCompositionError, match=message):
        compose(task, spec)


def test_defaulted_schema_extension_keeps_evaluation_identity():
    """Changing schema shape alone must not serialize a new default into identity."""

    class Old(ComponentSpec):
        kind: Literal["custom"]

    class New(Old):
        precision: int = 3

    registry = builtin_registry()
    registry["custom"] = ComponentKindRegistration(
        "custom",
        "1",
        Old,
        lambda c, x: ResolvedComponent(),
        lambda c, r: {},
        lambda c, x: c.meaning,
        "rubric",
    )
    payload = {
        "components": [{"kind": "custom", "id": "a", "meaning": "Meaning"}],
        "selection": {"kind": "primary"},
    }
    from execute_tools.evaluation_registry import component_adapter

    old = EvaluationSpec.model_validate(
        payload, context={"component_adapter": component_adapter(registry)}
    )
    registry["custom"] = replace(registry["custom"], schema=New)
    new = EvaluationSpec.model_validate(
        payload, context={"component_adapter": component_adapter(registry)}
    )
    ctx = EvaluationLoadContext({}, None, lambda ref, role: (None, {}))
    resolved = {"a": ResolvedComponent()}
    assert _identity(old, registry, resolved, {}, ctx) == _identity(
        new, registry, resolved, {}, ctx
    )


def test_scoring_child_cannot_bypass_launch_capability_guard(task):
    """Direct scoring entry must not ignore an evaluation declared by its manifest."""
    from workflows.task_composition import compose_metric_from_manifest

    compose(task, declaration(task))
    assert compose_metric_from_manifest(str(task / "composition.yaml")).spec.id
    spec = formula(declaration(task))
    spec["constraints"] = [{"component": "quality", "op": ">=", "threshold": 1.0}]
    compose(task, spec)
    with pytest.raises(TaskCompositionError, match="feasibility constraints"):
        compose_metric_from_manifest(str(task / "composition.yaml"))


def test_rubric_resolution_pins_content_and_never_enters_formula(task):
    """Optional digest syntax must resolve identically and reject mismatching evidence."""
    from agent.schemas.judge_task import RubricSpec, rubric_sha256

    rubric = {
        "schema_version": "siderius.rubric/v1",
        "id": "quality",
        "version": "1",
        "criteria": [{"name": "usefulness", "description": "Useful scientifically", "weight": 1.0}],
        "scale_min": 1,
        "scale_max": 5,
    }
    (task / "rubric.yaml").write_text(yaml.safe_dump(rubric))
    manifest_path = task / "composition.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["rubrics"] = [{"config": "rubric.yaml"}]
    manifest_path.write_text(yaml.safe_dump(manifest))
    spec = declaration(task)
    spec["components"].append(
        {
            "kind": "rubric",
            "id": "judgment",
            "meaning": "Scientific usefulness",
            "rubric": {"id": "quality", "version": "1"},
        }
    )
    spec["selection"] = {
        "kind": "rubric_balance",
        "rubric": {"id": "quality", "version": "1"},
        "guidance": "Balance usefulness and measured coverage.",
        "deterministic_ranking": {"kind": "primary"},
    }
    implicit = compose(task, spec)
    digest = rubric_sha256(RubricSpec.model_validate(rubric))
    spec["components"][1]["rubric"]["sha256"] = digest
    spec["selection"]["rubric"]["sha256"] = digest
    explicit = compose(task, spec)
    assert implicit.semantic_fingerprint == explicit.semantic_fingerprint
    assert explicit.evaluation is not None
    assert {"rubric balancing", "rubric components"} <= explicit.evaluation.required_capabilities
    spec["selection"]["rubric"]["sha256"] = "0" * 64
    with pytest.raises(TaskCompositionError, match="digest"):
        compose(task, spec)
    formula(spec)
    spec["selection"]["formula"]["params"]["terms"][0]["component"] = "judgment"
    with pytest.raises(TaskCompositionError, match="not deterministic"):
        compose(task, spec)


def test_contributor_nonfinite_identity_refuses_at_composition(task):
    """JSON-like plugin output must not inject nonstandard NaN into a run fingerprint."""
    spec = plugin_spec(task)
    (task / "kind.py").write_text(
        PLUGIN.replace("return dict(resolved.identity)", "return {\"noise\": float('nan')}")
    )
    with pytest.raises(TaskCompositionError, match="JSON"):
        compose(task, spec)


@pytest.mark.parametrize("manifest", sorted((ROOT / "configs/task_composition").glob("*.yaml")))
def test_absent_evaluation_adds_no_fingerprint_input(manifest, monkeypatch):
    """Real framework manifests must not gain an evaluation=null identity entry."""
    from workflows import task_composition as owner

    captured = []
    canonical = owner._canonical

    def capture(payload):
        if isinstance(payload, dict) and "metric_declaration" in payload:
            captured.append(payload)
        return canonical(payload)

    monkeypatch.setattr(owner, "_canonical", capture)
    result = owner.compose_run_task_bindings(str(manifest))
    assert result.evaluation is None
    assert len(captured) == 1
    assert "evaluation" not in captured[0]


@pytest.mark.parametrize(
    "fields",
    [
        "    scale: float = Field(default=1.0, exclude=True)",
        "    scale: float = Field(default=1.0, exclude_if=lambda value: True)",
        '    scale: float = 1.0\n    @field_serializer("scale")\n'
        "    def hide_scale(self, value):\n        return 1.0",
        "    scale: float = 1.0\n    @model_serializer\n"
        '    def hide_scale(self):\n        return {"kind": "energy"}',
        "    scale: Annotated[float, PlainSerializer(lambda value: 1.0)] = 1.0",
        "    details: Hidden = Field(default_factory=Hidden)",
    ],
)
def test_plugin_cannot_hide_evaluation_changes_from_resume_identity(task, fields):
    """Without registration refusal, a scale-only edit can retain the resume digest."""
    spec = plugin_spec(task)
    imports = (
        "from typing import Annotated\n"
        "from pydantic import BaseModel, Field, PlainSerializer, field_serializer, model_serializer\n"
        "class Hidden(BaseModel):\n"
        "    scale: float = Field(default=1.0, exclude=True)\n"
    )
    (task / "kind.py").write_text(imports + PLUGIN.replace("    scale: float = 1.0", fields))
    for scale in (1.0, 50.0):
        component = spec["components"][1]
        if "details:" in fields:
            component["details"] = {"scale": scale}
        else:
            component["scale"] = scale
        with pytest.raises(TaskCompositionError, match="must not exclude fields or use custom"):
            compose(task, spec)


def test_plugin_programming_error_is_not_reclassified_as_configuration(task):
    """Unexpected hook failures retain their type and traceback for debugging."""
    spec = plugin_spec(task)
    source = PLUGIN.replace(
        'return ResolvedComponent(direction="lower", identity={"protocol": "energy-v1"})',
        'raise RuntimeError("broken plugin implementation")',
    )
    (task / "kind.py").write_text(source)
    with pytest.raises(RuntimeError, match="broken plugin implementation"):
        compose(task, spec)


def test_primary_evaluation_binds_prompt_context_and_refuses_lost_binding(task, tmp_path):
    from agent.evaluation_context import bind_evaluation_prompt_context
    from agent.prompt_templates.constraints import append_constraint_disclosure
    from workflows.task_composition import CompositionNotBoundError, verify_composition_is_bound

    composed = compose(task, declaration(task))
    with bind_run_task_composition(composed, physical_data_root=str(tmp_path)):
        verify_composition_is_bound(composed)
        assert "Coverage of the evaluation bands." in append_constraint_disclosure("prompt", None)
        with bind_evaluation_prompt_context(None, composed.metric.spec, None):
            with pytest.raises(CompositionNotBoundError, match="evaluation"):
                verify_composition_is_bound(composed)
    assert "[TASK EVALUATION]" not in append_constraint_disclosure("prompt", None)
