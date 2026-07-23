"""Deterministic HealthGate eligibility for experiment candidates.

This module is the single policy boundary used by execution selectors and
raw/valid reporting.  HealthGate routing remains independent: an observe-mode
gate may resolve to ``continue`` while this classifier still marks the record
invalid for promotion.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Any

from execute_tools.health_checks.config import load_health_gates_config
from execute_tools.health_checks.schemas import BLOCKING_ACTIONS


class CandidateHealthValidity(StrEnum):
    """Eligibility state for scientific/execution candidate selection."""

    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def required_blocking_gate_ids(production_config_path: str | None = None) -> frozenset[str]:
    """Return gate IDs whose production failure action is blocking."""

    path = production_config_path
    if path is None:
        path = str(Path(__file__).resolve().parents[2] / "configs" / "health_checks.yaml")
    config = load_health_gates_config(path)
    return frozenset(
        gate.id for gate in config.health_gates if gate.on_fail.action in BLOCKING_ACTIONS
    )


def classify_candidate_health(
    record: Any,
    *,
    required_gate_ids: Iterable[str] | None = None,
) -> CandidateHealthValidity:
    """Classify one record for valid-candidate eligibility.

    Missing or non-executed required HealthGates are ``unknown``.  An actual
    failed blocking check, a collapse status, or a non-finite score is
    ``invalid``. Recording-only checks are ignored.
    """

    data = _as_mapping(record)
    if data.get("status") != "success":
        return CandidateHealthValidity.INVALID

    score = data.get("denoising_score")
    if not isinstance(score, int | float) or isinstance(score, bool) or not math.isfinite(score):
        return CandidateHealthValidity.INVALID

    # DataScope DS5 — self-describing disabled-mode records: a run that
    # explicitly disabled the HealthGate subsystem (health_gate_enabled=False
    # stamped on the record; policy is workspace-immutable, so mixed
    # histories cannot occur) waives the gate requirement — successful
    # finite-score records are VALID. Legacy records (field absent/None)
    # take the normal gate-requirement path below.
    if data.get("health_gate_enabled") is False:
        return CandidateHealthValidity.VALID

    required = frozenset(
        required_blocking_gate_ids() if required_gate_ids is None else required_gate_ids
    )
    results = {
        item.get("gate_name"): item
        for raw in data.get("health_gate_results") or []
        if (item := _as_mapping(raw)).get("gate_name")
    }
    if not required.issubset(results):
        return CandidateHealthValidity.UNKNOWN

    for gate_id in required:
        result = results[gate_id]
        execution_status = result.get("execution_status")
        if execution_status in {"not_run", "error"}:
            return CandidateHealthValidity.UNKNOWN
        if execution_status != "passed":
            return CandidateHealthValidity.INVALID
        if result.get("check_passed") is not True:
            return CandidateHealthValidity.INVALID
        if result.get("would_invalidate_under_production_policy") is True:
            return CandidateHealthValidity.INVALID

    return CandidateHealthValidity.VALID


def is_valid_candidate(
    record: Any,
    *,
    required_gate_ids: Iterable[str] | None = None,
) -> bool:
    """Return whether ``record`` is eligible for promotion/valid-best use."""

    return (
        classify_candidate_health(record, required_gate_ids=required_gate_ids)
        is CandidateHealthValidity.VALID
    )
