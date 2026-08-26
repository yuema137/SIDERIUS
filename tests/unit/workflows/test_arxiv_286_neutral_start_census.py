"""arXiv #286 — a fresh project starts NEUTRAL: the scripted grep-level census.

The paper's claim family (discussion (13): manifest omission-vs-named-absence
semantics; the zero-framework-edit contract): a user composing their OWN
minimal package must inherit no TIDMAD-specific registration, default, or
value. The quickstart pack is exactly that minimal fresh project, so the
census composes it and sweeps the composition's ENTIRE semantic surface for
anchor-task residue — with the shipped TIDMAD manifest as the built-in
NEGATIVE CONTROL proving the sweep can actually see such residue (a census
that cannot fire is decoration; the F-12bc-9 family).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

ANCHOR_TOKENS = ("tidmad", "abra", "denoising_score")


def _semantic_surface(manifest: str) -> str:
    """Every semantic value the composition carries, as one lowercase blob."""
    from workflows.task_composition import compose_run_task_bindings

    comp = compose_run_task_bindings(str(REPO_ROOT / manifest))
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


def test_a_fresh_minimal_project_carries_zero_anchor_task_residue():
    """The #286 acceptance, executable — the defect only this catches: a
    TIDMAD-shaped default (metric id, naming template, health family,
    topology, description prose) silently reaching a composition that never
    declared it. Fails by: any anchor token appearing anywhere in the
    quickstart composition's semantic surface."""
    surface = _semantic_surface("configs/task_composition/quickstart.yaml")
    hits = [t for t in ANCHOR_TOKENS if t in surface]
    assert not hits, (
        f"anchor-task residue {hits} reached a FRESH project's composition — "
        "a default the manifest never declared is leaking (issue #286)"
    )


def test_the_census_can_see_residue_the_negative_control():
    """The anti-decoration leg — the defect only this catches: the sweep
    itself going blind (a surface field dropped from `_semantic_surface`, a
    token list typo), leaving the positive test green for the wrong reason.
    The shipped TIDMAD manifest MUST trip every token class it genuinely
    carries. Fails by: the anchor manifest sweeping clean."""
    surface = _semantic_surface("configs/task_composition/tidmad.yaml")
    assert "tidmad" in surface, "the negative control did not fire — the census is blind"


def test_fresh_project_naming_is_its_own_declaration_not_the_anchor_template():
    """The #268-consistency leg, case DECLARED — the defect only this
    catches: a fresh project's EXPLICIT `deliverable:` declaration being
    overridden or defaulted back to the anchor task's indexed template. The
    quickstart declares its own naming (the #268-consistent explicit form —
    a finding of writing this census: the premise 'quickstart declares none'
    was wrong, and the declared state is the BETTER neutral-start witness).
    Fails by: the composed naming carrying the anchor prefix or vanishing."""
    from workflows.task_composition import compose_run_task_bindings

    comp = compose_run_task_bindings(
        str(REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml")
    )
    assert comp.deliverable_naming is not None
    assert comp.deliverable_naming.prefix.startswith("quickstart"), comp.deliverable_naming
    assert not comp.deliverable_naming.prefix.startswith("denoised")


def test_own_naming_task_without_declaration_is_refused_the_anchor_template():
    """The #268-consistency leg, case REFUSED (F-A4-1) — the defect only
    this catches: the four-state rule regressing so an own-naming task with
    NO declaration silently receives the anchor task's indexed template plus
    its deletion-capable cleanup glob (discussion (13)'s reported defect, in
    its repaired form). Pets is the shipped instance of this state. Fails
    by: `resolve_deliverable_naming` returning anything instead of the named
    refusal."""
    import pytest

    from execute_tools.deliverable_spec import (
        DeliverableNamingNotApplicableError,
        resolve_deliverable_naming,
    )
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    comp = compose_run_task_bindings(str(REPO_ROOT / "configs" / "task_composition" / "pets.yaml"))
    assert comp.deliverable_naming is None
    with bind_run_task_composition(comp, physical_data_root=str(REPO_ROOT)):
        with pytest.raises(DeliverableNamingNotApplicableError):
            resolve_deliverable_naming()
