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

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from sdsc_submission_scripts.run_one_iteration import write_manifest

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
