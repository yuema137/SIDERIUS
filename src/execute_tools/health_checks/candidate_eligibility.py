"""Deterministic HealthGate eligibility for experiment candidates.

This module is the single policy boundary used by execution selectors and
raw/valid reporting.  HealthGate routing remains independent: an observe-mode
gate may resolve to ``continue`` while this classifier still marks the record
invalid for promotion.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from execute_tools.health_checks._composition import HealthBindingState, TaskHealthBinding
from execute_tools.health_checks.config import (
    EFFECTIVE_CONFIG_BASENAME,
    load_composed_health_config,
    load_health_gates_config,
)

# CandidateHealthValidity moved to schemas.py (V19 PR 3 CB1 — the enum is
# pure vocabulary needed by schema-level consumers; the classifier
# functions below, which read gate config, stay here). Re-imported so
# every existing ``from ...candidate_eligibility import
# CandidateHealthValidity`` call site keeps working unchanged.
# BLOCKING_ACTIONS is deliberately NOT imported here any more. Scientific
# membership now comes from the declared `gate_role`; the action still
# decides ENFORCEMENT (whether a round is invalidated), and that use lives
# in the tuner. Conflating the two is the defect this module was fixed for.
from execute_tools.health_checks.schemas import CandidateHealthValidity, CheckVerdict


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def resolve_run_scientific_gate_ids(
    task_health_binding: TaskHealthBinding = HealthBindingState.LEGACY_OMITTED,
) -> frozenset[str] | None:
    """The scientific gate set for a RUN, resolved from its own Health declaration.

    Step 10 / P5+P6 **W6**, finding F-P56-2: composition must supply its own
    binding rather than acquire another task's policy through a default.
    The current omitted binding is neutral; no historical scientific roster
    is recovered.

    This is the composition-aware resolver. It exists so the run's Health
    declaration is resolved **ONCE, at the composition edge**, and consumed
    downstream as a RESOLVED VALUE — never re-loaded by a classifier that
    would have to know which task it is looking at.

    Nothing here branches on task identity: the argument is a
    ``TaskHealthBinding``, i.e. one of the three declared binding STATES
    (``LEGACY_OMITTED`` / ``EXPLICIT_NONE`` / an explicit path). A run supplies
    whichever its composition declared.

    Args:
        task_health_binding: the run's declared Health binding. Omission uses
            the existing neutral run-level default; EXPLICIT_NONE names an
            intentionally absent Health family.

    Returns:
        The blocking-role gate ids, or ``None`` when the roles cannot be
        established — ``None`` means UNKNOWN, exactly as
        :func:`resolve_scientific_gate_ids` defines it.
    """
    if task_health_binding is HealthBindingState.LEGACY_OMITTED:
        # Byte-for-byte the legacy path, cache included.
        return resolve_scientific_gate_ids(None)

    config, _task_config, _plugins = load_composed_health_config(None, task_health_binding)
    declared = {gate.id: gate.gate_role for gate in config.health_gates}
    if declared and all(role is not None for role in declared.values()):
        return frozenset(gid for gid, role in declared.items() if role == "blocking")
    if not declared:
        # A task that declares no gates has an empty scientific set — a
        # DECLARED absence, not an unknown one.
        return frozenset()
    return None


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
        established because any gate lacks a role. Historical body hashes,
        gate names and actions never supply missing roles. ``None`` means
        UNKNOWN, not the explicitly empty roster. Missing or malformed explicit
        files retain the loader's exceptions; no default is substituted.
    """
    # `None` means the shipped default config — the same convention
    # `load_health_gates_config` uses, rather than a second spelling of it.
    config = load_health_gates_config(config_path)
    declared = {gate.id: gate.gate_role for gate in config.health_gates}
    if all(role is not None for role in declared.values()):
        return frozenset(gid for gid, role in declared.items() if role == "blocking")

    return None


def _all_checks_inapplicable(result: dict[str, Any]) -> bool:
    """Whether every check in this persisted gate result was inapplicable.

    Reads the additive Step-08a ``check_verdicts`` and nothing else. A
    record written before 08a has no verdicts at all, and **absence is not
    inapplicability**: such a record returns False and takes exactly the
    pre-08a path. Fabricating verdicts for historical records — or reading a
    missing field as "nothing to check here" — would silently promote old
    UNKNOWN rounds to VALID.
    """
    verdicts = result.get("check_verdicts")
    if not isinstance(verdicts, dict) or not verdicts:
        return False
    return all(value == CheckVerdict.INAPPLICABLE.value for value in verdicts.values())


def classify_candidate_health(
    record: Any,
    *,
    required_gate_ids: Iterable[str] | None = None,
) -> CandidateHealthValidity:
    """Classify one record for valid-candidate eligibility.

    A missing roster (``None``, including omission) is ``unknown`` and performs
    no config I/O; an explicitly empty iterable declares no required gates.
    Missing or non-executed required HealthGates are ``unknown``. An actual
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

    if required_gate_ids is None:
        return CandidateHealthValidity.UNKNOWN
    required = frozenset(required_gate_ids)
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
            # Step 08a: a gate whose checks were ALL inapplicable carries no
            # missing evidence — there was nothing for it to establish about
            # this task — so it is excluded from the required set rather than
            # rendering the round UNKNOWN (parent design §7).
            #
            # An ERRORED check is never excluded: "we could not compute it"
            # IS missing evidence, and a required blocking check that could
            # not be computed must fail closed.
            if _all_checks_inapplicable(result):
                continue
            return CandidateHealthValidity.UNKNOWN
        if execution_status != "passed":
            return CandidateHealthValidity.INVALID
        if result.get("check_passed") is not True:
            return CandidateHealthValidity.INVALID
        if result.get("would_invalidate_under_production_policy") is True:
            return CandidateHealthValidity.INVALID

    return CandidateHealthValidity.VALID


def formal_validity_of(
    record: Any, *, config_path: str | None = None
) -> Literal["valid", "invalid", "unknown"]:
    """A FORMAL record's own role-aware HealthGate verdict.

    The input to ``ScientificAuthority.from_context``. It reads **this
    record's** gate results and nothing else — not the trial winner, not a
    trial count, not the score, not the skip/bypass decision. Authority is
    a property of the result, not of how its launch was justified (§16.D).

    Args:
        record: the formal record.
        config_path: the run's EFFECTIVE HealthGate config. ``None`` means
            the shipped default.

    Returns:
        ``"valid"`` / ``"invalid"`` / ``"unknown"`` — the classifier's own
        three-valued vocabulary, unchanged. ``"unknown"`` when the roles
        cannot be established, which is a gap and never a pass.
    """
    # The enum's values ARE the vocabulary `ScientificAuthority` accepts;
    # `test_formal_authority_wiring.py` pins the two together so a change
    # to either is caught rather than discovered at a call site.
    return classify_candidate_health(  # type: ignore[return-value]
        record, required_gate_ids=resolve_scientific_gate_ids(config_path)
    ).value


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


def pinned_workspace_gate_ids(workspace: str | Path) -> frozenset[str] | None:
    """The scientific gate set a WORKSPACE PINNED, or ``None`` for UNKNOWN.

    The workspace adapter of :func:`resolve_scientific_gate_ids` for a consumer that
    is judging ONE RUN'S persisted records. It resolves the run's own
    materialized ``health_checks_effective.yaml``; the repo-current shipped
    config is deliberately never consulted, because that is a DIFFERENT run's
    policy and a record can only be judged against the roster its own run
    declared. ``scripts/stage3/stage3_composed_best.py`` already resolved
    eligibility this way — this is that rule, named once, for the consumers
    that were still taking the zero-argument default.

    ``None`` means UNKNOWN, in either of the two ways a workspace can fail to
    establish a roster: it pinned no effective config at all (a run with
    ``health_gate_enabled=False`` materializes none), or its gate roles cannot
    be resolved. UNKNOWN is never a pass — :func:`classify_under_pinned_policy`
    is what a caller must put it through.

    Args:
        workspace: the run workspace directory, not the config file.

    Returns:
        The blocking-role gate ids, or ``None`` for UNKNOWN.
    """
    path = Path(workspace) / EFFECTIVE_CONFIG_BASENAME
    if not path.is_file():
        return None
    return resolve_scientific_gate_ids(str(path))


def classify_under_pinned_policy(
    record: Any,
    gate_ids: frozenset[str] | None,
) -> CandidateHealthValidity:
    """Validity of one persisted record under the RUN'S OWN resolved gate set.

    Delegates to the one classifier owning UNKNOWN. ``gate_ids is None`` means
    the run's policy could not be established, and the answer is UNKNOWN —
    never a silent fall-back to the repo-current shipped config, and never the
    empty set, which reads as "no gate is required" and would classify every
    record valid.

    Two things stay decidable without the policy artifact, and both are
    delegated to :func:`classify_candidate_health` rather than re-read here:

    * the DS5 record-level waiver — a run that stamped
      ``health_gate_enabled=False`` on the record already answered the
      question, and needs no roster to be believed;
    * a non-success or non-finite record, which is INVALID whether or not the
      policy resolved. An unresolvable policy must not upgrade a failure to
      "we could not tell".

    Args:
        record: the persisted record (mapping or model).
        gate_ids: the run's own scientific gate set, or ``None`` for UNKNOWN —
            typically from :func:`pinned_workspace_gate_ids`.
    """
    return classify_candidate_health(record, required_gate_ids=gate_ids)
