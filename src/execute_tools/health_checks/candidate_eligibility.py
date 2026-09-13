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
from typing import Any, Literal

import yaml

from execute_tools.health_checks._composition import HealthBindingState, TaskHealthBinding
from execute_tools.health_checks.config import (
    EFFECTIVE_CONFIG_BASENAME,
    default_health_policy_path,
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


def resolve_run_scientific_gate_ids(
    task_health_binding: TaskHealthBinding = HealthBindingState.LEGACY_OMITTED,
) -> frozenset[str] | None:
    """The scientific gate set for a RUN, resolved from its own Health declaration.

    Step 10 / P5+P6 **W6**. The zero-argument
    :func:`resolve_scientific_gate_ids` resolves through
    ``load_health_gates_config(None)``, which composes with
    ``LEGACY_OMITTED`` — the LEGACY TIDMAD task-health config. That default is
    correct for an un-composed run and WRONG for a composed one: it makes a
    composed contrast run bind TIDMAD's Health family process-globally, and the
    Step-08b run-scope guard then (correctly) refuses the run's own family.
    Finding F-P56-2.

    This is the composition-aware resolver. It exists so the run's Health
    declaration is resolved **ONCE, at the composition edge**, and consumed
    downstream as a RESOLVED VALUE — never re-loaded by a classifier that
    would have to know which task it is looking at.

    Nothing here branches on task identity: the argument is a
    ``TaskHealthBinding``, i.e. one of the three declared binding STATES
    (``LEGACY_OMITTED`` / ``EXPLICIT_NONE`` / an explicit path). A run supplies
    whichever its composition declared.

    Args:
        task_health_binding: the run's declared Health binding. The default
            reproduces the pre-W6 behaviour exactly, so every un-composed
            caller is unaffected.

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
    path = (
        production_config_path
        if production_config_path is not None
        else default_health_policy_path()
    )
    return resolve_scientific_gate_ids(path) or frozenset()


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

    The counterpart of :func:`required_blocking_gate_ids` for a consumer that
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

    **The one place the UNKNOWN rule is written.** ``gate_ids is None`` means
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
    if _as_mapping(record).get("health_gate_enabled") is False:
        return classify_candidate_health(record, required_gate_ids=frozenset())
    if gate_ids is None:
        base = classify_candidate_health(record, required_gate_ids=frozenset())
        if base is CandidateHealthValidity.INVALID:
            return CandidateHealthValidity.INVALID
        return CandidateHealthValidity.UNKNOWN
    return classify_candidate_health(record, required_gate_ids=gate_ids)
