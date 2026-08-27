"""Which persisted experiment records are FORMAL, and what formal evidence exists.

ONE authority for the frozen contract rule in
``docs/campaign/stage_artifact_contract.md`` section 1 ("FORMAL round" row):
a record is formal iff ``is_trial`` is ABSENT or ``False``.

The predicate used to live in ``sdsc_submission_scripts/gold_campaign_state.py``
as ``_is_formal_role``. It moved here unchanged when a SECOND consumer appeared
(the iteration manifest, F-SCANB-3): the campaign scanner and the manifest
writer must answer "is this record formal?" the same way, and two copies of a
three-case rule is exactly how the ``"is_trial" in rec`` variant — which
discarded every real formal record — survived (#316 B2).

``formal_evidence_of`` is the reporting half. An iteration that produced only
trial rounds has no scientifically authoritative result, and until F-SCANB-3
nothing in the manifest or the operator view said so: ``best_denoising_score``
is ``top_record`` over ALL records, trial and formal mixed
(``nodes/ml_hyperparameter_tune_agent/records.py``), and both the iteration
status and the reported ``best_score`` were derived from it. This module gives
that question a typed answer, computed over the SAME serialization the frozen
winner rule reads — ``ExperimentRecord.model_dump()``, which materialises
``is_trial: False`` onto every persisted formal record.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, computed_field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput


class RecordRoleError(RuntimeError):
    """An ``is_trial`` / ``trial_portion`` shape production never writes.

    Raised rather than silently classified either way, because a silent
    choice here could silently move a campaign winner. Callers that own a
    fail-closed refusal vocabulary of their own catch this alongside it.
    """


def is_formal_role(record: Mapping[str, Any], where: str) -> bool:
    """True iff ``record`` is a FORMAL record — ``is_trial`` absent OR ``False``.

    The FROZEN contract rule (``docs/campaign/stage_artifact_contract.md``
    section 1, "FORMAL round" row), as three cases:

    ==================  ========
    ``is_trial``        role
    ==================  ========
    ``True``            trial (excluded)
    ``False``           FORMAL
    key absent          FORMAL
    ==================  ========

    The superseded wording ("formal == ABSENCE of the ``is_trial`` key")
    described the BUILDER's IN-MEMORY dicts, where the key is set only on
    trial records. It does NOT describe the shape any consumer reads.
    ``HyperparamTuningOutput.all_records: list[ExperimentRecord]``
    re-validates every dict into the model, so ``model_dump()``
    (``nodes/ml_hyperparameter_tune_agent/records.py``: ``model_validate``
    -> ``model_dump`` -> ``publish_json_atomically``) MATERIALIZES the field
    defaults ``is_trial: False`` and ``trial_portion: None`` onto EVERY
    PERSISTED formal record. Under the absence test every real formal record
    was discarded, so the Gold scanner's champion set was permanently empty —
    and an empty champion set is silent, not loud: Stage 1 still exits 0 and
    burns its whole horizon, and Stage 2 refuses all 16 units.

    The falsy-tolerant test matches the two sibling readers that already got
    this right — the ``BestTracks`` authority
    (``nodes/ml_hyperparameter_tune_agent/policy.py``:
    ``not r.get("is_trial", False)``) and Stage-3's ``_formal_role``
    (``scripts/stage3/stage3_composed_best.py``, Q-S3-3).

    Args:
        record: One persisted record, as a mapping.
        where: Locator quoted in a refusal (path, exp_id, …).

    Returns:
        Whether the record played the FORMAL role.

    Raises:
        RecordRoleError: on an anomalous role shape — a NON-BOOL
            ``is_trial``, or a non-``None`` ``trial_portion`` on a record
            whose ``is_trial`` is not ``True``.
    """
    role = record.get("is_trial")
    if role is True:
        return False
    if role is not None and role is not False:
        raise RecordRoleError(
            f"record {where} carries is_trial={role!r} — a non-bool role is a "
            f"shape production never writes; refusing an anomalous role shape."
        )
    if record.get("trial_portion") is not None:
        raise RecordRoleError(
            f"record {where} is formal-shaped (is_trial={role!r}) but carries "
            f"trial_portion={record['trial_portion']!r} — a trial-only value "
            f"(#316 B2); refusing."
        )
    return True


class IterationFormalEvidence(BaseModel):
    """Whether one iteration produced a scientifically authoritative result.

    F-SCANB-3. Counts only — the scores themselves are already carried by
    ``HyperparamTuningOutput.best_formal_denoising_score`` /
    ``best_valid_formal_denoising_score`` and must not be duplicated into a
    second, drift-capable place.

    ``formal_success_count`` uses the frozen winner rule's own first two
    conditions (``status == "success"`` AND the formal role). It deliberately
    does NOT apply the HealthGate-validity condition: validity is a separate
    axis with its own reported field, and folding two axes into one number is
    how "no formal round ran" and "the formal round was invalidated" become
    indistinguishable.

    Attributes:
        record_count: Every record the iteration persisted.
        formal_record_count: Of those, the ones that played the FORMAL role.
        formal_success_count: Of THOSE, the ones that completed scoring.
    """

    model_config = ConfigDict(frozen=True)

    record_count: int
    formal_record_count: int
    formal_success_count: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_formal_evidence(self) -> bool:
        """Whether any formal round produced a completed result.

        Derived, never settable: a caller cannot claim formal evidence that
        its own counts contradict.
        """
        return self.formal_success_count > 0


def formal_evidence_of(output: HyperparamTuningOutput | None) -> IterationFormalEvidence:
    """Count an iteration's formal evidence from its OWN persisted shape.

    Takes the tuning output rather than a list of dicts so the role rule is
    applied to ``ExperimentRecord.model_dump()`` — the serialization
    production actually writes, and the one that materialises
    ``is_trial: False``. A helper that hand-built record dicts here would
    certify a shape no run ever produces, which is precisely how the sibling
    ``is_trial`` defect survived.

    Args:
        output: The iteration's tuning output, or ``None`` when the
            iteration crashed or produced none.

    Returns:
        The counts. An absent output is all-zero — the honest posture for an
        iteration that produced nothing.

    Raises:
        RecordRoleError: propagated from :func:`is_formal_role`.
    """
    records = list(getattr(output, "all_records", None) or [])
    formal: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        dumped = record.model_dump() if hasattr(record, "model_dump") else dict(record)
        if is_formal_role(dumped, f"all_records[{index}] exp_id={dumped.get('exp_id')!r}"):
            formal.append(dumped)
    return IterationFormalEvidence(
        record_count=len(records),
        formal_record_count=len(formal),
        formal_success_count=sum(1 for r in formal if r.get("status") == "success"),
    )
