"""Task-declared judge guidance and rubrics (``judge_blocks:`` / ``rubrics:``).

Defects caught here:

1. Fingerprint churn: a manifest declaring neither section must keep the
   semantic payload it had before these sections existed. Pinned against a
   value captured at base ``69a9d81a`` (not recomputed here).
2. Silent rebinding: a rubric whose content changed must not satisfy a
   reference to its old digest.
3. Ambiguous criteria: duplicate criterion names make per-criterion integers
   unattributable and must fail composition.
4. Unpinned declaration files: a rubric edited between review and launch must
   be visible to the reviewed-launch binding.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pytest
import yaml

from agent.schemas.judge_task import RubricRefError, resolve_rubric_ref
from execute_tools.task_registration_scope import run_registration_scope
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
FOURTH_TASK = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task"

#: sha256 of the fourth_task semantic payload WITHOUT ``preflight_estimator``,
#: captured at base ``69a9d81a`` before this change. The estimator identity is
#: excluded because its assembly digest hashes framework source files
#: (including ``workflows/task_composition.py``) and so moves on any edit there.
PRE_JUDGE_TASK_PAYLOAD_SHA256 = "26e32a7cf59466257955a25dd7efca03bf6bda75b236dbdb28c7261adedff178"

RUBRIC = {
    "schema_version": "siderius.rubric/v1",
    "id": "plausibility",
    "version": "1",
    "scale_min": 1,
    "scale_max": 5,
    "criteria": [
        {"name": "physical_consistency", "description": "Respects conservation.", "weight": 2},
        {"name": "novelty", "description": "Differs from earlier candidates.", "weight": 1.0},
    ],
}


def _pack(tmp_path: Path, **sections: object) -> Path:
    root = tmp_path / "fourth_task"
    shutil.copytree(FOURTH_TASK, root)
    manifest = root / "composition.yaml"
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    raw.update(sections)
    manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    return manifest


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _compose(manifest: Path):
    with run_registration_scope():
        return compose_run_task_bindings(str(manifest))


def _rubric_pack(tmp_path: Path, rubric: dict) -> tuple[Path, Path]:
    rubric_path = tmp_path / "fourth_task_rubric.yaml"
    _write(rubric_path, rubric)
    return _pack(tmp_path, rubrics=[{"config": str(rubric_path)}]), rubric_path


def test_undeclared_sections_keep_the_pre_change_semantic_payload(monkeypatch):
    import hashlib

    from workflows import task_composition

    canonical = task_composition._canonical
    captured: list[str] = []

    def capture(payload):
        legacy = {key: value for key, value in payload.items() if key != "preflight_estimator"}
        captured.append(hashlib.sha256(canonical(legacy).encode()).hexdigest())
        return canonical(payload)

    monkeypatch.setattr(task_composition, "_canonical", capture)
    composition = _compose(FOURTH_TASK / "composition.yaml")
    assert composition.judge_task is None
    assert captured == [PRE_JUDGE_TASK_PAYLOAD_SHA256]


@pytest.mark.parametrize(
    "sections", [{"judge_blocks": {"none": True}}, {"rubrics": []}], ids=["none", "empty"]
)
def test_explicitly_empty_sections_equal_absent_sections(tmp_path, sections):
    absent = _compose(_pack(tmp_path / "a"))
    empty = _compose(_pack(tmp_path / "b", **sections))
    assert empty.judge_task is None
    assert empty.semantic_fingerprint == absent.semantic_fingerprint


def test_declared_guidance_and_rubrics_join_the_fingerprint(tmp_path):
    guidance = tmp_path / "judge_blocks.yaml"
    _write(guidance, {"evaluation_guidance": "Flat residual above 1 kHz."})
    absent = _compose(_pack(tmp_path / "a")).semantic_fingerprint
    with_blocks = _compose(_pack(tmp_path / "b", judge_blocks={"config": str(guidance)}))
    assert with_blocks.judge_task is not None
    assert with_blocks.judge_task.blocks is not None
    assert with_blocks.judge_task.blocks.evaluation_guidance == "Flat residual above 1 kHz."
    assert with_blocks.semantic_fingerprint != absent

    manifest, rubric_path = _rubric_pack(tmp_path / "c", RUBRIC)
    before = _compose(manifest).semantic_fingerprint
    _write(rubric_path, {**RUBRIC, "scale_max": 7})
    assert _compose(manifest).semantic_fingerprint not in {before, absent}


def test_changed_rubric_content_refuses_the_old_reference(tmp_path):
    manifest, rubric_path = _rubric_pack(tmp_path, RUBRIC)
    declared = _compose(manifest).judge_task
    assert declared is not None
    (old_ref,) = declared.rubric_refs()
    assert resolve_rubric_ref(old_ref, declared.rubrics) == declared.rubrics[0]

    changed = {
        **RUBRIC,
        "criteria": [{**RUBRIC["criteria"][0], "weight": 3}, RUBRIC["criteria"][1]],
    }
    _write(rubric_path, changed)
    recomposed = _compose(manifest).judge_task
    assert recomposed is not None
    with pytest.raises(RubricRefError) as refused:
        resolve_rubric_ref(old_ref, recomposed.rubrics)
    assert refused.value.reason == "digest_mismatch"

    unknown = old_ref.model_copy(update={"version": "2"})
    with pytest.raises(RubricRefError) as missing:
        resolve_rubric_ref(unknown, recomposed.rubrics)
    assert missing.value.reason == "unknown_rubric"


def test_duplicate_criterion_names_are_refused(tmp_path):
    duplicate = {**RUBRIC, "criteria": [RUBRIC["criteria"][0], RUBRIC["criteria"][0]]}
    manifest, _ = _rubric_pack(tmp_path, duplicate)
    with pytest.raises(TaskCompositionError, match="criterion names must be unique"):
        _compose(manifest)


def test_one_rubric_identity_declared_twice_is_refused(tmp_path):
    first, second = tmp_path / "r1.yaml", tmp_path / "r2.yaml"
    _write(first, RUBRIC)
    _write(second, {**RUBRIC, "scale_max": 9})
    manifest = _pack(tmp_path, rubrics=[{"config": str(first)}, {"config": str(second)}])
    with pytest.raises(TaskCompositionError, match="declared more than once"):
        _compose(manifest)


def test_reviewed_launch_binding_pins_judge_declaration_files(tmp_path, monkeypatch):
    from workflows.reviewed_launch_binding import InstallationPin, capture_binding

    pin = InstallationPin(
        source_root="/qualified",
        source_head="1" * 40,
        interpreter="/qualified/.venv/bin/python",
        prefix="/qualified/.venv",
        python_version="3.12",
    )
    monkeypatch.setattr("workflows.reviewed_launch_binding.installation_pin", lambda: pin)

    guidance = tmp_path / "judge_blocks.yaml"
    _write(guidance, {"failure_signatures": "Constant output."})
    manifest, rubric_path = _rubric_pack(tmp_path, RUBRIC)
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    raw["judge_blocks"] = {"config": str(guidance)}
    manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    composition = _compose(manifest)

    args = argparse.Namespace(
        task_composition=None,
        llm_config=None,
        health_checks_config=None,
        required_runtime_profile_path=None,
        ml_lit_review_config=None,
        advice=None,
        human_advice_file=None,
    )
    binding = capture_binding(args, 1 << 20, source_paths=composition.provenance.source_paths)
    pinned = {pin.path for pin in binding.files}
    assert {str(guidance.absolute()), str(rubric_path.absolute())} <= pinned


def test_rubric_declaration_order_is_not_semantic(tmp_path):
    """Rubrics are addressed by (id, version); a positional payload would split one task in two."""
    first, second = tmp_path / "r1.yaml", tmp_path / "r2.yaml"
    _write(first, RUBRIC)
    _write(second, {**RUBRIC, "id": "rigor"})
    forward = _pack(tmp_path / "a", rubrics=[{"config": str(first)}, {"config": str(second)}])
    reverse = _pack(tmp_path / "b", rubrics=[{"config": str(second)}, {"config": str(first)}])
    assert _compose(forward).semantic_fingerprint == _compose(reverse).semantic_fingerprint


def test_rubric_scale_span_is_bounded(tmp_path):
    manifest, _ = _rubric_pack(tmp_path, {**RUBRIC, "scale_min": 0, "scale_max": 101})
    with pytest.raises(TaskCompositionError, match="scale span 101 exceeds 100"):
        _compose(manifest)
