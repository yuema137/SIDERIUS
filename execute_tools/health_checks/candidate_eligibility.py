"""Deterministic HealthGate eligibility for experiment candidates.

This module is the single policy boundary used by execution selectors and
raw/valid reporting.  HealthGate routing remains independent: an observe-mode
gate may resolve to ``continue`` while this classifier still marks the record
invalid for promotion.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from execute_tools.health_checks.config import load_health_gates_config

# CandidateHealthValidity moved to schemas.py (V19 PR 3 CB1 — the enum is
# pure vocabulary needed by schema-level consumers; the classifier
# functions below, which read gate config, stay here). Re-imported so
# every existing ``from ...candidate_eligibility import
# CandidateHealthValidity`` call site keeps working unchanged.
# BLOCKING_ACTIONS is deliberately NOT imported here any more. Scientific
# membership now comes from the declared `gate_role`; the action still
# decides ENFORCEMENT (whether a round is invalidated), and that use lives
# in the tuner. Conflating the two is the defect this module was fixed for.
from execute_tools.health_checks.schemas import CandidateHealthValidity


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


#: Gate roles as they stood in the shipped configs BEFORE `gate_role`
#: existed, keyed by the exact body sha256 those configs had at that time.
#:
#: This is an audited historical declaration, not a heuristic. It is keyed
#: on the sha so it can only ever answer for a config whose bytes are known;
#: a role-less config that is not in this map is UNKNOWN, never guessed.
#:
#: The two entries are `configs/health_checks.yaml` and
#: `configs/health_checks_baseline_observe_mode.yaml` at master 334d388d,
#: measured immediately before the roles were added.
_LEGACY_ROLES_BY_CONFIG_SHA: dict[str, dict[str, str]] = {
    # configs/health_checks.yaml — blocking enforcement
    "3b5521180f5460a4a7aa67ad0ff67701633d75ed8fdcac4277c222b713655b74": {
        "output_diversity_blocking": "blocking",
        "output_std_blocking": "blocking",
        "amplitude_collapse_blocking": "blocking",
        "pearson_dispersion_recording": "observational",
        "spectral_peak_ratio_recording": "observational",
        "per_file_output_std_recording": "observational",
    },
    # configs/health_checks_baseline_observe_mode.yaml — observe-only
    # enforcement, IDENTICAL science. That the two maps are equal is the
    # whole point: the role is a property of the check, not of the action.
    "d133a12d3133fb20d632383aa010b1a861fe0fdb6fb6436874b2142d6b5ef58d": {
        "output_diversity_blocking": "blocking",
        "output_std_blocking": "blocking",
        "amplitude_collapse_blocking": "blocking",
        "pearson_dispersion_recording": "observational",
        "spectral_peak_ratio_recording": "observational",
        "per_file_output_std_recording": "observational",
    },
}


def legacy_config_body_sha(config_path: str | None = None) -> str | None:
    """The body sha this config WOULD have had before ``gate_role`` existed.

    ``health_config_sha256`` stamps recorded before this hotfix were computed
    over a model dump with no ``gate_role`` key, so the current dump cannot
    match them. Removing the key reproduces the historical body exactly,
    which is what lets the compatibility map be keyed on a real recorded
    value rather than on a filename.

    Returns ``None`` when the file is missing or unparseable — absence of a
    sha is not evidence of anything, and the caller must treat it as UNKNOWN.
    """
    try:
        config = load_health_gates_config(config_path)
        body = config.model_dump(mode="json")
    except Exception:
        return None
    for gate in body.get("health_gates", []):
        if isinstance(gate, dict):
            gate.pop("gate_role", None)
    return hashlib.sha256(yaml.safe_dump(body, sort_keys=True).encode()).hexdigest()


def resolve_scientific_gate_ids(config_path: str | None = None) -> frozenset[str] | None:
    """The gates whose verdict decides scientific validity, by DECLARED role.

    **The one resolver.** In-run trial selection and resume-time incumbent
    classification both call this, so the two can no longer disagree — which
    they did: the same observe-only record classified ``invalid`` in-run and
    ``valid`` at resume, because in-run selection resolved against the
    repo-current blocking config while resume resolved against the effective
    observe-only one.

    Membership comes from ``gate_role``, never from ``on_fail.action``.
    Deriving it from the action inverts the answer under an observe-only
    config, where every action is ``continue`` and the action-derived set is
    therefore empty — so every record classified valid.

    Returns:
        The blocking-role gate ids, or ``None`` when the roles cannot be
        established: a role-less config whose sha is not in the audited
        compatibility map. ``None`` means UNKNOWN and the caller must exclude
        the record, never fall back to a guess.
    """
    # `None` means the shipped default config — the same convention
    # `load_health_gates_config` uses, rather than a second spelling of it.
    config = load_health_gates_config(config_path)
    declared = {gate.id: gate.gate_role for gate in config.health_gates}
    if all(role is not None for role in declared.values()):
        return frozenset(gid for gid, role in declared.items() if role == "blocking")

    # Role-less: a config written before this field existed. Recover only
    # through the audited map, keyed on the body it actually had.
    legacy = _LEGACY_ROLES_BY_CONFIG_SHA.get(legacy_config_body_sha(config_path) or "")
    if legacy is None:
        return None
    return frozenset(gid for gid, role in legacy.items() if role == "blocking")


def required_blocking_gate_ids(production_config_path: str | None = None) -> frozenset[str]:
    """Deprecated shim: the scientific gate set for one config.

    Retained so existing call sites keep working. New code should call
    :func:`resolve_scientific_gate_ids`, which can express UNKNOWN; this
    function collapses UNKNOWN to the empty set and so cannot distinguish
    "no blocking gates" from "roles could not be established".
    """
    path = production_config_path
    if path is None:
        path = str(Path(__file__).resolve().parents[2] / "configs" / "health_checks.yaml")
    return resolve_scientific_gate_ids(path) or frozenset()


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
