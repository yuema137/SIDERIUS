"""Static decision evidence survives the actual JSON process boundary.

Only the structural inspection is supplied as a fixture. The child runs the
production classifier; the parent runs the production loader and adapter.
No model, dataset, provider, or GPU is used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas.preflight import StaticPhaseDecision, StaticPreflightEvidence
from agent.skills.evaluate_vram_skill.evidence import (
    preflight_memory_fields,
    render_static_refusal,
    static_refusal_suggestion,
)
from agent.skills.evaluate_vram_skill.isolated_probe import (
    IsolatedProbeResult,
    IsolatedProbeSpec,
    run_isolated_preflight,
)
from agent.skills.evaluate_vram_skill.preflight_adapter import adapt_result

GIB = 1024**3


def structural_result(kind: str) -> dict:
    """Different admission causes with deliberately independent diagnostics."""
    decision = StaticPhaseDecision(
        phase="inference",
        batch_size=3,
        vram_cap_bytes=5 * GIB,
        vram_estimate_bytes=None if kind == "compute" else (8 if kind != "pass" else 4) * GIB,
        estimator=None if kind == "compute" else "inference_leaf_sum_v1",
        intensity_product=120 if kind in {"compute", "both"} else 60,
        intensity_limit=100,
    )
    evidence = StaticPreflightEvidence(phases=(decision,))
    return {
        "status": "success",
        "feasible": not evidence.binding_caps,
        "static_preflight_evidence": evidence.model_dump(mode="json"),
        # Passing legacy diagnostics remain separate from the admission estimate.
        "estimated_gb": 1.25 if kind == "pass" else (None if kind == "compute" else 8.0),
        "limit_gb": 5.0,
        "inference_batch": 3 if kind == "pass" else None,
        "dominant_phase": "training" if kind == "pass" else "inference",
        "num_params": 1234,
        "verdict": "FITS" if kind == "pass" else render_static_refusal(evidence),
        "suggestion": "" if kind == "pass" else static_refusal_suggestion(evidence),
    }


def classified_roundtrip(
    tmp_path: Path, inspection: dict, *, wire_override: dict | None = None
) -> tuple[IsolatedProbeResult, dict]:
    """Run the classifier in a child, then parse its file through the real IPC."""
    input_path = tmp_path / "inspection.json"
    result_path = tmp_path / "result.json"
    input_path.write_text(json.dumps(inspection), encoding="utf-8")
    script = tmp_path / "classifying_worker.py"
    script.write_text(
        "import json, pathlib, sys\n"
        "from agent.skills.evaluate_vram_skill.preflight_worker_main import _classify\n"
        "inspection = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "payload = _classify(inspection)\n"
        f"payload.update({wire_override!r} or {{}})\n"
        "pathlib.Path(sys.argv[2]).write_text(json.dumps(payload))\n",
        encoding="utf-8",
    )
    spec = IsolatedProbeSpec(
        label="static-evidence-transport",
        model_type="synthetic_candidate",
        vram_budget_gb=5.0,
        result_path=str(result_path),
        worker_memory_limit_bytes=GIB,
    )
    probe = run_isolated_preflight(
        spec,
        deadline_seconds=30.0,
        command=[sys.executable, str(script), str(input_path), str(result_path)],
    )
    return probe, adapt_result(probe.model_dump())


@pytest.mark.parametrize("kind", ["pass", "vram", "compute", "both"])
def test_static_evidence_survives_child_classifier_and_parent_loader(tmp_path, kind):
    inspection = structural_result(kind)
    probe, adapted = classified_roundtrip(tmp_path, inspection)
    expected = "COMPLETED_MEASUREMENT" if kind == "pass" else "STATIC_PREFLIGHT_REFUSAL"
    assert probe.outcome == expected, probe.detail
    assert not probe.has_capacity_authority
    assert not probe.may_recommend_vram_downsizing
    assert probe.cuda_peak_allocated_gb is None
    assert (
        StaticPreflightEvidence.model_validate(adapted["static_preflight_evidence"]).model_dump(
            mode="json"
        )
        == inspection["static_preflight_evidence"]
    )
    assert adapted.get("estimated_gb") == inspection["estimated_gb"]
    memory = preflight_memory_fields(adapted)
    assert memory["preflight_outcome"] == expected
    assert memory["static_preflight_evidence"] == inspection["static_preflight_evidence"]
    if kind == "pass":
        assert adapted["inference_batch"] == 3
        assert adapted["dominant_phase"] == "training"
        assert probe.static_preflight_evidence.phases[0].vram_estimate_bytes == 4 * GIB
    else:
        message = probe.agent_facing_message()
        assert "inference B=3" in message
        assert "not a measured GPU peak or CUDA OOM" in message
        if kind == "compute":
            assert "120 exceeds the rule limit 100" in message
            assert "structural estimate" not in message


@pytest.mark.parametrize(
    "malformation",
    ["missing", "future-version", "wrong-estimator", "passing-evidence", "unknown-status"],
)
def test_classifier_refuses_invalid_decision_contract(tmp_path, malformation):
    inspection = structural_result("vram")
    if malformation == "missing":
        inspection.pop("static_preflight_evidence")
    elif malformation == "future-version":
        inspection["static_preflight_evidence"]["version"] = "unknown-v2"
    elif malformation == "wrong-estimator":
        inspection["static_preflight_evidence"]["phases"][0]["estimator"] = (
            "training_saved_tensors_v1"
        )
    elif malformation == "passing-evidence":
        inspection["static_preflight_evidence"] = structural_result("pass")[
            "static_preflight_evidence"
        ]
    else:
        inspection["status"] = "unrecognized"
    probe, adapted = classified_roundtrip(tmp_path, inspection)
    assert probe.outcome == "PROBE_INFRASTRUCTURE_FAILURE", probe.detail
    assert not probe.has_capacity_authority
    assert "feasible" not in adapted


@pytest.mark.parametrize(
    "wire_override",
    [
        {"static_preflight_evidence": None},
        {"static_preflight_evidence": {"version": "unknown-v2", "phases": []}},
        {"outcome": "COMPLETED_MEASUREMENT"},
        {"outcome": "MEASURED_CUDA_OOM"},
        {"outcome": "HOST_MEMORY_ALLOCATION_FAILURE"},
    ],
)
def test_parent_revalidates_corrupt_or_contradictory_worker_payload(tmp_path, wire_override):
    probe, _ = classified_roundtrip(
        tmp_path, structural_result("vram"), wire_override=wire_override
    )
    assert probe.outcome == "PROBE_INFRASTRUCTURE_FAILURE", probe.detail
    assert not probe.has_capacity_authority


@pytest.mark.parametrize("outcome", ["MEASURED_CUDA_OOM", "MEASURED_PEAK_ABOVE_VRAM_CAP"])
def test_direct_result_cannot_grant_measurement_authority_to_static_evidence(outcome):
    with pytest.raises(ValidationError, match="Static decision evidence requires"):
        IsolatedProbeResult(
            label="direct-static-result",
            outcome=outcome,
            static_preflight_evidence=structural_result("vram")["static_preflight_evidence"],
        )


def test_direct_static_refusal_requires_rejecting_evidence():
    for evidence in (None, structural_result("pass")["static_preflight_evidence"]):
        with pytest.raises(ValidationError, match="Static"):
            IsolatedProbeResult(
                label="direct-static-result",
                outcome="STATIC_PREFLIGHT_REFUSAL",
                static_preflight_evidence=evidence,
            )


@pytest.mark.parametrize(
    ("inspection", "expected", "capacity_authority"),
    [
        ({"status": "cuda_oom", "message": "CUDA allocation failed"}, "MEASURED_CUDA_OOM", True),
        (
            {"status": "host_memory", "message": "Host allocation failed"},
            "HOST_MEMORY_ALLOCATION_FAILURE",
            True,
        ),
        (
            {"status": "error", "message": "Unrelated invalid input shape"},
            "PROBE_INFRASTRUCTURE_FAILURE",
            False,
        ),
    ],
)
def test_static_classification_does_not_erase_actual_failure_domain(
    tmp_path, inspection, expected, capacity_authority
):
    probe, _ = classified_roundtrip(tmp_path, inspection)
    assert probe.outcome == expected
    assert probe.has_capacity_authority is capacity_authority
    assert probe.static_preflight_evidence is None
