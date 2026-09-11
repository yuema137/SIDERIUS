"""Every field the tuner emits must survive to the artifact resume reads.

V20 PR D, FU-D-9. This module exists because the same defect occurred
THREE times in one PR, each time silently:

1. `formal_comparison_reference_source` — emitted into the tuner's dicts,
   never declared on `HyperparamTuningOutput`, so Pydantic's default
   `extra="ignore"` dropped it before `run_output_*.json`.
2. the same field again at the `write_manifest` hop, which had to copy it
   across explicitly.
3. `scientific_authority` — written onto the formal record by D-C2b, never
   declared on `ExperimentRecord`, so it vanished when `all_records` was
   validated. D-C2b's "tamper-evident, recomputable" property was
   unimplemented in the persisted form, and D-C4 could not function.

None of them failed a test. A dropped field is indistinguishable from a
field that was never set, so every per-field test kept passing while the
transport was broken.

**This is transport/reachability validation, not an immutability claim.**
The rule it enforces spans models and therefore cannot be expressed in any
single field's test: *a value the producer writes must be readable at the
consumer's end of the real path.* It is asserted by pushing a value
through the actual production boundaries and reading it back out of the
actual artifact — never by introspecting `model_fields`, which would pass
for a field that is declared but dropped downstream.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from workflows.run_one_iteration import write_manifest
from tests.helpers.tuner_source import tuner_lifecycle_source

# (field, where it lives, the value the producer writes)
OUTPUT_LEVEL = [
    ("healthgate_mode", "blocking"),
    ("result_authority", "scientific"),
    ("formal_comparison_reference_source", "negative_infinity_bootstrap"),
]

RECORD_LEVEL = [
    (
        "scientific_authority",
        {
            "healthgate_mode": "blocking",
            "declared_result_authority": "scientific",
            "formal_validity": "valid",
            "authoritative": True,
            "primary_basis": "blocking_scientific_formal_valid",
            "blocking_reasons": [],
            "enters_incumbent_selection": True,
            "enters_scientific_aggregation": True,
        },
    ),
]


def _formal_record() -> dict:
    return {
        "exp_id": "f1",
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-08-05 00:00:00",
        "params": {},
        "denoising_score": 1.5,
        "health_gate_results": [],
        "health_gate_enabled": False,
    }


def _producer_dict() -> dict:
    """The shape the tuner hands to `HyperparamTuningOutput.model_validate`."""
    record = _formal_record()
    for field, value in RECORD_LEVEL:
        record[field] = value
    doc = {
        "run_name": "transport",
        "model_type": "punet",
        "file_index": 6,
        "status": "completed",
        "completed_rounds": 1,
        "total_attempts": 1,
        "all_records": [record],
        "started_at": "2026-08-05 00:00:00",
        "finished_at": "2026-08-05 00:00:01",
        "best_valid_formal_denoising_score": 1.5,
        "best_valid_formal_exp_id": "f1",
    }
    for field, value in OUTPUT_LEVEL:
        doc[field] = value
    return doc


def _artifact(tmp_path) -> dict:
    """Producer dict -> real model -> real JSON artifact -> parsed back.

    This is the path `core/resume.py` actually reads: the tuner validates
    its dict into the typed output, serialises it to
    `run_output_{run}.json`, and resume parses that file.
    """
    output = HyperparamTuningOutput.model_validate(_producer_dict())
    path = tmp_path / "run_output_transport.json"
    path.write_text(output.model_dump_json(), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("field", "value"), OUTPUT_LEVEL)
def test_an_output_level_field_reaches_the_artifact(tmp_path, field, value):
    """MUTATION TARGET: removing the declaration from the output schema.

    Undeclared, Pydantic's default `extra="ignore"` drops it here and the
    artifact simply lacks the key — which is exactly what happened to
    `formal_comparison_reference_source`.
    """
    assert _artifact(tmp_path)[field] == value


@pytest.mark.parametrize(("field", "value"), RECORD_LEVEL)
def test_a_record_level_field_survives_nesting_inside_all_records(tmp_path, field, value):
    """MUTATION TARGET: removing the declaration from `ExperimentRecord`.

    The nesting is the whole point. `all_records` is validated into
    `ExperimentRecord` on the way through, so a field declared nowhere is
    dropped even though the producer wrote it and the OUTPUT-level schema
    never sees it. This is the `scientific_authority` defect.
    """
    restored = _artifact(tmp_path)["all_records"][0]
    assert restored[field] == value


def test_every_declared_channel_is_present_in_one_artifact(tmp_path):
    """The concept, not the fields: ONE artifact must carry all of them.

    A per-field test cannot catch a boundary that drops a different field,
    which is how three separate instances each passed review.
    """
    doc = _artifact(tmp_path)
    missing = [f for f, _ in OUTPUT_LEVEL if doc.get(f) is None]
    missing += [f for f, _ in RECORD_LEVEL if doc["all_records"][0].get(f) is None]
    assert missing == [], f"dropped in transport: {missing}"


def test_the_output_level_fields_reach_the_iteration_manifest(tmp_path):
    """The SECOND hop, and its own defect class.

    `write_manifest` reads the typed output and copies fields across by
    hand, so a field can survive into `run_output_*.json` and still never
    reach `manifest.json` — which is what happened to
    `formal_comparison_reference_source` after its schema fix.
    """
    output = HyperparamTuningOutput.model_validate(_producer_dict())
    manifest = write_manifest(iter_dir=str(tmp_path), run_name="transport", results=[output])

    assert manifest["formal_comparison_reference_source"] == "negative_infinity_bootstrap"
    # And the manifest must remain strict-JSON serialisable.
    assert "Infinity" not in json.dumps(manifest, allow_nan=False)


class TestTheLaunchDeclarationSurvivesEveryBranch:
    """A validated launch declaration is not a tuner-result field.

    **Found by Gate 2 attempt 1, not by any test.** A real chain launched
    with `--healthgate_mode blocking --result_authority scientific` wrote
    `healthgate_mode: null` into its artifact — because the run FAILED, and
    both the tuner's degraded output dict and `write_manifest` sourced the
    posture from the healthy `tune_output` that never existed.

    The consequence is not cosmetic: under D-C4 a record whose iteration
    declared nothing is `unreconstructable_legacy` and can never become an
    incumbent. A failed iteration would therefore look like a
    pre-declaration artifact, which it is not.

    **The corrected rule**: D-C1b refuses the launch outright unless both
    axes are declared and consistent, so by the time ANY artifact is
    written they exist. Every post-launch branch carries them — completed,
    no-records, degraded, crashed — sourced from the validated input.

    The original FU-D-9 tests covered the healthy branch only, which is
    exactly how this survived: a field present on one path and absent on
    another, for the third time in this PR.
    """

    DECLARED: ClassVar[dict[str, str]] = {
        "healthgate_mode": "blocking",
        "result_authority": "scientific",
    }

    class _Output:
        """A tuner output that carries NO declaration — the degraded shape
        whose absence caused the defect."""

        model_type = "punet"
        completed_rounds = 0
        best_denoising_score = None
        best_exp_id = None
        healthgate_mode = None
        result_authority = None

    @pytest.mark.parametrize("crashed", [True, False], ids=["crashed", "no_records"])
    def test_the_manifest_declares_on_every_failure_branch(self, tmp_path, crashed):
        """MUTATION TARGET: reverting to `getattr(tune_output, …)`.

        Both branches produce no usable tuner output, which is precisely
        when the old code wrote null.
        """
        from workflows.run_one_iteration import write_manifest

        manifest = write_manifest(
            iter_dir=str(tmp_path),
            run_name="decl",
            results=[],
            crashed=crashed,
            **self.DECLARED,
        )
        assert manifest["healthgate_mode"] == "blocking"
        assert manifest["result_authority"] == "scientific"

    def test_the_caller_declaration_outranks_a_null_tuner_output(self, tmp_path):
        """The exact Gate 2 shape: a tuner output EXISTS but carries no
        declaration. The validated launch fact must still win."""
        from workflows.run_one_iteration import write_manifest

        manifest = write_manifest(
            iter_dir=str(tmp_path),
            run_name="decl",
            results=[self._Output()],
            **self.DECLARED,
        )
        assert manifest["healthgate_mode"] == "blocking"
        assert manifest["result_authority"] == "scientific"

    def test_an_undeclared_caller_still_yields_null_not_a_default(self, tmp_path):
        """FAIL-CLOSED. Threading the declaration in must not invent one:
        a caller outside the new contract still records null, which
        downstream reads as 'authority not establishable' — never as a
        silent `blocking`."""
        from workflows.run_one_iteration import write_manifest

        manifest = write_manifest(iter_dir=str(tmp_path), run_name="decl", results=[], crashed=True)
        assert manifest["healthgate_mode"] is None
        assert manifest["result_authority"] is None

    def test_the_tuner_degraded_output_carries_the_declaration(self):
        """MUTATION TARGET: the degraded dict omitting it again.

        Structural, because reaching the degraded branch requires a run
        that fails after partial persistence — which is what Gate 2 did,
        and what no unit test had reproduced.
        """
        import inspect

        from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent

        src = tuner_lifecycle_source()
        failed_block = src[src.index('"status": "failed"') :][:1200]
        assert '"healthgate_mode": agent_input.healthgate_mode' in failed_block
        assert '"result_authority": agent_input.result_authority' in failed_block

    def test_every_manifest_call_site_supplies_the_declaration(self):
        """MUTATION TARGET: wiring some branches and not others — the
        defect class this whole class exists for.

        Checked per CALL NODE via AST. A substring count was tried first
        and a mutation proved it useless: it tolerated one missing site,
        so removing the declaration from a crashed branch still passed.
        There are several failure branches and each is a separate chance
        to write a null posture for a declared run.
        """
        import ast
        from pathlib import Path

        launcher = (
            Path(__file__).resolve().parents[4] / "sdsc_submission_scripts" / "run_one_iteration.py"
        )
        tree = ast.parse(launcher.read_text(encoding="utf-8"))
        undeclared: list[int] = []
        calls = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "write_manifest":
                continue
            calls += 1
            keywords = {kw.arg for kw in node.keywords}
            if not {"healthgate_mode", "result_authority"} <= keywords:
                undeclared.append(node.lineno)

        assert calls >= 6, f"expected every failure branch present; found {calls} calls"
        assert undeclared == [], (
            f"write_manifest called without the launch declaration at lines "
            f"{undeclared}; those branches write a null posture for a run that "
            f"WAS declared, which D-C4 then reads as unreconstructable"
        )
