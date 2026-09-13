"""Preserve role/action and unknown-history failures without scientific defaults.

Historical SHA recovery is retired, not relocated to a consumer. This suite
guards the generic resolver, including the original observe-only laundering
failure: continuing execution must not promote a scientifically failed result.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from execute_tools.health_checks.candidate_eligibility import (
    classify_candidate_health,
    classify_under_pinned_policy,
    formal_validity_of,
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


@pytest.mark.parametrize("missing", ["all", "one"])
@pytest.mark.parametrize("action", ["continue", "invalidate_round"])
def test_unknown_roles_are_not_guessed_or_rescued_by_default(tmp_path, missing, action):
    """A partial roster cannot become empty at the classifier/formal boundary."""
    body = load_health_gates_config(str(FIXTURES / "mixed_blocking.yaml")).model_dump(mode="json")
    for gate in body["health_gates"][:1] if missing == "one" else body["health_gates"]:
        gate.pop("gate_role")
    for gate in body["health_gates"]:
        gate["on_fail"]["action"] = action
    path = tmp_path / "health_checks_effective.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    resolved = resolve_scientific_gate_ids(str(path))
    assert resolved is None
    record = {"status": "success", "denoising_score": 0.7}
    assert classify_candidate_health(record, required_gate_ids=resolved).value == "unknown"
    assert classify_under_pinned_policy(record, resolved).value == "unknown"
    assert formal_validity_of(record, config_path=str(path)) == "unknown"


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (None, FileNotFoundError),
        ("health_gates: [", yaml.YAMLError),
        ("health_gates: wrong-shape", ValueError),
    ],
)
def test_explicit_unreadable_config_refuses_instead_of_default_rescue(tmp_path, content, error):
    path = tmp_path / "health_checks_effective.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(error):
        resolve_scientific_gate_ids(str(path))


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "unknown"),
        ({"health_gate_enabled": False}, "valid"),
        ({"status": "error_training", "health_gate_enabled": False}, "invalid"),
        ({"denoising_score": float("inf"), "health_gate_enabled": False}, "invalid"),
    ],
)
def test_absent_roster_precedence_never_loads_config(monkeypatch, overrides, expected):
    """Omission and explicit None share the same no-I/O classifier authority."""
    from execute_tools.health_checks import candidate_eligibility

    def refuse_load(*args, **kwargs):
        raise AssertionError("classifier reloaded a config")

    monkeypatch.setattr(candidate_eligibility, "load_health_gates_config", refuse_load)
    record = {"status": "success", "denoising_score": 0.7, **overrides}
    assert classify_candidate_health(record).value == expected
    assert classify_candidate_health(record, required_gate_ids=None).value == expected
    assert classify_under_pinned_policy(record, None).value == expected


def test_explicit_empty_and_misleading_observational_id_remain_supported(tmp_path):
    """Only role declares membership; a blocking suffix is not a role."""
    body = load_health_gates_config(str(FIXTURES / "mixed_blocking.yaml")).model_dump(mode="json")
    body["health_gates"] = body["health_gates"][:1]
    body["health_gates"][0]["gate_role"] = "observational"
    path = tmp_path / "effective.yaml"
    record = {"status": "success", "denoising_score": 0.7}
    for gates in (body["health_gates"], []):
        path.write_text(yaml.safe_dump({"health_gates": gates}), encoding="utf-8")
        resolved = resolve_scientific_gate_ids(str(path))
        assert resolved == frozenset()
        assert classify_candidate_health(record, required_gate_ids=resolved).value == "valid"
