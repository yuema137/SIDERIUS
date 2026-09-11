"""V21 PR E — read-side proposal-scale funnel assembly (O-E-3: join on read).

This module is a READER. It writes nothing, creates no artifact, and owns
no measurement — every number it reports lives in a stage-native file
written by the stage that measured it:

```text
{iter_dir}/attempt_{NNN}_{name}/proposal_{run}.json               proposal stage
{iter_dir}/attempt_{NNN}_{name}/impl_{KKK}/implementor_{run}.json  implementor stage
{iter_dir}/attempt_{NNN}_{name}/impl_{KKK}/validation_{run}.json   validator stage
{iter_dir}/{model_type}/run_output_{run}.json                     tuner stage
```

(S2 / U6, #256: ``impl_{KKK}`` is one directory per implement→validate
retry; the funnel reads the TERMINAL one. A pre-U6 workspace keeps the
two files at the attempt level and is read the same way.)

**Join rule (O-E-4/O-E-5): only an explicit ``candidate_id`` joins
records.** Identity is never inferred from ``model_name``, a directory
suffix, ``exp_id``, record ordering or filename coincidence. Artifacts
with ``candidate_id=None`` (pre-PR-E, or non-proposer candidates such as
a fixed validation plan) each stay a SEPARATE unjoinable evidence item —
two ``None``s never merge into one pseudo-candidate.

**Derivation rule (O-E-2): ``stopped_at_stage`` is computed here, on
read, from native outcomes — it is stored nowhere.** Each stage's own
evidence is carried verbatim as the reason; where a stage has no typed
reason (implementation), the reason is honestly ABSENT, never invented.

**Convention rule (O-E-6 FINAL):** the four parameter columns carry
convention-explicit display labels and are never combined — no delta,
ratio, mean or verdict is computed across unlike conventions, or at all.

``preflight_factor`` is a MEASUREMENT carried from the proposal artifact,
never a disposition — the proposer's preflight is advisory-only by its C1
contract and admits/rejects nothing.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from execute_tools.impl_attempts import stage_artifact_dir

#: Stage names, in funnel order. ``stopped_at_stage`` is one of these or
#: None for a candidate whose evidence reaches the tuner.
StageName = Literal["proposal", "implementation", "validation", "tuner"]

_STAGE_FILES: tuple[tuple[StageName, str], ...] = (
    ("proposal", "proposal_"),
    ("implementation", "implementor_"),
    ("validation", "validation_"),
)


class UnreadableArtifact(BaseModel):
    """A file that exists but could not be parsed.

    Reported as UNREADABLE, never silently reinterpreted as "stage
    absent" — a truncated validation JSON is evidence of a problem, not
    evidence the candidate skipped validation.
    """

    path: str
    error: str


class StageEvidence(BaseModel):
    """One stage's native artifact, carried nearly verbatim.

    ``native`` holds the stage's own persisted payload — the funnel never
    re-types or re-judges it. ``reason_absent`` marks a stage that has no
    typed native reason (implementation, §0.E), preserved as information.
    """

    present: bool = False
    source_path: str | None = None
    native: dict[str, Any] | None = None
    reason_absent: bool = False


class DuplicateIdConflict(BaseModel):
    """One non-None ``candidate_id`` observed in MORE THAN ONE distinct
    attempt directory.

    Mint uniqueness is probabilistic (uuid4 — random, not an allocator with
    a uniqueness proof), and no run-scoped registry can span the chain's
    per-iteration subprocesses without new persistent state. The read side
    is therefore the enforceable seam: it holds the attempt-directory
    evidence that the candidates are distinct, reports the conflict LOUDLY,
    keeps the rows separate, and attaches tuner evidence to NONE of them —
    attributing it to either would be resolving an ambiguity by guess.
    """

    candidate_id: str
    attempt_dirs: list[str]
    #: Tuner outputs carrying the conflicted id — withheld from attachment.
    withheld_tuner_outputs: list[str] = Field(default_factory=list)


class CandidateFunnelRow(BaseModel):
    """The assembled per-candidate view. In memory only — never persisted."""

    candidate_id: str | None = Field(
        description="None = unjoinable (legacy or non-proposer candidate).",
    )
    attempt_dir: str | None = None
    stages: dict[str, StageEvidence] = Field(default_factory=dict)
    #: O-E-6 display labels — read-side names only; the schemas keep theirs.
    proposed_trainable_parameter_count_estimate: int | None = None
    preflight_factor: float | None = None
    implemented_total_parameter_count: int | None = None
    implemented_trainable_parameter_count: int | None = None
    #: One candidate fans into MANY tuner records; per-record, in file order.
    trained_trainable_parameter_counts: list[int | None] = Field(default_factory=list)
    tuner_record_count: int = 0
    #: Derived on read (O-E-2). None = the evidence reaches the tuner.
    stopped_at_stage: StageName | None = None
    #: The stopping stage's NATIVE reason payload; None when the stage has
    #: no typed reason (reason_absent on the stage marks that honestly).
    stop_reason_native: dict[str, Any] | None = None
    incomplete_stages: list[str] = Field(default_factory=list)
    unreadable: list[UnreadableArtifact] = Field(default_factory=list)
    #: True when this row's id appears in another attempt directory too —
    #: its derived fields (esp. stopped_at_stage) are then unreliable; see
    #: the funnel's ``duplicate_id_conflicts`` for the loud report.
    id_conflict: bool = False


class IterationFunnel(BaseModel):
    """Everything the reader could see in ONE iteration directory."""

    discoverable: bool = Field(
        description="False when the directory does not exist or is not a "
        "directory — NOT the same as zero candidates (§10: non-local or "
        "missing storage is 'not discoverable', never 'empty').",
    )
    iter_dir: str
    rows: list[CandidateFunnelRow] = Field(default_factory=list)
    #: Artifacts with candidate_id=None — each its own evidence item.
    unjoinable: list[CandidateFunnelRow] = Field(default_factory=list)
    #: Attempt dirs holding no proposal artifact: the proposer emitted
    #: nothing there, so there IS no candidate (§0.D) — reported, not rowed.
    no_candidate_dirs: list[str] = Field(default_factory=list)
    #: LOUD duplicate-identity report. Empty on every healthy run.
    duplicate_id_conflicts: list[DuplicateIdConflict] = Field(default_factory=list)


def _read_json(path: str) -> tuple[dict[str, Any] | None, UnreadableArtifact | None]:
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, UnreadableArtifact(path=path, error=f"{type(exc).__name__}: {exc}")
    if not isinstance(payload, dict):
        return None, UnreadableArtifact(
            path=path, error=f"expected a JSON object, got {type(payload).__name__}"
        )
    return payload, None


def _stage_artifacts(attempt_dir: str) -> dict[StageName, str]:
    """Map stage -> artifact path for whichever stage files exist.

    Matches on the ``{stage}_`` filename prefix — never on model_name.

    S2 / U6 (#256): the proposal lives at the attempt level; the
    implementor and validation artifacts live in the TERMINAL nested
    ``impl_NNN/`` (``execute_tools.impl_attempts.stage_artifact_dir``),
    which resolves to the attempt directory itself for a pre-U6 workspace.
    Under O-E-4 every retry is the same candidate, so the terminal outcome
    is the one the funnel reports; the earlier retries stay on disk as
    evidence and are deliberately NOT rows.
    """
    found: dict[StageName, str] = {}
    listing: dict[str, list[str]] = {}
    for stage, prefix in _STAGE_FILES:
        search_dir = attempt_dir if stage == "proposal" else stage_artifact_dir(attempt_dir)
        if search_dir not in listing:
            try:
                listing[search_dir] = sorted(os.listdir(search_dir))
            except OSError:
                listing[search_dir] = []
        for entry in listing[search_dir]:
            if entry.startswith(prefix) and entry.endswith(".json"):
                found[stage] = os.path.join(search_dir, entry)
                break
    return found


def _derive_stop(row: CandidateFunnelRow) -> None:
    """O-E-2: derive where the candidate stopped from native outcomes.

    Funnel order, first failure or first absence wins:
      - validation present with ``passed=False``  -> stopped at validation,
        native verdict carried verbatim as the reason;
      - implementation absent after a proposal    -> stopped at
        implementation, reason ABSENT (no typed reason exists, §0.E);
      - validation absent after implementation    -> stopped at validation
        (never ran), reason absent;
      - no tuner records after a passing validation -> stopped at tuner
        (never ran / nothing persisted), reason absent;
      - tuner records exist -> did not stop early (None). The tuner's own
        statuses/failure fields live in its native records and are not
        re-judged here.
    """
    proposal = row.stages.get("proposal", StageEvidence())
    implementation = row.stages.get("implementation", StageEvidence())
    validation = row.stages.get("validation", StageEvidence())

    if validation.present and validation.native is not None:
        if validation.native.get("passed") is False:
            row.stopped_at_stage = "validation"
            row.stop_reason_native = validation.native
            return
        if row.tuner_record_count == 0:
            row.stopped_at_stage = "tuner"
            row.stop_reason_native = None
            row.stages.setdefault("tuner", StageEvidence()).reason_absent = True
            return
        row.stopped_at_stage = None
        return

    if implementation.present:
        # Implementor emitted, validation never did.
        row.stopped_at_stage = "validation"
        row.stop_reason_native = None
        row.stages.setdefault("validation", StageEvidence()).reason_absent = True
        return

    if proposal.present:
        row.stopped_at_stage = "implementation"
        row.stop_reason_native = None
        # §0.E: the one stage with no typed native reason.
        row.stages.setdefault("implementation", StageEvidence()).reason_absent = True
        return

    row.stopped_at_stage = "proposal"
    row.stop_reason_native = None


def _row_from_attempt_dir(attempt_dir: str) -> list[CandidateFunnelRow]:
    """Build rows for one attempt directory.

    With explicit ids, artifacts sharing an id merge into one row. With
    ``None`` ids, EVERY artifact is its own unjoinable row — same-directory
    co-location is a directory fact, not an identity (§10 forbids joining
    on the dir suffix).
    """
    artifacts = _stage_artifacts(attempt_dir)
    by_id: dict[str, CandidateFunnelRow] = {}
    loose: list[CandidateFunnelRow] = []
    unreadable: list[UnreadableArtifact] = []

    for stage, path in artifacts.items():
        payload, err = _read_json(path)
        if err is not None:
            unreadable.append(err)
            continue
        assert payload is not None
        cid = payload.get("candidate_id")
        evidence = StageEvidence(present=True, source_path=path, native=payload)
        if isinstance(cid, str):
            row = by_id.setdefault(
                cid, CandidateFunnelRow(candidate_id=cid, attempt_dir=attempt_dir)
            )
            row.stages[stage] = evidence
        else:
            solo = CandidateFunnelRow(candidate_id=None, attempt_dir=attempt_dir)
            solo.stages[stage] = evidence
            loose.append(solo)

    rows = list(by_id.values()) + loose
    if rows and unreadable:
        # Attach unreadable artifacts to every row of this dir — the reader
        # cannot know whose they were, and hiding them on none would make a
        # malformed file invisible.
        for row in rows:
            row.unreadable.extend(unreadable)
    elif unreadable:
        carrier = CandidateFunnelRow(candidate_id=None, attempt_dir=attempt_dir)
        carrier.unreadable.extend(unreadable)
        loose.append(carrier)
        rows = loose
    return rows


def _attach_measurements(row: CandidateFunnelRow) -> None:
    """O-E-6 display labels. Reads, labels, never combines."""
    proposal = row.stages.get("proposal")
    if proposal and proposal.native is not None:
        row.proposed_trainable_parameter_count_estimate = proposal.native.get(
            "parameter_count_estimate"
        )
        row.preflight_factor = proposal.native.get("preflight_factor")
    validation = row.stages.get("validation")
    if validation and validation.native is not None:
        row.implemented_total_parameter_count = validation.native.get(
            "realized_total_parameter_count"
        )
        row.implemented_trainable_parameter_count = validation.native.get(
            "realized_trainable_parameter_count"
        )


def _mark_incomplete(row: CandidateFunnelRow) -> None:
    """Name what is missing rather than dropping or defaulting (§E.3d.4).

    Distinguishes "stage not reached" (listed in ``incomplete_stages``)
    from "stage reached, number absent" (stage present, measurement None —
    visible directly on the row's fields).
    """
    reached: list[str] = [name for name, ev in row.stages.items() if ev.present]
    order = ["proposal", "implementation", "validation", "tuner"]
    if row.tuner_record_count > 0:
        reached.append("tuner")
    row.incomplete_stages = [name for name in order if name not in reached]


def assemble_iteration_funnel(iter_dir: str) -> IterationFunnel:
    """Assemble the funnel for one iteration directory, read-only.

    Args:
        iter_dir: an ``iteration_NNN`` directory as laid out by
            ``run_workflow`` — attempt dirs plus per-model tuning dirs.

    Returns:
        An :class:`IterationFunnel`. ``discoverable=False`` when the
        directory is absent — deliberately distinct from an existing but
        empty directory, which yields ``discoverable=True`` with no rows.
    """
    if not os.path.isdir(iter_dir):
        return IterationFunnel(discoverable=False, iter_dir=iter_dir)

    funnel = IterationFunnel(discoverable=True, iter_dir=iter_dir)

    rows: list[CandidateFunnelRow] = []
    for entry in sorted(os.listdir(iter_dir)):
        full = os.path.join(iter_dir, entry)
        if not (entry.startswith("attempt_") and os.path.isdir(full)):
            continue
        dir_rows = _row_from_attempt_dir(full)
        if not dir_rows:
            funnel.no_candidate_dirs.append(full)
            continue
        rows.extend(dir_rows)

    # Tuner evidence: run_output_*.json inside per-model tuning dirs.
    # Joined ONLY via the output's / records' explicit candidate_id.
    tuner_outputs: list[tuple[str, dict[str, Any]]] = []
    for entry in sorted(os.listdir(iter_dir)):
        full = os.path.join(iter_dir, entry)
        if entry.startswith("attempt_") or not os.path.isdir(full):
            continue
        for name in sorted(os.listdir(full)):
            if name.startswith("run_output_") and name.endswith(".json"):
                path = os.path.join(full, name)
                payload, err = _read_json(path)
                if err is not None:
                    carrier = CandidateFunnelRow(candidate_id=None, attempt_dir=None)
                    carrier.unreadable.append(err)
                    funnel.unjoinable.append(carrier)
                    continue
                assert payload is not None
                tuner_outputs.append((path, payload))

    # Duplicate-id detection (the enforceable uniqueness seam): a non-None
    # id in more than one DISTINCT attempt directory is two candidates whose
    # identities collided. Never merge them, never pick one — report loudly.
    rows_by_claimed_id: dict[str, list[CandidateFunnelRow]] = {}
    for row in rows:
        if row.candidate_id is not None and row.attempt_dir is not None:
            rows_by_claimed_id.setdefault(row.candidate_id, []).append(row)
    conflicted: dict[str, DuplicateIdConflict] = {}
    for cid, group in rows_by_claimed_id.items():
        if len({r.attempt_dir for r in group}) > 1:
            conflict = DuplicateIdConflict(
                candidate_id=cid,
                attempt_dirs=sorted({r.attempt_dir for r in group if r.attempt_dir}),
            )
            conflicted[cid] = conflict
            funnel.duplicate_id_conflicts.append(conflict)
            for r in group:
                r.id_conflict = True

    by_id = {
        row.candidate_id: row
        for row in rows
        if row.candidate_id is not None and row.candidate_id not in conflicted
    }
    for path, payload in tuner_outputs:
        cid = payload.get("candidate_id")
        records = payload.get("all_records") or []
        if isinstance(cid, str) and cid in conflicted:
            # Withheld: attributing this output to one of the colliding
            # candidates would be a silent guess.
            conflicted[cid].withheld_tuner_outputs.append(path)
            continue
        if isinstance(cid, str):
            row = by_id.get(cid)
            if row is None:
                row = CandidateFunnelRow(candidate_id=cid, attempt_dir=None)
                rows.append(row)
                by_id[cid] = row
            row.stages["tuner"] = StageEvidence(
                present=True,
                source_path=path,
                # The run-level output minus its (potentially large) record
                # list; the records contribute the per-record fields below.
                native={k: v for k, v in payload.items() if k != "all_records"},
            )
            row.tuner_record_count = len(records)
            row.trained_trainable_parameter_counts = [
                rec.get("model_params") for rec in records if isinstance(rec, dict)
            ]
        else:
            solo = CandidateFunnelRow(candidate_id=None, attempt_dir=None)
            solo.stages["tuner"] = StageEvidence(present=True, source_path=path, native=None)
            solo.tuner_record_count = len(records)
            solo.trained_trainable_parameter_counts = [
                rec.get("model_params") for rec in records if isinstance(rec, dict)
            ]
            funnel.unjoinable.append(solo)

    for row in rows:
        _attach_measurements(row)
        _derive_stop(row)
        _mark_incomplete(row)

    funnel.rows = [row for row in rows if row.candidate_id is not None]
    for row in rows:
        if row.candidate_id is None:
            _attach_measurements(row)
            _derive_stop(row)
            _mark_incomplete(row)
            funnel.unjoinable.append(row)
    return funnel


def read_trained_parameter_counts(iter_dirs: list[str]) -> list[int]:
    """LEGACY STAGE-LOCAL SANITY CHECK reader (§11) — one stage, no join.

    Reads ``model_params`` values out of tuner run outputs under the given
    iteration directories. This is NOT a funnel and must never be
    described as one: pre-PR-E records carry no ``candidate_id``, are
    unjoinable by rule, and no identity is inferred here from anything —
    the return value is a flat list of one stage's native measurements,
    suitable only for reproducing an already-recorded range.
    """
    counts: list[int] = []
    for iter_dir in iter_dirs:
        if not os.path.isdir(iter_dir):
            continue
        for entry in sorted(os.listdir(iter_dir)):
            full = os.path.join(iter_dir, entry)
            if not os.path.isdir(full):
                continue
            for name in sorted(os.listdir(full)):
                if name.startswith("run_output_") and name.endswith(".json"):
                    payload, err = _read_json(os.path.join(full, name))
                    if err is not None or payload is None:
                        continue
                    for rec in payload.get("all_records") or []:
                        if isinstance(rec, dict) and isinstance(rec.get("model_params"), int):
                            counts.append(rec["model_params"])
    return counts
