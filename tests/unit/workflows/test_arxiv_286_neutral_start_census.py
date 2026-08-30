"""arXiv #286 — a fresh project starts NEUTRAL: the scripted grep-level census.

The paper's claim family (discussion (13): manifest omission-vs-named-absence
semantics; the zero-framework-edit contract): a user composing their OWN
minimal package must inherit no TIDMAD-specific registration, default, or
value. The quickstart pack is exactly that minimal fresh project, so the
census composes it and sweeps the composition's ENTIRE semantic surface for
anchor-task residue. A temporary quickstart variant injects the exact anchor
token as the NEGATIVE CONTROL, proving the sweep can see such residue without
making this framework-contract test depend on a shipped scientific task.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
QUICKSTART = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"
QUICKSTART_TASK_CONFIG = REPO_ROOT / "examples" / "quickstart" / "declared" / "task_config.yaml"
DECLARED_NAMING_TASK = REPO_ROOT / "tests" / "fixtures" / "fcov8_declared_naming_task.py"

ANCHOR_TOKENS = ("tidmad", "abra", "denoising_score")


def _semantic_surface(manifest: Path) -> str:
    """Every semantic value the composition carries, as one lowercase blob."""
    from execute_tools.task_registration_scope import run_registration_scope
    from workflows.task_composition import compose_run_task_bindings

    with run_registration_scope():
        comp = compose_run_task_bindings(str(manifest))
    surface = {
        "task_data_path_id": comp.task_data_path_id,
        "metric": comp.metric.spec.model_dump(mode="json"),
        "task_health_binding": str(comp.task_health_binding),
        "task_description": comp.task_description,
        "forward_contract": comp.forward_contract.model_dump(mode="json"),
        "dataset_profile": comp.dataset_profile.to_wire(),
        "deliverable_naming": (
            comp.deliverable_naming.model_dump(mode="json")
            if comp.deliverable_naming is not None
            else None
        ),
        "fingerprint": comp.semantic_fingerprint,
    }
    return json.dumps(surface, sort_keys=True).lower()


def _quickstart_variant(tmp_path: Path, mutate) -> Path:
    """Write a checkout-portable quickstart variant under ``tmp_path``.

    Composition references are relative to the manifest, so moving the YAML
    without resolving them would test path failure rather than the semantic
    change. Only the pack-owned reference prefix moves; every declared value
    and plugin remains the quickstart's own.
    """
    payload = yaml.safe_load(QUICKSTART.read_text(encoding="utf-8"))

    def resolve_refs(value):
        if isinstance(value, dict):
            return {key: resolve_refs(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve_refs(item) for item in value]
        if isinstance(value, str) and value.startswith("../../examples/"):
            return str((QUICKSTART.parent / value).resolve())
        return value

    payload = resolve_refs(payload)
    # Give every temporary variant its own already-generic data-path identity.
    # This avoids colliding with a quickstart registration another test may
    # legitimately have established earlier in the same pytest process.
    payload["task_data_path"] = {
        "file": str(DECLARED_NAMING_TASK),
        "symbol": "DeclaredNamingTaskDataPath",
        "id": "fcov8_declared_naming_task",
    }
    payload.pop("model_plugins", None)
    mutate(payload)
    manifest = tmp_path / "composition.yaml"
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return manifest


def test_a_fresh_minimal_project_carries_zero_anchor_task_residue():
    """The #286 acceptance, executable — the defect only this catches: a
    TIDMAD-shaped default (metric id, naming template, health family,
    topology, description prose) silently reaching a composition that never
    declared it. Fails by: any anchor token appearing anywhere in the
    quickstart composition's semantic surface."""
    surface = _semantic_surface(QUICKSTART)
    hits = [t for t in ANCHOR_TOKENS if t in surface]
    assert not hits, (
        f"anchor-task residue {hits} reached a FRESH project's composition — "
        "a default the manifest never declared is leaking (issue #286)"
    )


def test_the_census_can_see_residue_the_negative_control(tmp_path: Path):
    """The anti-decoration leg — the defect only this catches: the sweep
    itself going blind (a surface field dropped from `_semantic_surface`, a
    token list typo), leaving the positive test green for the wrong reason.
    The control injects the exact anchor token into a field already included
    in the semantic surface. Fails by: the injected composition sweeping
    clean."""

    def inject_anchor(payload):
        task_config = yaml.safe_load(QUICKSTART_TASK_CONFIG.read_text(encoding="utf-8"))
        task_config["task_description"] = "tidmad negative-control task"
        path = tmp_path / "task_config.yaml"
        path.write_text(yaml.safe_dump(task_config, sort_keys=False), encoding="utf-8")
        payload["task_config"]["config"] = str(path)

    manifest = _quickstart_variant(tmp_path, inject_anchor)
    surface = _semantic_surface(manifest)
    assert "tidmad" in surface, "the negative control did not fire — the census is blind"


def test_fresh_project_naming_is_its_own_declaration_not_the_anchor_template():
    """The #268-consistency leg, case DECLARED — the defect only this
    catches: a fresh project's EXPLICIT `deliverable:` declaration being
    overridden or defaulted back to the anchor task's indexed template. The
    quickstart declares its own naming (the #268-consistent explicit form —
    a finding of writing this census: the premise 'quickstart declares none'
    was wrong, and the declared state is the BETTER neutral-start witness).
    Fails by: the composed naming carrying the anchor prefix or vanishing."""
    from execute_tools.task_registration_scope import run_registration_scope
    from workflows.task_composition import compose_run_task_bindings

    with run_registration_scope():
        comp = compose_run_task_bindings(str(QUICKSTART))
    assert comp.deliverable_naming is not None
    assert comp.deliverable_naming.prefix.startswith("quickstart"), comp.deliverable_naming
    assert not comp.deliverable_naming.prefix.startswith("denoised")


def test_own_naming_task_without_declaration_is_refused_the_anchor_template(tmp_path: Path):
    """The #268-consistency leg, case REFUSED (F-A4-1) — the defect only
    this catches: the four-state rule regressing so an own-naming task with
    NO declaration silently receives the anchor task's indexed template plus
    its deletion-capable cleanup glob (discussion (13)'s reported defect, in
    its repaired form). A quickstart variant with its declaration removed is
    the task-neutral witness. Fails by: `resolve_deliverable_naming` returning
    anything instead of the named refusal."""

    from execute_tools.deliverable_spec import (
        DeliverableNamingNotApplicableError,
        resolve_deliverable_naming,
    )
    from execute_tools.task_registration_scope import run_registration_scope
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    manifest = _quickstart_variant(tmp_path, lambda payload: payload.pop("deliverable"))
    with run_registration_scope():
        comp = compose_run_task_bindings(str(manifest))
    assert comp.deliverable_naming is None
    with bind_run_task_composition(comp, physical_data_root=str(REPO_ROOT)):
        with pytest.raises(DeliverableNamingNotApplicableError):
            resolve_deliverable_naming()
