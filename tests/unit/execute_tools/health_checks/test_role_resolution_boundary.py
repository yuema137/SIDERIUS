"""Preserve role/action and unknown-history failures without scientific defaults.

The historical two-config SHA oracle is owned by siderius-exp. This suite
guards the generic resolver, including the original observe-only laundering
failure: continuing execution must not promote a scientifically failed result.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from execute_tools.health_checks.candidate_eligibility import (
    classify_candidate_health,
    legacy_config_body_sha,
    resolve_scientific_gate_ids,
)
from execute_tools.health_checks.config import load_health_gates_config
from execute_tools.health_checks.schemas import CandidateHealthValidity

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "health"


def test_enforcement_cannot_change_scientific_membership():
    """All-continue actions still retain the declared blocking role."""
    paths = [str(FIXTURES / name) for name in ("mixed_blocking.yaml", "mixed_observe_only.yaml")]
    assert [resolve_scientific_gate_ids(path) for path in paths] == [
        frozenset({"synthetic_stability_blocking"}),
        frozenset({"synthetic_stability_blocking"}),
    ]
    actions = [load_health_gates_config(path).health_gates[0].on_fail.action for path in paths]
    assert actions == ["invalidate_round", "continue"]
    record = {
        "status": "success",
        "denoising_score": 0.7,
        "health_gate_results": [
            {
                "gate_name": "synthetic_stability_blocking",
                "execution_status": "passed",
                "check_passed": False,
                "would_invalidate_under_production_policy": True,
            }
        ],
    }
    for path in paths:
        assert (
            classify_candidate_health(record, required_gate_ids=resolve_scientific_gate_ids(path))
            is CandidateHealthValidity.INVALID
        )


def test_unknown_roleless_config_is_not_guessed_from_name_or_action(tmp_path):
    body = load_health_gates_config(str(FIXTURES / "mixed_blocking.yaml")).model_dump(mode="json")
    for gate in body["health_gates"]:
        gate.pop("gate_role")
    path = tmp_path / "health_checks_effective.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    assert resolve_scientific_gate_ids(str(path)) is None
    assert (
        legacy_config_body_sha(str(path))
        == hashlib.sha256(yaml.safe_dump(body, sort_keys=True).encode()).hexdigest()
    )
    # Modern nullable role fields must not contaminate the historical digest.
    current_body = load_health_gates_config(str(path)).model_dump(mode="json")
    assert (
        legacy_config_body_sha(str(path))
        != hashlib.sha256(yaml.safe_dump(current_body, sort_keys=True).encode()).hexdigest()
    )


@pytest.mark.parametrize("content", [None, "health_gates: [", "health_gates: wrong-shape"])
def test_unreadable_config_supplies_no_compatibility_evidence(tmp_path, content):
    path = tmp_path / "health_checks_effective.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert legacy_config_body_sha(str(path)) is None
